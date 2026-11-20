import os
from typing import Optional

from .gateway import LLMResponse


class GeminiProvider:

    # Google serves the 2.5 models only to projects that already used them and recommends
    # the 3.x Flash models for new keys (ai.google.dev/gemini-api/docs/deprecations, Nov 2026).
    # If a model is not available to this key, the next one is tried automatically.
    DEFAULT_MODEL = "gemini-3.8-flash"
    FALLBACK_MODELS = ("gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
                       "gemini-2.5-flash")

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        timeout_seconds: int = 60,
        fallback_models=None,
    ):
        self._model = model
        chain = [model] + [m for m in (fallback_models or self.FALLBACK_MODELS) if m != model]
        self._candidates = chain
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

    @staticmethod
    def _thinking_config(types, model):
        """Keep hidden 'thinking' small so it does not use up the visible answer's tokens."""
        try:
            if model.startswith("gemini-3"):
                return types.ThinkingConfig(thinking_level="low")
            if model.startswith("gemini-2.5-flash"):
                return types.ThinkingConfig(thinking_budget=0)
        except Exception:      # older google-genai without these fields
            return None
        return None

    @staticmethod
    def _is_model_unavailable(exc):
        text = f"{type(exc).__name__} {exc}".lower()
        return any(s in text for s in ("not_found", "404", "not found", "no longer available",
                                       "is not supported", "unsupported model",
                                       "not available", "deprecated"))

    @staticmethod
    def _is_overloaded(exc):
        text = f"{type(exc).__name__} {exc}".lower()
        return any(s in text for s in ("503", "unavailable", "overloaded", "high demand"))

    def _generate_with_fallback(self, contents, system, temperature, max_tokens):
        from google.genai import types
        last = None
        for model in list(self._candidates):
            cfg = dict(system_instruction=system or None, temperature=temperature,
                       max_output_tokens=max_tokens)
            thinking = self._thinking_config(types, model)
            if thinking is not None:
                cfg["thinking_config"] = thinking
            try:
                try:
                    config = types.GenerateContentConfig(**cfg)
                except Exception:
                    cfg.pop("thinking_config", None)
                    config = types.GenerateContentConfig(**cfg)
                response = self._get_client().models.generate_content(
                    model=model, contents=contents, config=config)
            except Exception as exc:
                if self._is_overloaded(exc):
                    last = exc            # busy right now: try the next model for this request only
                    continue
                if self._is_model_unavailable(exc):
                    last = exc
                    self._candidates = [m for m in self._candidates if m != model]
                    continue
                raise
            if model != self._model:
                self._model = model          # remember the model that works for this key
            return response
        raise RuntimeError(f"No Gemini model is available to this API key right now "
                           f"(tried {', '.join(self.FALLBACK_MODELS)}). Last error: {last}")

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

        response = self._generate_with_fallback(contents, combined_system, temperature,
                                                 max_tokens)

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
