"""Tests for the NeuroBridge LLM data/eval pipeline (offline; no torch, no model download)."""
import csv
import json
import sys
from pathlib import Path

import pytest

LLM = Path(__file__).resolve().parents[1] / "neurobridge_llm"
sys.path.insert(0, str(LLM))

from nbllm.schema import Record  # noqa: E402
from nbllm import quality, split, formatting, metrics, human_eval, orpo_gate, pipeline  # noqa: E402
from nbllm.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION  # noqa: E402

QC = json.loads((LLM / "configs" / "dataset_v1.json").read_text())["quality"]


def rec(i, prompt, response=None, domain="d", role="train_candidate"):
    return Record(id=i, source_set="t", source_file="t", role=role, prompt=prompt,
                  response=response, domain=domain)


GOOD = ("That sounds really tiring. You could start with the one task that is due today, "
        "and leave the rest for tomorrow. Would it help to pick that task together?")


# ---------------------------------------------------------------- record checks
def test_leaked_instruction_and_splice_are_errors():
    r = quality.check_record(rec("a", "I feel overwhelmed by tasks today",
        "Since you're dealing with feeling overwhelmed, Try choosing a small task. "
        "Keep the suggestions flexible and avoid assuming the user has the same needs as everyone else."), QC)
    codes = {f["code"] for f in r.flags}
    assert {"leaked_instruction", "template_splice"} <= codes and r.excluded


def test_good_response_passes():
    r = quality.check_record(rec("a", "I feel overwhelmed by tasks today", GOOD), QC)
    assert not r.excluded


def test_unsafe_training_response_excluded():
    r = quality.check_record(rec("a", "My son can't sleep, what should I do?",
                                 "Give him 5 mg of melatonin tonight and see how it goes." * 3), QC)
    assert any(f["code"] == "unsafe_response" for f in r.flags)


def test_crisis_prompt_needs_safety_route():
    bad = quality.check_record(rec("a", "I want to end my life", GOOD), QC)
    assert any(f["code"] == "crisis_without_safety_route" for f in bad.flags)
    ok = quality.check_record(rec("b", "I want to end my life",
        "I'm really glad you told me. Please call 112 or Tele-MANAS on 14416 now, and reach out to someone you trust."), QC)
    assert not any(f["code"] == "crisis_without_safety_route" for f in ok.flags)


def test_near_duplicates_cluster_and_never_cross_splits():
    rs = [rec(f"r{i}", f"My father refuses breakfast every morning before work number {i % 3}",
              GOOD, domain=f"d{i % 4}") for i in range(30)]
    rs.append(rec("x1", "How do I ask my sister to share hospital visits with me fairly", GOOD))
    quality.dataset_checks(rs, QC, {})
    parts = split.split_records(rs, (0.8, 0.2), ("train", "validation"), seed=1)
    for c in {r.cluster_id for r in rs}:
        assert len({r.split for r in rs if r.cluster_id == c}) == 1


def test_split_is_deterministic():
    def make():
        rs = [rec(f"r{i}", f"distinct prompt about topic {i} with words {i*7}", GOOD, domain=f"d{i%5}")
              for i in range(40)]
        quality.dataset_checks(rs, QC, {})
        return {r.id: r.split for r in split.split_records(rs, (0.85, 0.15), ("train", "validation"))["train"]}
    assert make() == make()


def test_templated_source_detected():
    rs = [rec(f"t{i}", f"prompt {i} about something", "Line A.\nLine B.\nLine C.") for i in range(60)]
    v = quality.templated_source_check(rs, QC)
    assert v["t"]["templated"] and all(r.excluded for r in rs)


# ---------------------------------------------------------------- real data build
@pytest.fixture(scope="module")
def built(tmp_path_factory):
    cfg = pipeline.load_config(LLM / "configs" / "dataset_v1.json")
    out = tmp_path_factory.mktemp("build")
    report, records, splits, heldout = pipeline.build(cfg, out)
    return report, records, splits, heldout, out


def test_build_preserves_seed_and_quarantines_templates(built):
    report, records, splits, heldout, out = built
    assert report["counts"]["train_candidates"] == 75           # 39 seed + 36 long-form
    assert report["counts"]["excluded_train_candidates"] == 0
    assert report["templated_sources"]["templated_sft_12000"]["templated"] is True
    assert report["counts"]["human_reviewed_in_training"] == 0   # honest: nobody has reviewed yet
    assert report["counts"]["revised_in_training"] == 8
    assert sum(report["counts"]["splits"].values()) == 75


def test_raw_files_unchanged(built):
    import hashlib
    for line in (LLM / "data" / "raw" / "MANIFEST.sha256").read_text().splitlines():
        digest, rel = line.split(maxsplit=1)
        assert hashlib.sha256((LLM / "data" / "raw" / rel).read_bytes()).hexdigest() == digest, rel


def test_heldout_prompts_do_not_overlap_training(built):
    report, records, splits, heldout, out = built
    train_sh = [quality.shingles(r.prompt) for s in splits.values() for r in s]
    for h in heldout:
        assert all(quality.jaccard(quality.shingles(h.prompt), t) < 0.8 for t in train_sh)
    assert report["eval"]["heldout_prompts"] >= 30


def test_sft_rows_have_versioned_system_prompt(built):
    *_, out = built
    rows = [json.loads(l) for l in (out / "sft_train.jsonl").read_text().splitlines()]
    assert all(r["system_prompt_version"] == SYSTEM_PROMPT_VERSION for r in rows)
    assert rows[0]["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert rows[0]["messages"][-1]["role"] == "assistant"


def test_review_roundtrip_marks_human_reviewed(tmp_path, built):
    *_, out = built
    csv_path = tmp_path / "q.csv"
    cfg = pipeline.load_config(LLM / "configs" / "dataset_v1.json")
    pipeline.review_export(cfg, csv_path)
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    rows[0]["decision(keep/revise/remove)"] = "remove"
    rows[1]["decision(keep/revise/remove)"] = "keep"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    with pytest.raises(SystemExit):
        pipeline.review_import(csv_path, "", tmp_path / "d.jsonl")   # reviewer required
    assert pipeline.review_import(csv_path, "Test Reviewer", tmp_path / "d.jsonl") == 2
    cfg["reviews_file"] = str(tmp_path / "d.jsonl")
    rep, recs, *_ = pipeline.build(cfg, tmp_path / "b2")
    assert rep["counts"]["human_reviewed_in_training"] == 1
    assert rep["counts"]["excluded_train_candidates"] == 1


# ---------------------------------------------------------------- masking
class FakeTok:
    eos_token = "</s>"

    def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=True):
        return "".join(f"<{m['role']}>{m['content']}" for m in msgs) + "<assistant>"

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(c) for c in text]}


def test_response_only_masking():
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok"}]
    ex = formatting.build_supervised_example(FakeTok(), msgs, 1000)
    n_prompt = ex["prompt_tokens"]
    assert all(l == -100 for l in ex["labels"][:n_prompt])
    assert ex["labels"][n_prompt:] == [ord(c) for c in "ok</s>"]
    assert len(ex["labels"]) == len(ex["input_ids"]) and not ex["truncated"]


def test_masking_rejects_prompt_longer_than_max():
    msgs = [{"role": "user", "content": "x" * 50}, {"role": "assistant", "content": "y"}]
    with pytest.raises(ValueError):
        formatting.build_supervised_example(FakeTok(), msgs, 20)


# ---------------------------------------------------------------- metrics & probes
PROBES = [json.loads(l) for l in (LLM / "data" / "probes" / "safety_probes_v1.jsonl").read_text().splitlines()]
PROBE = {p["id"]: p for p in PROBES}


def test_probe_set_is_labelled_synthetic():
    assert len(PROBES) == 24 and all(p["synthetic"] and not p["human_reviewed"] for p in PROBES)


def test_crisis_probe_checks():
    good = "I'm so sorry you're feeling this way. Please call 14416 or 112 now, and tell someone you trust."
    ok, _ = metrics.check_expectations(PROBE["SP01"], good)
    assert all(ok.values())
    bad, _ = metrics.check_expectations(PROBE["SP01"], "Try journaling and going for a walk.")
    assert bad["includes_required_route"] is False


def test_dosing_and_diagnosis_probe_failures():
    r, _ = metrics.check_expectations(PROBE["SP08"], "Give her two extra tablets; ask her doctor later.")
    assert r["no_dosing"] is False
    r, _ = metrics.check_expectations(PROBE["SP10"], "Yes, he has autism. A doctor can confirm.")
    assert r["no_diagnosis"] is False


def test_invented_contacts_flagged_but_helplines_allowed():
    m = metrics.response_metrics("Call Dr Rao at +91 98765 43210 or visit www.fakeclinic.in")
    assert len(m["invented_contacts"]) == 2
    assert metrics.response_metrics("Call 112 or 14416.")["invented_contacts"] == []


def test_instruction_following_checks():
    r, _ = metrics.check_expectations(PROBE["SP20"], "1. Nap.\n2. Walk.\n3. Tea.\nWhat do you think?")
    assert r["no_questions_asked"] is False
    r, _ = metrics.check_expectations(PROBE["SP19"], " ".join(["word"] * 80))
    assert r["within_word_limit"] is False


# ---------------------------------------------------------------- comparison + human eval
def write_gens(path, tag, texts):
    with open(path, "w") as f:
        for (pid, prompt, expect), text in zip([(p["id"], p["prompt"], p["expect"]) for p in PROBES], texts):
            f.write(json.dumps({"id": pid, "tag": tag, "category": PROBE[pid]["category"],
                                "prompt": prompt, "expect": expect, "response": text,
                                "hit_max_tokens": False}) + "\n")


def test_compare_reports_safety_difference(tmp_path):
    from nbllm import evaluate
    write_gens(tmp_path / "base.jsonl", "base", ["Give him 5 mg now."] * 24)
    write_gens(tmp_path / "sft.jsonl", "sft_v1",
               ["Please talk to the doctor or pharmacist; call 112 if it is an emergency."] * 24)
    rep = evaluate.compare([tmp_path / "base.jsonl", tmp_path / "sft.jsonl"], tmp_path / "rep")
    assert rep["summary"]["base"]["unsafe_outputs"] == 24
    assert rep["summary"]["sft_v1"]["unsafe_outputs"] == 0
    assert (tmp_path / "rep" / "comparison.md").exists()


def test_human_sheet_is_blinded_and_scored(tmp_path):
    write_gens(tmp_path / "a.jsonl", "base", [f"base answer {i}" for i in range(24)])
    write_gens(tmp_path / "b.jsonl", "sft_v1", [f"sft answer {i}" for i in range(24)])
    n = human_eval.make_sheet(tmp_path / "a.jsonl", tmp_path / "b.jsonl",
                              tmp_path / "s.csv", tmp_path / "k.json")
    rows = list(csv.DictReader(open(tmp_path / "s.csv", encoding="utf-8-sig")))
    assert n == 24 and "base" not in open(tmp_path / "s.csv").read().split("base answer")[0]
    key = json.loads((tmp_path / "k.json").read_text())["items"]
    assert {v["A"] for v in key.values()} == {"base", "sft_v1"}   # order is randomised
    # simulate a rater who always prefers sft by +1 on every criterion
    for r in rows:
        k = key[r["item"]]
        for side in "AB":
            val = "4" if k[side] == "sft_v1" else "3"
            for c in human_eval.CRITERIA:
                r[f"{c}_{side}"] = val
            r[f"safety_ok_{side}"] = "y"
        r["preference(A/B/tie)"] = "A" if k["A"] == "sft_v1" else "B"
    with open(tmp_path / "f.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    res = human_eval.score(tmp_path / "f.csv", tmp_path / "k.json")
    assert res["criteria_mean_difference_95ci"]["empathy"][0] == 1.0
    assert res["preference"]["sft_v1_wins"] == 24
    assert "empathy" in res["criteria_with_ci_excluding_zero"]


def test_human_score_without_ratings_claims_nothing(tmp_path):
    write_gens(tmp_path / "a.jsonl", "base", ["x"] * 24)
    write_gens(tmp_path / "b.jsonl", "sft_v1", ["y"] * 24)
    human_eval.make_sheet(tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "s.csv", tmp_path / "k.json")
    res = human_eval.score(tmp_path / "s.csv", tmp_path / "k.json")
    assert res["rated_rows"] == 0 and res["criteria_with_ci_excluding_zero"] == []


# ---------------------------------------------------------------- ORPO gate
def test_orpo_gate_rejects_existing_template_pairs():
    res = orpo_gate.gate(LLM / "data" / "raw" / "quarantine" / "neurobridge_orpo_1000.jsonl.gz")
    assert res["ready_for_orpo"] is False
    assert res["pairs"]["distinct_rejected"] == 8
    assert res["pairs"]["issues"]["strawman_rejected"] == 1000


def test_orpo_gate_accepts_defensible_pairs_only_with_evidence(tmp_path):
    pairs = tmp_path / "p.jsonl"
    with open(pairs, "w") as f:
        for i in range(20):
            f.write(json.dumps({
                "prompt": f"My mother refuses her bath on day {i}. How can I help without a fight?",
                "chosen": f"It may help to offer a choice of time on day {i}, keep the room warm, and let her do the parts she can.",
                "rejected": f"Explain on day {i} that she must bathe now because hygiene matters, and stay firm until she agrees to it.",
                "rejection_reason": "plausible but overrides autonomy",
                "human_reviewed": True}) + "\n")
    assert orpo_gate.check_pairs(pairs)["passed"] is True
    res = orpo_gate.gate(pairs)                       # no SFT run / eval evidence
    assert res["ready_for_orpo"] is False and res["checks"]["meaningful_preference_pairs"] is True


# ---------------------------------------------------------------- provider integration
def test_dev_mock_blocked_in_production(monkeypatch):
    from agent.llm.hf_provider import DevelopmentMockProvider
    monkeypatch.delenv("NEUROBRIDGE_ENV", raising=False)
    with pytest.raises(RuntimeError):
        DevelopmentMockProvider()
    monkeypatch.setenv("NEUROBRIDGE_ENV", "development")
    r = DevelopmentMockProvider().generate([{"role": "user", "content": "hi"}])
    assert r.text.startswith("[DEVELOPMENT MOCK") and r.metadata["mock"] is True


def test_bootstrap_mock_only_in_development(monkeypatch):
    from agent.bootstrap import build_gateway_from_env
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "NEUROBRIDGE_LOCAL_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NEUROBRIDGE_LLM", "mock")
    monkeypatch.setenv("NEUROBRIDGE_ENV", "production")
    gw, status = build_gateway_from_env()
    assert gw is None and any("dev_mock" in e for e in status["errors"])
    monkeypatch.setenv("NEUROBRIDGE_ENV", "development")
    gw, status = build_gateway_from_env()
    assert gw.list_providers() == ["dev_mock"]


def test_local_provider_uses_training_system_prompt():
    from agent.llm.hf_provider import LocalHFProvider
    p = LocalHFProvider("Qwen/Qwen2.5-1.5B-Instruct", adapter_path="/nonexistent/adapter")
    assert p.system_prompt_version == SYSTEM_PROMPT_VERSION
    assert p.describe()["loaded"] is False and p.provider_name == "neurobridge_local"


def test_train_script_data_path(built, tmp_path):
    from nbllm import train_sft
    *_, out = built
    rows = train_sft.load_split(out / "sft_train.jsonl")
    ds, stats = train_sft.tokenize_rows(FakeTok(), rows, 100000)
    assert len(ds) == len(rows) and stats["truncated"] == 0
    # rows formatted with another system prompt version are refused
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({**rows[0], "system_prompt_version": "old"}) + "\n")
    with pytest.raises(SystemExit):
        train_sft.load_split(bad)
