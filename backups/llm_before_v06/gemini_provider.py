import os
from typing import Optional

from .gateway import LLMResponse


class GeminiProvider:

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        api_key: Optional[str] = None,
        timeout_seconds: int = 60,
    ):
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._api_key = api_key or self._load_api_key()
        self._client = None

    @property
    def provider_name(self):
        return "gemini"

    @property
    def model_name(self):
        return self._model

    @staticmethod
    def _load_api_key():
        # First check environment variables
        key = os.environ.get("GEMINI_API_KEY")

        if key:
            return key

        # Then check Colab Secrets
        try:
            from google.colab import userdata
            key = userdata.get("GEMINI_API_KEY")
            if key:
                return key
        except Exception:
            pass

        raise RuntimeError(
            "Gemini API key not found. Add GEMINI_API_KEY "
            "to Colab Secrets or environment variables."
        )

    def _get_client(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(
                    timeout=self._timeout_seconds * 1000
                ),
            )

        return self._client

    def generate(
        self,
        messages,
        system_prompt=None,
        temperature=0.3,
        max_tokens=1024,
        **kwargs,
    ):
        from google.genai import types

        contents = []
        extracted_system_parts = []

        # Gemini uses "user" and "model" roles
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")

            if role == "system":
                extracted_system_parts.append(str(content))
                continue

            gemini_role = "model" if role == "assistant" else "user"

            contents.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part.from_text(text=str(content))],
                )
            )

        combined_system = "\n\n".join(
            part for part in (
                system_prompt,
                *extracted_system_parts
            )
            if part
        )

        response = self._get_client().models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=combined_system or None,
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        response_text = getattr(response, "text", None)

        if not response_text:
            raise RuntimeError("Gemini returned an empty response.")

        usage = {}

        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata:
            usage = {
                "prompt_tokens": getattr(
                    usage_metadata, "prompt_token_count", None
                ),
                "completion_tokens": getattr(
                    usage_metadata, "candidates_token_count", None
                ),
                "total_tokens": getattr(
                    usage_metadata, "total_token_count", None
                ),
            }

        finish = None
        try:
            finish = str(response.candidates[0].finish_reason)
        except Exception:
            pass
        return LLMResponse(
            text=response_text,
            provider="gemini",
            model=self._model,
            usage=usage,
            metadata={"finish_reason": finish,
                      "truncated": bool(finish and "MAX_TOKENS" in finish)},
        )
