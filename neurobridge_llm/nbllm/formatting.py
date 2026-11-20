"""SFT formatting and response-only loss masking.

`build_supervised_example` works with any tokenizer exposing `apply_chat_template` and
`__call__(text, add_special_tokens=False) -> {"input_ids": [...]}` (Hugging Face
tokenizers do), so it is unit-testable without downloading a model. The approach is the one
validated in notebook cell 59/60 (prompt tokens -> label -100), made reusable.
"""
from nbllm.prompts import SYSTEM_PROMPT_VERSION, system_prompt

IGNORE_INDEX = -100


def to_messages(rec, style=None):
    msgs = [{"role": "system", "content": system_prompt(style)},
            {"role": "user", "content": rec["prompt"]}]
    if rec.get("response"):
        msgs.append({"role": "assistant", "content": rec["response"]})
    return msgs


def to_sft_row(rec):
    return {"id": rec["id"], "domain": rec.get("domain"), "source_set": rec["source_set"],
            "system_prompt_version": SYSTEM_PROMPT_VERSION,
            "synthetic": rec["synthetic"], "human_reviewed": rec["human_reviewed"],
            "messages": to_messages(rec)}


def build_supervised_example(tokenizer, messages, max_length):
    """Tokenize; mask everything except the assistant reply. Returns dict + truncation info."""
    if messages[-1]["role"] != "assistant":
        raise ValueError("Last message must be the assistant response")
    prompt_text = tokenizer.apply_chat_template(messages[:-1], tokenize=False,
                                                add_generation_prompt=True)
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    eos = getattr(tokenizer, "eos_token", None) or ""
    response_ids = tokenizer(messages[-1]["content"] + eos, add_special_tokens=False)["input_ids"]
    if len(prompt_ids) >= max_length:
        raise ValueError(f"Prompt alone ({len(prompt_ids)} tokens) exceeds max_length={max_length}")
    input_ids = (prompt_ids + response_ids)[:max_length]
    labels = ([IGNORE_INDEX] * len(prompt_ids) + response_ids)[:max_length]
    return {
        "input_ids": input_ids,
        "attention_mask": [1] * len(input_ids),
        "labels": labels,
        "truncated": len(prompt_ids) + len(response_ids) > max_length,
        "prompt_tokens": len(prompt_ids),
        "response_tokens": len(response_ids),
    }


class ResponseOnlyCollator:
    """Pads input_ids/attention_mask/labels; padded label positions are ignored."""

    def __init__(self, pad_token_id):
        self.pad_id = pad_token_id

    def __call__(self, batch):
        import torch
        n = max(len(x["input_ids"]) for x in batch)
        pad = lambda seq, v: seq + [v] * (n - len(seq))  # noqa: E731
        return {
            "input_ids": torch.tensor([pad(x["input_ids"], self.pad_id) for x in batch]),
            "attention_mask": torch.tensor([pad(x["attention_mask"], 0) for x in batch]),
            "labels": torch.tensor([pad(x["labels"], IGNORE_INDEX) for x in batch]),
        }
