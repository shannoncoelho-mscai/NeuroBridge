"""QLoRA SFT for NeuroBridge with response-only loss.

  python -m nbllm.train_sft --config configs/sft_qwen15b_t4.json --dry-run   # tokenizer only
  python -m nbllm.train_sft --config configs/sft_qwen15b_t4.json             # GPU training

Uses plain transformers.Trainer + a custom collator (no TRL dependency) because TRL API
changes broke 04_train_sft.py repeatedly in the notebook. Writes run_metadata.json with the
config, dataset file hashes, package versions, loss history and the best checkpoint.
"""
import argparse
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nbllm.schema import read_jsonl, sha256_file  # noqa: E402
from nbllm.formatting import build_supervised_example, ResponseOnlyCollator  # noqa: E402
from nbllm.prompts import SYSTEM_PROMPT_VERSION  # noqa: E402


def load_split(path):
    rows = [r for _, r, e in read_jsonl(path) if r]
    bad = [r["id"] for r in rows if r.get("system_prompt_version") != SYSTEM_PROMPT_VERSION]
    if bad:
        raise SystemExit(f"{len(bad)} rows were formatted with a different system prompt version; "
                         "rebuild the dataset.")
    return rows


def tokenize_rows(tok, rows, max_length):
    out, stats = [], {"truncated": 0, "max_total": 0, "response_tokens": [], "skipped_prompt_too_long": 0}
    for r in rows:
        try:
            ex = build_supervised_example(tok, r["messages"], max_length)
        except ValueError:
            stats["skipped_prompt_too_long"] += 1
            continue
        stats["truncated"] += ex["truncated"]
        stats["max_total"] = max(stats["max_total"], ex["prompt_tokens"] + ex["response_tokens"])
        stats["response_tokens"].append(ex["response_tokens"])
        out.append({k: ex[k] for k in ("input_ids", "attention_mask", "labels")})
    rt = stats.pop("response_tokens")
    stats["mean_response_tokens"] = round(sum(rt) / max(1, len(rt)), 1)
    return out, stats


def load_base_for_training(cfg, use_gradient_checkpointing=True):
    """4-bit QLoRA on GPU; full-precision on CPU only when cfg['allow_cpu'] (smoke tests)."""
    import torch
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig, set_seed
    from peft import prepare_model_for_kbit_training
    cuda = torch.cuda.is_available()
    if not cuda and not cfg.get("allow_cpu"):
        raise SystemExit("A GPU is required (Colab: Runtime > Change runtime type > T4 GPU).")
    set_seed(cfg["seed"])
    bf16 = cuda and torch.cuda.is_bf16_supported()
    if cuda and cfg.get("quantize_4bit", True):
        dtype = torch.bfloat16 if bf16 else torch.float16
        quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                   bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype)
        model = AutoModelForCausalLM.from_pretrained(cfg["base_model"], quantization_config=quant,
                                                     device_map="auto")
        model.config.use_cache = False
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=use_gradient_checkpointing)
    else:
        model = AutoModelForCausalLM.from_pretrained(cfg["base_model"])
        model.config.use_cache = False
    return model, cuda, bf16


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nbllm.train_sft")
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text())
    data_dir = (ROOT / cfg["dataset_dir"]).resolve()
    out_dir = (ROOT / cfg["output_dir"]).resolve()
    train_rows = load_split(data_dir / "sft_train.jsonl")
    val_rows = load_split(data_dir / "sft_validation.jsonl")

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(cfg["base_model"])
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    train_ds, tstats = tokenize_rows(tok, train_rows, cfg["max_length"])
    val_ds, vstats = tokenize_rows(tok, val_rows, cfg["max_length"])
    print(json.dumps({"train_examples": len(train_ds), "validation_examples": len(val_ds),
                      "train_tokens": tstats, "validation_tokens": vstats}, indent=2))
    if tstats["truncated"] or vstats["truncated"]:
        print("WARNING: some examples exceed max_length and were truncated")
    if a.dry_run:
        return

    import torch
    import transformers
    import peft
    from datasets import Dataset
    from transformers import Trainer, TrainingArguments
    from peft import LoraConfig, get_peft_model
    model, cuda, bf16 = load_base_for_training(cfg)
    lc = cfg["lora"]
    model = get_peft_model(model, LoraConfig(r=lc["r"], lora_alpha=lc["alpha"],
                                             lora_dropout=lc["dropout"], bias="none",
                                             task_type="CAUSAL_LM",
                                             target_modules=lc["target_modules"]))
    model.print_trainable_parameters()
    t = cfg["training"]
    args = TrainingArguments(
        output_dir=str(out_dir / "checkpoints"), num_train_epochs=t["epochs"],
        per_device_train_batch_size=t["batch_size"], per_device_eval_batch_size=1,
        gradient_accumulation_steps=t["grad_accum"], learning_rate=t["learning_rate"],
        lr_scheduler_type=t["scheduler"], warmup_ratio=t["warmup_ratio"],
        weight_decay=t["weight_decay"], logging_steps=1, eval_strategy="epoch",
        save_strategy="epoch", save_total_limit=t["epochs"], load_best_model_at_end=True,
        metric_for_best_model="eval_loss", greater_is_better=False,
        fp16=cuda and not bf16, bf16=cuda and bf16,
        optim="paged_adamw_8bit" if cuda else "adamw_torch", gradient_checkpointing=cuda,
        max_steps=t.get("max_steps", -1), use_cpu=not cuda,
        report_to="none", remove_unused_columns=False, seed=cfg["seed"], data_seed=cfg["seed"])
    trainer = Trainer(model=model, args=args, train_dataset=Dataset.from_list(train_ds),
                      eval_dataset=Dataset.from_list(val_ds),
                      data_collator=ResponseOnlyCollator(tok.pad_token_id))
    t0 = time.time()
    result = trainer.train()
    adapter_dir = out_dir / "adapter"
    trainer.save_model(str(adapter_dir))
    tok.save_pretrained(str(adapter_dir))
    history = trainer.state.log_history
    meta = {
        "config": cfg, "config_file": a.config, "system_prompt_version": SYSTEM_PROMPT_VERSION,
        "dataset_files": {f.name: sha256_file(f) for f in (data_dir / "sft_train.jsonl",
                                                            data_dir / "sft_validation.jsonl")},
        "dataset_report": json.loads((data_dir / "report.json").read_text())["counts"]
        if (data_dir / "report.json").exists() else None,
        "train_examples": len(train_ds), "validation_examples": len(val_ds),
        "token_stats": {"train": tstats, "validation": vstats},
        "train_runtime_s": round(time.time() - t0, 1), "train_loss": result.training_loss,
        "eval_losses": [h for h in history if "eval_loss" in h],
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "best_eval_loss": trainer.state.best_metric,
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "transformers": transformers.__version__, "peft": peft.__version__},
        "gpu": torch.cuda.get_device_name(0) if cuda else "cpu (smoke test)",
        "base_model": cfg["base_model"],
        "stage": "sft",
        "note": "Loss is not a quality measure. Run nbllm.evaluate and nbllm.human_eval.",
    }
    (out_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    print("Adapter:", adapter_dir, "| best eval loss:", trainer.state.best_metric)


if __name__ == "__main__":
    main()
