# NeuroBridge — v0.6 (web app + deep agent)
live demo
## Live demo
**https://neurobridge-428948222095.asia-south1.run.app**

> **Quick start (Colab):** upload `NeuroBridge_Deep_Agent_v0.6.zip` to My Drive, open
> **`RUN_NeuroBridge_Website.ipynb`** in Colab, add `GROQ_API_KEY`, `GEMINI_API_KEY`,
> `TAVILY_API_KEY` and `NB_ADMIN_PASSWORD` under 🔑 Secrets, then **Runtime → Run all**.
> The notebook checks every key with a real request, starts the server and opens the website.

A neurodiversity-support web application for neurodivergent people **and** the people who
support them, built on the NeuroBridge chat LLM and research agent. **Not a doctor and not an
emergency service:** it does not diagnose, change medication, or make emergency decisions,
and every consequential action (booking, registering, sharing) needs the user's approval.

**Open the app at `/app`.** Two experiences in one platform:

- **Individual:** My Day, AI Assistant, Tasks (help-me-start, what-next, focus/body-doubling),
  Routines (step player, skip without penalty), Check-in, Sensory toolkit, Communication
  cards (full-screen + text-to-speech), private Journal, Support Blueprint, Goals,
  Learn & life skills, Community, Events & groups, Providers & appointments, My circle,
  and the **I'm overwhelmed** calm mode on every page.
- **Caregiver:** Dashboard, Care assistant, Care calendar, Care journal (with non-causal
  pattern counts), People I support (consent-based shared view), Coordination (care tasks,
  handovers), Support requests, Learning hub, Providers & appointments, Events, Community,
  Wellbeing.
- **Appointments with psychiatrists and therapists:** an admin adds real providers after
  checking them (registration, phone call) and adds the times the clinic agreed to; people book
  those times in the app or through the agent, after approving the exact clinic, time and fee.
  The booking shows *waiting for the clinic* until the admin records the clinic's answer.
  Clinics found on the web (not in the directory) can't be booked by NeuroBridge — the agent
  shows them with sources, and **Track this clinic** keeps them in a list with a ready-to-send
  message (call / WhatsApp / email).
- **Community Connect:** interest groups, posts, replies, supportive reactions, peer
  connections and private messages between connected adults, report, block, moderation
  queue, under-18 protections, and user-proposed events reviewed by an admin.

See `docs/WEB_APP_GUIDE.md` for how each part works and what is and isn't finished.

Docs: `docs/AUDIT.md` (agent notebook audit), `docs/LLM_AND_PLATFORM_AUDIT.md` (training
notebook + platform audit), `docs/STATUS.md`, `ARCHITECTURE.md`, `DATASET_GUIDE.md`,
`TRAINING_GUIDE.md`, `AI_MODEL_GUIDE.md`, `TESTING_GUIDE.md`, `ENVIRONMENT_SETUP.md`,
`DEPLOYMENT_GUIDE.md`. API reference: `/docs` (OpenAPI) on the running server.

## Layout

```
agent/
  orchestrator.py      plan → execute → observe → verify → correct → replan → goal gate
  loop.py              bounded task loop (approval pauses, honest dry-run flag)
  planner/planner.py   LLM planner (tool/skill-aware; validated by the orchestrator)
  executor/            engine (lifecycle + approvals), tool executor, tool bridge (retries)
  tools/               web_search, web_page_reader, booking_db, builtin registry
  research/            evidence, synthesis, verification, correction, goal_gate, expansion
  safety/policy.py     emergency / self-harm / medication / diagnosis checks (in & out)
  middleware/          language policy + script detection
  llm/                 gateway (fallback), Groq, Gemini, multilingual wrapper
  memory/              consent-based memory store / suggestion / approval
  skills/              skills registry (reconstructed — see AUDIT)
  mcp/server.py        optional MCP server (read-only tools)
  api/app.py           FastAPI app;  api/static/index.html  original agent console at /ui
nbapp/                 the web application (mounted on the same FastAPI app)
  db.py                SQLite schema + numbered migrations      security.py  passwords, sessions, rate limits
  consent.py           care-circle permissions (scopes)         notify.py    notifications + quiet hours
  routes_*.py          accounts, personal, care, community, events/providers/learning
  assistant.py         one assistant = chat LLM + deep agent, with safety, approvals, memory
  static/              the web app UI (/app): plain JS, no build step
neurobridge_llm/       LLM pipeline: data/raw (recovered datasets), nbllm/ (pipeline, train_sft,
                       evaluate, human_eval, orpo_gate), configs/, NeuroBridge_LLM_Pipeline.ipynb
tests/                 offline test suite (178 tests: web app, providers & booking, agent, safety, LLM pipeline, real tiny-model training smoke test)
scripts/live_eval.py   live evaluation with real keys
backups/               untouched reconstruction of the original notebook state
```

## Run locally

```bash
cd NeuroBridge_Deep_Agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export GROQ_API_KEY=...          # and/or GEMINI_API_KEY=...
export TAVILY_API_KEY=...        # recommended for search + page reading
# optional: export NEUROBRIDGE_ADMIN_TOKEN=some-long-secret   (provider verification/slots)
# optional: an admin account for moderation (never hard-coded):
# export NEUROBRIDGE_ADMIN_EMAIL=you@example.org NEUROBRIDGE_ADMIN_PASSWORD='a-long-password'

# optional: clearly-labelled demo accounts + sample data to explore the app
python scripts/seed_demo_app.py --password "choose-a-demo-password"

uvicorn agent.api.app:app --port 8000
# open http://localhost:8000/app   (agent console: /ui, API docs: /docs)
```

In production also set `NEUROBRIDGE_DISABLE_LEGACY_API=1` so only the signed-in `/api/*`
routes are reachable (the older `/chat`, `/agent`, `/booking`, `/events`, `/memory` endpoints
take a user id in the request and have no sign-in).

Run the tests (offline, no keys needed):

```bash
python -m pytest -q tests/
```

Run the live evaluation (uses your keys and the real web):

```bash
python scripts/live_eval.py
```

## Run in Google Colab (your current setup)

Use **`RUN_NeuroBridge_Website.ipynb`** (top of the zip). It:

1. finds the newest `NeuroBridge_Deep_Agent_v*.zip` in My Drive, unzips and installs it;
2. loads `GROQ_API_KEY`, `GEMINI_API_KEY`, `TAVILY_API_KEY`, `NB_ADMIN_PASSWORD` from Colab
   Secrets and runs `scripts/check_keys.py`, which makes one tiny real request to each service
   and says plainly what is wrong (rejected key, used-up quota, model not enabled, no network);
3. keeps app data on Drive (`MyDrive/neurobridge_data`) so accounts survive restarts;
4. turns on your trained base / SFT / SFT+ORPO models automatically if their adapters are in
   `MyDrive/neurobridge/llm_runs*/` and a GPU is on (otherwise Groq + Gemini only);
5. optionally loads clearly-labelled demo accounts, events and four demo clinics;
6. starts the server and opens `/app`.

Models: Groq `openai/gpt-oss-120b` (falls back to `openai/gpt-oss-20b`), Gemini
`gemini-3.8-flash` (falls back to `gemini-3.5-flash`, `gemini-3.5-flash-lite`,
`gemini-2.5-flash` — Google serves 2.5 only to keys that used it before). Both run with low
hidden "thinking" so answers aren't cut off. Override with `NEUROBRIDGE_GROQ_MODEL` /
`NEUROBRIDGE_GEMINI_MODEL`.

## NeuroBridge LLM (dataset → SFT → evaluation)

```bash
cd neurobridge_llm
python -m nbllm.pipeline build                    # offline, ~4 s
# GPU (Colab T4): open neurobridge_llm/NeuroBridge_LLM_Pipeline.ipynb and run top to bottom
```

To serve the three models (base / SFT / SFT+ORPO) with a model picker and side-by-side compare in the UI:
`NEUROBRIDGE_LOCAL_MODEL=Qwen/Qwen2.5-1.5B-Instruct NEUROBRIDGE_SFT_ADAPTER=.../runs/sft_v2_12k/adapter
NEUROBRIDGE_ORPO_ADAPTER=.../runs/sft_orpo_v1/adapter`. The notebook's last cell does this.

## Events, groups and clubs

`NEUROBRIDGE_SEED_DEMO_EVENTS=1` adds 11 clearly-labelled demo listings: support circles,
an ADHD body-doubling club, a sensory-friendly art club, a hearing-voices peer group, a DID
peer group, workshops, gatherings and community meetings. Book them in **Events & groups**,
or ask the agent ("find an online ADHD club and sign me up"); you approve the exact details
first. Real listings: `POST /events` with `x-admin-token`.

## Using the API

The web app uses the signed-in `/api/*` routes (Bearer token from `POST /api/auth/login`);
the full list is at `/docs`. The original agent endpoints are below.

| Endpoint | Purpose |
|---|---|
| `POST /chat` | Support chat (safety-checked in and out, multilingual, memory-aware with `user_id`) |
| `POST /agent/run` | Research agent run: `{goal, success_criteria, user_id, preferred_language, allow_booking_actions}` |
| `GET /agent/runs/{id}` | Run status, answer, sources, verification, tasks, trace |
| `POST /agent/runs/{id}/approve` | Approve or decline a paused action: `{approval_id, approved}` |
| `GET /agent/tools` | Registered tools, permissions, approval flags |
| `POST /chat/compare` | Same message to several models: `{message, providers:["nb_base","nb_sft","nb_sft_orpo"]}` (no silent fallback) |
| `GET /events`, `GET /events/{id}/prepare`, `POST /events/{id}/register` | Events; register needs `explicit_approval` + the `approved_details_hash` from prepare (409 if details changed) |
| `GET /events/mine/{user}`, `POST /events/registrations/{id}/cancel`, `POST /events` (admin) | Registrations / organisers |
| `GET /booking/slots`, `/booking/providers` | Verified registry only |
| `POST /booking/request` → `POST /booking/approve` | Caregiver request, then explicit approval (`explicit_approval: true`) |
| `POST /booking/providers/register` | New provider (pending until verified) |
| `POST /booking/providers/{id}/verify`, `POST /booking/slots` | Admin only (`x-admin-token`) |
| `/memory/*` | Consent-gated memory (as in the notebook) |

Run statuses: `COMPLETED` (goal gate passed), `PARTIAL`, `WAITING_APPROVAL`,
`NO_EVIDENCE`, `FAILED`, `EMERGENCY_GUIDANCE`.

### MCP (optional)

```bash
python -m agent.mcp.server        # stdio; exposes web_search, web_page_reader, provider_search, find_slots
```

Booking actions are intentionally not exposed over MCP.
