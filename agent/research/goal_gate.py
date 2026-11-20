"""Goal-completion gate (notebook cell 115) — now computed, not hand-entered.

A goal is COMPLETE only if: real (non-simulated) evidence exists, the answer passed
verification, and every success criterion is judged met. Criteria are judged by the LLM
against the answer + evidence; if that judgement is unavailable, criteria are reported as
'unknown' and the goal is NOT marked complete.
"""
import json

from agent.research.jsonutil import extract_json

GOAL_COMPLETE = "GOAL_COMPLETE"
QUALITY_APPROVED_BUT_INCOMPLETE = "QUALITY_APPROVED_BUT_GOAL_INCOMPLETE"
QUALITY_REJECTED = "QUALITY_REJECTED"
NO_EVIDENCE = "NO_EVIDENCE"


def judge_criteria(gateway, goal_text, criteria, answer, evidence_items):
    if not criteria:
        criteria = [f"The answer addresses the goal: {goal_text}"]
    prompt = (
        f"GOAL:\n{goal_text}\n\nANSWER:\n{answer}\n\nEVIDENCE:\n"
        f"{json.dumps(evidence_items, ensure_ascii=False)[:8000]}\n\n"
        f"CRITERIA:\n{json.dumps(criteria, ensure_ascii=False)}\n\n"
        "For each criterion decide if the ANSWER meets it using ONLY the evidence. Return JSON: "
        '{"criteria": [{"criterion": "...", "met": true, "reason": "..."}]}'
    )
    try:
        response = gateway.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You are a strict goal-completion judge. Return JSON only.",
            temperature=0.0, max_tokens=900)
        data = extract_json(response.text) or {}
        judged = data.get("criteria")
        if isinstance(judged, list) and judged:
            return [{"criterion": str(c.get("criterion", "")), "met": c.get("met") is True,
                     "reason": str(c.get("reason", ""))} for c in judged if isinstance(c, dict)]
    except Exception as exc:
        return [{"criterion": c, "met": None, "reason": f"judge unavailable: {exc}"}
                for c in criteria]
    return [{"criterion": c, "met": None, "reason": "judge returned invalid JSON"}
            for c in criteria]


def goal_gate(gateway, goal_text, criteria, answer, verification, evidence_items,
              simulated=False):
    if simulated:
        return {"status": QUALITY_REJECTED, "goal_complete": False, "criteria": [],
                "unmet_requirements": ["Run was simulated; no real work was performed."],
                "needs_research": False}
    if not evidence_items:
        return {"status": NO_EVIDENCE, "goal_complete": False, "criteria": [],
                "unmet_requirements": ["No evidence could be retrieved."], "needs_research": True}
    judged = judge_criteria(gateway, goal_text, criteria, answer, evidence_items)
    unmet = [c["criterion"] for c in judged if c["met"] is not True]
    quality = bool(verification.get("passed"))
    if quality and not unmet:
        status = GOAL_COMPLETE
    elif quality:
        status = QUALITY_APPROVED_BUT_INCOMPLETE
    else:
        status = QUALITY_REJECTED
    return {"status": status, "goal_complete": status == GOAL_COMPLETE, "criteria": judged,
            "unmet_requirements": unmet, "needs_research": status != GOAL_COMPLETE}
