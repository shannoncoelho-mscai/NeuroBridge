"""NeuroBridge web search tool.

Provider order: Tavily (needs TAVILY_API_KEY + `tavily-python`) -> DuckDuckGo (`ddgs`).
Each result carries the text under BOTH "snippet" and "content" — the notebook version
stored "snippet" while the evidence merger read "content", which emptied all evidence.

Failures are returned as {"success": False, "error": ...}; the tool executor records them
as ToolStatus.FAILURE. Results are never invented.
"""
import os

MAX_QUERY_CHARS = 400


def _normalize(item, provider):
    text = item.get("content") or item.get("body") or item.get("snippet") or ""
    return {
        "title": item.get("title", "") or "",
        "url": item.get("url") or item.get("href") or "",
        "snippet": text,
        "content": text,
        "score": item.get("score"),
        "provider": provider,
    }


def _tavily_search(query, max_results):
    from tavily import TavilyClient  # optional dependency
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    params = dict(query=query, search_depth="advanced", max_results=max_results,
                  include_answer=True)
    country = os.environ.get("NEUROBRIDGE_SEARCH_COUNTRY", "india").strip()
    if country:
        params["country"] = country          # boosts results from this country
    try:
        response = client.search(**params)
    except TypeError:                        # older tavily-python without `country`
        params.pop("country", None)
        response = client.search(**params)
    return {
        "answer": response.get("answer", "") or "",
        "results": [_normalize(i, "tavily") for i in response.get("results", [])],
    }


def _ddgs_search(query, max_results):
    from ddgs import DDGS  # optional dependency
    with DDGS() as ddgs:
        items = list(ddgs.text(query, max_results=max_results))
    return {"answer": "", "results": [_normalize(i, "ddgs") for i in items]}


def available_providers():
    providers = []
    if os.environ.get("TAVILY_API_KEY"):
        try:
            import tavily  # noqa: F401
            providers.append("tavily")
        except ImportError:
            pass
    try:
        import ddgs  # noqa: F401
        providers.append("ddgs")
    except ImportError:
        pass
    return providers


def web_search(query: str, max_results: int = 5):
    query = (query or "").strip()
    if not query:
        return {"success": False, "query": query, "count": 0, "answer": "",
                "results": [], "error": "Empty query"}
    if len(query) > MAX_QUERY_CHARS:
        # Long paragraph-style queries made searches fail in the notebook (cell 121).
        query = query[:MAX_QUERY_CHARS]

    max_results = max(1, min(int(max_results or 5), 10))
    errors = []
    providers = available_providers()
    if not providers:
        return {"success": False, "query": query, "count": 0, "answer": "", "results": [],
                "error": "No search provider configured (set TAVILY_API_KEY and install "
                         "tavily-python, or install ddgs)."}

    for provider in providers:
        try:
            data = _tavily_search(query, max_results) if provider == "tavily" \
                else _ddgs_search(query, max_results)
            results = [r for r in data["results"] if r["url"]]
            if not results:
                errors.append(f"{provider}: no results")
                continue
            return {"success": True, "query": query, "count": len(results),
                    "answer": data["answer"], "results": results, "provider": provider,
                    "error": None}
        except Exception as exc:
            errors.append(f"{provider}: {type(exc).__name__}: {exc}")

    return {"success": False, "query": query, "count": 0, "answer": "", "results": [],
            "error": "; ".join(errors)}


def research_therapists(location="Panjim, Goa", age_group="children under 13"):
    """Kept for backward compatibility with the notebook."""
    queries = [
        f"child psychologist {location} {age_group}",
        f"pediatric psychologist {location}",
        f"child mental health services {location}",
    ]
    collected = [web_search(q, max_results=5) for q in queries]
    return {"success": any(r["success"] for r in collected), "location": location,
            "age_group": age_group, "research": collected}
