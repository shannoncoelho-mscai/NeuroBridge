# Training guide (Qwen2.5-1.5B-Instruct, QLoRA SFT)

**Status:** the training code is written and its data path is unit-tested. It has **not
been run** in this environment (no GPU, no model download). Run it in Colab with
`neurobridge_llm/NeuroBridge_LLM_Pipeline.ipynb`.

## Steps

```bash
cd neurobridge_llm
pip install -r requirements-train.txt          # pinned to versions that worked on Colab T4
python -m nbllm.pipeline build
python -m nbllm.train_sft --config configs/sft_qwen15b_t4.json --dry-run
python -m nbllm.train_sft --config configs/sft_qwen15b_t4.json
```

Output: `runs/sft_v1/adapter/` (LoRA adapter + tokenizer) and `runs/sft_v1/run_metadata.json`
(config, dataset hashes, package versions, GPU, loss history, best checkpoint).

## Design decisions

* **Response-only loss.** Prompt and system tokens are labelled −100. This is the approach
  validated in the notebook's `07_train_sft_v2.py`; the earlier `04_train_sft.py` lost it
  when `completion_only_loss` was deleted to fix a TRL version error.
* **Plain `transformers.Trainer`** with a custom collator. No TRL dependency, because TRL
  API changes broke the notebook scripts four times.
* **Same system prompt for training and serving** (`nbllm/prompts.py`, version
  `nb-sys-v1`). The trainer refuses data built with a different version.
* **Defaults for 64 examples:** 3 epochs, effective batch 4 (16 steps per epoch),
  LR 1e-4, cosine schedule, warm-up 10%, LoRA r=16/α=32 on all projection layers. The
  best checkpoint is chosen by validation loss.
* 4-bit NF4 with double quantisation; fp16 on T4 (bf16 where supported).

## What to expect honestly

With 64 synthetic examples, SFT can shift **style** (length, structure, tone). It cannot
add knowledge or make the model reliably safe. The previous 12k-template run reached a
train loss of 0.23 and learned the template's defects. A low loss is not a goal. Judge the
model only through `nbllm.evaluate` and `nbllm.human_eval` (see AI_MODEL_GUIDE.md).

## Using the 12k samples (`dataset_v2_with_12k`)

The templated 12k set can be used, but only with an explicit, recorded opt-in
(`accept_templated` in the config, which is written into the dataset card). The pipeline:
* removes exact duplicates (12,000 → 768 unique prompts);
* strips leaked instruction lines (6,000);
* fixes the broken splice (12,000);
* keeps flagging the set as templated (each line reused 21.5×).

Expect style-level learning: shorter replies, ending on a question, "one small step"
phrasing. It will not add knowledge. `dataset_v2_curated` (94 examples, no 12k) is the
comparison condition.

## Preference optimisation (ORPO)

`nbllm.train_orpo` implements ORPO (L = L_SFT + λ·L_OR, λ=0.1) directly and continues the
SFT LoRA, producing the SFT+ORPO adapter. Pairs come from `nbllm.build_pairs`: chosen is the
dataset answer, rejected is the base model's own answer to the same prompt. These are
plausible rejects, not strawmen, but they are **not human-reviewed**, so the gate fails and
ORPO runs only with `--ablation`. The ablation is labelled in `run_metadata.json`,
`adapter/ABLATION_NOTICE.md` and the UI model name. Verified on CPU with a tiny model:
L_OR starts at ≈ ln 2 and the run completes end to end.

### Gate (unchanged)

Not yet justified. `python -m nbllm.orpo_gate ...` must exit 0 first. It requires:
* an SFT run;
* an automatic comparison on ≥ 30 shared prompts;
* ≥ 30 human-rated rows;
* SFT not less safe than base;
* human-reviewed pairs that have rejection reasons and non-strawman rejected answers.

The existing 1,000 pairs fail.
