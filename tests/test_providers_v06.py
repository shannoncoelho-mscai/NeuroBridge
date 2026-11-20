"""Provider behaviour with the real SDK types and fake network clients (no keys needed)."""
import types as pytypes

import pytest

genai_types = pytest.importorskip("google.genai.types")

from agent.llm.gemini_provider import GeminiProvider
from agent.llm.groq_provider import GroqProvider


class _GeminiModels:
    def __init__(self, unavailable=(), text="Hello from Gemini"):
        self.unavailable = set(unavailable)
        self.calls = []
        self.text = text

    def generate_content(self, model, contents, config):
        self.calls.append((model, config))
        if model in self.unavailable:
            raise RuntimeError(f"404 NOT_FOUND. models/{model} is no longer available to new users")
        cand = pytypes.SimpleNamespace(finish_reason="STOP")
        return pytypes.SimpleNamespace(text=self.text, candidates=[cand], usage_metadata=None)


def _gemini(unavailable=(), **kw):
    p = GeminiProvider(api_key="test-key", **kw)
    models = _GeminiModels(unavailable)
    p._client = pytypes.SimpleNamespace(models=models)
    return p, models


def test_gemini_default_is_current_3x_model():
    p, models = _gemini()
    r = p.generate([{"role": "user", "content": "hi"}], system_prompt="be kind")
    assert r.text == "Hello from Gemini"
    model, config = models.calls[0]
    assert model == "gemini-3.8-flash"
    assert config.thinking_config.thinking_level.value == "LOW"   # thinking kept small
    assert config.system_instruction == "be kind"


def test_gemini_falls_back_when_model_unavailable_and_remembers():
    p, models = _gemini(unavailable={"gemini-3.8-flash"})
    r = p.generate([{"role": "user", "content": "hi"}])
    assert [m for m, _ in models.calls] == ["gemini-3.8-flash", "gemini-3.5-flash"]
    assert r.model == "gemini-3.5-flash" and p.model_name == "gemini-3.5-flash"
    p.generate([{"role": "user", "content": "again"}])
    assert models.calls[-1][0] == "gemini-3.5-flash"          # does not retry the dead model


def test_gemini_25_uses_zero_thinking_budget():
    p, models = _gemini(model="gemini-2.5-flash")
    p.generate([{"role": "user", "content": "hi"}])
    assert models.calls[0][1].thinking_config.thinking_budget == 0


def test_gemini_all_unavailable_gives_clear_error():
    p, _ = _gemini(unavailable=set(GeminiProvider.FALLBACK_MODELS))
    with pytest.raises(RuntimeError, match="No Gemini model is available"):
        p.generate([{"role": "user", "content": "hi"}])


def test_gemini_other_errors_are_not_swallowed():
    p = GeminiProvider(api_key="k")

    class Bad:
        def generate_content(self, **kw):
            raise RuntimeError("401 API key not valid")
    p._client = pytypes.SimpleNamespace(models=Bad())
    with pytest.raises(RuntimeError, match="API key not valid"):
        p.generate([{"role": "user", "content": "hi"}])


class _GroqCompletions:
    def __init__(self, dead=()):
        self.dead, self.calls = set(dead), []

    def create(self, **params):
        self.calls.append(params)
        if params["model"] in self.dead:
            raise RuntimeError("Error code: 404 - model_not_found: The model does not exist")
        msg = pytypes.SimpleNamespace(content="Hello from Groq")
        choice = pytypes.SimpleNamespace(message=msg, finish_reason="stop")
        return pytypes.SimpleNamespace(choices=[choice], usage=None)


def _groq(dead=()):
    p = GroqProvider(api_key="k")
    comp = _GroqCompletions(dead)
    p._client = pytypes.SimpleNamespace(chat=pytypes.SimpleNamespace(completions=comp))
    return p, comp


def test_groq_uses_low_reasoning_and_falls_back():
    p, comp = _groq(dead={"openai/gpt-oss-120b"})
    r = p.generate([{"role": "user", "content": "hi"}])
    assert r.text == "Hello from Groq"
    assert [c["model"] for c in comp.calls] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert comp.calls[0]["reasoning_effort"] == "low"
    assert p.model_name == "openai/gpt-oss-20b"


def test_gemini_busy_model_is_skipped_for_this_call_only():
    p = GeminiProvider(api_key="k")
    calls = []

    class Busy:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model == "gemini-3.8-flash" and len(calls) == 1:
                raise RuntimeError("503 UNAVAILABLE. The model is overloaded. Please try again later.")
            cand = pytypes.SimpleNamespace(finish_reason="STOP")
            return pytypes.SimpleNamespace(text="ok", candidates=[cand], usage_metadata=None)
    p._client = pytypes.SimpleNamespace(models=Busy())
    assert p.generate([{"role": "user", "content": "hi"}]).model == "gemini-3.5-flash"
    assert "gemini-3.8-flash" in p._candidates        # not removed: it was only busy
