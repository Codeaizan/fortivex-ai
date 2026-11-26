"""Fictional inventory used when the teammate's service is unavailable."""

import re


VEHICLE_ALIASES = {
    "Aster Urban": ("aster urban", "urban", "अर्बन"),
    "Aster Ridge": ("aster ridge", "ridge", "रिज"),
}

DEMO_CATALOG = {
    "Aster Urban": {
        "boot": ("The Aster Urban has 385 litres of boot space.", "एस्टर अर्बन में 385 लीटर का बूट स्पेस है।"),
        "price": ("The Aster Urban automatic starts at ₹9,20,000 ex-showroom in this demo.",
                  "इस डेमो में एस्टर अर्बन ऑटोमैटिक की शुरुआती एक्स-शोरूम कीमत 9 लाख 20 हजार रुपये है।"),
        "engine": ("The Aster Urban automatic has a 1.2-litre petrol engine.",
                   "एस्टर अर्बन ऑटोमैटिक में 1.2 लीटर का पेट्रोल इंजन है।"),
    },
    "Aster Ridge": {
        "boot": ("The Aster Ridge has 440 litres of boot space.", "एस्टर रिज में 440 लीटर का बूट स्पेस है।"),
        "price": ("The Aster Ridge automatic starts at ₹12,40,000 ex-showroom in this demo.",
                  "इस डेमो में एस्टर रिज ऑटोमैटिक की शुरुआती एक्स-शोरूम कीमत 12 लाख 40 हजार रुपये है।"),
        "engine": ("The Aster Ridge automatic has a 1.5-litre petrol engine.",
                   "एस्टर रिज ऑटोमैटिक में 1.5 लीटर का पेट्रोल इंजन है।"),
    },
}

DEMO_VARIANTS = {
    "Aster Urban": (
        "Aster Urban demo variants: Petrol Manual and Petrol Automatic.",
        "एस्टर अर्बन के डेमो वैरिएंट पेट्रोल मैनुअल और पेट्रोल ऑटोमैटिक हैं।",
    ),
    "Aster Ridge": (
        "Aster Ridge demo variant: Petrol Automatic.",
        "एस्टर रिज का डेमो वैरिएंट पेट्रोल ऑटोमैटिक है।",
    ),
}
VARIANT_QUESTION = re.compile(r"\b(?:variants|trims|variant options|trim levels)\b|वैरिएंट|वेरिएंट|वैरियंट|ट्रिम")

CATALOG_QUESTION = re.compile(
    r"\b(?:what|which) (?:cars|vehicles|models)\b"
    r"|\b(?:cars|vehicles|models) (?:you (?:are )?(?:selling|sell|have|offer)|(?:are )?(?:available|in stock))\b"
    r"|\b(?:show|list) (?:me )?(?:your |the )?(?:cars|vehicles|models)\b"
    r"|\b(?:your )?(?:inventory|lineup|catalog(?:ue)?)\b"
    r"|(?:कौन|उपलब्ध|बेच|स्टॉक).*(?:गाड़|कार|मॉडल)"
    r"|(?:गाड़|कार|मॉडल).*(?:कौन|उपलब्ध|बेच|स्टॉक)"
)

TOPICS = {
    "boot": ("boot", "luggage", "cargo", "बूट", "डिक्की"),
    "price": ("price", "cost", "pricing", "kitne", "kimat", "कीमत", "दाम", "प्राइस", "कितने रुपये"),
    "engine": ("engine", "petrol", "fuel", "इंजन", "पेट्रोल"),
}


def known_vehicle(text):
    lower = text.casefold()
    for name, aliases in VEHICLE_ALIASES.items():
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", lower) for alias in aliases):
            return name
    return ""


def demo_record(question, vehicle, language):
    lower = question.casefold()
    topic = next((key for key, terms in TOPICS.items() if any(term in lower for term in terms)), None)
    if not topic and VARIANT_QUESTION.search(lower):
        if vehicle and vehicle not in DEMO_VARIANTS:
            return []
        variants = (DEMO_VARIANTS[vehicle],) if vehicle else DEMO_VARIANTS.values()
        return [
            {"text": entry[language == "hi"], "source": "Fictional demo inventory", "page": None}
            for entry in variants
        ]
    if not vehicle and CATALOG_QUESTION.search(lower):
        text = (
            "डेमो कैटलॉग में एस्टर अर्बन और एस्टर रिज हैं। आप किस मॉडल के बारे में जानना चाहेंगे?"
            if language == "hi" else
            f"The fictional demo catalog includes {' and '.join(DEMO_CATALOG)}. Which model would you like to know about?"
        )
        return [{"text": text, "source": "Fictional demo inventory", "page": None}]
    if vehicle not in DEMO_CATALOG or not topic:
        return []
    facts = DEMO_CATALOG[vehicle][topic]
    return [{"text": facts[language == "hi"], "source": "Fictional demo inventory", "page": None}]
