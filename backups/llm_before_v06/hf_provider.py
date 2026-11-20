"""Local Hugging Face providers: base model + NeuroBridge LoRA adapters (SFT, SFT+ORPO).

One base model is loaded once (LocalModelPool); each adapter is attached with its own name and
switched per request, so base / SFT / SFT+ORPO can all be served from a single T4.

Environment (agent/bootstrap.py):
  NEUROBRIDGE_LOCAL_MODEL     e.g. Qwen/Qwen2.5-1.5B-Instruct       -> provider "nb_base"
  NEUROBRIDGE_SFT_ADAPTER     runs/sft_v1/adapter                    -> provider "nb_sft"
  NEUROBRIDGE_ORPO_ADAPTER    runs/sft_orpo_v1/adapter               -> provider "nb_sft_orpo"
  NEUROBRIDGE_LOCAL_4BIT      1 (default) -> 4-bit on GPU

Errors raise (so the gateway can fall back); no canned text is ever returned.
"""
import json
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from .gateway import LLMResponse

_REPO = Path(__file__).resolve().parents[2]


def _training_system_prompt():
    sys.path.insert(0, str(_REPO / "neurobridge_llm"))
    try:
        from nbllm.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION
        return SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION
    except Exception:
        return None, None


def _run_metadata(adapter_path):
    """run_metadata.json sits next to the adapter dir (written by train_sft / train_orpo)."""
    if not adapter_path:
        return {}
    for cand in (Path(adapter_path) / "run_metadata.json", Path(adapter_path).parent / "run_metadata.json"):
        if cand.exists():
            try:
                m = json.loads(cand.read_text())
                return {"run": m.get("config", {}).get("run_name"), "stage": m.get("stage", "sft"),
                        "ablation": bool(m.get("ablation")), "gate_passed": m.get("gate", {}).get("ready_for_orpo"),
                        "train_examples": m.get("train_examples") or m.get("pairs"),
                        "best_eval_loss": m.get("best_eval_loss")}
            except Exception:
                return {}
    return {}


class LocalModelPool:
    def __init__(self, base_model, adapters=None, four_bit=True, device_map="auto"):
        self.base_model = base_model
        self.adapters = {k: v for k, v in (adapters or {}).items() if v}
        self.four_bit = four_bit
        self.device_map = device_map
        self.model = None
        self.tok = None
        self.lock = threading.Lock()

    def load(self):
        if self.model is not None:
            return
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        kwargs = {"device_map": self.device_map}
        if self.four_bit and torch.cuda.is_available():
            from transformers import BitsAndBytesConfig
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.float16)
        for name, path in self.adapters.items():
            if not Path(path).exists():
                raise RuntimeError(f"Adapter '{name}' not found: {path}")
        self.tok = AutoTokenizer.from_pretrained(self.base_model)
        model = AutoModelForCausalLM.from_pretrained(self.base_model, **kwargs)
        if self.adapters:
            from peft import PeftModel
            items = list(self.adapters.items())
            model = PeftModel.from_pretrained(model, items[0][1], adapter_name=items[0][0])
            for name, path in items[1:]:
                model.load_adapter(path, adapter_name=name)
        model.eval()
        self.model = model

    def generate(self, adapter, msgs, max_new_tokens, temperature):
        import contextlib
        import torch
        with self.lock:
            self.load()
            ids = self.tok.apply_chat_template(msgs, add_generation_prompt=True,
                                               return_tensors="pt").to(self.model.device)
            gen = {"max_new_tokens": max_new_tokens,
                   "pad_token_id": self.tok.pad_token_id or self.tok.eos_token_id,
                   "repetition_penalty": float(os.environ.get("NEUROBRIDGE_LOCAL_REPETITION_PENALTY", "1.1")),
                   "min_new_tokens": int(os.environ.get("NEUROBRIDGE_LOCAL_MIN_NEW_TOKENS", "0"))}
            if temperature and temperature > 0:
                gen.update(do_sample=True, temperature=temperature, top_p=0.9)
            else:
                gen["do_sample"] = False
            if adapter:
                if adapter not in self.adapters:
                    raise RuntimeError(f"Adapter not loaded: {adapter}")
                self.model.set_adapter(adapter)
                ctx = contextlib.nullcontext()
            else:
                ctx = self.model.disable_adapter() if self.adapters else contextlib.nullcontext()
            with torch.no_grad(), ctx:
                out = self.model.generate(ids, attention_mask=torch.ones_like(ids), **gen)
            new = out[0][ids.shape[-1]:]
            return self.tok.decode(new, skip_special_tokens=True).strip(), int(ids.shape[-1]), int(new.shape[-1])


LABELS = {"nb_base": "NeuroBridge base ({base}, no fine-tuning)",
          "nb_sft": "NeuroBridge SFT",
          "nb_sft_orpo": "NeuroBridge SFT+ORPO"}


class LocalHFProvider:
    def __init__(self, model: str = None, adapter_path: Optional[str] = None, four_bit: bool = True,
                 name: Optional[str] = None, pool: Optional[LocalModelPool] = None,
                 adapter_name: Optional[str] = None):
        if pool is None:  # backwards-compatible single-adapter construction
            adapter_name = adapter_name or ("adapter" if adapter_path else None)
            pool = LocalModelPool(model, {adapter_name: adapter_path} if adapter_path else {}, four_bit)
        self.pool = pool
        self.adapter_name = adapter_name
        self._adapter_path = pool.adapters.get(adapter_name) if adapter_name else None
        self._name = name or ("neurobridge_local" if adapter_name else "local_base")
        self.system_prompt, self.system_prompt_version = _training_system_prompt()
        self.run_info = _run_metadata(self._adapter_path)

    @property
    def provider_name(self):
        return self._name

    @property
    def model_name(self):
        return self.pool.base_model + (f"+{self.adapter_name}" if self.adapter_name else "")

    @property
    def label(self):
        base = LABELS.get(self._name, self._name).format(base=Path(self.pool.base_model).name)
        if self.run_info.get("ablation"):
            base += " (ablation: preference pairs not human-reviewed)"
        return base

    def describe(self):
        return {"provider": self._name, "label": self.label, "base_model": self.pool.base_model,
                "adapter": self._adapter_path, "four_bit": self.pool.four_bit,
                "loaded": self.pool.model is not None, "run": self.run_info,
                "system_prompt_version": self.system_prompt_version}

    def generate(self, messages, system_prompt=None, temperature=0.3, max_tokens=512, **kwargs):
        sys_parts = [p for p in (self.system_prompt, system_prompt) if p]
        msgs = ([{"role": "system", "content": "\n\n".join(sys_parts)}] if sys_parts else [])
        msgs += [m for m in messages if m.get("role") in ("user", "assistant")]
        max_new = min(max_tokens, 1024)
        text, n_in, n_out = self.pool.generate(self.adapter_name, msgs, max_new, temperature)
        if not text:
            raise RuntimeError("Local model returned an empty response.")
        return LLMResponse(text=text, provider=self._name, model=self.model_name,
                           usage={"prompt_tokens": n_in, "completion_tokens": n_out},
                           metadata={"truncated": n_out >= max_new, "label": self.label})


def build_local_providers(base_model, sft_adapter=None, orpo_adapter=None, four_bit=True):
    adapters = {}
    if sft_adapter:
        adapters["sft"] = sft_adapter
    if orpo_adapter:
        adapters["sft_orpo"] = orpo_adapter
    pool = LocalModelPool(base_model, adapters, four_bit)
    providers = [LocalHFProvider(pool=pool, name="nb_base")]
    if sft_adapter:
        providers.append(LocalHFProvider(pool=pool, adapter_name="sft", name="nb_sft"))
    if orpo_adapter:
        providers.append(LocalHFProvider(pool=pool, adapter_name="sft_orpo", name="nb_sft_orpo"))
    return providers


class DevelopmentMockProvider:
    """For UI/dev work without any model. Refuses to exist outside development mode."""

    def __init__(self):
        if os.environ.get("NEUROBRIDGE_ENV", "production").lower() != "development":
            raise RuntimeError("DevelopmentMockProvider is only allowed when NEUROBRIDGE_ENV=development")

    @property
    def provider_name(self):
        return "dev_mock"

    def generate(self, messages, system_prompt=None, **kwargs):
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return LLMResponse(
            text=("[DEVELOPMENT MOCK — not an AI response] Received: " + last[:200]),
            provider="dev_mock", model="none", metadata={"mock": True})
