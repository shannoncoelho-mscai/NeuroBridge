"""ORPO / preference-optimisation readiness gate.

  python -m nbllm.orpo_gate --pairs data/preferences/pairs.jsonl \
      --sft-run runs/sft_v1 --comparison runs/eval/report/comparison.json \
      --human runs/eval/human_scores.json --sft-tag sft_v1 --base-tag base

Preconditions from the project brief, each checked separately:
 1. a stable SFT model exists (run metadata + adapter);
 2. reliable evaluation exists: automatic comparison on shared prompts AND blinded human ratings;
 3. SFT is not worse than base on safety;
 4. preference pairs are meaningful: unique, human-reviewed, each with a documented
    rejection reason, and with rejected responses that are plausible (not strawmen).
Exit code 0 only if every check passes.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nbllm.schema import read_jsonl  # noqa: E402
from nbllm.quality import words, shingles, jaccard  # noqa: E402

# Dismissive / absurd patterns typical of artificial rejected answers.
STRAWMAN_RE = re.compile(
    r"\b(?:just (?:try harder|be more disciplined|get it done)|stop (?:worrying|making excuses|complaining)|"
    r"you (?:should not|shouldn't) be struggling|other people can manage|ignore how you feel|"
    r"don't ask for help|fix your attitude|this is easy|you are overthinking|"
    r"everyone has problems|stop being (?:so )?(?:dramatic|sensitive))\b", re.IGNORECASE)


def check_pairs(path, min_unique_rejected=0.9, min_len_ratio=0.4):
    rows = [r for _, r, e in read_jsonl(path) if r]
    issues = Counter()
    if not rows:
        return {"passed": False, "pairs": 0, "issues": {"no_pairs": 1}}
    rejected_texts = [r.get("rejected", "") for r in rows]
    uniq = len(set(rejected_texts)) / len(rows)
    for r in rows:
        p, c, rej = r.get("prompt", ""), r.get("chosen", ""), r.get("rejected", "")
        if not (p and c and rej):
            issues["missing_field"] += 1
            continue
        if c.strip() == rej.strip():
            issues["chosen_equals_rejected"] += 1
        if STRAWMAN_RE.search(rej):
            issues["strawman_rejected"] += 1
        if len(words(rej)) < min_len_ratio * len(words(c)):
            issues["rejected_much_shorter"] += 1
        if jaccard(shingles(rej, 2), shingles(p, 2)) == 0 and len(words(rej)) < 25:
            issues["rejected_ignores_prompt"] += 1
        if not (r.get("rejection_reason") or "").strip():
            issues["no_rejection_reason"] += 1
        if r.get("human_reviewed") is not True:
            issues["not_human_reviewed"] += 1
    n = len(rows)
    blocking = {k: v for k, v in issues.items() if v}
    passed = (uniq >= min_unique_rejected and not blocking.get("missing_field")
              and blocking.get("strawman_rejected", 0) <= 0.05 * n
              and blocking.get("rejected_much_shorter", 0) <= 0.2 * n
              and not blocking.get("no_rejection_reason") and not blocking.get("not_human_reviewed")
              and not blocking.get("chosen_equals_rejected"))
    return {"passed": passed, "pairs": n, "unique_rejected_ratio": round(uniq, 3),
            "distinct_rejected": len(set(rejected_texts)), "issues": dict(issues)}


def gate(pairs, sft_run=None, comparison=None, human=None, sft_tag="sft_v1", base_tag="base"):
    checks = {}
    run = Path(sft_run) if sft_run else None
    checks["stable_sft_model"] = bool(run and (run / "run_metadata.json").exists()
                                      and (run / "adapter").exists())
    comp = json.loads(Path(comparison).read_text()) if comparison and Path(comparison).exists() else None
    checks["automatic_evaluation"] = bool(comp and {sft_tag, base_tag} <= set(comp["models"])
                                          and comp["common_prompts"] >= 30)
    hum = json.loads(Path(human).read_text()) if human and Path(human).exists() else None
    checks["human_evaluation"] = bool(hum and hum.get("rated_rows", 0) >= 30)
    if comp and checks["automatic_evaluation"]:
        s, b = comp["summary"][sft_tag], comp["summary"][base_tag]
        checks["sft_not_less_safe"] = s["unsafe_outputs"] <= b["unsafe_outputs"] and \
            s["invented_contacts"] <= b["invented_contacts"]
    else:
        checks["sft_not_less_safe"] = False
    pair_report = check_pairs(pairs) if pairs and Path(pairs).exists() else {"passed": False,
                                                                             "issues": {"file_missing": 1}}
    checks["meaningful_preference_pairs"] = pair_report["passed"]
    return {"ready_for_orpo": all(checks.values()), "checks": checks, "pairs": pair_report}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nbllm.orpo_gate")
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--sft-run")
    ap.add_argument("--comparison")
    ap.add_argument("--human")
    ap.add_argument("--sft-tag", default="sft_v1")
    ap.add_argument("--base-tag", default="base")
    a = ap.parse_args(argv)
    res = gate(a.pairs, a.sft_run, a.comparison, a.human, a.sft_tag, a.base_tag)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["ready_for_orpo"] else 1)


if __name__ == "__main__":
    main()
