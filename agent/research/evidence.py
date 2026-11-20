"""Evidence collection, merging, classification and ranking.

Ported from notebook cells 123, 127, 128, 140 (previously notebook-only). Fixes:
- search results' text is read from "content" OR "snippet" (the notebook read only
  "content" while results stored "snippet", so every evidence item was empty);
- the classifier is no longer Goa-specific;
- each ranked item gets a stable citation id (S1, S2, ...) used by synthesis/verification.
"""
from urllib.parse import urlparse


def tool_result_succeeded(tool_result):
    status = str(getattr(tool_result, "status", "")).lower()
    payload = getattr(tool_result, "result", None)
    if "success" not in status:
        return False
    if isinstance(payload, dict) and payload.get("success") is False:
        return False
    return not getattr(tool_result, "error", None)


def record_tool_observations(state):
    """Convert ToolResults into AgentObservations (idempotent per call_id)."""
    existing = {
        str(o.content.get("call_id")) for o in state.observations
        if isinstance(o.content, dict) and o.content.get("call_id")
    }
    recorded = 0
    for tr in state.tool_results:
        call_id = str(getattr(tr, "call_id", ""))
        if call_id and call_id in existing:
            continue
        success = tool_result_succeeded(tr)
        state.add_observation(
            source=f"tool:{tr.tool_name}",
            content={"call_id": call_id, "tool_name": tr.tool_name,
                     "status": str(getattr(tr.status, "value", tr.status)),
                     "success": success, "result": tr.result, "error": tr.error},
            confidence=0.9 if success else 0.3,
        )
        existing.add(call_id)
        recorded += 1
    return {"recorded": recorded, "total": len(state.observations)}


def merge_evidence(state):
    """Collect unique search results from successful web_search observations."""
    pool, seen = [], set()
    ok = failed = 0
    for obs in state.observations:
        c = obs.content if isinstance(obs.content, dict) else None
        if not c or c.get("tool_name") != "web_search":
            continue
        if c.get("success") is not True:
            failed += 1
            continue
        ok += 1
        payload = c.get("result") or {}
        for item in payload.get("results") or []:
            url = item.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            pool.append({
                "source": obs.source,
                "query": payload.get("query", ""),
                "title": item.get("title", ""),
                "url": url,
                "content": item.get("content") or item.get("snippet") or "",
                "score": item.get("score"),
                "page_content": "",
            })
    return {"evidence": pool, "total_evidence": len(pool), "successful_searches": ok,
            "failed_searches": failed, "unique_sources": len(seen)}


def add_page_content(evidence_pool, reader_result):
    """Attach extracted page text (from web_page_reader) to matching evidence items."""
    by_url = {e["url"]: e for e in evidence_pool["evidence"]}
    added = 0
    for item in (reader_result or {}).get("results", []):
        if not item.get("success"):
            continue
        url = item.get("url", "")
        target = by_url.get(url)
        if target is None:
            target = {"source": "tool:web_page_reader", "query": "", "title": url, "url": url,
                      "content": "", "score": None, "page_content": ""}
            evidence_pool["evidence"].append(target)
            by_url[url] = target
        target["page_content"] = item.get("content", "")
        added += 1
    evidence_pool["total_evidence"] = len(evidence_pool["evidence"])
    return added


OFFICIAL_SUFFIXES = (".gov", ".gov.in", ".nic.in", ".gov.uk", ".nhs.uk", ".edu", ".ac.in",
                     ".ac.uk", ".mil", ".int")
ACADEMIC_DOMAINS = ("ncbi.nlm.nih.gov", "nih.gov", "who.int", "cdc.gov", "apa.org",
                    "nimhans.ac.in", "icmr.gov.in", "cochrane.org", "aap.org", "nice.org.uk")
DIRECTORY_TERMS = ("justdial", "practo", "psychologyindia", "lybrate", "sulekha", "yelp")


def classify_source(url, title=""):
    domain = urlparse(url or "").netloc.lower().replace("www.", "")
    if any(d in domain for d in ACADEMIC_DOMAINS):
        category, priority = "academic_professional", 5
    elif domain.endswith(OFFICIAL_SUFFIXES):
        category, priority = "government_official", 5
    elif any(t in domain for t in ("hospital", "clinic", "healthcare", "health")):
        category, priority = "healthcare_institution", 3
    elif any(t in domain for t in DIRECTORY_TERMS):
        category, priority = "directory_listing", 2
    else:
        category, priority = "general_source", 1
    return {"category": category, "priority": priority, "domain": domain,
            "classification_basis": "domain_heuristic", "requires_verification": True}


def rank_evidence(evidence_pool):
    ranked = [{**item, **classify_source(item.get("url", ""), item.get("title", ""))}
              for item in evidence_pool.get("evidence", [])]
    ranked.sort(key=lambda x: (x["priority"], bool(x.get("page_content")), x.get("score") or 0),
                reverse=True)
    for i, item in enumerate(ranked, 1):
        item["citation_id"] = f"S{i}"
    counts = {}
    for item in ranked:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return {"evidence": ranked, "total": len(ranked), "category_counts": counts,
            "ranking_method": "heuristic_domain_classification"}


def evidence_for_prompt(ranked, max_items=8, max_chars_per_item=1500):
    """Token-budgeted evidence list (ported idea from notebook cell 150)."""
    out = []
    for item in ranked.get("evidence", [])[:max_items]:
        text = (item.get("page_content") or "") or item.get("content", "")
        out.append({"id": item["citation_id"], "title": item.get("title", ""),
                    "url": item.get("url", ""), "source_category": item.get("category"),
                    "text": text[:max_chars_per_item]})
    return out


def evidence_text_corpus(ranked):
    """All retrieved text (titles, snippets, pages, URLs) for grounding checks."""
    parts = []
    for item in ranked.get("evidence", []):
        parts += [item.get("title", ""), item.get("content", ""), item.get("page_content", ""),
                  item.get("url", "")]
    return "\n".join(p for p in parts if p)
