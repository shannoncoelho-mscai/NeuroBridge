from agent.memory.memory_store import save_memory


def save_approved_memory_candidates(
    user_id,
    candidates,
    approved_keys,
    explicit_consent=False,
    allow_sensitive=False
):
    """
    Saves only explicitly selected memory candidates.
    Never saves automatically.
    """

    if not user_id:
        return {"success": False, "error": "user_id_required", "saved": []}

    if not explicit_consent:
        return {
            "success": False,
            "error": "explicit_user_consent_required",
            "saved": []
        }

    approved_keys = set(approved_keys or [])
    saved = []
    rejected = []

    for candidate in candidates or []:
        key = candidate.get("key")

        if key not in approved_keys:
            continue

        if candidate.get("sensitive", False) and not allow_sensitive:
            rejected.append({
                "key": key,
                "reason": "sensitive_memory_requires_separate_approval"
            })
            continue

        result = save_memory(
            user_id=user_id,
            memory_type=candidate.get("memory_type", "long_term"),
            category=candidate.get("category", "other"),
            key=key,
            value=candidate.get("value", ""),
            consent=True,
            source="user_approved_candidate",
            ttl_days=candidate.get("suggested_ttl_days")
        )

        if result.get("success"):
            saved.append(key)
        else:
            rejected.append({
                "key": key,
                "reason": result.get("error", "save_failed")
            })

    return {
        "success": len(rejected) == 0,
        "saved": saved,
        "rejected": rejected,
        "saved_count": len(saved)
    }
