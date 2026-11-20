"""Base-vs-fine-tuned evaluation.

  # 1) generate (GPU; run once per model on the SAME prompt files)
  python -m nbllm.evaluate generate --tag base --out runs/eval/base.jsonl \
      --prompts build/dataset_v1/eval_heldout_prompts.jsonl data/probes/safety_probes_v1.jsonl
  python -m nbllm.evaluate generate --tag sft_v1 --adapter runs/sft_v1/adapter --out runs/eval/sft_v1.jsonl ...
  # 2) score + compare (CPU)
  python -m nbllm.evaluate score runs/eval/base.jsonl runs/eval/sft_v1.jsonl --out runs/eval/report

Decoding is greedy (deterministic) and identical for all models; the same system prompt
is used for base and fine-tuned models so the comparison isolates the adapter.
"""
import argparse
import json
import platform
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from nbllm.schema import read_jsonl, write_jsonl  # noqa: E402
from nbllm.metrics import response_metrics, check_expectations  # noqa: E402
from nbllm.prompts import SYSTEM_PROMPT_VERSION, system_prompt  # noqa: E402

BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"


def load_prompts(paths):
    items = []
    for p in paths:
        for _, row, err in read_jsonl(p):
            if row and not err:
                row.setdefault("category", row.get("domain"))
                row["prompt_file"] = Path(p).name
                items.append(row)
    ids = [i["id"] for i in items]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    if dup:
        raise SystemExit(f"Duplicate prompt ids across files: {dup[:5]}")
    return items


def generate(args):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    torch.manual_seed(0)
    cuda = torch.cuda.is_available()
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.float16) if (args.four_bit and cuda) else None
    tok = AutoTokenizer.from_pretrained(args.adapter or args.base)
    model = AutoModelForCausalLM.from_pretrained(args.base, quantization_config=quant,
                                                 device_map="auto" if cuda else None,
                                                 torch_dtype=torch.float16 if cuda else torch.float32)
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()
    items = load_prompts(args.prompts)
    if args.limit:
        items = items[:args.limit]
    out, done = [], set()
    if Path(args.out).exists() and args.resume:
        out = [r for _, r, e in read_jsonl(args.out) if r]
        done = {r["id"] for r in out}
    meta = {"tag": args.tag, "base": args.base, "adapter": args.adapter, "four_bit": args.four_bit,
            "max_new_tokens": args.max_new_tokens, "decoding": "greedy",
            "repetition_penalty": args.repetition_penalty,
            "system_prompt_version": SYSTEM_PROMPT_VERSION,
            "python": platform.python_version(), "torch": torch.__version__}
    for n, item in enumerate(items, 1):
        if item["id"] in done:
            continue
        msgs = [{"role": "system", "content": system_prompt(item.get("style"))},
                {"role": "user", "content": item["prompt"]}]
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to(model.device)
        t0 = time.time()
        with torch.no_grad():
            y = model.generate(ids, attention_mask=torch.ones_like(ids),
                               max_new_tokens=args.max_new_tokens, do_sample=False,
                               min_new_tokens=args.min_new_tokens,
                               repetition_penalty=args.repetition_penalty,
                               pad_token_id=tok.pad_token_id or tok.eos_token_id)
        new = y[0][ids.shape[-1]:]
        text = tok.decode(new, skip_special_tokens=True).strip()
        out.append({"id": item["id"], "tag": args.tag, "category": item.get("category"),
                    "prompt_file": item["prompt_file"], "prompt": item["prompt"],
                    "expect": item.get("expect"), "response": text, "new_tokens": int(new.shape[-1]),
                    "hit_max_tokens": int(new.shape[-1]) >= args.max_new_tokens,
                    "seconds": round(time.time() - t0, 2), "meta": meta})
        if n % 5 == 0:
            write_jsonl(args.out, out)
            print(f"{n}/{len(items)}")
    write_jsonl(args.out, out)
    print("Saved", args.out)


def training_reference(dataset_dir):
    """4-gram set + style profile of the training responses (for a 'learning' signal)."""
    from nbllm.quality import words
    grams, prof = set(), {"words": [], "list_items": [], "ends_with_question": []}
    for _, r, e in read_jsonl(Path(dataset_dir) / "sft_train.jsonl"):
        if not r:
            continue
        text = r["messages"][-1]["content"]
        w = words(text)
        grams.update(" ".join(w[i:i + 4]) for i in range(max(0, len(w) - 3)))
        m = response_metrics(text)
        prof["words"].append(m["words"])
        prof["list_items"].append(m["list_items"])
        prof["ends_with_question"].append(text.rstrip().endswith("?"))
    profile = {k: round(sum(v) / max(1, len(v)), 3) for k, v in prof.items()}
    return grams, profile


def score_file(path, ref=None):
    from nbllm.quality import words
    rows = [r for _, r, e in read_jsonl(path) if r]
    scored = []
    for r in rows:
        m = response_metrics(r["response"])
        if ref:
            w = words(r["response"])
            g = [" ".join(w[i:i + 4]) for i in range(max(0, len(w) - 3))]
            m["train_4gram_overlap"] = round(sum(x in ref[0] for x in g) / len(g), 3) if g else 0.0
            m["ends_with_question"] = r["response"].rstrip().endswith("?")
        checks, human = check_expectations(r, r["response"], m)
        m["truncated"] = bool(r.get("hit_max_tokens"))
        scored.append({**r, "metrics": m, "checks": checks, "human_checks": human})
    return scored


def aggregate(scored):
    n = len(scored)
    if not n:
        return {}
    keys = ["words", "list_items", "questions", "distinct_1", "distinct_2",
            "repeated_trigram_ratio", "boilerplate_hits"]
    agg = {k: round(sum(s["metrics"][k] for s in scored) / n, 3) for k in keys}
    agg["n"] = n
    agg["truncated_rate"] = round(sum(s["metrics"]["truncated"] for s in scored) / n, 3)
    agg["unsafe_outputs"] = sum(s["metrics"]["unsafe_output"] for s in scored)
    agg["leaked_instruction"] = sum(s["metrics"]["leaked_instruction"] for s in scored)
    agg["invented_contacts"] = sum(bool(s["metrics"]["invented_contacts"]) for s in scored)
    openings = Counter(s["metrics"]["opening"] for s in scored)
    agg["top_opening_share"] = round(openings.most_common(1)[0][1] / n, 3)
    all_checks = [v for s in scored for v in s["checks"].values()]
    agg["check_pass_rate"] = round(sum(all_checks) / len(all_checks), 3) if all_checks else None
    by_cat = defaultdict(list)
    for s in scored:
        if s.get("expect"):
            by_cat[s["category"]].extend(s["checks"].values())
    agg["probe_pass_rate_by_category"] = {c: f"{sum(v)}/{len(v)}" for c, v in sorted(by_cat.items())}
    agg["needs_human_review"] = sum(bool(s["human_checks"]) for s in scored)
    if "train_4gram_overlap" in scored[0]["metrics"]:
        agg["train_4gram_overlap"] = round(sum(s["metrics"]["train_4gram_overlap"] for s in scored) / n, 3)
        agg["ends_with_question_rate"] = round(sum(s["metrics"]["ends_with_question"] for s in scored) / n, 3)
    return agg


def compare(files, out_dir, train_ref_dir=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ref = training_reference(train_ref_dir) if train_ref_dir else None
    per_model = {}
    for f in files:
        scored = score_file(f, ref)
        tag = scored[0]["tag"] if scored else Path(f).stem
        per_model[tag] = scored
        write_jsonl(out / f"scored_{tag}.jsonl", scored)
    ids = [set(s["id"] for s in v) for v in per_model.values()]
    common = set.intersection(*ids) if ids else set()
    if any(len(i) != len(common) for i in ids):
        print("WARNING: models were not run on identical prompt sets; comparing the intersection only")
    summary = {tag: aggregate([s for s in v if s["id"] in common]) for tag, v in per_model.items()}
    # paired failures: which checks fail per model on the same prompt
    failures = defaultdict(dict)
    for tag, v in per_model.items():
        for s in v:
            if s["id"] in common:
                failed = [k for k, ok in s["checks"].items() if not ok]
                if failed:
                    failures[s["id"]][tag] = failed
    report = {"models": list(per_model), "common_prompts": len(common), "summary": summary,
              "training_style_profile": ref[1] if ref else None,
              "failures": failures,
              "interpretation": ("Automatic screening only. Differences here are not evidence that "
                                 "a model is more helpful or empathetic; use the blinded human ratings.")}
    (out / "comparison.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (out / "comparison.md").write_text(markdown_report(report), encoding="utf-8")
    return report


def markdown_report(rep):
    tags = rep["models"]
    rows = ["n", "words", "list_items", "questions", "distinct_2", "repeated_trigram_ratio",
            "boilerplate_hits", "truncated_rate", "top_opening_share", "unsafe_outputs",
            "leaked_instruction", "invented_contacts", "check_pass_rate", "needs_human_review",
            "train_4gram_overlap", "ends_with_question_rate"]
    md = [f"# Model comparison ({rep['common_prompts']} shared prompts)", "",
          "> " + rep["interpretation"], "",
          ("> **Learning signal:** `train_4gram_overlap` is the share of each reply's 4-word phrases "
           "that also occur in the training responses, and `ends_with_question_rate` tracks a habit "
           "of the training data. A rise from base to SFT/ORPO shows the model learned from the data; "
           f"it does not by itself mean the answers are better. Training-data profile: "
           f"{rep.get('training_style_profile')}") if rep.get("training_style_profile") else "",
          "", "| metric | " + " | ".join(tags) + " |",
          "|---|" + "---|" * len(tags)]
    for r in rows:
        md.append(f"| {r} | " + " | ".join(str(rep["summary"][t].get(r)) for t in tags) + " |")
    md += ["", "## Probe pass rate by category", "", "| category | " + " | ".join(tags) + " |",
           "|---|" + "---|" * len(tags)]
    cats = sorted({c for t in tags for c in rep["summary"][t].get("probe_pass_rate_by_category", {})})
    for c in cats:
        md.append(f"| {c} | " + " | ".join(rep["summary"][t]["probe_pass_rate_by_category"].get(c, "-")
                                           for t in tags) + " |")
    md += ["", "## Failed checks per prompt", ""]
    for pid, by in sorted(rep["failures"].items()):
        md.append(f"* **{pid}**: " + "; ".join(f"{t}: {', '.join(f)}" for t, f in by.items()))
    return "\n".join(md) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nbllm.evaluate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--tag", required=True)
    g.add_argument("--base", default=BASE_MODEL)
    g.add_argument("--adapter")
    g.add_argument("--prompts", nargs="+", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--max-new-tokens", type=int, default=384)
    g.add_argument("--min-new-tokens", type=int, default=0)
    g.add_argument("--repetition-penalty", type=float, default=1.0)
    g.add_argument("--limit", type=int, help="only the first N prompts (smoke tests)")
    g.add_argument("--no-4bit", dest="four_bit", action="store_false")
    g.add_argument("--resume", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("files", nargs="+")
    s.add_argument("--out", required=True)
    s.add_argument("--train-ref", help="dataset dir; adds train_4gram_overlap (learning signal)")
    a = ap.parse_args(argv)
    if a.cmd == "generate":
        generate(a)
        return
    else:
        rep = compare(a.files, a.out, a.train_ref)
        print(json.dumps(rep["summary"], indent=2))


if __name__ == "__main__":
    main()
