"""Check that the API keys really work, with one tiny real call each.

    python scripts/check_keys.py

Reads GROQ_API_KEY, GEMINI_API_KEY and TAVILY_API_KEY from the environment. Prints a clear
OK / problem line per service and what to do about a problem. Never prints the keys.
Exit code 0 when at least one language model and web search work.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _hint(exc):
    t = f"{type(exc).__name__}: {exc}".lower()
    if any(s in t for s in ("401", "invalid api key", "api key not valid", "unauthorized",
                            "permission_denied", "api_key_invalid")):
        return "The key was rejected. Copy it again from the provider's website (no spaces)."
    if any(s in t for s in ("429", "rate limit", "quota", "resource_exhausted")):
        return "The key works but its free limit is used up for now. Wait a bit or use another provider."
    if any(s in t for s in ("no gemini model is available", "no groq model is available")):
        return "None of the known models is enabled for this key. See docs/AI_MODEL_GUIDE.md."
    if any(s in t for s in ("connection", "timed out", "timeout", "name resolution", "ssl")):
        return "Could not reach the service. Check the internet connection (in Colab: rerun the cell)."
    if "no module named" in t:
        return "A package is missing. Run: pip install -r requirements.txt"
    return "Unexpected error - see the message above."


def _short(exc):
    return f"{type(exc).__name__}: {str(exc)[:220]}"


def check_groq():
    if not os.environ.get("GROQ_API_KEY"):
        return None, "not set"
    from agent.llm.groq_provider import GroqProvider
    p = GroqProvider(model=os.environ.get("NEUROBRIDGE_GROQ_MODEL", "openai/gpt-oss-120b"))
    r = p.generate([{"role": "user", "content": "Reply with the single word: OK"}], max_tokens=64)
    return True, f"model {r.model} replied: {r.text.strip()[:40]!r}"


def check_gemini():
    if not os.environ.get("GEMINI_API_KEY"):
        return None, "not set"
    from agent.llm.gemini_provider import GeminiProvider
    p = GeminiProvider(model=os.environ.get("NEUROBRIDGE_GEMINI_MODEL", GeminiProvider.DEFAULT_MODEL))
    r = p.generate([{"role": "user", "content": "Reply with the single word: OK"}], max_tokens=64)
    note = ""
    if r.model != os.environ.get("NEUROBRIDGE_GEMINI_MODEL", GeminiProvider.DEFAULT_MODEL):
        note = f" (the default model is not enabled for this key; using {r.model})"
    return True, f"model {r.model} replied: {r.text.strip()[:40]!r}{note}"


def check_tavily():
    if not os.environ.get("TAVILY_API_KEY"):
        return None, "not set (the agent will fall back to DuckDuckGo, which is less reliable)"
    from tavily import TavilyClient
    r = TavilyClient(api_key=os.environ["TAVILY_API_KEY"]).search(
        query="Tele-MANAS helpline India", max_results=2)
    n = len(r.get("results", []))
    if not n:
        raise RuntimeError("Tavily answered but returned no results.")
    return True, f"{n} results, e.g. {r['results'][0].get('url', '')[:70]}"


def main():
    print("Checking keys (one tiny real request each; keys are never printed)\n")
    results = {}
    for name, fn in (("Groq", check_groq), ("Gemini", check_gemini), ("Tavily", check_tavily)):
        try:
            ok, msg = fn()
        except Exception as exc:          # noqa: BLE001 - report every failure plainly
            ok, msg = False, _short(exc) + "\n      -> " + _hint(exc)
        results[name] = ok
        mark = {True: "OK     ", False: "PROBLEM", None: "-      "}[ok]
        print(f"  [{mark}] {name:7s} {msg}")
    llm_ok = results["Groq"] or results["Gemini"]
    print()
    if llm_ok and results["Tavily"]:
        print("All set: the assistant can chat, and the agent can search the web and read pages.")
    elif llm_ok:
        print("Chat works. Add a working TAVILY_API_KEY for reliable web research.")
    else:
        print("No language model works yet, so the assistant cannot answer. Fix the key(s) above.")
    return 0 if llm_ok and results["Tavily"] is not False else 1


if __name__ == "__main__":
    sys.exit(main())
