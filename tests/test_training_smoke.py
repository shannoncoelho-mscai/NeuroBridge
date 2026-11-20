"""End-to-end training/serving smoke test with a tiny random Qwen2-architecture model.

Runs the REAL code paths: SFT (LoRA, response-only loss) -> base generations -> preference
pairs -> ORPO (ablation) -> generation with each adapter -> comparison -> multi-adapter
serving -> /chat/compare. Skipped when torch/transformers/peft are not installed.
Model quality is meaningless here by design.
"""
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("torch")
pytest.importorskip("peft")
pytest.importorskip("datasets")

LLM = Path(__file__).resolve().parents[1] / "neurobridge_llm"
sys.path.insert(0, str(LLM))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    from smoke_tiny_model import build as build_tiny
    from nbllm import pipeline, train_sft, train_orpo, build_pairs, evaluate
    t = tmp_path_factory.mktemp("smoke")
    cfg = pipeline.load_config(LLM / "configs" / "dataset_v2_curated.json")
    pipeline.build(cfg, t / "data")
    tiny = build_tiny(t / "tiny", [t / "data" / "sft_train.jsonl"])
    sft_cfg = json.loads((LLM / "configs" / "sft_qwen15b_t4.json").read_text())
    sft_cfg.update(base_model=str(tiny), dataset_dir=str(t / "data"), output_dir=str(t / "sft"),
                   allow_cpu=True, quantize_4bit=False, max_length=2048)
    sft_cfg["lora"]["r"] = 4
    sft_cfg["training"].update(max_steps=3, grad_accum=1)
    (t / "sft.json").write_text(json.dumps(sft_cfg))
    train_sft.main(["--config", str(t / "sft.json")])
    gen = ["--base", str(tiny), "--no-4bit", "--max-new-tokens", "16", "--min-new-tokens", "8",
           "--repetition-penalty", "3.0"]
    build_pairs.export_prompts(t / "data", t / "pp.jsonl", limit=12)
    evaluate.main(["generate", "--tag", "base", *gen, "--prompts", str(t / "pp.jsonl"), "--out", str(t / "pb.jsonl")])
    n, _ = build_pairs.build(t / "data", t / "pb.jsonl", t / "pairs.jsonl")
    orpo_cfg = json.loads((LLM / "configs" / "orpo_qwen15b_t4.json").read_text())
    orpo_cfg.update(base_model=str(tiny), sft_adapter=str(t / "sft" / "adapter"), sft_run=str(t / "sft"),
                    pairs=str(t / "pairs.jsonl"), output_dir=str(t / "orpo"), allow_cpu=True,
                    quantize_4bit=False, max_length=2048, comparison=None, human_scores=None)
    orpo_cfg["training"].update(max_steps=3, grad_accum=1, learning_rate=1e-3)
    (t / "orpo.json").write_text(json.dumps(orpo_cfg))
    return {"t": t, "tiny": tiny, "pairs": n, "gen": gen}


def test_sft_produces_adapter_and_metadata(chain):
    meta = json.loads((chain["t"] / "sft" / "run_metadata.json").read_text())
    assert (chain["t"] / "sft" / "adapter" / "adapter_model.safetensors").exists()
    assert meta["stage"] == "sft" and meta["train_examples"] > 50 and meta["dataset_files"]


def test_orpo_refuses_without_gate_or_ablation(chain):
    from nbllm import train_orpo
    with pytest.raises(SystemExit):
        train_orpo.main(["--config", str(chain["t"] / "orpo.json")])


def test_orpo_ablation_trains_and_is_labelled(chain):
    from nbllm import train_orpo
    assert chain["pairs"] > 0
    train_orpo.main(["--config", str(chain["t"] / "orpo.json"), "--ablation"])
    meta = json.loads((chain["t"] / "orpo" / "run_metadata.json").read_text())
    assert meta["ablation"] is True and meta["stage"] == "sft+orpo"
    assert (chain["t"] / "orpo" / "adapter" / "ABLATION_NOTICE.md").exists()
    assert abs(meta["history"][0]["l_or"] - 0.693) < 0.3     # ~ln 2 when chosen/rejected are equally likely


def test_orpo_loss_math():
    import torch
    from nbllm.train_orpo import orpo_loss
    lp = torch.tensor([-1.0])
    loss, log_odds, l_or = orpo_loss(lp, lp, torch.tensor(2.0), 0.1)
    assert abs(float(l_or) - 0.6931) < 1e-3 and abs(float(loss) - (2.0 + 0.1 * 0.6931)) < 1e-3
    _, lo, l_or2 = orpo_loss(torch.tensor([-0.5]), torch.tensor([-3.0]), torch.tensor(1.0), 0.1)
    assert float(lo) > 0 and float(l_or2) < 0.6931            # preferring chosen lowers L_OR


def test_three_models_generate_compare_and_serve(chain, monkeypatch):
    from nbllm import evaluate
    from agent.llm.hf_provider import build_local_providers
    t, gen = chain["t"], chain["gen"]
    prompts = str(LLM / "data" / "probes" / "safety_probes_v1.jsonl")
    for tag, adapter in (("base", None), ("sft_v1", t / "sft" / "adapter"), ("sft_orpo", t / "orpo" / "adapter")):
        extra = ["--adapter", str(adapter)] if adapter else []
        evaluate.main(["generate", "--tag", tag, *gen, *extra, "--prompts", prompts, "--limit", "4",
                       "--out", str(t / f"e_{tag}.jsonl")])
    rep = evaluate.compare([t / "e_base.jsonl", t / "e_sft_v1.jsonl", t / "e_sft_orpo.jsonl"], t / "rep",
                           train_ref_dir=t / "data")
    assert set(rep["models"]) == {"base", "sft_v1", "sft_orpo"} and "train_4gram_overlap" in rep["summary"]["base"]

    monkeypatch.setenv("NEUROBRIDGE_LOCAL_REPETITION_PENALTY", "3.0")
    monkeypatch.setenv("NEUROBRIDGE_LOCAL_MIN_NEW_TOKENS", "8")
    provs = build_local_providers(str(chain["tiny"]), str(t / "sft" / "adapter"), str(t / "orpo" / "adapter"),
                                  four_bit=False)
    assert [p.provider_name for p in provs] == ["nb_base", "nb_sft", "nb_sft_orpo"]
    assert "ablation" in provs[2].label
    outs = [p.generate([{"role": "user", "content": "hello"}], temperature=0, max_tokens=10).text for p in provs]
    assert all(outs) and outs[0] != outs[2]                 # ORPO adapter changes the output

    import agent.api.app as api
    from fastapi.testclient import TestClient
    from agent.llm.gateway import LLMGateway
    from agent.tools.booking_db import BookingStore
    gw = LLMGateway(default_provider="nb_sft")
    for p in provs:
        gw.register_provider(p)
    api.initialize(gw, store=BookingStore(t / "b.sqlite3"))
    c = TestClient(api.app)
    r = c.post("/chat/compare", json={"message": "hello", "providers": ["nb_base", "nb_sft", "nb_sft_orpo"]}).json()
    assert [x["provider"] for x in r["results"]] == ["nb_base", "nb_sft", "nb_sft_orpo"]
    assert all(x.get("reply") for x in r["results"])
    labels = {m["provider"]: m["label"] for m in c.get("/providers").json()["models"]}
    assert labels["nb_sft"] == "NeuroBridge SFT"
