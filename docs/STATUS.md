# NeuroBridge v0.6 — Status (2026-11-20)

## v0.6: real providers, agent booking, working keys

**178 passed, 0 failed** (`python -m pytest -q tests/`). New: 13 provider/booking tests
(agent finds and books a listed psychiatrist only after the exact details are approved; books
nothing when none is listed and points to the tracker; declined approval; never books for
someone else; prefers real listings over demo; past times hidden; admin directory with
required verification note; contact shared only if chosen; clinic confirm/decline with
notification; minors can't book; outside-clinic tracker private per user; deleted with the
account) and 7 provider tests (Gemini/Groq model fallback and low thinking, using the real
SDK types).

| Area | Status |
|---|---|
| Groq / Gemini / Tavily calls | Match the current SDKs (google-genai 1.51+, tavily-python); checked with fake clients. **Not called live from here** (no network): run `scripts/check_keys.py` in Colab. |
| Provider directory (admin adds, verifies with a note, adds clinic-agreed times) | Working, tested (API + browser) |
| Booking a listed psychiatrist / psychologist / therapist (page or agent) | Working, tested. Reserved → *waiting for the clinic* → admin records *confirmed* / *declined* |
| Clinics found on the web | Shown with sources; **cannot be booked by NeuroBridge**. "Track this clinic" + drafted message (call / WhatsApp / email) |
| Colab launcher `RUN_NeuroBridge_Website.ipynb` | Cells checked for syntax; steps mirrored locally (seed, start, browser). Not run inside Colab from here. |

Honest limits: a booking is only as real as the listing. "Verified" means an admin checked
the listing and the clinic agreed to receive bookings; NeuroBridge has no link to clinics'
own systems, so the admin (or a partner clinic) must confirm each booking by phone or email.

---

## v0.5 status (kept for history)

## v0.5: the web application

**158 passed, 0 failed** (`python -m pytest -q tests/`, run 2026-11-20): 35 agent
evaluation, 15 API, 26 events & safety, 28 LLM pipeline, 3 MCP, 7 regressions, 5 real
tiny-model training smoke, **39 web app** (auth, roles, isolation, consent scopes,
revocation, guardian mode, community moderation, minors, assistant routing, approvals,
memory, notifications/quiet hours, export and deletion).

Also checked live: the server starts, `/app` loads, register → sign in works over HTTP; with
no model key the assistant says so (HTTP 503) instead of inventing a reply, while a choking
message still gets the fixed first-aid guidance. Every page was opened in headless Chrome as
an individual (Asha, demo) and a caregiver (Ravi, demo), at desktop and mobile widths, and
checked with axe-core for colour contrast in light, dark, low-stimulation and high-contrast
modes.

| Area | Status |
|---|---|
| Accounts, roles, sessions, rate limits, audit, export, deletion | Working, tested |
| Consent (scoped, item-level sharing, revocation, guardian mode) | Working, tested |
| Individual pages (My Day … Settings, Overwhelm mode) | Working, tested (API + browser) |
| Caregiver pages (Dashboard … Wellbeing) | Working, tested (API + browser) |
| Community Connect (groups, posts, connections, DMs, report/block, moderation, minors) | Working, tested; word lists English-only |
| Assistant = chat LLM + deep agent | Working with fakes; live quality depends on your keys/model |
| Events, providers, appointments in the app | Working (local registry; demo listings labelled) |
| Interface translation | Partial: assistant replies in chosen language; UI labels mostly English |
| Email / push / SMS | Not implemented (in-app notifications only) |
| PostgreSQL | Not implemented (SQLite; fine for a pilot) |

See `docs/WEB_APP_GUIDE.md`.

---

## v0.4 status (kept for history)

## Test results (offline suite, `python -m pytest -q tests/`)

**119 passed, 0 failed.** Breakdown: 35 agent-evaluation, 15 API, 3 MCP (including a real
stdio client↔server round-trip), 5 regression, 28 LLM-pipeline (batch 2).

Regression tests run against the **original reconstructed code**: 2 passed (gateway
fallback, approval gate), **3 failed**: tool inner-failure reported as success, loop
iteration double-count, simulated runs indistinguishable from real ones. All 5 pass now.

Tests use scripted fakes for the LLM and search (`tests/fakes.py`). They prove the control
logic, safety gates and grounding checks. They do **not** prove answer quality with a real
LLM.

**Not run (impossible in the build environment):** live LLM calls (no keys), live web
search/extraction (outbound network blocked; a real DuckDuckGo attempt was refused by the
proxy and was correctly reported as a failure). Run `scripts/live_eval.py` with your keys.

The UI was exercised in headless Chrome against a fake-backed test server (screenshots
in `docs/screenshots/`). Chat, emergency routing, research run with redaction, and the
booking request → approval → confirmation flow all worked, with no console errors.

## Feature status

| Feature | Status | Notes |
|---|---|---|
| Planning / task decomposition | Working (offline) | LLM plan is validated: unknown tools removed, args sanitised, session user forced, search added if missing; deterministic fallback if the planner fails |
| Tool selection & execution | Working (offline) | Registry + permissions + approval + bounded retries on transient errors |
| Research & webpage reading | Implemented; **live untested** | Tavily → DDGS; page reader with SSRF checks; reads top 3 sources per round |
| Observe → verify → correct → replan | Working (offline) | Replans on no evidence and on unmet criteria (max 2 rounds) |
| Evidence-grounded responses | Working (offline) | Deterministic check of URLs, phones, e-mails, prices, organisation names, citations; LLM verifier can only tighten; unsupported statements redacted; redacted runs capped at PARTIAL |
| Failure recovery / retry | Working (offline) | Transient retry, replan, honest NO_EVIDENCE/FAILED |
| Goal completion checks | Working (offline) | Criteria judged by LLM; judge failure ⇒ never COMPLETE |
| Safety & permission checks | Working (keyword-based) | Emergency/self-harm halt with 112 / Tele-MANAS 14416; medication/diagnosis policy; output dosing/diagnosis filter; booking needs permission + approval |
| Multilingual | Partially working | Preference by code or name; script detection; Hindi/Marathi/Konkani ambiguous; translation quality depends on the LLM; safety keywords are mostly English |
| Memory | Working | API save/get/delete tested (notebook's final patch had never been re-tested); deterministic sensitive-data backstop |
| Booking | Working (local registry) | Verified providers only, transactional, caregiver approval, no double-booking; registry is empty until providers are registered and verified |
| API | Working | All original endpoints kept; new agent/approval/booking endpoints |
| UI | Working | `/ui`: chat, research (status, sources, verification, tasks, trace, approvals), appointments |
| MCP | Working, isolated | Read-only tools; mcp 2.x and 1.x supported; no package changes |
| Skills | Reconstructed | Original source not in notebook; API-compatible rebuild |

## Known bugs / limitations

1. **Live behaviour is unverified.** Prompts were not tuned against a real LLM in this
   session. The planner, verifier JSON and judge may need tuning once live.
2. Safety detection is keyword/regex based. It will miss paraphrased or non-English
   emergencies (only a few Hindi terms) and will produce false positives.
3. The entity grounding check works on title-case phrases. It can miss lowercase invented
   names, and it treats unmatched non-organisation phrases only as warnings.
4. Agent runs are stored in memory, so pending approvals are lost if the server restarts.
5. Mixed goals (research + booking in one request) only report the research part in the answer.
6. (Fixed in v0.6) Gemini 503s and retired models now fall back to the next model automatically.
7. No authentication: `caregiver_user_id` is trusted from the client. Admin endpoints use a
   shared token only.
8. CORS defaults to `*` (set `NEUROBRIDGE_CORS_ORIGINS`).
9. The earlier `NeuroBridge_FINAL_v5/neurobridge_guard.py` crisis guard is on Drive but was
   not in the notebook, so it is not integrated.

## Batch 2 — NeuroBridge LLM (`neurobridge_llm/`)

| Component | Status |
|---|---|
| Dataset recovery (39 seed + 8 revisions, 36 long-form, 440 prompts, quarantined template sets) | Done; counts match notebook; checksummed |
| Dataset pipeline (validate, clean, dedupe, leak/splice/safety checks, classify, split, format, card) | Working, tested on real data: 64 train / 11 validation / 41 held-out prompts |
| Human review round-trip | Working (tested); **0 examples human-reviewed so far** |
| Safety probe set (24, labelled synthetic) | Written; expectations machine-checkable where possible |
| Automatic base-vs-fine-tuned comparison | Scoring tested offline; **generation not run** (needs GPU) |
| Blinded human evaluation + bootstrap CIs | Tested with simulated ratings; **no real ratings exist** |
| QLoRA SFT script | Data path tested; **training not run here** |
| ORPO gate | Working; rejects the existing 1,000 pairs |
| Local HF / adapter provider, dev mock (blocked in production), active-provider display | Implemented; gating tested; model loading not run here |

No claim is made that any fine-tuned NeuroBridge model is better than the base model;
no comparative evaluation exists yet.

## Batch 3

| Change | Status |
|---|---|
| Cut-off replies | Fixed: truncation detection (Groq/Gemini/local) + automatic continuation (max 2), `reasoning_effort=low` for gpt-oss, 2048-token chat budget; tested with fakes |
| Markdown in UI | Headings, lists, tables, links rendered; HTML escaped first (an injected `<script>` was checked in a headless browser) |
| Emergency first aid | Fixed, sourced steps for 8 situations + self-harm + command hallucinations; calm opening, firm 112 stance; 10 detection tests incl. non-emergency planning questions |
| Firm medical stance in sensitive chats | System prompt + policy notes (psychosis, DID, medication, diagnosis) |
| Base / SFT / SFT+ORPO selector + compare | Implemented; **real** multi-adapter serving verified on a tiny random model; Qwen-scale not run here |
| 12k samples in training | `dataset_v2_with_12k` (768 unique, repaired, explicitly accepted as templated) |
| ORPO | Implemented (ORPO paper objective), pairs from base outputs, gate + labelled ablation; real CPU smoke run |
| Learning-signal metric | `train_4gram_overlap`, `ends_with_question_rate` |
| In-site events | Store, approval bound to exact details (re-approval on change), waitlist, agent search + booking after approval, UI tab, 11 labelled demo listings |
| DID / schizophrenia | 11 training examples + 8 probes (v2) + safety notes; **need qualified clinical review** |

Not done / not verified: Qwen-scale training and evaluation (needs your Colab T4 run);
whether SFT/ORPO answers are *better* (needs human ratings); clinical review of the
DID/psychosis content; reviewing the first-aid text with a certified trainer.
