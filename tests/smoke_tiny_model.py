"""Build a tiny random Qwen2-architecture model + tokenizer offline (for smoke tests only).

Outputs are meaningless by design; the point is to execute the real training/serving code
paths (QLoRA-style LoRA SFT, ORPO, multi-adapter serving) without a GPU or downloads.
"""
import json
import sys
from pathlib import Path

CHAT_TEMPLATE = (
    "{% for m in messages %}<|im_start|>{{ m['role'] }}\n{{ m['content'] }}<|im_end|>\n{% endfor %}"
    "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}")


def build(out_dir, corpus_files):
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers, decoders
    from transformers import PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM
    import torch
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    texts = []
    for f in corpus_files:
        for line in Path(f).read_text(encoding="utf-8").splitlines()[:400]:
            if line.strip():
                row = json.loads(line)
                texts += [m["content"] for m in row.get("messages", [])] or [row.get("prompt", "")]
    tk = Tokenizer(models.BPE(unk_token="<unk>"))
    tk.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tk.decoder = decoders.ByteLevel()
    special = ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<unk>"]
    tk.train_from_iterator(texts, trainers.BpeTrainer(vocab_size=600, special_tokens=special,
                                                      initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    tok = PreTrainedTokenizerFast(tokenizer_object=tk, eos_token="<|im_end|>", pad_token="<|endoftext|>",
                                  unk_token="<unk>")
    tok.chat_template = CHAT_TEMPLATE
    tok.save_pretrained(out)
    torch.manual_seed(0)
    cfg = Qwen2Config(vocab_size=len(tok), hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                      num_attention_heads=2, num_key_value_heads=1, max_position_embeddings=2048,
                      eos_token_id=tok.eos_token_id, pad_token_id=tok.pad_token_id, tie_word_embeddings=True)
    Qwen2ForCausalLM(cfg).save_pretrained(out)
    return out


if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2:]))
