"""NeuroBridge language policy, normalisation and lightweight script detection.

Detection is deterministic and script-based. It is reliable for distinguishing scripts
(Latin, Devanagari, Bengali, Tamil, ...). It canNOT reliably tell apart languages that share
a script (Hindi / Marathi / Konkani all use Devanagari); in that case the result is marked
ambiguous and the LLM is asked to mirror the user's language.
"""

SUPPORTED_LANGUAGES = {
    "English": "en",
    "Hindi": "hi",
    "Konkani": "kok",
    "Marathi": "mr",
    "Bengali": "bn",
    "Tamil": "ta",
    "Telugu": "te",
    "Malayalam": "ml",
    "Kannada": "kn",
    "Gujarati": "gu",
    "Punjabi": "pa",
    "Urdu": "ur",
}
CODE_TO_NAME = {code: name for name, code in SUPPORTED_LANGUAGES.items()}

LANGUAGE_POLICY = """
Respond in the caregiver language by default.
Detect language when no preference is provided.
Allow language switching and mixed-language conversation.
Use simple, compassionate caregiver-friendly language.
Preserve healthcare terminology and safety warnings.
Keep names, phone numbers, addresses, and URLs unchanged.
Do not guess uncertain medical translations.
"""

# Unicode block ranges -> candidate languages
_SCRIPTS = [
    ("Devanagari", 0x0900, 0x097F, ["hi", "mr", "kok"]),
    ("Bengali", 0x0980, 0x09FF, ["bn"]),
    ("Gurmukhi", 0x0A00, 0x0A7F, ["pa"]),
    ("Gujarati", 0x0A80, 0x0AFF, ["gu"]),
    ("Tamil", 0x0B80, 0x0BFF, ["ta"]),
    ("Telugu", 0x0C00, 0x0C7F, ["te"]),
    ("Kannada", 0x0C80, 0x0CFF, ["kn"]),
    ("Malayalam", 0x0D00, 0x0D7F, ["ml"]),
    ("Arabic", 0x0600, 0x06FF, ["ur"]),
]

# A few high-frequency function words to break Devanagari ties. Heuristic only.
_DEVANAGARI_HINTS = {
    "mr": ["आहे", "आहेत", "मला", "माझ्या", "काय", "नाही", "आणि", "करू"],
    "hi": ["है", "हैं", "मुझे", "मेरा", "मेरी", "क्या", "नहीं", "और", "कैसे"],
    "kok": ["आसा", "म्हाका", "हांव", "कितें", "ना", "आनी"],
}


def normalize_language(value):
    """Return (code, name) for a code or name, or (None, None) if unsupported/empty."""
    if not value:
        return None, None
    text = str(value).strip()
    if text in CODE_TO_NAME:
        return text, CODE_TO_NAME[text]
    for name, code in SUPPORTED_LANGUAGES.items():
        if name.lower() == text.lower():
            return code, name
    return None, None


def detect_language(text):
    """Detect language from script. Returns dict(code, name, script, confidence, ambiguous)."""
    counts = {}
    latin = 0
    for ch in text or "":
        cp = ord(ch)
        if ("a" <= ch.lower() <= "z"):
            latin += 1
            continue
        for script, lo, hi, _ in _SCRIPTS:
            if lo <= cp <= hi:
                counts[script] = counts.get(script, 0) + 1
                break

    if not counts and not latin:
        return {"code": None, "name": None, "script": None, "confidence": 0.0, "ambiguous": True}

    if not counts or latin > 3 * max(counts.values()):
        # Latin script: assume English. Romanised Hindi etc. cannot be distinguished here.
        return {"code": "en", "name": "English", "script": "Latin",
                "confidence": 0.6, "ambiguous": True if counts else False}

    script = max(counts, key=counts.get)
    candidates = next(c for s, _, _, c in _SCRIPTS if s == script)
    if len(candidates) == 1:
        code = candidates[0]
        return {"code": code, "name": CODE_TO_NAME[code], "script": script,
                "confidence": 0.9, "ambiguous": False}

    scores = {code: sum(text.count(w) for w in words) for code, words in _DEVANAGARI_HINTS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0 or list(scores.values()).count(scores[best]) > 1:
        return {"code": "hi", "name": "Hindi", "script": script, "confidence": 0.4,
                "ambiguous": True, "candidates": candidates}
    return {"code": best, "name": CODE_TO_NAME[best], "script": script,
            "confidence": 0.6, "ambiguous": True, "candidates": candidates}


def get_language_context(preferred_language=None, user_text=None):
    """Language context for prompts. Accepts a code ('hi') or a name ('Hindi')."""
    code, name = normalize_language(preferred_language)
    if preferred_language and code:
        return {"language": name, "language_code": code, "policy": LANGUAGE_POLICY,
                "supported": True, "source": "preference"}
    if preferred_language and not code:
        return {"language": str(preferred_language), "language_code": None,
                "policy": LANGUAGE_POLICY, "supported": False, "source": "preference"}

    if user_text:
        detected = detect_language(user_text)
        if detected["code"] and not detected["ambiguous"]:
            return {"language": detected["name"], "language_code": detected["code"],
                    "policy": LANGUAGE_POLICY, "supported": True, "source": "detected",
                    "detection": detected}
        return {"language": "auto-detect", "language_code": None, "policy": LANGUAGE_POLICY,
                "supported": True, "source": "detected_ambiguous", "detection": detected}

    return {"language": "auto-detect", "language_code": None, "policy": LANGUAGE_POLICY,
            "supported": True, "source": "none"}
