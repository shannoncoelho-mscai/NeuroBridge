"""Blinded pairwise human evaluation.

  python -m nbllm.human_eval make-sheet runs/eval/base.jsonl runs/eval/sft_v1.jsonl \
      --sheet runs/eval/rating_sheet.csv --key runs/eval/rating_key.json
  # raters fill the sheet (do NOT give them the key)
  python -m nbllm.human_eval score --sheet filled.csv --key runs/eval/rating_key.json

Rubric (1-5 per response): relevance, helpfulness, empathy, specificity, autonomy_respect;
safety_ok (y/n) per response; overall preference (A/B/tie). Results are reported with
bootstrap 95% CIs; with few prompts the CI will be wide, which is the honest answer.
"""
import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nbllm.schema import read_jsonl  # noqa: E402

CRITERIA = ["relevance", "helpfulness", "empathy", "specificity", "autonomy_respect"]
RUBRIC = {
    "relevance": "Addresses this person's specific situation (1=generic, 5=specific to what they said)",
    "helpfulness": "Gives something usable now, in a manageable amount (1=unusable/overwhelming, 5=very usable)",
    "empathy": "Acknowledges feelings without being formulaic or excessive (1=cold/formulaic, 5=genuine)",
    "specificity": "Concrete steps or wording rather than platitudes (1=platitudes, 5=concrete)",
    "autonomy_respect": "Offers choices; respects the person and the cared-for person (1=directive/controlling, 5=respectful)",
}


def make_sheet(file_a, file_b, sheet, key, seed=13, raters=1):
    a = {r["id"]: r for _, r, e in read_jsonl(file_a) if r}
    b = {r["id"]: r for _, r, e in read_jsonl(file_b) if r}
    ids = sorted(set(a) & set(b))
    rng = random.Random(seed)
    rng.shuffle(ids)
    key_rows = {}
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        header = ["item", "rater", "prompt", "response_A", "response_B"]
        for side in "AB":
            header += [f"{c}_{side}" for c in CRITERIA] + [f"safety_ok_{side}"]
        header += ["preference(A/B/tie)", "comments"]
        w.writerow(header)
        for n, pid in enumerate(ids, 1):
            flip = rng.random() < 0.5
            left, right = (b[pid], a[pid]) if flip else (a[pid], b[pid])
            item = f"I{n:03d}"
            key_rows[item] = {"id": pid, "A": left["tag"], "B": right["tag"]}
            for rater in range(1, raters + 1):
                w.writerow([item, f"R{rater}", left["prompt"], left["response"], right["response"]]
                           + [""] * (2 * (len(CRITERIA) + 1) + 2))
    Path(key).write_text(json.dumps({"models": [next(iter(a.values()))["tag"], next(iter(b.values()))["tag"]],
                                     "seed": seed, "rubric": RUBRIC, "items": key_rows}, indent=2))
    return len(ids)


def _bootstrap(values, rng, n=2000):
    if not values:
        return None, None, None
    means = []
    for _ in range(n):
        s = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(s) / len(s))
    means.sort()
    return round(sum(values) / len(values), 3), round(means[int(0.025 * n)], 3), round(means[int(0.975 * n)], 3)


def score(sheet, key, seed=0):
    k = json.loads(Path(key).read_text())
    m1, m2 = k["models"]
    rng = random.Random(seed)
    diffs = {c: [] for c in CRITERIA}
    wins = []            # +1 m2 preferred, -1 m1 preferred, 0 tie
    safety = {m1: [0, 0], m2: [0, 0]}
    skipped = 0
    with open(sheet, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            item = k["items"].get(row["item"])
            if not item:
                continue
            side_model = {"A": item["A"], "B": item["B"]}
            try:
                vals = {s: {c: float(row[f"{c}_{s}"]) for c in CRITERIA} for s in "AB"}
            except (ValueError, KeyError):
                skipped += 1
                continue
            for c in CRITERIA:
                v1 = vals["A"][c] if side_model["A"] == m1 else vals["B"][c]
                v2 = vals["A"][c] if side_model["A"] == m2 else vals["B"][c]
                if not all(1 <= v <= 5 for v in (v1, v2)):
                    raise SystemExit(f"Score out of range in {row['item']}")
                diffs[c].append(v2 - v1)
            for s in "AB":
                ok = (row.get(f"safety_ok_{s}") or "").strip().lower()
                if ok in ("y", "n", "yes", "no"):
                    safety[side_model[s]][1] += 1
                    safety[side_model[s]][0] += ok.startswith("y")
            pref = (row.get("preference(A/B/tie)") or "").strip().upper()
            if pref in ("A", "B"):
                wins.append(1 if side_model[pref] == m2 else -1)
            elif pref == "TIE":
                wins.append(0)
    result = {"comparison": f"{m2} minus {m1}", "rated_rows": len(wins), "skipped_incomplete": skipped,
              "criteria_mean_difference_95ci": {c: _bootstrap(v, rng) for c, v in diffs.items()},
              "preference": {f"{m2}_wins": wins.count(1), f"{m1}_wins": wins.count(-1),
                             "ties": wins.count(0),
                             f"{m2}_win_rate_excl_ties_95ci": _bootstrap(
                                 [1.0 if w == 1 else 0.0 for w in wins if w != 0], rng)},
              "safety_ok_rate": {m: (f"{a}/{n}" if n else None) for m, (a, n) in safety.items()}}
    sig = [c for c, (mean, lo, hi) in result["criteria_mean_difference_95ci"].items()
           if lo is not None and (lo > 0 or hi < 0)]
    result["criteria_with_ci_excluding_zero"] = sig
    result["conclusion_guidance"] = (
        "Only criteria whose 95% CI excludes zero support a directional claim. "
        "If none do, report 'no detectable difference', not 'improvement'.")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nbllm.human_eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make-sheet")
    m.add_argument("file_a")
    m.add_argument("file_b")
    m.add_argument("--sheet", required=True)
    m.add_argument("--key", required=True)
    m.add_argument("--raters", type=int, default=1)
    s = sub.add_parser("score")
    s.add_argument("--sheet", required=True)
    s.add_argument("--key", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "make-sheet":
        print("Items:", make_sheet(a.file_a, a.file_b, a.sheet, a.key, raters=a.raters))
    else:
        print(json.dumps(score(a.sheet, a.key), indent=2))


if __name__ == "__main__":
    main()
