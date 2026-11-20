"""Self-correction (notebook cell 110), controller (cell 112), deterministic redaction."""
import json
import re

from agent.research.verification import URL_RE


def correct_answer(gateway, goal_text, original_answer, verification, evidence_items):
    det = verification.get("deterministic", {})
    llm = verification.get("llm", {})
    feedback = {
        "critical_issues": det.get("critical_issues", []),
        "unsupported_claims": det.get("unsupported_claims", []),
        "issues": det.get("issues", []) + list(llm.get("issues", []) or []),
        "llm_unsupported_claims": llm.get("unsupported_claims", []),
        "missing_information": llm.get("missing_information", []),
    }
    prompt = (
        f"USER GOAL:\n{goal_text}\n\nORIGINAL ANSWER:\n{original_answer}\n\n"
        f"VERIFIER FEEDBACK:\n{json.dumps(feedback, ensure_ascii=False, indent=1)}\n\n"
        f"EVIDENCE:\n{json.dumps(evidence_items, ensure_ascii=False, indent=1)[:10000]}\n\n"
        "Revise the answer to fix every issue. REMOVE any provider, organisation, URL, phone, "
        "e-mail or price that is not in the evidence. Cite [S#] for every factual sentence. "
        "Label missing details as not confirmed. No diagnosis or medication advice. "
        "Return the revised answer only."
    )
    response = gateway.generate(
        messages=[{"role": "user", "content": prompt}],
        system_prompt=("You are NeuroBridge's self-correction engine. Never fabricate evidence "
                       "to make an answer look complete."),
        temperature=0.1, max_tokens=3000)
    return response.text


def choose_answer(original, original_v, revised, revised_v, threshold=80):
    """Deterministic controller: accept a revision only if it verifies and does not regress."""
    o_score, r_score = original_v.get("score", 0), revised_v.get("score", 0)
    if revised_v.get("passed") and r_score >= threshold and r_score >= o_score:
        return {"decision": "ACCEPT_REVISION", "answer": revised, "verification": revised_v}
    if original_v.get("passed") and o_score >= threshold:
        return {"decision": "KEEP_ORIGINAL", "answer": original, "verification": original_v}
    better = (revised, revised_v) if r_score >= o_score else (original, original_v)
    return {"decision": "REJECT_BOTH", "answer": better[0], "verification": better[1]}


def redact_unsupported(answer, deterministic_report):
    """Last resort: drop sentences containing unsupported hard facts and mark the removal."""
    bad_values = [str(i["value"]) for i in deterministic_report.get("critical_issues", [])
                  if i["type"] != "invalid_citation"]
    bad_values += [str(i["value"]) for i in deterministic_report.get("unsupported_claims", [])]
    invalid_cites = [v for i in deterministic_report.get("critical_issues", [])
                     if i["type"] == "invalid_citation" for v in i["value"]]
    if not bad_values and not invalid_cites:
        return answer, 0
    removed = 0
    out_lines = []
    for line in answer.splitlines():
        sentences = re.split(r"(?<=[.!?])\s+", line)
        kept = []
        for sentence in sentences:
            if any(v and v in sentence for v in bad_values):
                removed += 1
                continue
            for cite in invalid_cites:
                sentence = sentence.replace(f"[{cite}]", "")
            kept.append(sentence)
        out_lines.append(" ".join(kept))
    text = "\n".join(out_lines).strip()
    if removed:
        text += ("\n\nNote: NeuroBridge removed {} statement(s) that could not be matched to "
                 "any retrieved source.").format(removed)
    return text, removed


def strip_unlisted_urls(answer, allowed_urls):
    allowed = {u.rstrip("/").lower() for u in allowed_urls}
    return URL_RE.sub(lambda m: m.group(0) if m.group(0).rstrip(".,;:!?)").rstrip("/").lower()
                      in allowed else "[link removed: not in sources]", answer)
