# NeuroBridge Deep Agent — Audit (2026-11-20)

## How this audit was done

The only artifact supplied was the Colab build notebook (`Untitled17.ipynb`, 213 cells).
The project itself lives on Google Drive (`MyDrive/neurobridge/NeuroBridge_Deep_Agent`),
which is not reachable from this workspace. The repository was therefore **reconstructed by
replaying every notebook cell in order** into a sandbox (Drive path redirected, Colab
secrets stubbed, Gradio `launch()` cells skipped). Every file-writing and file-patching cell
ran successfully; failures were limited to cells that need API keys, the network, or
in-memory objects created by earlier failed cells.

The reconstructed tree is preserved unmodified in `backups/original_reconstructed/`.
Notebook-made backups of `app.py` / `engine.py` are in `backups/notebook_backups/`.

**Files that exist on Drive but whose source never appears in the notebook** (cannot be
recovered byte-for-byte): `agent/skills/base.py`, `agent/skills/registry.py`,
`agent/skills/loader.py`, the DDGS-era first version of `tools/web_search.py`, and the
earlier `NeuroBridge_FINAL_v5/neurobridge_guard.py` crisis guard. Skills were rebuilt from
the API the notebook uses (`Skill(...)`, `SkillRegistry.register/get/names/select/list_skills`).

## Component status (before this work)

| Component | Status | Evidence |
|---|---|---|
| `config.py`, `schemas.py` | Working | Inline tests passed (cells 7, 9) |
| LLM gateway + fallback | Working | Mock fallback test passed (cell 11); live Groq call succeeded (cell 25) |
| Gemini provider | Partially working | Model `gemini-3.8-flash` returned 503 (cell 16) |
| Groq provider | Working | Live call succeeded (cells 22, 25) |
| Planner (LLM, tool-aware) | Working with live LLM | Valid 9-task plan (cell 30); tool-aware patch applied (cells 92–93) |
| Execution engine (lifecycle, approval gate) | Working | Approval + lifecycle tests passed (cells 41, 51) |
| Agent loop | **Partially working** | Double-counts iterations (loop and `start_task` both increment); `start_task` exceptions uncaught; dry-run marks tasks **completed with simulated results**; `/agent/run` therefore reports `completed: true` for work that never happened |
| Tool registry / executor | **Bug** | Tools that catch their own errors return `{"success": false}`, but the executor records `ToolStatus.SUCCESS` (visible in cell 121 output) |
| Tool bridge | Partially working | Blocks approval-required tools outright, no way to approve/resume |
| Web search | **Not persisted** | File on Drive is the DDGS version that returned "No results found" (cell 79). The working Tavily version exists only in notebook memory (cell 81) |
| Web page reader | **Not persisted** | Defined only in notebook memory (cell 138); never written to a file |
| Evidence merge/rank | **Not persisted + bug** | Notebook-only. Search results store text under `snippet`, merge reads `content` → **all evidence text empty** (cell 127 output) |
| Synthesis / verifier / correction / controller / goal gate | **Not persisted** | Notebook-only functions (cells 102–117). Goal-gate "unmet requirements" were typed in by hand (cell 116), not computed |
| Grounding | **Failing** | Grounding audit (cell 152) found 6 provider/organisation names in the answer that do not appear in any retrieved source |
| Research expansion / retry | Notebook-only; gap queries were full paragraphs, which made search fail (cell 121) |
| "Live end-to-end research test" | **Not a real pass** | Cell 184 printed `Completed: True`, but the planner had been monkey-patched to a hard-coded `echo` task; no research ran |
| Skills | **Missing source** | Files exist on Drive, never shown; registry was empty at cell 83 |
| Multilingual | Partially working | Prompt-only; `get_language_context` keys on names ("Hindi") while config uses codes ("hi"); no detection; one syntax error was later repaired (cells 161–164) |
| Appointment booking | **Split** | `tools/appointment_booking.py` is an in-memory state machine only. The SQLite booking functions (search, slots, request, approve, cancel) are notebook-only (cells 170–175). DB has 0 providers |
| Memory | Mostly working | Store/manager/approval files persisted. API `/memory/save` failed (`save_memory` not defined, cells 205, 209); final patch (cell 211) was **never re-tested**. Sensitivity relies solely on the LLM flag |
| API | Partially working | Chat + memory endpoints; `/agent/run` simulation only; `/agent/tools` returns `[]`; no approvals, booking, research endpoints; gateway must be injected by hand |
| UI | Colab-only | Gradio `share=True` cells (77–78); not part of the package |
| MCP | **Missing** | `agent/mcp/` contains only an empty `__init__.py` |
| Evaluation | **Missing** | `agent/evaluation/` and `tests/` empty; all tests were inline notebook cells |
| Safety | Prompt-level only | System prompt says "do not diagnose"; no input/output checks, no emergency routing, no medication-change refusal in code |

## Architectural problems

1. Most of the agent's research brain (cells 101–158) only ever existed in notebook memory.
2. Two parallel booking implementations with different status vocabularies.
3. Hard-coded Panjim/child-psychologist logic inside generic functions.
4. Patch-by-string-replacement of source files from the notebook, with silent no-ops when
   the target string was not found.
5. No single entry point that builds gateway + tools + pipeline from environment variables.

## Prioritized completion plan

1. **P0 – Honesty bugs:** tool inner-failure masking, simulated completions, loop counting.
2. **P0 – Persist notebook-only logic** as modules (search, reader, evidence, synthesis,
   verification, correction, goal gate, booking DB), fixing the `snippet`/`content` bug.
3. **P0 – Safety layer in code:** emergency detection, diagnosis/medication refusal,
   output checks, permission + approval gating for consequential tools.
4. **P1 – Orchestrator:** plan → execute → observe → verify → correct → replan, with retry,
   bounded loops, deterministic grounding checks, goal-completion gate.
5. **P1 – API integration:** app factory from env, real tool list, research run, approvals,
   booking, memory endpoints re-tested.
6. **P1 – Evaluation suite** (pytest, offline, deterministic fakes for LLM/search).
7. **P2 – UI:** chat with execution trace, sources, errors, approvals.
8. **P2 – MCP:** version-tolerant adapter, isolated and optional.
