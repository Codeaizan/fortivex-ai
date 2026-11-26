import re


# Slugs match the model metadata in the bundled Tata catalog.
TATA_MODELS = {
    "tiago": ("Tata Tiago", "टियागो"),
    "altroz": ("Tata Altroz", "अल्ट्रोज़", "अल्ट्रोज"),
    "aeris": ("Tata Aeris", "एरिस"),
    "punch": ("Tata Punch", "पंच"),
    "nexon": ("Tata Nexon", "नेक्सन"),
    "curvv": ("Tata Curvv", "कर्व"),
    "sierra": ("Tata Sierra", "सिएरा", "सियरा"),
    "harrier": ("Tata Harrier", "हैरियर", "हेरियर"),
    "safari": ("Tata Safari", "सफारी", "सफ़ारी"),
    "tiago.ev": ("Tata Tiago EV", "टियागो ईवी", "टियागो ई वी"),
    "punch.ev": ("Tata Punch EV", "पंच ईवी", "पंच ई वी"),
    "nexon.ev": ("Tata Nexon EV", "नेक्सन ईवी", "नेक्सन ई वी"),
    "curvv.ev": ("Tata Curvv EV", "कर्व ईवी", "कर्व ई वी"),
    "sierra.ev": ("Tata Sierra EV", "सिएरा ईवी", "सियरा ईवी"),
    "harrier.ev": ("Tata Harrier EV", "हैरियर ईवी", "हेरियर ईवी"),
    "tigor.ev": ("Tata Tigor EV", "टिगोर ईवी", "टिगोर ई वी"),
    "xpres": ("Tata XPRES", "एक्सप्रेस"),
    "xpres-t ev": ("Tata XPRES-T EV", "एक्सप्रेस टी ईवी", "xpres t ev"),
}

ALIASES = {
    alias: slug
    for slug, (display, *synonyms) in TATA_MODELS.items()
    for alias in (slug, display.casefold().removeprefix("tata "), *synonyms)
}
ALIASES["xpres-t"] = "xpres-t ev"

_MODEL_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(alias) for alias in sorted(ALIASES, key=len, reverse=True)) + r")(?!\w)"
)


def mentioned_models(text):
    return tuple(dict.fromkeys(ALIASES[match.group()] for match in _MODEL_RE.finditer(text.casefold())))
