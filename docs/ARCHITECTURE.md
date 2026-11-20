# Architecture (what is implemented in this repository)

```
            Browser (/ui, static HTML+JS)
                      │ REST (FastAPI, OpenAPI at /docs)
   ┌──────────────────┴───────────────────────────────────────────┐
   │ agent/api/app.py                                              │
   │  /chat ── safety.classify_input ─► multilingual_generate ─►   │
   │           safety.enforce_output                               │
   │  /agent/* ─► orchestrator (plan→execute→observe→verify→       │
   │              correct→replan→goal gate; approvals)             │
   │  /booking/*  ─► tools/booking_db (verified registry, approval)│
   │  /memory/*   ─► memory/ (consent-gated SQLite)                │
   └──────┬───────────────────────────┬───────────────────────────┘
          │ LLMGateway (registry+fallback)   │ ToolRegistry (permissions, approval)
   Groq │ Gemini │ LocalHF(+adapter) │ dev mock   web_search │ web_page_reader │ provider_search …
                      ▲
   neurobridge_llm/ (offline): data pipeline → SFT → evaluation → human eval → ORPO gate
                      │ produces runs/<run>/adapter used by LocalHF provider
```

* **Agent layer** (`agent/`): batch 1. See `docs/STATUS.md`.
* **Model layer** (`neurobridge_llm/`): batch 2. Dataset pipeline, training, evaluation.
  Shares the system prompt (`nbllm/prompts.py`) and safety rules (`agent/safety/policy.py`)
  with the serving path.
* **Storage:** SQLite files in `data/` (memory, bookings). No migrations yet.

## Not in this repository

The platform described in the master brief is not here: auth, roles, profile, planner,
journal, care circle, community, knowledge centre, innovation hub, admin dashboard, and
the React/Vite/Tailwind frontend. A separate backend exists in
`neurobridge-platform-phase1.zip` (FastAPI, Docker, CI, 68 tests). It has not been
inspected because it was not provided. Integration plan: audit that backend first, then
mount this agent and model layer into it as services, rather than run two backends.
