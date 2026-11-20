# NeuroBridge web app guide (v0.6)

Open `http://localhost:8000/app` after starting the server (see README). The app is a
plain-JavaScript single-page app served by the same FastAPI server as the agent, so it needs
no Node/npm build and runs unchanged in Colab.

## Why this stack

The existing project was FastAPI + SQLite + a vanilla-JS console. The brief suggests React/
Next.js only "if the current architecture is unsuitable". It was suitable, and the only place
you run the project is Colab, where a Node build step is an extra failure point. So the web
app (`nbapp/`) is a FastAPI router package mounted on the existing app, with SQLite and
numbered migrations (`nbapp/db.py`). Moving to PostgreSQL later means swapping the `Database`
class; the SQL is plain and portable.

## Accounts, roles and security

| What | How |
|---|---|
| Roles | `individual`, `caregiver`, `admin` (admin only via env vars, never self-registration) |
| Passwords | PBKDF2-SHA256, per-user salt, 10+ characters |
| Sessions | random bearer token; only its SHA-256 hash is stored; expiry `NEUROBRIDGE_SESSION_DAYS` |
| Rate limits | login, register, assistant and posting are rate-limited per user/IP |
| Isolation | every query is scoped to the signed-in user; tests try cross-user access |
| Minors | under-18 accounts use guardian/supported consent mode; cannot be caregivers; adults cannot message them privately in Community |
| Audit log | sign-in, sharing changes, exports, deletion, moderation actions |
| Export / delete | Settings → download all my data (JSON); delete account removes rows, not just hides them |
| Legacy API | the old open `/chat`, `/agent`, `/events`… endpoints stay for the notebook; set `NEUROBRIDGE_DISABLE_LEGACY_API=1` in production |

No compliance claim (GDPR, DPDP Act, HIPAA) is made — that needs a real assessment.

## Consent: how a caregiver sees anything

1. The caregiver invites the individual (the reply never reveals whether an email exists).
2. The individual accepts. **The link alone grants nothing.**
3. The individual turns on scopes one by one: `blueprint`, `routines`, `calendar`, `goals`,
   `tasks`, `checkin_summary`, `coordination` — and inside each scope only items they mark
   *shared* are visible.
4. Journal, AI memory and AI conversations are **never** shareable.
5. Revoking a scope or disconnecting removes access immediately. Every change is recorded in
   `consent_records`.

## Individual experience

My Day (energy check-in, "maybe start with", tasks, coming up, routines, done today) ·
Assistant · Tasks (steps, *Help me start*, *What next?*, focus/body-doubling timer, postpone
without penalty) · Routines (templates, step player, skip/alternative steps, no streaks) ·
Check-in (tap-only options; notes optional) · Sensory toolkit (strategies you can like/hide,
kit checklist, sensory diary) · Communication cards (categories, favourites, full-screen,
text-to-speech) · Journal (private, tags, search, optional AI reflection) · Support
Blueprint (13 sections, per-section sharing, export) · Goals · Learn & life skills · Community ·
Events & groups · Providers & appointments · My circle · Settings.

**I'm overwhelmed** is on every page: a low-stimulation screen with one question and six
choices (Quiet, Less talking, Help me communicate, Grounding, I need someone, I'm not sure).
"I need someone" sends a support request only to the active circle.

## Caregiver experience

Dashboard · Care assistant (can use only what the person has shared) · Care calendar ·
Care journal (private by default; *patterns* are counts with a "this is not a cause"
notice) · People I support (consent-based view) · Coordination (care tasks, handovers,
contacts — needs the `coordination` scope) · Support requests · Learning hub · Providers ·
Events · Community · Wellbeing (stress check-in, rest and delegation ideas, no guilt).

## Community Connect

Interest groups (14 seeded in `nbapp/content.py`: ADHD body-doubling, autistic adults,
parents & caregivers, sensory tips, special interests club, study & work, art & making, Goa
meetups, hearing voices peer space, plural & DID respectful space, games & puzzles club,
nature walks club, quiet social club, carer wellbeing; under-18s can join only groups
marked safe for minors), posts, replies, supportive reactions, peer connections and
private messages between connected adults, report, block, moderator queue, and user-proposed
events that an admin reviews.

Safety rules (`nbapp/moderation.py`): content is **held for a human, never silently
deleted**, when it contains crisis language (author is shown 112 / Tele-MANAS 14416
immediately), abuse, phone numbers/emails/addresses, or spam. Three reports hold a post.
Joining requires a handle (not a real name) and agreeing to the guidelines.

## The assistant (chat LLM + deep agent together)

`POST /api/assistant/message` with `mode` = `auto | chat | agent`:

- **Safety first**: emergencies, self-harm, command hallucinations, harm to others get the
  fixed, sourced guidance with no LLM call and no actions.
- **auto** routes to the **agent** for research, sources, places, providers, events and
  bookings; to **chat** for conversation, planning and wording help.
- Chat uses the person's preferences (short/detailed/simple language), shared context and
  memories (only if memory is on). The reply lists which context was used.
- Agent runs show friendly activity steps (Understanding request → Searching → Reading
  sources → Verifying → Completing task), sources, and approvals. Bookings run only when
  the user ticks *allow actions* **and** approves the exact details.
- The **Model** menu appears when more than one model is loaded (Groq, Gemini, NeuroBridge
  base / SFT / SFT+ORPO).

## Providers and appointments (v0.6)

**Admin → Provider directory.** Add a psychiatrist, psychologist, counsellor or therapist with
qualifications/registration, address, phone, email, website and the link the details came
from. A listing is hidden until you **Verify & list** it with a note saying what you checked
(e.g. registration looked up on the State Medical Council / NMC or RCI register; clinic phoned
and agreed to receive NeuroBridge bookings). The note and date are shown to users. Add the
times the clinic agreed to. **Reserved appointments** lists each booking with the person's
name and phone *only if they chose to share them*; after calling the clinic, press
**Clinic confirmed** or **Declined** (declining frees the time). The person is notified.

**Person → Providers & appointments.** Filter by profession, see what was checked, pick a
time, optionally share name and phone with the clinic, and confirm the exact details. Status:
*Request — needs your confirmation* → *Reserved — waiting for the clinic* → *Confirmed by the
clinic* (or *Cancelled*). Under-18 accounts can't book directly.

**Agent.** *"Find a psychiatrist in Panaji who understands adult ADHD and book an appointment"*
(with **Allow bookings** ticked) searches the web for real providers (cited sources), checks
the directory, picks the best listed time (real listings first, then specialty match, then
earliest) and asks you to approve the exact provider, time, place and fee. Nothing is booked
without that approval. If no listed provider fits, nothing is booked; each source gets
**＋ Track this clinic**, which saves it under *Clinics I'm contacting* with a drafted message
(copy, call, WhatsApp or email) and a status you update yourself.

## Demo data

`python scripts/seed_demo_app.py --password '...'` creates Asha (individual), Ravi
(caregiver linked to Asha) and a moderator, all `@demo.neurobridge.local`, plus demo events
and four demo clinics (two psychiatry, one psychology, one OT) with open times, all labelled *demo*. Never run it on a real deployment.

## Not finished

- No email sending (invites and password reset are shown in-app only).
- Notifications are in-app; no push/SMS.
- UI text is English; the assistant answers in the chosen language, but interface
  translation strings exist only for a few labels (`static/i18n.js`).
- Speech-to-text depends on the browser (Chrome works; Firefox does not).
- Moderation word lists are short starting points and English-only.
- SQLite is fine for a pilot; use PostgreSQL for many simultaneous users.
