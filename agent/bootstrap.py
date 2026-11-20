"""Build NeuroBridge components from environment variables.

Environment
  GROQ_API_KEY, GEMINI_API_KEY      LLM providers (at least one needed for chat/agent)
  NEUROBRIDGE_GROQ_MODEL            default: openai/gpt-oss-120b (as used in the notebook)
  NEUROBRIDGE_GEMINI_MODEL          default: gemini-3.8-flash (falls back to 3.5-flash, 3.5-flash-lite, 2.5-flash)
  NEUROBRIDGE_DEFAULT_PROVIDER      default: groq (fallback is the other provider)
  TAVILY_API_KEY                    web search + page extraction (recommended)
  NEUROBRIDGE_BOOKING_DB            path to the booking SQLite DB
  NEUROBRIDGE_LOCAL_MODEL           local HF base model (e.g. Qwen/Qwen2.5-1.5B-Instruct)
  NEUROBRIDGE_SFT_ADAPTER           SFT LoRA adapter dir -> provider nb_sft (alias NEUROBRIDGE_ADAPTER_PATH)
  NEUROBRIDGE_ORPO_ADAPTER          SFT+ORPO LoRA adapter dir -> provider nb_sft_orpo
  NEUROBRIDGE_LOCAL_4BIT            1 = 4-bit on GPU (default)
  NEUROBRIDGE_ENV / NEUROBRIDGE_LLM development + mock -> labelled dev mock (never in production)

API keys are never logged or returned by any endpoint.
"""
import os

from agent.llm.gateway import LLMGateway


def build_gateway_from_env():
    status = {"providers": [], "errors": []}
    gateway = LLMGateway(default_provider=os.environ.get("NEUROBRIDGE_DEFAULT_PROVIDER", "groq"))

    if os.environ.get("GROQ_API_KEY"):
        try:
            import groq  # noqa: F401
            from agent.llm.groq_provider import GroqProvider
            gateway.register_provider(GroqProvider(
                model=os.environ.get("NEUROBRIDGE_GROQ_MODEL", "openai/gpt-oss-120b")))
            status["providers"].append("groq")
        except Exception as exc:
            status["errors"].append(f"groq: {type(exc).__name__}: {exc}")
    if os.environ.get("GEMINI_API_KEY"):
        try:
            from google import genai  # noqa: F401
            from agent.llm.gemini_provider import GeminiProvider
            gateway.register_provider(GeminiProvider(
                model=os.environ.get("NEUROBRIDGE_GEMINI_MODEL", "gemini-3.8-flash")))
            status["providers"].append("gemini")
        except Exception as exc:
            status["errors"].append(f"gemini: {type(exc).__name__}: {exc}")

    if os.environ.get("NEUROBRIDGE_LOCAL_MODEL"):
        try:
            from agent.llm.hf_provider import build_local_providers
            local = build_local_providers(
                os.environ["NEUROBRIDGE_LOCAL_MODEL"],
                sft_adapter=os.environ.get("NEUROBRIDGE_SFT_ADAPTER")
                or os.environ.get("NEUROBRIDGE_ADAPTER_PATH") or None,
                orpo_adapter=os.environ.get("NEUROBRIDGE_ORPO_ADAPTER") or None,
                four_bit=os.environ.get("NEUROBRIDGE_LOCAL_4BIT", "1") == "1")
            for prov in local:
                gateway.register_provider(prov)
                status["providers"].append(prov.provider_name)
            status["local_models"] = [p.describe() for p in local]
        except Exception as exc:
            status["errors"].append(f"local: {type(exc).__name__}: {exc}")
    if os.environ.get("NEUROBRIDGE_LLM") == "mock":
        try:
            from agent.llm.hf_provider import DevelopmentMockProvider
            gateway.register_provider(DevelopmentMockProvider())
            status["providers"].append("dev_mock")
        except Exception as exc:
            status["errors"].append(f"dev_mock: {exc}")

    if not status["providers"]:
        return None, status

    names = status["providers"]
    if gateway.default_provider not in names:
        gateway.default_provider = names[0]
    others = [n for n in names if n != gateway.default_provider]
    gateway.fallback_provider = others[0] if others else None
    return gateway, status
