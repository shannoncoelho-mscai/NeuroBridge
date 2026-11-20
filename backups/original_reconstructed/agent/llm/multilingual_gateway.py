from agent.middleware.language_support import get_language_context

def build_multilingual_system_prompt(base_system_prompt=None, preferred_language=None):
    context = get_language_context(preferred_language)
    language = context["language"]
    language_code = context.get("language_code")
    policy = context["policy"]

    language_instruction = (
        "\\nLANGUAGE INSTRUCTION:\\n"
        f"Respond in {language} language. "
        if language != "auto-detect"
        else "\\nLANGUAGE INSTRUCTION:\\nDetect the language of the latest caregiver message and reply in that language. "
    )

    if language_code:
        language_instruction += f"Language code: {language_code}. "

    combined = (base_system_prompt or "").strip()
    combined += "\\n\\n" + policy.strip() + language_instruction
    return combined


def multilingual_generate(
    gateway,
    messages,
    preferred_language=None,
    system_prompt=None,
    temperature=0.3,
    max_tokens=1024,
    **kwargs,
):
    """Call the existing gateway with multilingual instructions added."""
    enhanced_prompt = build_multilingual_system_prompt(
        base_system_prompt=system_prompt,
        preferred_language=preferred_language,
    )
    return gateway.generate(
        messages=messages,
        system_prompt=enhanced_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )