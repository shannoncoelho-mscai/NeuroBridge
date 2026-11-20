# NeuroBridge Deep Agent — prototype v0.4

Caregiver-support assistant with a research agent. **Not a doctor and not an emergency
service:** it does not diagnose, change medication, or make emergency decisions, and
every consequential action needs the caregiver's approval.

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
  api/app.py           FastAPI app;  api/static/index.html  web UI at /ui
neurobridge_llm/       LLM pipeline: data/raw (recovered datasets), nbllm/ (pipeline, train_sft,
                       evaluate, human_eval, orpo_gate), configs/, NeuroBridge_LLM_Pipeline.ipynb
tests/                 offline test suite (119 tests, incl. a real tiny-model training smoke test)
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

uvicorn agent.api.app:app --port 8000
# open http://localhost:8000/ui   (API docs: http://localhost:8000/docs)
```

Run the tests (offline, no keys needed):

```bash
python -m pytest -q tests/
```

Run the live evaluation (uses your keys and the real web):

```bash
python scripts/live_eval.py
```

## Run in Google Colab (your current setup)

Upload `NeuroBridge_Deep_Agent_v0.4.zip` to Drive and unzip it into a **new** folder so
your existing Drive project stays untouched:

```python
from google.colab import drive, userdata
drive.mount('/content/drive')
!mkdir -p /content/drive/MyDrive/neurobridge/NeuroBridge_Deep_Agent_v2
!unzip -o -q /content/drive/MyDrive/NeuroBridge_Deep_Agent_v0.4.zip -d /content/drive/MyDrive/neurobridge/NeuroBridge_Deep_Agent_v2
%cd /content/drive/MyDrive/neurobridge/NeuroBridge_Deep_Agent_v2/NeuroBridge_Deep_Agent
!pip -q install -r requirements.txt

import os
for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "TAVILY_API_KEY"):
    try:
        os.environ[k] = userdata.get(k)      # from Colab Secrets; value never printed
        print(k, "loaded")
    except Exception as e:                   # enable "Notebook access" for the secret
        print(k, "NOT loaded:", type(e).__name__)
# Keys must be set BEFORE starting the server; restart it after changing keys:
# !pkill -f "uvicorn agent.api.app"

!python -m pytest -q tests/

import subprocess
server = subprocess.Popen(["python", "-m", "uvicorn", "agent.api.app:app", "--port", "8000"])

import time, urllib.request
time.sleep(5)
print(urllib.request.urlopen("http://localhost:8000/health").read().decode())  # server is up?

from google.colab import output
output.serve_kernel_port_as_window(8000, path="/ui")   # click the link this prints
# alternative:
# from google.colab.output import eval_js
# print(eval_js("google.colab.kernel.proxyPort(8000)").rstrip("/") + "/ui")
```

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
