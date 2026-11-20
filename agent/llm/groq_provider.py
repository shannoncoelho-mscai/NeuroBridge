import os
from typing import Optional

from .gateway import LLMResponse


class GroqProvider:

    def __init__(
        self,
        model: str = "openai/gpt-oss-120b",
        api_key: Optional[str] = None,
        timeout_seconds: int = 60,
    ):
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._api_key = api_key or self._load_api_key()
        self._client = None

    @property
    def provider_name(self):
        return "groq"

    @property
    def model_name(self):
        return self._model

    @staticmethod
    def _load_api_key():
        key = os.environ.get("GROQ_API_KEY")

        if key:
            return key

        try:
            from google.colab import userdata
            key = userdata.get("GROQ_API_KEY")
            if key:
                return key
        except Exception:
            pass

        raise RuntimeError(
            "Groq API key not found. Add GROQ_API_KEY "
            "to Colab Secrets or environment variables."
        )

    def _get_client(self):
        if self._client is None:
            from groq import Groq

            self._client = Groq(
                api_key=self._api_key,
                timeout=self._timeout_seconds,
            )

        return self._client

    FALLBACK_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b")

    @staticmethod
    def _is_model_unavailable(exc):
        text = f"{type(exc).__name__} {exc}".lower()
        return any(s in text for s in ("model_not_found", "model_decommissioned",
                                       "decommissioned", "does not exist", "not found",
                                       "404"))

    def _create(self, params):
        """Call Groq; if the configured model has been retired, try the fallbacks."""
        chain = [self._model] + [m for m in self.FALLBACK_MODELS if m != self._model]
        last = None
        for model in chain:
            p = dict(params, model=model)
            if "gpt-oss" not in model:
                p.pop("reasoning_effort", None)
            try:
                try:
                    result = self._get_client().chat.completions.create(**p)
                except TypeError:
                    p.pop("reasoning_effort", None)
                    result = self._get_client().chat.completions.create(**p)
            except Exception as exc:
                if self._is_model_unavailable(exc):
                    last = exc
                    continue
                raise
            self._model = model
            return result
        raise RuntimeError(f"No Groq model is available (tried {', '.join(chain)}). "
                           f"Last error: {last}")

    def generate(
        self,
        messages,
        system_prompt=None,
        temperature=0.3,
        max_tokens=1024,
        **kwargs,
    ):
        groq_messages = []

        if system_prompt:
            groq_messages.append({
                "role": "system",
                "content": system_prompt,
            })

        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")

            if role in ("system", "user", "assistant"):
                groq_messages.append({
                    "role": role,
                    "content": str(content),
                })

        params = dict(model=self._model, messages=groq_messages, temperature=temperature,
                      max_tokens=max_tokens)
        # gpt-oss models spend part of max_tokens on hidden reasoning; keep it low so the
        # visible answer is not cut off.
        if "gpt-oss" in self._model:
            params["reasoning_effort"] = kwargs.get("reasoning_effort", "low")
        result = self._create(params)

        choice = result.choices[0]
        response_text = choice.message.content
        finish_reason = getattr(choice, "finish_reason", None)

        if not response_text:
            if finish_reason == "length":
                raise RuntimeError("Groq used the whole token budget before answering "
                                   "(reasoning). Increase max_tokens.")
            raise RuntimeError("Groq returned an empty response.")

        usage = {}

        if result.usage:
            usage = {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "total_tokens": result.usage.total_tokens,
            }

        return LLMResponse(
            text=response_text,
            provider="groq",
            model=self._model,
            usage=usage,
            metadata={"finish_reason": finish_reason,
                      "truncated": finish_reason == "length"},
        )
