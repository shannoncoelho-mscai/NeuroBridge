from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


# =========================================================
# LLM RESPONSE
# =========================================================

@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str = "unknown"

    usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# =========================================================
# PROVIDER INTERFACE
# =========================================================

class LLMProvider(Protocol):

    @property
    def provider_name(self) -> str:
        ...

    def generate(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        **kwargs,
    ) -> LLMResponse:
        ...


# =========================================================
# PROVIDER REGISTRY
# =========================================================

class ProviderRegistry:

    def __init__(self):
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider):
        name = provider.provider_name.lower().strip()

        if not name:
            raise ValueError("Provider name cannot be empty.")

        self._providers[name] = provider

    def get(self, name: str) -> LLMProvider:
        name = name.lower().strip()

        if name not in self._providers:
            raise ValueError(
                f"Provider '{name}' is not registered. "
                f"Available providers: {self.list_providers()}"
            )

        return self._providers[name]

    def list_providers(self) -> list[str]:
        return sorted(self._providers.keys())

    def has_provider(self, name: str) -> bool:
        return name.lower().strip() in self._providers


# =========================================================
# LLM GATEWAY
# =========================================================

class LLMGateway:

    def __init__(
        self,
        registry: Optional[ProviderRegistry] = None,
        default_provider: str = "gemini",
        fallback_provider: Optional[str] = None,
    ):
        self.registry = registry or ProviderRegistry()

        self.default_provider = default_provider.lower().strip()
        self.fallback_provider = (
            fallback_provider.lower().strip()
            if fallback_provider
            else None
        )

    def register_provider(self, provider: LLMProvider):
        self.registry.register(provider)

    def set_default_provider(self, provider_name: str):
        if not self.registry.has_provider(provider_name):
            raise ValueError(
                f"Provider '{provider_name}' is not registered."
            )

        self.default_provider = provider_name.lower().strip()

    def set_fallback_provider(
        self,
        provider_name: Optional[str],
    ):
        if provider_name is not None:
            if not self.registry.has_provider(provider_name):
                raise ValueError(
                    f"Fallback provider '{provider_name}' "
                    "is not registered."
                )

        self.fallback_provider = (
            provider_name.lower().strip()
            if provider_name
            else None
        )

    def list_providers(self) -> list[str]:
        return self.registry.list_providers()

    def generate(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        **kwargs,
    ) -> LLMResponse:

        primary_name = (
            provider.lower().strip()
            if provider
            else self.default_provider
        )

        primary = self.registry.get(primary_name)

        try:
            return primary.generate(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

        except Exception as primary_error:

            # Do not retry the same provider as fallback.
            if (
                not self.fallback_provider
                or self.fallback_provider == primary_name
            ):
                raise RuntimeError(
                    f"LLM provider '{primary_name}' failed."
                ) from primary_error

            fallback = self.registry.get(self.fallback_provider)

            try:
                response = fallback.generate(
                    messages=messages,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )

                response.metadata["fallback_used"] = True
                response.metadata["primary_provider"] = primary_name

                return response

            except Exception as fallback_error:
                raise RuntimeError(
                    "Both primary and fallback LLM providers failed. "
                    f"Primary: {primary_name}; "
                    f"Fallback: {self.fallback_provider}"
                ) from fallback_error
