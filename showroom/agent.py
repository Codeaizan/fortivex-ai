import os
import re
from datetime import datetime

import httpx

from .catalog import TATA_MODELS, mentioned_models
from .demo_data import demo_record, known_vehicle
from .store import SHOWROOM_TZ, new_state


GREETINGS = {
    "en": "Welcome to the showroom. How can I help?",
    "hi": "नमस्ते, शोरूम में आपका स्वागत है। मैं आपकी क्या मदद करूँ?",
}
LANGUAGE_PROMPT = "Would you prefer English or Hindi?\nआप हिंदी या अंग्रेज़ी में बात करना चाहेंगे?"
HINDI_MONTHS = (
    "जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
    "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर",
)
INDIC_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUMBER_WORDS = dict(zip(
    "zero one two three four five six seven eight nine".split()
    + "शून्य एक दो तीन चार पाँच छह सात आठ नौ".split(), "0123456789" * 2,
))
NUMBER_WORDS.update({"oh": "0", "पांच": "5", "छः": "6", "छह": "6"})
CONFIRM_WORDS = {
    "yes", "yes please", "yes confirm", "yes confirm it", "yes book it",
    "yes please book it", "confirm", "confirm it", "confirm booking", "book it",
    "हाँ", "हां", "जी हाँ", "जी हां", "हाँ बुक करें", "हां बुक करें",
    "बुक करें", "कन्फर्म करें", "हाँ कर दीजिए", "हां कर दीजिए", "haan", "han", "yes book",
}
CANCEL_WORDS = {
    "no", "cancel", "cancel booking", "stop booking", "no thanks", "no thank you",
    "do not book", "don't book", "नहीं", "रद्द", "रद्द करें", "मत बुक करें", "नहीं धन्यवाद",
}
OUTBOUND_ERRORS = (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError)


def say(language, english, hindi, sources=()):
    return {"language": language, "text": hindi if language == "hi" else english, "sources": list(sources)}


def format_slot(slot, language):
    time = datetime.fromisoformat(slot).astimezone(SHOWROOM_TZ)
    hour = time.strftime("%I:%M").lstrip("0")
    if language == "hi":
        period = "सुबह" if time.hour < 12 else ("दोपहर" if time.hour < 16 else "शाम")
        return f"{time.day} {HINDI_MONTHS[time.month - 1]}, {period} {hour} बजे"
    return f"{time.strftime('%A')}, {time.day} {time.strftime('%B')} at {hour} {time.strftime('%p')} IST"


def normalize(text):
    return " ".join(re.sub(r"[,!?।.;:]+", " ", text.casefold()).split())


def language_choice(text):
    normalized = normalize(text)
    if normalized in {
        "english", "english please", "switch to english", "speak english", "in english",
        "अंग्रेजी", "अंग्रेज़ी", "अंग्रेजी में", "अंग्रेज़ी में",
    }:
        return "en"
    if normalized in {
        "hindi", "hindi please", "switch to hindi", "speak hindi", "in hindi", "हिंदी", "हिन्दी",
        "हिंदी में", "हिन्दी में", "हिंदी में बात करें", "हिंदी में बात करो",
    }:
        return "hi"
    english_request = re.fullmatch(
        r"(?:please )?(?:(?:(?:i (?:would like|want|prefer) to|(?:can|could|may) (?:we|you)|let['’]s) )?"
        r"(?:talk|speak|continue|proceed|switch) (?:in |to )?|"
        r"i (?:prefer|choose|would prefer|would like) )(english|hindi)(?: please)?",
        normalized,
    )
    if english_request:
        return "en" if english_request[1] == "english" else "hi"
    hindi_request = re.fullmatch(
        r"(?:(?:कृपया|मुझे|मैं|हम) )?(हिंदी|हिन्दी|अंग्रेज़ी|अंग्रेजी) में बात"
        r"(?: करना चाह(?:ता|ती|ते) (?:हूँ|हूं|हैं)| करनी है| कर(?:ें|ो|ीजिए))",
        normalized,
    )
    if hindi_request:
        return "hi" if hindi_request[1] in {"हिंदी", "हिन्दी"} else "en"
    return None


def detect_typed_language(text):
    if re.search(r"[\u0900-\u097f]", text):
        return "hi"
    if set(re.findall(r"[a-z]+", text.casefold())) & {"namaste", "kitna", "kitni", "hai", "chahiye", "kya", "mera"}:
        return "hi"
    return "en"


def phone_number(text):
    text = text.casefold().translate(INDIC_DIGITS)
    text = re.sub(r"^(?:my (?:phone |mobile )?number is|my number is|मेरा फ़ोन नंबर|मेरा फोन नंबर|मेरा नंबर)\s+", "", text)
    text = re.sub(r"\s+है[।.]?$", "", text)
    digits = re.sub(r"[\s().,+-]", "", text)
    if not digits.isascii() or not digits.isdigit():
        pieces = text.replace("-", " ").replace(",", " ").replace(".", " ").split()
        if not pieces or any(piece not in NUMBER_WORDS and not piece.isascii() for piece in pieces):
            return ""
        digits = "".join(NUMBER_WORDS.get(piece, piece) for piece in pieces)
        if not digits.isascii() or not digits.isdigit():
            return ""
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits if len(digits) == 10 else ""


def slot_number(text):
    normalized = normalize(text).translate(INDIC_DIGITS)
    normalized = re.sub(
        r"^(?:please )?(?:(?:i (?:want|would like|prefer) to|i(?:'|’)ll|let(?:'|’)s) "
        r"(?:go with|choose|take|pick|select|book) |(?:go with|choose|take|pick|select|book) )",
        "", normalized,
    )
    normalized = re.sub(r"^the |^please | please$", "", normalized)
    normalized = re.sub(r"^(?:मुझे|मैं|हम) ", "", normalized)
    normalized = re.sub(r" (?:चाहिए|लेना है|चुनना है|लेना चाह(?:ता|ती) हूँ|लेना चाह(?:ता|ती) हूं|बुक कर दीजिए)$", "", normalized)
    match = re.fullmatch(r"(?:option |slot |number |विकल्प |नंबर )?([1-3])(?: please)?", normalized)
    if match:
        return int(match[1]) - 1
    names = (
        {"one", "first", "first one", "first option", "first slot", "option one", "slot one", "पहला", "पहला विकल्प", "एक"},
        {"two", "second", "second one", "second option", "second slot", "option two", "slot two", "दूसरा", "दूसरा विकल्प", "दो"},
        {"three", "third", "third one", "third option", "third slot", "option three", "slot three", "तीसरा", "तीसरा विकल्प", "तीन"},
    )
    return next((index for index, choices in enumerate(names) if normalized in choices), None)


class Agent:
    def __init__(self, store, integrations):
        self.store = store
        self.integrations = integrations
        self.demo_fallback = os.getenv("SHOWROOM_DEMO_FALLBACK", "0") == "1"

    def offer_slots(self, state, language):
        slots = self.store.available_slots()
        if not slots:
            state.update(step="idle", slots=[])
            return say(language, "There are no demo slots available this week.",
                       "इस सप्ताह टेस्ट ड्राइव का कोई समय उपलब्ध नहीं है।")
        state.update(step="slot", slots=slots)
        options = [f"{index}. {format_slot(slot, language)}" for index, slot in enumerate(slots, start=1)]
        listing = " ".join(options)
        return say(
            language, f"For the {state['vehicle']}, I have these slots. {listing} Which option works for you?",
            f"{state['vehicle']} के लिए ये समय उपलब्ध हैं। {listing} आप कौन सा विकल्प चुनना चाहेंगे?",
        )

    def start_booking(self, state, language, text):
        models = mentioned_models(text)
        if len(models) == 1:
            state["vehicle"] = TATA_MODELS[models[0]][0]
        if state["vehicle"]:
            return self.offer_slots(state, language)
        state["step"] = "vehicle"
        return say(language, "Which car would you like to test drive?",
                   "आप किस कार की टेस्ट ड्राइव लेना चाहेंगे?")

    def respond(self, call, text, detected_language, confidence):
        language = call["language"]
        state = call["state"]
        normalized = normalize(text)
        chosen = language_choice(text)
        if chosen:
            return chosen, state, say(chosen, "I'll continue in English. How can I help?",
                                      "अब मैं हिंदी में बात करूँगी। मैं आपकी क्या मदद करूँ?"), None, None
        if not language:
            if detected_language not in {"en", "hi"} or confidence < 0.65 or normalized in {
                "hello", "hi", "hey", "नमस्ते", "हेलो",
            }:
                return None, state, {"text": LANGUAGE_PROMPT, "language": "mixed"}, None, None
            language = detected_language
        state, reply, booking, notice = self._conversation(call, text, normalized, state, language)
        return language, state, reply, booking, notice

    def _conversation(self, call, text, normalized, state, language):
        step = state["step"]
        if step != "idle" and normalized in CANCEL_WORDS:
            reset = new_state()
            reset["vehicle"] = state["vehicle"]
            return reset, say(language, "I've closed the pending booking request. How else can I help?",
                              "मैंने बुकिंग का अनुरोध बंद कर दिया है। मैं और क्या मदद करूँ?"), None, None
        if step == "vehicle":
            if len(text) > 80 or normalized in CONFIRM_WORDS:
                return state, say(language, "Please tell me the model name.", "कृपया मॉडल का नाम बताइए।"), None, None
            state["vehicle"] = known_vehicle(text) or text.strip(" .!?।")
            return state, self.offer_slots(state, language), None, None
        if step == "slot":
            index = slot_number(normalized)
            if index is None or index >= len(state["slots"]):
                return state, say(language, "You can say first, second, or third. Which available option would you like?",
                                  "कृपया दिए गए विकल्पों में से एक नंबर चुनें।"), None, None
            state.update(step="name", slot=state["slots"][index], slots=[])
            return state, say(language, "What name should I use for the booking?",
                              "बुकिंग किस नाम से करूँ?"), None, None
        if step == "name":
            customer = re.sub(r"^(my name is|i am|i'm|मेरा नाम|मेरा नेम)\s+", "", text.strip(), flags=re.I)
            customer = re.sub(r"\s+है[।.]?$", "", customer).strip(" .!?।")
            if not 2 <= len(customer) <= 80 or any(character.isdigit() for character in customer) or normalized in CONFIRM_WORDS:
                return state, say(language, "Please say your name.", "कृपया अपना नाम बताइए।"), None, None
            state.update(step="phone", customer=customer)
            return state, say(language, "What's your 10-digit callback number? You can also type it.",
                              "आपका 10 अंकों का फ़ोन नंबर क्या है? आप इसे टाइप भी कर सकते हैं।"), None, None
        if step == "phone":
            phone = phone_number(text)
            if not phone:
                return state, say(language, "Please enter or say the 10 digits one at a time.",
                                  "कृपया 10 अंक एक-एक करके बोलें या टाइप करें।"), None, None
            state.update(step="confirm", phone=phone)
            slot = format_slot(state["slot"], language)
            return state, say(
                language, f"Booking for {state['customer']}: {state['vehicle']} on {slot}, callback ending in {phone[-4:]}. Shall I confirm?",
                f"{state['customer']} के नाम से {state['vehicle']} की टेस्ट ड्राइव, {slot}। फ़ोन नंबर के अंतिम चार अंक {phone[-4:]} हैं। क्या मैं बुकिंग पक्की करूँ?",
            ), None, None
        if step == "confirm":
            if normalized not in CONFIRM_WORDS:
                return state, say(language, "Say yes to confirm this booking, or cancel.",
                                  "बुकिंग पक्की करने के लिए हाँ कहें, या रद्द करें।"), None, None
            booking = {key: state[key] for key in ("vehicle", "slot", "customer", "phone")}
            reset = new_state()
            reset["vehicle"] = booking["vehicle"]
            return reset, None, booking, None

        candidates = mentioned_models(text)
        current_vehicle = TATA_MODELS[candidates[0]][0] if len(candidates) == 1 else known_vehicle(text)
        if current_vehicle:
            state["vehicle"] = current_vehicle
        try:
            turn = self.integrations.first_turn(text, language, call["turns"], state["vehicle"])
        except OUTBOUND_ERRORS:
            return state, say(
                language, "The local assistant is unavailable. Please try again in a moment.",
                "स्थानीय सहायक उपलब्ध नहीं है। कृपया थोड़ी देर में फिर कोशिश करें।",
            ), None, "Check the local llama.cpp server on port 8080."

        if "text" in turn:
            return state, {
                "text": turn["text"], "language": language, "generated_by": "llm",
            }, None, None
        if turn["name"] == "start_test_drive":
            requested = turn["arguments"].get("vehicle")
            if isinstance(requested, str) and requested.strip() and len(requested) <= 80:
                if normalize(requested) in normalized:
                    state["vehicle"] = known_vehicle(requested) or requested.strip()
            return state, self.start_booking(state, language, text), None, None
        return self._answer_lookup(turn, state, language, text, normalized, current_vehicle)

    def _answer_lookup(self, turn, state, language, text, normalized, current_vehicle):
        query = turn["arguments"].get("query")
        query = query.strip()[:500] if isinstance(query, str) and query.strip() else text
        notice = None
        candidates = mentioned_models(text) or mentioned_models(query)
        model = candidates[0] if len(candidates) == 1 else None
        try:
            records = self.integrations.search(query, model=model)
        except OUTBOUND_ERRORS:
            records = []
            notice = "RAG service unavailable. Check the service on port 8000."
        if not records and self.demo_fallback:
            model = current_vehicle or known_vehicle(query)
            if not model and re.match(r"^(?:its|and its|उसका|उसकी)(?:\s|$)", normalized):
                model = state["vehicle"]
            records = demo_record(text, model, language) or demo_record(query, model, language)
            if records:
                notice = "This reply uses the fictional demo catalog. Start the RAG service on port 8000 for your real showroom catalog."

        demo = bool(records and records[0]["source"] == "Fictional demo inventory")
        asks_stock = bool(re.search(
            r"\b(?:right now|currently|today|live stock|in stock|current inventory|stock)\b|अभी|आज|स्टॉक",
            normalized,
        ))
        catalog_only = asks_stock and bool(records) and (demo or all(
            record["source"].casefold().endswith(".pdf") for record in records
        ))
        generated_by = None
        try:
            answer = self.integrations.answer_search(turn, records, language, catalog_only)
            generated_by = "llm"
        except OUTBOUND_ERRORS:
            if demo:
                answer = " ".join(record["text"] for record in records)
                notice = "Fictional catalog reply. The local answer model is unavailable."
            else:
                answer = say(
                    language, "The local assistant couldn't complete that search reply. Please try again.",
                    "स्थानीय सहायक खोज का उत्तर पूरा नहीं कर सका। कृपया फिर कोशिश करें।",
                )["text"]
                notice = "Check the local llama.cpp server on port 8080."
        if catalog_only:
            answer += " " + say(
                language, "I can't verify live showroom stock.",
                "मैं शोरूम के लाइव स्टॉक की पुष्टि नहीं कर सकती।",
            )["text"]
        return state, {
            "text": answer, "language": language, "sources": records, "generated_by": generated_by,
        }, None, notice


    @staticmethod
    def booking_reply(language, booking, reference):
        if not reference:
            return say(language, "That slot has just become unavailable. Ask me to offer new slots.",
                       "वह समय अब उपलब्ध नहीं है। नए समय देखने के लिए मुझसे कहें।")
        slot = format_slot(booking["slot"], language)
        return say(language, f"Your test drive for the {booking['vehicle']} is confirmed for {slot}. Reference {reference}.",
                   f"{booking['vehicle']} की टेस्ट ड्राइव {slot} के लिए पक्की हो गई है। आपका बुकिंग नंबर {reference} है।")
