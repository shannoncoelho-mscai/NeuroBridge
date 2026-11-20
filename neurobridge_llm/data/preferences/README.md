# Preference pairs (for ORPO/DPO, only after the gate passes)

No pairs exist yet. The 1,000 earlier pairs are in `data/raw/quarantine/` and fail the gate
(8 distinct strawman rejected answers).

Format: one JSON object per line in `pairs.jsonl`:

```json
{"prompt": "...", "chosen": "...", "rejected": "...",
 "rejection_reason": "plausible but overrides the person's autonomy",
 "human_reviewed": true, "reviewer": "name"}
```

Good sources of defensible `rejected` responses:
* real outputs of the base or SFT model that raters judged worse in `nbllm.human_eval`;
* plausible but flawed answers: too long or list-heavy for a low-energy user, generic,
  ignores a stated constraint, subtly directive, or misses a safety route.

Do not write absurd or hostile answers just to make training easy. `nbllm.orpo_gate`
rejects them.
