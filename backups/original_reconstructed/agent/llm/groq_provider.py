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

        result = self._get_client().chat.completions.create(
            model=self._model,
            messages=groq_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        response_text = result.choices[0].message.content

        if not response_text:
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
        )
