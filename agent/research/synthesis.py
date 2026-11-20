"""Evidence-grounded synthesis (ported from notebook cells 102/130/151)."""
import json

SYNTHESIS_RULES = """RULES:
- Use ONLY the evidence below. Every factual sentence must end with citation ids like [S1].
- Never invent providers, organisations, phone numbers, e-mails, addresses, prices,
  qualifications, availability or URLs. If a detail is not in the evidence, say it is
  not confirmed.
- Clearly separate CONFIRMED (in evidence) from UNVERIFIED / MISSING information.
- Do not diagnose, recommend medication changes or give doses. Suggest consulting a
  qualified professional for clinical decisions.
- Be compassionate, practical and easy to understand. Keep it concise.
- End with a short "Sources" list: [S#] title — URL, only for sources you cited."""


def synthesize(gateway, goal_text, evidence_items, failed_queries=None, language_note=None,
               policy_note=None, max_tokens=3000):
    if not evidence_items:
        raise ValueError("Cannot synthesize without evidence.")
    prompt = (
        f"USER GOAL:\n{goal_text}\n\nEVIDENCE (id, title, url, text):\n"
        f"{json.dumps(evidence_items, ensure_ascii=False, indent=1)}\n\n"
        + (f"SEARCHES THAT FAILED OR FOUND NOTHING:\n{json.dumps(failed_queries)}\n\n"
           if failed_queries else "")
        + SYNTHESIS_RULES
        + (f"\n\nSAFETY NOTE:\n{policy_note}" if policy_note else "")
        + (f"\n\n{language_note}" if language_note else "")
    )
    response = gateway.generate(
        messages=[{"role": "user", "content": prompt}],
        system_prompt=("You are NeuroBridge's evidence-grounded synthesis engine for caregivers. "
                       "You cite sources and never fabricate."),
        temperature=0.2, max_tokens=max_tokens)
    return response.text
