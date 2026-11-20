from agent.middleware.language_support import get_language_context


def _latest_user_text(messages):
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def build_multilingual_system_prompt(base_system_prompt=None, preferred_language=None,
                                     user_text=None):
    """Original API: returns the combined system prompt string."""
    return build_multilingual_prompt_and_context(base_system_prompt, preferred_language,
                                                 user_text)[0]


def build_multilingual_prompt_and_context(base_system_prompt=None, preferred_language=None,
                                          user_text=None):
    context = get_language_context(preferred_language, user_text=user_text)
    language = context["language"]
    language_code = context.get("language_code")

    if language != "auto-detect":
        instruction = f"\nLANGUAGE INSTRUCTION:\nRespond in {language}. "
    else:
        instruction = ("\nLANGUAGE INSTRUCTION:\nDetect the language of the latest caregiver "
                       "message and reply in that same language. ")
    if language_code:
        instruction += f"Language code: {language_code}. "

    combined = (base_system_prompt or "").strip()
    combined += "\n\n" + context["policy"].strip() + "\n" + instruction
    return combined, context


def multilingual_generate(
    gateway,
    messages,
    preferred_language=None,
    system_prompt=None,
    temperature=0.3,
    max_tokens=1024,
    **kwargs,
):
    """Call the existing gateway with multilingual instructions added.

    The language context used is attached to response.metadata["language"].
    """
    enhanced_prompt, context = build_multilingual_prompt_and_context(
        base_system_prompt=system_prompt,
        preferred_language=preferred_language,
        user_text=_latest_user_text(messages),
    )
    response = gateway.generate(
        messages=messages,
        system_prompt=enhanced_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    try:
        response.metadata["language"] = {
            k: v for k, v in context.items() if k != "policy"
        }
    except Exception:
        pass
    return response
