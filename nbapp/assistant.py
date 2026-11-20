"""The NeuroBridge AI Assistant for signed-in users: one place that uses BOTH the chatbot
LLM (conversation, planning, communication help) and the deep agent (web research with
citations, finding providers/events, bookings that need approval).

Routing ("auto" mode): requests that need fresh facts, sources, places, people or a booking
go to the agent; everything else goes to chat. The user can force either mode.
Safety runs first in both: emergencies, self-harm and crisis signals get the fixed,
verified guidance (agent/safety) with no LLM call and no actions.
"""
import json
import re
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nbapp import consent
from nbapp.db import now
from nbapp.routes_auth import memory_key, DEFAULT_PREFS
from nbapp.security import current_user, get_db, limiter

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

AGENT_RE = re.compile(
    r"\b(research|search (?:for|the web)|look up|sources?|citations?|cite|"
    r"evidence|studies|study shows|latest|news|near me|nearby|in (?:my )?(?:city|area)|"
    r"therapists?|psychologists?|psychiatrists?|clinics?|providers?|organi[sz]ations?|"
    r"support groups?|workshops?|clubs?|meet-?ups?|gatherings?|events?|book|booking|"
    r"register|sign me up|appointments?|schemes?|helplines?)\b", re.IGNORECASE)
CHAT_FIRST_RE = re.compile(r"^(?:how do i|how can i|help me (?:write|draft|plan|start|"
                           r"understand)|can you explain|what is|what are|why do|i feel|i'm|im )",
                           re.IGNORECASE)

ACTIVITY_LABELS = {"skills": "Understanding request", "plan": "Creating plan",
                   "execute": "Searching", "read": "Reading sources", "observe": "Processing information",
                   "synthesize": "Writing answer", "verify": "Verifying", "correct": "Correcting",
                   "replan": "Replanning", "goal_gate": "Checking the goal", "approval": "Waiting for "
                   "your approval", "finish": "Completing task", "safety": "Safety check"}

ASSISTANT_PROMPT = (
    "You are NeuroBridge, a neurodiversity-affirming support assistant for neurodivergent "
    "people and the people who support them. Neurodivergence is not something to cure. "
    "Respect autonomy: offer choices, never coerce, never treat compliance or masking as the "
    "goal. Do not diagnose, prescribe, or suggest medication changes; suggest a professional "
    "where appropriate. Never claim causes of behaviour with certainty. "
    "For task help: give ONE small first step unless asked for more. "
    "Do not invent names, phone numbers, links, prices or bookings; for facts, places or "
    "providers the user can switch to Research, which searches the web and cites sources. "
    "Do not say you have done anything (booked, sent, saved) — you cannot act from chat. "
    "In sensitive situations be soft, slow and calming, but say plainly when medical help is "
    "needed, and that they must call 112 if it is severe or sudden. Always finish your answer."
)


def decide_mode(message: str) -> str:
    text = message.strip()
    if CHAT_FIRST_RE.search(text) and not re.search(r"\b(near me|sources?|research|book|register|"
                                                    r"sign me up)\b", text, re.IGNORECASE):
        return "chat"
    return "agent" if AGENT_RE.search(text) else "chat"


def _core():
    import agent.api.app as core
    return core


def _prefs(db, user):
    row = db.one("SELECT prefs FROM user_settings WHERE user_id=?", (user["id"],))
    return {**DEFAULT_PREFS, **(json.loads(row["prefs"]) if row else {})}


def build_context(db, user, about_individual_id=None):
    """Personal context for the system prompt — only what this user may see."""
    from nbapp.routes_personal import blueprint_for
    prefs = _prefs(db, user)
    parts = [f"The user is a {'neurodivergent individual' if user['role'] == 'individual' else 'caregiver/supporter'}"
             f" called {user['display_name']}."]
    if user["is_minor"]:
        parts.append("The user is under 18: keep content age-appropriate.")
    if prefs.get("simple_language"):
        parts.append("Use simple, plain language and short sentences.")
    length = prefs.get("response_length", "balanced")
    if length == "short":
        parts.append("Keep answers short: at most 4 sentences or 4 bullet points.")
    elif length == "detailed":
        parts.append("The user likes detailed answers with clear headings.")
    used = []
    if user["role"] == "individual":
        bp = [s for s in blueprint_for(db, user["id"]) if s["content"].strip()]
        if bp:
            used.append("your Support Blueprint")
            parts.append("Their own Support Blueprint (use it to personalise; don't recite it):\n" +
                         "\n".join(f"- {s['title']}: {s['content'][:300]}" for s in bp[:8]))
    elif about_individual_id:
        if consent.can_view(db, user, about_individual_id, "blueprint"):
            person = db.one("SELECT display_name FROM users WHERE id=?", (about_individual_id,))
            bp = blueprint_for(db, about_individual_id, shared_only=True)
            if bp:
                used.append(f"{person['display_name']}'s shared Blueprint")
                parts.append(f"The caregiver is asking about {person['display_name']}, who chose "
                             "to share this (respect it; their preferences come first):\n" +
                             "\n".join(f"- {s['title']}: {s['content'][:300]}" for s in bp[:8]))
    if prefs.get("memory_enabled", True):
        from agent.memory.memory_store import memory_context
        mem = memory_context(memory_key(user))
        if mem and "no " not in mem.lower()[:20]:
            used.append("saved memories")
            parts.append(mem)
    return "\n".join(parts), used, prefs


class MessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=6000)
    conversation_id: Optional[int] = None
    mode: str = "auto"  # auto | chat | agent
    provider: Optional[str] = None
    allow_actions: bool = False
    about_individual_id: Optional[int] = None
    language: Optional[str] = None


def _conversation(db, user, cid):
    c = db.one("SELECT * FROM conversations WHERE id=?", (cid,))
    if not c or c["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return c


def _save(db, cid, role, text, mode=None, meta=None, sources=None):
    mid = db.insert("ai_messages", conversation_id=cid, role=role, content=text, mode=mode,
                    meta=json.dumps(meta or {}), created_at=now())
    for s in sources or []:
        db.insert("ai_sources", message_id=mid, ref=s.get("ref") or s.get("id"),
                  title=s.get("title"), url=s.get("url"), published=s.get("published"))
    db.run("UPDATE conversations SET updated_at=? WHERE id=?", (now(), cid))
    return mid


def summarise_run(run):
    seen, activity = set(), []
    for e in run.get("trace", []):
        label = ACTIVITY_LABELS.get(e.get("phase"))
        if label and label not in seen:
            seen.add(label)
            activity.append(label)
    return {"status": run.get("status"), "run_id": run.get("run_id"), "activity": activity,
            "approvals": [a for a in run.get("approvals", []) if a.get("status") == "pending"],
            "verification": {k: run.get("verification", {}).get(k) for k in
                             ("decision", "supported", "unsupported_claims") if
                             isinstance(run.get("verification"), dict)},
            "errors": run.get("errors", []),
            "provider_request": bool(run.get("provider_request"))}


def _history(db, cid, limit=12):
    rows = db.all("SELECT role, content FROM ai_messages WHERE conversation_id=? ORDER BY id DESC "
                  "LIMIT ?", (cid, limit))
    return [{"role": r["role"], "content": r["content"][:3000]} for r in reversed(rows)]


def chat_llm(db, user, message, history, provider=None, language=None, about=None,
             extra_system=None, max_tokens=2048):
    core = _core()
    if core.gateway is None:
        raise HTTPException(status_code=503, detail="No AI model is connected. Add a GROQ_API_KEY "
                                                    "or GEMINI_API_KEY (see README), then restart.")
    from agent.safety.policy import classify_input, enforce_output
    from agent.llm.multilingual_gateway import multilingual_generate
    safety = classify_input(message)
    ctx, used, prefs = build_context(db, user, about)
    system = ASSISTANT_PROMPT + "\n" + ctx
    if safety["policy_note"]:
        system += "\nSAFETY NOTE: " + safety["policy_note"]
    if extra_system:
        system += "\n" + extra_system
    messages = history + [{"role": "user", "content": message}]

    def call(note=None):
        return multilingual_generate(gateway=core.gateway, messages=messages,
                                     preferred_language=language or user.get("language"),
                                     system_prompt=system + ("\n" + note if note else ""),
                                     provider=provider, temperature=0.4, max_tokens=max_tokens)
    resp = call()
    text, out_safety = enforce_output(core.extract_response_text(resp),
                                      regenerate=lambda n: core.extract_response_text(call(n)))
    prov = getattr(resp, "provider", provider)
    return text, {"provider": prov, "label": core.provider_label(prov or ""),
                  "context_used": used, "safety": {"category": safety["category"],
                                                   "output": out_safety}}


@router.get("/conversations")
def list_conversations(user=Depends(current_user), db=Depends(get_db)):
    return {"conversations": db.all("SELECT * FROM conversations WHERE owner_id=? ORDER BY "
                                    "updated_at DESC LIMIT 100", (user["id"],))}


@router.get("/conversations/{cid}")
def get_conversation(cid: int, user=Depends(current_user), db=Depends(get_db)):
    c = _conversation(db, user, cid)
    msgs = db.all("SELECT * FROM ai_messages WHERE conversation_id=? ORDER BY id", (cid,))
    for m in msgs:
        m["meta"] = json.loads(m["meta"] or "{}")
        m["sources"] = db.all("SELECT ref, title, url, published FROM ai_sources WHERE message_id=?",
                              (m["id"],))
    return {"conversation": c, "messages": msgs}


@router.delete("/conversations/{cid}")
def delete_conversation(cid: int, user=Depends(current_user), db=Depends(get_db)):
    _conversation(db, user, cid)
    db.run("DELETE FROM conversations WHERE id=?", (cid,))
    return {"deleted": True}


@router.post("/message")
def message(body: MessageBody, user=Depends(current_user), db=Depends(get_db)):
    limiter.check(("assistant", user["id"]), 40, 600)
    if body.about_individual_id and not consent.link_between(db, body.about_individual_id,
                                                             user["id"]):
        raise HTTPException(status_code=403, detail="You are not connected to this person.")
    if body.conversation_id:
        conv = _conversation(db, user, body.conversation_id)
    else:
        cid = db.insert("conversations", owner_id=user["id"], title=body.message[:60],
                        about_individual_id=body.about_individual_id, created_at=now(),
                        updated_at=now())
        conv = db.one("SELECT * FROM conversations WHERE id=?", (cid,))
    cid = conv["id"]
    history = _history(db, cid)
    _save(db, cid, "user", body.message)

    from agent.safety.policy import classify_input
    safety = classify_input(body.message)
    if safety["halt_agent"]:
        meta = {"safety": {"category": safety["category"]}, "llm_called": False,
                "emergency": True}
        mid = _save(db, cid, "assistant", safety["override_response"], "safety", meta)
        return {"conversation_id": cid, "message_id": mid, "mode": "safety",
                "reply": safety["override_response"], "meta": meta, "sources": []}

    mode = body.mode if body.mode in ("chat", "agent") else decide_mode(body.message)
    if mode == "chat":
        try:
            text, meta = chat_llm(db, user, body.message, history, body.provider, body.language,
                                  conv["about_individual_id"])
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"The AI model did not respond ({exc}). "
                                                        "Please try again.")
        meta["routed"] = body.mode == "auto"
        mid = _save(db, cid, "assistant", text, "chat", meta)
        return {"conversation_id": cid, "message_id": mid, "mode": "chat", "reply": text,
                "meta": meta, "sources": []}

    core = _core()
    if core.agent is None:
        raise HTTPException(status_code=503, detail="The research agent is not running.")
    from agent.tools.builtin import BOOKING_WRITE
    perms = {BOOKING_WRITE} if body.allow_actions else set()
    try:
        run = core.agent.run(body.message, user_id=memory_key(user),
                             preferred_language=body.language or user.get("language"),
                             granted_permissions=perms)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"The agent hit an error ({exc}).")
    return _store_run(db, user, cid, run, routed=body.mode == "auto")


def _store_run(db, user, cid, run, routed=False):
    meta = summarise_run(run)
    meta["routed"] = routed
    meta["actions_allowed"] = bool(run.get("approvals")) or None
    text = run.get("answer") or ("I couldn't complete this. " + "; ".join(run.get("errors") or []))
    if run.get("status") == "WAITING_APPROVAL" and not run.get("answer"):
        text = "I've prepared this, but I need your approval before doing anything."
    mid = _save(db, cid, "assistant", text, "agent", meta, run.get("sources"))
    with db.connect() as c:
        c.execute("INSERT INTO agent_runs (run_id, owner_id, conversation_id, status, created_at) "
                  "VALUES (?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET status=excluded.status",
                  (run["run_id"], user["id"], cid, run.get("status"), now()))
    return {"conversation_id": cid, "message_id": mid, "mode": "agent", "reply": text,
            "meta": meta, "sources": run.get("sources") or []}


class ApprovalBody(BaseModel):
    approval_id: str
    approved: bool
    reason: Optional[str] = Field(default=None, max_length=300)


@router.post("/runs/{run_id}/approve")
def approve(run_id: str, body: ApprovalBody, user=Depends(current_user), db=Depends(get_db)):
    owned = db.one("SELECT * FROM agent_runs WHERE run_id=?", (run_id,))
    if not owned or owned["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Not found")
    core = _core()
    try:
        run = core.agent.resume(run_id, body.approval_id, approved=body.approved,
                                reviewed_by=f"user:{user['id']}", rejection_reason=body.reason)
    except KeyError:
        raise HTTPException(status_code=410, detail="This request has expired (the server "
                                                    "restarted). Please ask again.")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.audit(user["id"], "agent_approval", run_id, "approved" if body.approved else "rejected")
    return _store_run(db, user, owned["conversation_id"], run)


# ----------------------------------------------------------------------------- task help
class HelpBody(BaseModel):
    task_id: int
    kind: str = "start"  # start | next | simplify


RULE_STARTERS = {
    "start": "Set a 2-minute timer and do only the very first visible part of: {t}.",
    "next": "Pick the smallest piece of what's left of '{t}' and do just that.",
    "simplify": "Make '{t}' smaller: what is the 'good enough' version you could do today?",
}


@router.post("/task-help")
def task_help(body: HelpBody, user=Depends(current_user), db=Depends(get_db)):
    task = db.one("SELECT * FROM tasks WHERE id=? AND owner_id=?", (body.task_id, user["id"]))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if body.kind not in RULE_STARTERS:
        raise HTTPException(status_code=400, detail="Unknown help type")
    steps = db.all("SELECT text, done FROM task_steps WHERE task_id=? ORDER BY position",
                   (task["id"],))
    done = [s["text"] for s in steps if s["done"]]
    core = _core()
    if core.gateway is None:
        text, source = RULE_STARTERS[body.kind].format(t=task["title"]), "rule"
    else:
        ask = {"start": "Give ONE tiny, concrete first action (under 20 words) to start this task. "
                        "No list, no explanation.",
               "next": "Give the ONE next tiny action (under 20 words). No list.",
               "simplify": "Suggest a simpler 'good enough' version of this task in one sentence."}
        prompt = (f"Task: {task['title']}\nNotes: {task['notes'] or '-'}\n"
                  f"Already done: {', '.join(done) or 'nothing yet'}\n{ask[body.kind]}")
        try:
            text, _ = chat_llm(db, user, prompt, [], max_tokens=200)
            text, source = text.strip().split("\n")[0][:300], "ai"
        except HTTPException:
            raise
        except Exception:
            text, source = RULE_STARTERS[body.kind].format(t=task["title"]), "rule"
    if body.kind != "simplify":
        pos = db.one("SELECT COALESCE(MAX(position),-1)+1 p FROM task_steps WHERE task_id=?",
                     (task["id"],))["p"]
        db.insert("task_steps", task_id=task["id"], text=text, source=source, position=pos)
    return {"step": text, "source": source,
            "note": "Simple starter (no AI connected)." if source == "rule" else None}


class ReflectBody(BaseModel):
    journal_id: int


@router.post("/reflect")
def reflect(body: ReflectBody, user=Depends(current_user), db=Depends(get_db)):
    """Optional AI reflection on one journal entry, only when the user presses the button.
    The text is sent to the configured AI provider; the reflection is not saved."""
    e = db.one("SELECT * FROM journal_entries WHERE id=? AND owner_id=?", (body.journal_id, user["id"]))
    if not e:
        raise HTTPException(status_code=404, detail="Entry not found")
    text, meta = chat_llm(db, user, "Here is my journal entry. Reflect it back gently in 3–5 "
                                    "sentences: what you notice, one kind observation, and one "
                                    "optional question. No advice unless I ask, no diagnosis.\n\n"
                          + e["body"][:6000], [], max_tokens=600)
    return {"reflection": text, "provider": meta.get("label")}


# ----------------------------------------------------------------------------- memory
class MemorySuggest(BaseModel):
    conversation_id: int


class MemorySave(BaseModel):
    candidates: List[dict]
    approved_keys: List[str]
    allow_sensitive: bool = False


@router.get("/memory")
def memory_list(user=Depends(current_user), db=Depends(get_db)):
    from agent.memory.memory_store import get_memories
    return {"memories": get_memories(memory_key(user)),
            "enabled": _prefs(db, user).get("memory_enabled", True),
            "explanation": "NeuroBridge only remembers things you approve. Your memories are "
                           "never shown to anyone in your circle."}


@router.delete("/memory/{key}")
def memory_forget(key: str, user=Depends(current_user)):
    from agent.memory.memory_store import delete_memory
    delete_memory(memory_key(user), key)
    return {"deleted": True}


@router.post("/memory/suggest")
def memory_suggest(body: MemorySuggest, user=Depends(current_user), db=Depends(get_db)):
    if not _prefs(db, user).get("memory_enabled", True):
        raise HTTPException(status_code=409, detail="Memory is switched off in Settings.")
    _conversation(db, user, body.conversation_id)
    core = _core()
    if core.gateway is None:
        raise HTTPException(status_code=503, detail="No AI model connected")
    from agent.memory.memory_manager import extract_memory_candidates
    from agent.memory.memory_store import get_memories
    text = "\n".join(f"{m['role']}: {m['content']}" for m in _history(db, body.conversation_id, 20))
    result = extract_memory_candidates(core.gateway, text, get_memories(memory_key(user)))
    return {"candidates": result.get("candidates", []), "requires_user_approval": True}


@router.post("/memory/save")
def memory_save(body: MemorySave, user=Depends(current_user), db=Depends(get_db)):
    if not _prefs(db, user).get("memory_enabled", True):
        raise HTTPException(status_code=409, detail="Memory is switched off in Settings.")
    from agent.memory.memory_manager import is_sensitive_text
    from agent.memory.memory_store import save_memory
    saved, rejected = [], []
    for c in body.candidates[:20]:
        key = str(c.get("key", ""))[:80]
        if key not in body.approved_keys:
            continue
        sensitive = bool(c.get("sensitive")) or is_sensitive_text(f"{key} {c.get('value', '')}")
        if sensitive and not body.allow_sensitive:
            rejected.append({"key": key, "reason": "sensitive: needs separate approval"})
            continue
        r = save_memory(user_id=memory_key(user), memory_type=c.get("memory_type", "long_term"),
                        category=c.get("category", "other"), key=key,
                        value=str(c.get("value", ""))[:500], consent=True, source="user_approved")
        (saved if r.get("success") else rejected).append(key if r.get("success") else
                                                         {"key": key, "reason": r.get("error")})
    db.audit(user["id"], "memory_saved", detail=str(len(saved)))
    return {"saved": saved, "rejected": rejected}
