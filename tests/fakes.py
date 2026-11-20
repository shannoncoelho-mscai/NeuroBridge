"""Deterministic test doubles. These are used ONLY by the test suite; the application never
falls back to them, so no fake answers can reach a real user."""
import json
import re

from agent.llm.gateway import LLMGateway, LLMResponse


class ScriptedLLM:
    """Routes each call by its system prompt. Behaviour can be overridden per role."""

    def __init__(self, name="scripted", **overrides):
        self.provider_name = name
        self.calls = []
        self.overrides = overrides

    def _role(self, system_prompt, content):
        sp = (system_prompt or "").lower()
        if "task planner" in sp:
            return "planner"
        if "synthesis engine" in sp:
            return "synthesis"
        if "verifier" in sp or "compact, valid json" in sp:
            return "verifier"
        if "self-correction" in sp:
            return "correction"
        if "goal-completion judge" in sp:
            return "judge"
        if "memory suggestion" in sp:
            return "memory"
        if "return json only" in sp and "search queries" in content.lower():
            return "queries"
        return "chat"

    def generate(self, messages, system_prompt=None, temperature=0.3, max_tokens=1024, **kw):
        content = messages[-1]["content"] if messages else ""
        role = self._role(system_prompt, content)
        self.calls.append({"role": role, "system_prompt": system_prompt, "content": content})
        handler = self.overrides.get(role)
        if callable(handler):
            text = handler(content, system_prompt)
        elif isinstance(handler, Exception):
            raise handler
        elif handler is not None:
            text = handler
        else:
            text = getattr(self, f"_default_{role}")(content)
        return LLMResponse(text=text, provider=self.provider_name, model="scripted")

    # ---- defaults
    def _default_planner(self, content):
        goal = re.search(r"GOAL:\s*(.+?)\n", content)
        goal = goal.group(1) if goal else "caregiver stress"
        return json.dumps({"reasoning_summary": "Search then summarise.", "tasks": [
            {"name": "Search evidence", "description": "Search the web", "dependencies": [],
             "required_tool": "web_search", "required_skill": "research",
             "tool_arguments": {"query": "caregiver stress coping strategies"},
             "requires_approval": False},
            {"name": "Summarise", "description": "Summarise the findings", "dependencies": [0],
             "required_tool": None, "required_skill": "caregiver_support",
             "tool_arguments": {}, "requires_approval": False}]})

    def _default_synthesis(self, content):
        m = re.search(r"EVIDENCE \(id, title, url, text\):\n(.*?)\n\n(?:SEARCHES|RULES)", content, re.S)
        items = json.loads(m.group(1)) if m else []
        lines = [f"{it['text'][:120].rstrip('.')} [{it['id']}]." for it in items[:2]]
        sources = [f"[{it['id']}] {it['title']} — {it['url']}" for it in items[:2]]
        return "\n".join(lines) + "\n\nSources:\n" + "\n".join(sources)

    def _default_verifier(self, content):
        return json.dumps({"passed": True, "score": 90, "issues": [], "unsupported_claims": [],
                           "safety_issues": [], "missing_information": [],
                           "recommendations": [], "reason": "ok"})

    def _default_correction(self, content):
        m = re.search(r"EVIDENCE:\n(.*)\n\nRevise", content, re.S)
        try:
            items = json.loads(m.group(1))
        except Exception:
            items = []
        return "\n".join(f"{it['text'][:120].rstrip('.')} [{it['id']}]." for it in items[:2])

    def _default_judge(self, content):
        crit = re.search(r"CRITERIA:\n(\[.*?\])\n", content, re.S)
        criteria = json.loads(crit.group(1)) if crit else []
        return json.dumps({"criteria": [{"criterion": c, "met": True, "reason": "in evidence"}
                                        for c in criteria]})

    def _default_queries(self, content):
        return json.dumps({"queries": ["caregiver respite support programs"]})

    def _default_memory(self, content):
        return json.dumps({"candidates": []})

    def _default_chat(self, content):
        return "I'm here to help. Could you tell me a little more about your situation?"


def make_gateway(**overrides):
    llm = ScriptedLLM(**overrides)
    gw = LLMGateway(default_provider="scripted")
    gw.register_provider(llm)
    return gw, llm


SEARCH_RESULTS = {
    "default": [
        {"title": "Caregiver stress: Tips for taking care of yourself", "url":
         "https://www.mayoclinic.org/caregiver-stress", "content":
         "Caregiver stress can be reduced by accepting help, setting realistic goals and "
         "joining a support group.", "score": 0.9},
        {"title": "Respite care for caregivers - NIH", "url": "https://www.nia.nih.gov/respite",
         "content": "Respite care provides short-term relief for primary caregivers.",
         "score": 0.8},
    ]
}


class FakeSearch:
    """Configurable fake web_search with the same return shape as the real tool."""

    def __init__(self, results=None, fail_times=0, error="ConnectionError: reset by peer",
                 always_fail=False, empty=False):
        self.results = results if results is not None else SEARCH_RESULTS["default"]
        self.fail_times = fail_times
        self.error = error
        self.always_fail = always_fail
        self.empty = empty
        self.calls = []

    def __call__(self, query, max_results=5):
        self.calls.append(query)
        if self.always_fail or len(self.calls) <= self.fail_times:
            return {"success": False, "query": query, "count": 0, "answer": "", "results": [],
                    "error": self.error}
        if self.empty:
            return {"success": False, "query": query, "count": 0, "answer": "", "results": [],
                    "error": "ddgs: no results"}
        res = [dict(r, snippet=r["content"]) for r in self.results[:max_results]]
        return {"success": True, "query": query, "count": len(res), "answer": "",
                "results": res, "error": None}


class FakeReader:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.calls = []

    def __call__(self, urls):
        self.calls.append(urls)
        results = [{"url": u, "success": u in self.pages, "content": self.pages.get(u, "")}
                   for u in urls]
        ok = [r for r in results if r["success"]]
        return {"success": bool(ok), "results": results, "failed_results": [],
                "extracted_count": len(ok), "error": None if ok else "nothing extracted"}
