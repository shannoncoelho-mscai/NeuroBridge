
import json
import re

MEMORY_EXTRACTION_PROMPT = """
You are NeuroBridge's memory suggestion engine.

Review the conversation and identify only information that may be useful
for future conversations with this same user.

Return JSON only:
{
  "candidates": [
    {
      "key": "short_stable_key",
      "category": "preference|care_context|goal|schedule|other",
      "memory_type": "long_term|short_term",
      "value": "fact stated by user",
      "reason": "why this may help later",
      "sensitive": false,
      "suggested_ttl_days": null
    }
  ]
}

Rules:
- Extract facts explicitly stated by the user.
- Do not infer facts or invent details.
- Do not include assistant-generated claims.
- Avoid passwords, account numbers, addresses, financial secrets,
  or highly sensitive information.
- Health information, diagnoses, medication, and detailed medical history
  must be marked sensitive=true and must not be recommended for automatic saving.
- Long-term: stable preferences, recurring goals, general context.
- Short-term: active tasks, temporary constraints, current plans.
- Short-term memories should usually have an expiry.
- Do not repeat existing memories.
- If there is nothing appropriate to remember, return an empty candidates list.
"""

def extract_memory_candidates(gateway, conversation_text, existing_memories=None):
    existing_memories = existing_memories or []

    messages = [{
        "role": "user",
        "content": (
            "CONVERSATION:\n" + conversation_text +
            "\n\nEXISTING MEMORIES:\n" +
            json.dumps(existing_memories, ensure_ascii=False)
        )
    }]

    response = gateway.generate(
        messages=messages,
        system_prompt=MEMORY_EXTRACTION_PROMPT,
        temperature=0.1,
        max_tokens=1200
    )

    text = response.text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Memory extractor returned invalid JSON.")
        data = json.loads(text[start:end+1])

    candidates = data.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("Invalid memory candidates.")

    # Safety validation
    safe_candidates = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        value = str(candidate.get("value", "")).strip()
        key = str(candidate.get("key", "")).strip()
        mem_type = candidate.get("memory_type")

        if not value or not key:
            continue
        if mem_type not in ("long_term", "short_term"):
            continue

        candidate["sensitive"] = bool(candidate.get("sensitive", False))
        candidate["consent_required"] = True
        candidate["save_allowed_by_extractor"] = False

        safe_candidates.append(candidate)

    return {
        "candidates": safe_candidates,
        "requires_user_approval": True,
        "provider": getattr(response, "provider", None),
    }
