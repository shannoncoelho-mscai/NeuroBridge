"""ORPO on top of an SFT adapter (SFT -> SFT+ORPO).

  python -m nbllm.train_orpo --config configs/orpo_qwen15b_t4.json            # requires the gate to pass
  python -m nbllm.train_orpo --config configs/orpo_qwen15b_t4.json --ablation # research ablation

Objective (Hong et al., 2024, "ORPO: Monolithic Preference Optimization without Reference
Model"):  L = L_SFT(chosen) + lambda * L_OR,
  L_OR = -log sigmoid( log odds(chosen) - log odds(rejected) ),
  odds(y) = P(y|x) / (1 - P(y|x)),  log P(y|x) = mean token log-prob of y (length-normalised).

Implemented directly on transformers.Trainer (no TRL dependency, same reason as SFT).
The SFT LoRA weights are loaded as trainable and further trained, so the saved adapter is a
single SFT+ORPO adapter that the NeuroBridge provider serves as "nb_sft_orpo".

If nbllm.orpo_gate does not pass, training only runs with --ablation, and the run metadata,
adapter README and UI label all say so: the result must not be presented as a validated
improvement.
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
from nbllm.formatting import IGNORE_INDEX, to_messages  # noqa: E402
from nbllm.prompts import SYSTEM_PROMPT_VERSION  # noqa: E402
from nbllm import orpo_gate  # noqa: E402


def tokenize_pair(tok, pair, max_length):
    msgs = to_messages({"prompt": pair["prompt"]})
    prompt_text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    p_ids = tok(prompt_text, add_special_tokens=False)["input_ids"][: max_length // 2]
    eos = getattr(tok, "eos_token", None) or ""
    out = {}
    for side in ("chosen", "rejected"):
        r_ids = tok(pair[side] + eos, add_special_tokens=False)["input_ids"]
        ids = (p_ids + r_ids)[:max_length]
        labels = ([IGNORE_INDEX] * len(p_ids) + r_ids)[:max_length]
        out[f"{side}_input_ids"] = ids
        out[f"{side}_labels"] = labels
    return out


class PairCollator:
    def __init__(self, pad_id):
        self.pad = pad_id

    def __call__(self, batch):
        import torch
        out = {}
        for side in ("chosen", "rejected"):
            n = max(len(b[f"{side}_input_ids"]) for b in batch)
            ids = [b[f"{side}_input_ids"] + [self.pad] * (n - len(b[f"{side}_input_ids"])) for b in batch]
            lab = [b[f"{side}_labels"] + [IGNORE_INDEX] * (n - len(b[f"{side}_labels"])) for b in batch]
            att = [[1] * len(b[f"{side}_input_ids"]) + [0] * (n - len(b[f"{side}_input_ids"])) for b in batch]
            out[f"{side}_input_ids"] = torch.tensor(ids)
            out[f"{side}_labels"] = torch.tensor(lab)
            out[f"{side}_attention_mask"] = torch.tensor(att)
        return out


def sequence_logps(logits, labels):
    """Mean log-prob of label tokens per sequence (labels shifted by one)."""
    import torch
    logits = logits[:, :-1, :].float()
    labels = labels[:, 1:]
    mask = labels != IGNORE_INDEX
    safe = labels.clamp(min=0)
    logp = torch.log_softmax(logits, dim=-1).gather(-1, safe.unsqueeze(-1)).squeeze(-1)
    return (logp * mask).sum(-1) / mask.sum(-1).clamp(min=1)


def orpo_loss(chosen_logps, rejected_logps, chosen_nll, lam):
    """Returns (loss, log_odds_ratio, l_or). logps are length-normalised (<= 0)."""
    import torch
    import torch.nn.functional as F
    eps = 1e-6
    log_odds = (chosen_logps - rejected_logps) - (
        torch.log1p(-torch.exp(chosen_logps).clamp(max=1 - eps))
        - torch.log1p(-torch.exp(rejected_logps).clamp(max=1 - eps)))
    l_or = -F.logsigmoid(log_odds)
    return chosen_nll + lam * l_or.mean(), log_odds, l_or


def make_trainer_class():
    from transformers import Trainer

    class ORPOTrainer(Trainer):
        lam = 0.1
        history = []

        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            c = model(input_ids=inputs["chosen_input_ids"], attention_mask=inputs["chosen_attention_mask"],
                      labels=inputs["chosen_labels"])
            r = model(input_ids=inputs["rejected_input_ids"], attention_mask=inputs["rejected_attention_mask"])
            c_lp = sequence_logps(c.logits, inputs["chosen_labels"])
            r_lp = sequence_logps(r.logits, inputs["rejected_labels"])
            loss, log_odds, l_or = orpo_loss(c_lp, r_lp, c.loss, self.lam)
            self.history.append({"step": self.state.global_step, "loss": loss.item(),
                                 "nll_chosen": c.loss.item(), "l_or": l_or.mean().item(),
                                 "log_odds_ratio": log_odds.mean().item(),
                                 "logp_chosen": c_lp.mean().item(), "logp_rejected": r_lp.mean().item()})
            return (loss, c) if return_outputs else loss

    return ORPOTrainer


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nbllm.train_orpo")
    ap.add_argument("--config", required=True)
    ap.add_argument("--ablation", action="store_true",
                    help="Run even if the readiness gate fails; recorded as an ablation.")
    a = ap.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text())
    rel = lambda p: str((ROOT / p).resolve()) if p and not Path(p).is_absolute() else p  # noqa: E731
    pairs_path, sft_adapter, out_dir = rel(cfg["pairs"]), rel(cfg["sft_adapter"]), Path(rel(cfg["output_dir"]))

    gate = orpo_gate.gate(pairs_path, rel(cfg.get("sft_run")), rel(cfg.get("comparison")),
                          rel(cfg.get("human_scores")), cfg.get("sft_tag", "sft_v1"), cfg.get("base_tag", "base"))
    print(json.dumps({"gate": gate["checks"], "pairs": gate["pairs"]}, indent=2))
    if not gate["ready_for_orpo"] and not a.ablation:
        raise SystemExit("ORPO readiness gate failed. Fix the listed checks, or rerun with --ablation "
                         "to train a clearly-labelled research ablation.")

    import torch
    import transformers
    import peft
    from datasets import Dataset
    from transformers import AutoTokenizer, TrainingArguments
    from peft import PeftModel
    from nbllm.train_sft import load_base_for_training

    tok = AutoTokenizer.from_pretrained(cfg["base_model"])
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    pairs = [r for _, r, e in read_jsonl(pairs_path) if r]
    if not pairs:
        raise SystemExit(f"No preference pairs in {pairs_path}; nothing to train.")
    data = [tokenize_pair(tok, p, cfg["max_length"]) for p in pairs]
    model, cuda, bf16 = load_base_for_training(cfg)
    model = PeftModel.from_pretrained(model, sft_adapter, is_trainable=True)
    model.print_trainable_parameters()
    t = cfg["training"]
    args = TrainingArguments(
        output_dir=str(out_dir / "checkpoints"), num_train_epochs=t["epochs"],
        per_device_train_batch_size=t["batch_size"], gradient_accumulation_steps=t["grad_accum"],
        learning_rate=t["learning_rate"], lr_scheduler_type=t["scheduler"], warmup_ratio=t["warmup_ratio"],
        logging_steps=1, save_strategy="no", max_steps=t.get("max_steps", -1),
        fp16=cuda and not bf16, bf16=cuda and bf16,
        optim="paged_adamw_8bit" if cuda else "adamw_torch", gradient_checkpointing=cuda,
        use_cpu=not cuda, report_to="none", remove_unused_columns=False, seed=cfg["seed"])
    Trainer = make_trainer_class()
    Trainer.lam = cfg["lambda"]
    Trainer.history = []
    trainer = Trainer(model=model, args=args, train_dataset=Dataset.from_list(data),
                      data_collator=PairCollator(tok.pad_token_id))
    t0 = time.time()
    trainer.train()
    adapter_dir = out_dir / "adapter"
    trainer.save_model(str(adapter_dir))
    tok.save_pretrained(str(adapter_dir))
    hist = Trainer.history
    first, last = (hist[0], hist[-1]) if hist else ({}, {})
    meta = {
        "stage": "sft+orpo", "config": cfg, "config_file": a.config,
        "ablation": bool(a.ablation and not gate["ready_for_orpo"]),
        "gate": gate, "system_prompt_version": SYSTEM_PROMPT_VERSION,
        "pairs": len(pairs), "pairs_file_sha256": sha256_file(pairs_path),
        "sft_adapter": sft_adapter, "base_model": cfg["base_model"], "lambda": cfg["lambda"],
        "train_runtime_s": round(time.time() - t0, 1), "history": hist,
        "log_odds_ratio_first_last": [first.get("log_odds_ratio"), last.get("log_odds_ratio")],
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "transformers": transformers.__version__, "peft": peft.__version__},
        "gpu": torch.cuda.get_device_name(0) if cuda else "cpu (smoke test)",
        "note": ("A rising log-odds ratio shows the model learned to prefer 'chosen' over 'rejected' "
                 "on the training pairs. It is not evidence of better answers; run nbllm.evaluate "
                 "and nbllm.human_eval on held-out prompts."),
    }
    (out_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    if meta["ablation"]:
        (adapter_dir / "ABLATION_NOTICE.md").write_text(
            "This SFT+ORPO adapter was trained with --ablation: the ORPO readiness gate failed "
            f"({[k for k, v in gate['checks'].items() if not v]}). Do not present it as a validated "
            "improvement.\n")
    print("Adapter:", adapter_dir, "| ablation:", meta["ablation"],
          "| log-odds ratio first->last:", meta["log_odds_ratio_first_last"])


if __name__ == "__main__":
    main()
