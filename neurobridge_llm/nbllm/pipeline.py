"""Dataset build pipeline.

    python -m nbllm.pipeline build  --config configs/dataset_v1.json
    python -m nbllm.pipeline review-export --config configs/dataset_v1.json   # CSV for humans
    python -m nbllm.pipeline review-import --csv reviews.csv --reviewer "Name"

Steps: load -> normalise -> human-review decisions -> record checks -> classification ->
dataset checks (exact/near duplicates, templating, openings) -> exclusion -> leakage-safe
split -> held-out eval set (+ overlap check against training) -> SFT formatting ->
dataset card + report + manifest.
"""
import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # neurobridge_llm/
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))                 # repo root (agent.*)

from nbllm.schema import load_source, write_jsonl, read_jsonl, sha256_file  # noqa: E402
from nbllm.quality import (normalize_text, check_record, dataset_checks,  # noqa: E402
                           templated_source_check, shingles, jaccard, repair_response)
from nbllm.classify import check_label  # noqa: E402
from nbllm.split import split_records  # noqa: E402
from nbllm.formatting import to_sft_row  # noqa: E402
from nbllm.prompts import SYSTEM_PROMPT_VERSION  # noqa: E402


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    cfg["_path"] = str(path)
    cfg["_hash"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
    return cfg


def load_reviews(path):
    if not path or not Path(path).exists():
        return {}
    out = {}
    for _, row, err in read_jsonl(path):
        if row and not err:
            out[row["id"]] = row  # last decision wins
    return out


def apply_review(rec, decision):
    d = decision["decision"]
    rec.human_reviewed = True
    if d == "remove":
        rec.flag("human_removed", "error", decision.get("notes", ""))
    elif d == "revise":
        if not decision.get("revised_response"):
            rec.flag("revise_without_text", "error")
        else:
            rec.original_response = rec.original_response or rec.response
            rec.response = decision["revised_response"]
            rec.revised = True
            rec.author = rec.author + "+human_revision"


def build(cfg, out_dir=None):
    base = ROOT
    version = cfg["version"]
    out = Path(out_dir or base / "build" / version)
    out.mkdir(parents=True, exist_ok=True)
    report = {"version": version, "built_at": datetime.now(timezone.utc).isoformat(),
              "config": cfg["_path"], "config_hash": cfg["_hash"],
              "system_prompt_version": SYSTEM_PROMPT_VERSION, "sources": [], "load_errors": []}

    records = []
    for spec in cfg["sources"]:
        recs, errs = load_source(spec, base)
        report["load_errors"] += errs
        files = sorted(base.glob(spec["glob"])) if "glob" in spec else [base / spec["path"]]
        report["sources"].append({"set": spec["set"], "role": spec["role"], "records": len(recs),
                                  "files": {str(f.relative_to(base)): sha256_file(f) for f in files}})
        records += recs
    repairs_by_set = {s["set"]: s.get("repairs", []) for s in cfg["sources"]}
    for r in records:
        r.prompt = normalize_text(r.prompt)
        r.response = normalize_text(r.response)
        if repairs_by_set.get(r.source_set):
            r.response, r.repairs = repair_response(r.response, repairs_by_set[r.source_set])
    report["repairs"] = dict(Counter(x for r in records for x in r.repairs))

    reviews = load_reviews(base / cfg.get("reviews_file", "data/reviews/decisions.jsonl"))
    for r in records:
        if r.id in reviews and r.role == "train_candidate":
            apply_review(r, reviews[r.id])

    qc = cfg["quality"]
    for r in records:
        check_record(r, qc)
        check_label(r)
    accepted = {s["set"]: s["accept_templated"] for s in cfg["sources"] if s.get("accept_templated")}
    report["templated_sources"] = templated_source_check(records, qc, accepted)
    report["accepted_templated_sources"] = accepted

    for r in records:
        if r.role == "quarantine":
            r.flag("quarantined_source", "error", "excluded by configuration")
    active = [r for r in records if r.role != "quarantine"]
    report["dataset_checks"] = dataset_checks(active, qc, {})

    train_pool = [r for r in active if r.role == "train_candidate" and not r.excluded]
    if cfg.get("require_human_review"):
        for r in train_pool:
            if not r.human_reviewed:
                r.flag("not_human_reviewed", "error", "require_human_review=true")
        train_pool = [r for r in train_pool if not r.excluded]
    splits = split_records(train_pool, tuple(cfg["split"]["ratios"]), tuple(cfg["split"]["names"]),
                           seed=cfg["split"]["seed"])

    # Held-out evaluation prompts: stratified sample, never overlapping training prompts.
    train_sh = [shingles(r.prompt) for r in train_pool]
    eval_pool = [r for r in active if r.role == "eval_prompts" and not r.excluded]
    leaks = 0
    clean_eval = []
    for r in eval_pool:
        s = shingles(r.prompt)
        if any(jaccard(s, t) >= qc["near_dup_threshold"] for t in train_sh):
            r.flag("overlaps_training_prompt", "error")
            leaks += 1
        else:
            clean_eval.append(r)
    by_cat = defaultdict(list)
    for r in sorted(clean_eval, key=lambda r: r.id):
        by_cat[r.domain or "unknown"].append(r)
    rng = random.Random(cfg["eval"]["seed"])
    heldout = []
    for cat in sorted(by_cat):
        picks = rng.sample(by_cat[cat], min(cfg["eval"]["per_category"], len(by_cat[cat])))
        heldout += sorted(picks, key=lambda r: r.id)
    report["eval"] = {"candidate_prompts": len(eval_pool), "overlapping_training_removed": leaks,
                      "heldout_prompts": len(heldout), "categories": len(by_cat)}

    # ---- write artifacts
    write_jsonl(out / "records_all.jsonl", [r.to_dict() for r in records])
    for name, rows in splits.items():
        write_jsonl(out / f"sft_{name}.jsonl", [to_sft_row(r.to_dict()) for r in rows])
    write_jsonl(out / "eval_heldout_prompts.jsonl",
                [{"id": r.id, "category": r.domain, "variation": r.variation, "prompt": r.prompt,
                  "source_set": r.source_set} for r in heldout])

    flag_counts = Counter((f["code"], f["severity"]) for r in records for f in r.flags)
    report["flags"] = {f"{c}:{s}": n for (c, s), n in sorted(flag_counts.items())}
    report["counts"] = {
        "total_records": len(records),
        "by_role": dict(Counter(r.role for r in records)),
        "train_candidates": sum(r.role == "train_candidate" for r in records),
        "excluded_train_candidates": sum(r.role == "train_candidate" and r.excluded for r in records),
        "splits": {k: len(v) for k, v in splits.items()},
        "split_domains": {k: dict(Counter(r.domain for r in v)) for k, v in splits.items()},
        "synthetic_in_training": sum(r.synthetic for r in train_pool),
        "human_reviewed_in_training": sum(r.human_reviewed for r in train_pool),
        "revised_in_training": sum(r.revised for r in train_pool),
        "repaired_in_training": sum(bool(r.repairs) for r in train_pool),
        "by_source_in_training": dict(Counter(r.source_set for r in train_pool)),
    }
    # leakage assertion: no cluster appears in two splits
    seen = {}
    for name, rows in splits.items():
        for r in rows:
            assert seen.setdefault(r.cluster_id, name) == name, f"cluster {r.cluster_id} leaked"
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (out / "DATASET_CARD.md").write_text(dataset_card(report), encoding="utf-8")
    return report, records, splits, heldout


def dataset_card(rep):
    c = rep["counts"]
    lines = [
        f"# NeuroBridge dataset {rep['version']}", "",
        f"Built {rep['built_at']} from `{rep['config']}` (config hash `{rep['config_hash']}`), "
        f"system prompt `{rep['system_prompt_version']}`.", "",
        "## Provenance and status", "",
        f"* Training examples by source: {c.get('by_source_in_training')}.",
        f"* Training examples: **{sum(c['splits'].values())}** "
        f"({', '.join(f'{k}: {v}' for k, v in c['splits'].items())}).",
        f"* Synthetic: **{c['synthetic_in_training']}**; human-reviewed: "
        f"**{c['human_reviewed_in_training']}**; revised: {c['revised_in_training']}.",
        "* All current training text is **assistant-authored synthetic data**. It is not "
        "clinically validated and not human-validated unless the human-reviewed count above "
        "says otherwise.",
        f"* Held-out evaluation prompts: {rep['eval']['heldout_prompts']} across "
        f"{rep['eval']['categories']} categories ({rep['eval']['overlapping_training_removed']} "
        "removed for overlapping training prompts). They have no reference answers; they are "
        "for comparing models.", "",
        "## Sources", "", "| set | role | records |", "|---|---|---|",
    ]
    lines += [f"| {s['set']} | {s['role']} | {s['records']} |" for s in rep["sources"]]
    lines += ["", "## Templated-source check", "",
              "| set | unique prompts | distinct lines | line reuse | templated |", "|---|---|---|---|---|"]
    lines += [f"| {k} | {v['records']} | {v['distinct_lines']} | {v.get('line_reuse')}× | "
              f"{('**yes — accepted by config**' if v.get('accepted_by_config') else '**yes — excluded**') if v['templated'] else 'no'} |"
              for k, v in rep["templated_sources"].items()]
    if rep.get("accepted_templated_sources"):
        lines += ["", "**Templated sources accepted by explicit configuration:**", ""]
        lines += [f"* `{k}` — reason given: {v}" for k, v in rep["accepted_templated_sources"].items()]
    if rep.get("repairs"):
        lines += ["", "**Deterministic repairs applied:** " +
                  ", ".join(f"{k} × {v}" for k, v in rep["repairs"].items())]
    lines += ["", "## Quality flags (all roles)", "", "| flag | count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rep["flags"].items()]
    lines += ["", "## Domains per split", ""]
    for split, doms in c["split_domains"].items():
        lines.append(f"* **{split}**: " + ", ".join(f"{d} {n}" for d, n in sorted(doms.items())))
    lines += ["", "## Known limitations", "",
              "* Small: tens of examples. Expect limited, style-level effects from SFT, not new "
              "knowledge.",
              "* Two authoring styles: seed (~300–450 chars) and v2 long-form (~1,400–2,800 "
              "chars). Response length is a confound in evaluation.",
              "* Keyword classifier and safety filters are heuristic; flags are prompts for human "
              "review, not ground truth."]
    return "\n".join(lines) + "\n"


REVIEW_FIELDS = ["id", "source_set", "domain", "flags", "prompt", "response",
                 "decision(keep/revise/remove)", "revised_response", "notes"]


def review_export(cfg, path):
    _, records, _, _ = build(cfg)
    rows = [r for r in records if r.role == "train_candidate"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(REVIEW_FIELDS)
        for r in rows:
            w.writerow([r.id, r.source_set, r.domain,
                        "; ".join(f"{x['code']}({x['severity']})" for x in r.flags),
                        r.prompt, r.response, "", "", ""])
    return len(rows)


def review_import(csv_path, reviewer, out_path):
    if not reviewer or not reviewer.strip():
        raise SystemExit("--reviewer is required: reviews must be attributable to a person.")
    decisions = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            d = (row.get("decision(keep/revise/remove)") or "").strip().lower()
            if not d:
                continue
            if d not in ("keep", "revise", "remove"):
                raise SystemExit(f"Invalid decision '{d}' for {row['id']}")
            decisions.append({"id": row["id"], "decision": d,
                              "revised_response": (row.get("revised_response") or "").strip() or None,
                              "notes": row.get("notes", ""), "reviewer": reviewer.strip(),
                              "reviewed_at": datetime.now(timezone.utc).isoformat()})
    existing = list(r for _, r, e in read_jsonl(out_path)) if Path(out_path).exists() else []
    write_jsonl(out_path, existing + decisions)
    return len(decisions)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nbllm.pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--config", default=str(ROOT / "configs" / "dataset_v1.json"))
    b.add_argument("--out")
    e = sub.add_parser("review-export")
    e.add_argument("--config", default=str(ROOT / "configs" / "dataset_v1.json"))
    e.add_argument("--csv", default=str(ROOT / "data" / "reviews" / "review_queue.csv"))
    i = sub.add_parser("review-import")
    i.add_argument("--csv", required=True)
    i.add_argument("--reviewer", required=True)
    i.add_argument("--out", default=str(ROOT / "data" / "reviews" / "decisions.jsonl"))
    a = ap.parse_args(argv)
    if a.cmd == "build":
        rep, *_ = build(load_config(a.config), a.out)
        print(json.dumps({"counts": rep["counts"], "eval": rep["eval"],
                          "templated_sources": rep["templated_sources"]}, indent=2))
    elif a.cmd == "review-export":
        Path(a.csv).parent.mkdir(parents=True, exist_ok=True)
        print(f"Wrote {review_export(load_config(a.config), a.csv)} rows to {a.csv}")
    else:
        print(f"Imported {review_import(a.csv, a.reviewer, a.out)} decisions into {a.out}")


if __name__ == "__main__":
    main()
