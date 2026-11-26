import hashlib
from pathlib import Path
from uuid import uuid4

from .agent import GREETINGS


CACHE = Path(__file__).resolve().parent.parent / "runtime" / "greetings"


def welcome_text(language):
    if language == "auto":
        return f"{GREETINGS['en']}\n{GREETINGS['hi']}", "mixed"
    return GREETINGS[language], language


def welcome_clip(speech, language):
    text, spoken_language = welcome_text(language)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    path = CACHE / f"{language}-{digest}.wav"
    try:
        return path.read_bytes()
    except FileNotFoundError:
        pass

    audio = speech.synthesize(text, spoken_language)
    CACHE.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        pending.write_bytes(audio)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)
    return audio
