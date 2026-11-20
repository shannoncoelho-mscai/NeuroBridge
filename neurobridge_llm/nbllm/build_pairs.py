"""Build ORPO preference pairs: chosen = curated/training response, rejected = base-model output.

  python -m nbllm.build_pairs export-prompts --dataset build/dataset_v2_with_12k --out runs/pairs/prompts.jsonl --limit 300
  python -m nbllm.evaluate generate --tag base --prompts runs/pairs/prompts.jsonl --out runs/pairs/base_outputs.jsonl
  python -m nbllm.build_pairs build --dataset build/dataset_v2_with_12k --generations runs/pairs/base_outputs.jsonl \
      --out data/preferences/pairs_auto_v1.jsonl

Rejected answers are the base model's own, plausible responses (not strawmen). Pairs are
marked human_reviewed=false; review them (keep/remove) before claiming anything. The gate
in nbllm.orpo_gate will keep failing until they are reviewed.
"""
import argparse
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nbllm.schema import read_jsonl, write_jsonl  # noqa: E402
from nbllm.metrics import response_metrics  # noqa: E402

REASON = "base-model output for the same prompt (automatically paired; not human-reviewed)"


def _train_rows(dataset):
    return [r for _, r, e in read_jsonl(Path(dataset) / "sft_train.jsonl") if r]


def export_prompts(dataset, out, limit=300, seed=11, per_source=None):
    rows = _train_rows(dataset)
    rng = random.Random(seed)
    by_src = {}
    for r in rows:
        by_src.setdefault(r["source_set"], []).append(r)
    picked = []
    # keep every curated example; sample the templated source down to the limit
    for src, items in sorted(by_src.items()):
        if src.startswith("templated"):
            continue
        picked += items
    remaining = max(0, limit - len(picked))
    for src, items in sorted(by_src.items()):
        if src.startswith("templated"):
            picked += rng.sample(items, min(remaining, len(items)))
    write_jsonl(out, [{"id": r["id"], "category": r.get("domain"), "prompt": r["messages"][1]["content"],
                       "source_set": r["source_set"]} for r in picked[:limit]])
    return len(picked[:limit]), Counter(r["source_set"] for r in picked[:limit])


def build(dataset, generations, out):
    rows = {r["id"]: r for r in _train_rows(dataset)}
    gens = [g for _, g, e in read_jsonl(generations) if g]
    pairs, skipped = [], Counter()
    for g in gens:
        r = rows.get(g["id"])
        if not r:
            skipped["unknown_id"] += 1
            continue
        chosen = r["messages"][-1]["content"]
        rejected = (g.get("response") or "").strip()
        if not rejected:
            skipped["empty_base_output"] += 1
            continue
        if rejected == chosen:
            skipped["identical"] += 1
            continue
        if response_metrics(chosen)["unsafe_output"]:
            skipped["unsafe_chosen"] += 1
            continue
        pairs.append({"id": g["id"], "prompt": r["messages"][1]["content"], "chosen": chosen,
                      "rejected": rejected, "rejection_reason": REASON, "human_reviewed": False,
                      "source_set": r["source_set"], "rejected_from": g.get("tag", "base"),
                      "rejected_truncated": bool(g.get("hit_max_tokens"))})
    write_jsonl(out, pairs)
    return len(pairs), dict(skipped)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nbllm.build_pairs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export-prompts")
    e.add_argument("--dataset", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--limit", type=int, default=300)
    b = sub.add_parser("build")
    b.add_argument("--dataset", required=True)
    b.add_argument("--generations", required=True)
    b.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "export-prompts":
        n, by = export_prompts(a.dataset, a.out, a.limit)
        print(f"Exported {n} prompts: {dict(by)}")
    else:
        n, skipped = build(a.dataset, a.generations, a.out)
        print(f"Built {n} pairs; skipped {skipped}")


if __name__ == "__main__":
    main()
