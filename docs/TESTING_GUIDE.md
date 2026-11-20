# Testing guide

```bash
pip install -r requirements.txt
python -m pytest -q tests/                    # all offline; no keys, GPU or network
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_regressions.py` | 7 | notebook inline checks + batch-1 audit bugs |
| `tests/test_agent_evaluation.py` | 35 | research answers, unsupported claims, missing sources, tool failures, incomplete tasks, unsafe medical advice, permissions, multilingual, task completion |
| `tests/test_api.py` | 15 | chat safety, agent runs, approvals, booking, admin auth, memory API |
| `tests/test_mcp.py` | 3 | MCP tools (+ real stdio round-trip); skipped if no MCP SDK |
| `tests/test_events_and_safety_v3.py` | 26 | events + detail-bound approval, agent event booking, first-aid guidance, psychosis/DID notes, reply continuation, compare without silent fallback |
| `tests/test_training_smoke.py` | 5 | **real** SFT → pairs → ORPO → 3-model generation/compare/serving on a tiny random Qwen2-architecture model (skipped without torch) |
| `tests/test_llm_pipeline.py` | 28 | dataset checks, real-data build, raw-file checksums, leakage-safe split, review round-trip, response-only masking, probe metrics, comparison, blinded human scoring, ORPO gate, provider gating |

Last run: **178 passed, 0 failed** (2026-11-20; torch 2.15 CPU, transformers 4.48.3, peft 0.14.0, google-genai 3.6.1, groq 1.7.0). New in v0.6: `test_providers_booking_v06.py` (13) and `test_providers_v06.py` (7).

LLM and search calls in tests use deterministic fakes (`tests/fakes.py`). The suite tests
control logic, safety gates and data handling, **not** model quality.

## Live / GPU checks (run yourself)

* `python scripts/live_eval.py` runs the agent against real Groq/Gemini + Tavily.
* `neurobridge_llm/NeuroBridge_LLM_Pipeline.ipynb` runs training, generation and evaluation
  on a Colab T4.

## Not covered (no code to test yet)

Frontend component, navigation and responsive tests; authentication; and the
platform modules in `neurobridge-platform-phase1.zip`. That zip's own suite reported
68 passed / 3 xfailed in the notebook.
