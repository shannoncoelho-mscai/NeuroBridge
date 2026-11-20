"""Research expansion / replanning queries (notebook cell 117, generalised).

The notebook built gap queries by pasting the whole goal plus a requirement sentence into
one query (hundreds of characters), which made search fail. Queries here are short.
"""
import re

from agent.research.jsonutil import extract_json

_STOP = {"the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "please", "use",
         "research", "find", "provide", "give", "me", "my", "i", "that", "this", "is", "are",
         "credible", "sources", "source", "summary", "concise", "links", "link", "do", "not",
         "any", "some", "about", "web", "search", "collect", "practical", "prepare", "help"}


def keyword_query(text, max_words=10):
    words = [w for w in re.findall(r"[\w'-]+", text or "") if w.lower() not in _STOP]
    return " ".join(words[:max_words])


def initial_queries(goal_text, n=2):
    base = keyword_query(goal_text)
    queries = [base] if base else [goal_text[:120]]
    if n > 1 and base:
        queries.append(base + " guidance")
    return queries[:n]


def gap_queries(gateway, goal_text, unmet_requirements, tried_queries, max_queries=3):
    """Ask the LLM for short new queries; fall back to keyword extraction."""
    queries = []
    if gateway is not None:
        try:
            prompt = (
                f"GOAL: {goal_text}\nUNMET REQUIREMENTS: {unmet_requirements}\n"
                f"ALREADY TRIED: {tried_queries}\n"
                f"Write up to {max_queries} NEW web search queries (each 3-10 words) that could "
                'close these gaps. Return JSON: {"queries": ["..."]}')
            response = gateway.generate(messages=[{"role": "user", "content": prompt}],
                                        system_prompt="Return JSON only.", temperature=0.3,
                                        max_tokens=300)
            data = extract_json(response.text) or {}
            queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()]
        except Exception:
            queries = []
    if not queries:
        queries = [keyword_query(f"{goal_text} {req}", 10) for req in unmet_requirements]
    tried = {q.lower() for q in tried_queries}
    out = []
    for q in queries:
        q = " ".join(q.split()[:12])
        if q and q.lower() not in tried and q not in out:
            out.append(q)
    return out[:max_queries]
