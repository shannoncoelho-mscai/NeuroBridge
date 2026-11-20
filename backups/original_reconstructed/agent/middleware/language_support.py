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

LANGUAGE_POLICY = """
Respond in the caregiver language by default.
Detect language when no preference is provided.
Allow language switching and mixed-language conversation.
Use simple, compassionate caregiver-friendly language.
Preserve healthcare terminology and safety warnings.
Keep names, phone numbers, addresses, and URLs unchanged.
Do not guess uncertain medical translations.
"""

def get_language_context(preferred_language=None):
    if preferred_language:
        supported = preferred_language in SUPPORTED_LANGUAGES
        return {
            "language": preferred_language,
            "language_code": SUPPORTED_LANGUAGES.get(preferred_language),
            "policy": LANGUAGE_POLICY,
            "supported": supported,
        }
    return {
        "language": "auto-detect",
        "language_code": None,
        "policy": LANGUAGE_POLICY,
        "supported": True,
    }
