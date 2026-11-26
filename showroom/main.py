import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock, Thread
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .agent import Agent, detect_typed_language, format_slot
from .greetings import welcome_clip, welcome_text
from .live import config_ready, serve_live
from .services import Integrations, Speech, local_url
from .store import Store


HERE = Path(__file__).resolve().parent
LOG = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 8 * 1024 * 1024


class NewCall(BaseModel):
    language: Literal["auto", "en", "hi"] = "auto"
    voice_mode: Literal["local", "gemini"] = "local"


def public_call(call):
    language = call["language"] or "en"
    state = call["state"]
    return {
        "id": call["id"], "started_at": call["started_at"], "ended_at": call["ended_at"],
        "language": call["language"], "summary": call["summary"], "turns": call["turns"],
        "bookings": call["bookings"],
        "booking_active": state["step"] != "idle",
        "options": [
            {"label": format_slot(slot, language), "value": str(index)}
            for index, slot in enumerate(state["slots"], start=1)
        ] if state["step"] == "slot" and not call["ended_at"] else [],
        "awaiting_confirmation": state["step"] == "confirm" and not call["ended_at"],
    }


def create_app(store=None, integrations=None, speech=None):
    store = store or Store(Path(os.getenv("SHOWROOM_DB", str(HERE.parent / "runtime" / "showroom.sqlite3"))))
    speech = speech or Speech()
    integrations = integrations or Integrations()
    agent = Agent(store, integrations)
    conversation_lock = Lock()
    live_calls = set()

    @asynccontextmanager
    async def lifespan(_app):
        store.initialize()
        def warm_speech():
            try:
                with speech.lock:
                    _ = speech.recognizer
                speech.synthesize("Welcome.", "en")
                speech.synthesize("???????", "hi")
            except Exception:
                LOG.exception("Speech warmup failed")
        if isinstance(speech, Speech):
            Thread(target=warm_speech, daemon=True).start()
        yield

    app = FastAPI(title="Showroom Voice Agent", lifespan=lifespan)
    templates = Jinja2Templates(directory=HERE / "templates")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def require_call(call_id):
        call = store.call(call_id)
        if not call:
            raise HTTPException(404, "Conversation not found.")
        return call

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        admin_url = local_url(os.getenv("SHOWROOM_RAG_ADMIN_URL", "http://127.0.0.1:8502"))
        return templates.TemplateResponse(request=request, name="index.html", context={"rag_admin_url": admin_url, "gemini_ready": config_ready()})

    @app.websocket("/api/calls/{call_id}/live")
    async def live_voice(socket: WebSocket, call_id: str):
        if call_id in live_calls:
            await socket.close(code=1008)
            return
        live_calls.add(call_id)
        try:
            await serve_live(socket, call_id, store, integrations, agent, conversation_lock, public_call)
        finally:
            live_calls.discard(call_id)

    @app.get("/api/status")
    def local_status():
        return {"llm": integrations.model_status(), "rag": integrations.rag_status()}

    @app.get("/api/bookings")
    def list_bookings():
        return store.bookings()

    @app.get("/api/calls")
    def list_calls():
        return store.calls()

    @app.post("/api/calls", status_code=201)
    def create_call(body: NewCall):
        language = None if body.language == "auto" else body.language
        greeting_language = "en" if body.voice_mode == "gemini" and body.language == "auto" else body.language
        greeting, spoken_language = welcome_text(greeting_language)
        return public_call(store.create_call(language, greeting, spoken_language))

    @app.get("/api/greetings/{language}/audio")
    def greeting_audio(language: Literal["auto", "en", "hi"]):
        try:
            audio = welcome_clip(speech, language)
        except Exception as error:
            LOG.warning("Welcome speech failed: %s", type(error).__name__)
            raise HTTPException(503, "Welcome audio is unavailable. Run the speech-model preparation step.") from error
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=600"})

    @app.get("/api/calls/{call_id}")
    def get_call(call_id: str):
        return public_call(require_call(call_id))

    @app.post("/api/calls/{call_id}/turn")
    def add_turn(
        call_id: str,
        text: Annotated[str | None, Form(max_length=1500)] = None,
        audio: Annotated[UploadFile | None, File()] = None,
    ):
        text = text.strip() if text else ""
        if bool(text) == bool(audio):
            raise HTTPException(422, "Send either a text reply or a microphone recording.")
        with conversation_lock:
            call = require_call(call_id)
            if call["ended_at"]:
                raise HTTPException(409, "This conversation has ended.")
            if audio:
                contents = audio.file.read(MAX_AUDIO_BYTES + 1)
                if len(contents) > MAX_AUDIO_BYTES:
                    raise HTTPException(413, "The audio clip is too long. Try a shorter turn.")
                if not contents:
                    raise HTTPException(422, "The microphone recording was empty.")
                try:
                    text, detected_language, confidence = speech.transcribe(contents, call["language"])
                except Exception as error:
                    LOG.warning("Transcription failed: %s", type(error).__name__)
                    raise HTTPException(503, "Speech recognition is unavailable. Check the speech setup or type your reply.") from error
                if not text.strip():
                    raise HTTPException(422, "No speech was detected. Try speaking again.")
                text = text[:1500]
            else:
                detected_language, confidence = detect_typed_language(text), 1.0

            language, state, reply, booking, notice = agent.respond(call, text, detected_language, confidence)
            saved = store.save_exchange(
                call_id, text, detected_language, language, state, reply, booking,
                lambda reference: agent.booking_reply(language, booking, reference),
            )
            if not saved:
                raise HTTPException(409, "This conversation has ended.")
            return {"call": public_call(require_call(call_id)), "notice": notice}

    @app.post("/api/calls/{call_id}/end")
    def end_call(call_id: str):
        with conversation_lock:
            result = store.end_call(call_id)
            if result is None:
                raise HTTPException(404, "Conversation not found.")
            return public_call(result)

    @app.get("/api/turns/{turn_id}/audio")
    def reply_audio(turn_id: int):
        turn = store.turn(turn_id)
        if not turn or turn["role"] != "assistant":
            raise HTTPException(404, "Spoken reply not found.")
        try:
            language = "auto" if turn["language"] == "mixed" else turn["language"]
            if language in {"auto", "en", "hi"} and turn["text"] == welcome_text(language)[0]:
                audio = welcome_clip(speech, language)
            else:
                audio = speech.synthesize(turn["text"], turn["language"])
        except Exception as error:
            LOG.warning("Speech synthesis failed: %s", type(error).__name__)
            raise HTTPException(503, "Speech playback is unavailable. Run the speech-model preparation step.") from error
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=600"})

    return app


app = create_app()
