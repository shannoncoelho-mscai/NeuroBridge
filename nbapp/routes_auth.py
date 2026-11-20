"""Accounts: register, sign in/out, me, settings, export, secure deletion."""
import json
import re
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from nbapp import content
from nbapp.db import now
from nbapp.security import (hash_password, verify_password, password_problem, new_session,
                            current_user, get_db, limiter, client_key, public_user)

router = APIRouter(prefix="/api", tags=["accounts"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DEFAULT_PREFS = {
    "font_scale": 1.0, "dyslexia_font": False, "high_contrast": False, "reduced_motion": False,
    "low_stimulation": False, "simple_language": False, "response_length": "balanced",
    "tts": True, "memory_enabled": True, "theme": "light",
}


class RegisterBody(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)
    display_name: str = Field(min_length=1, max_length=60)
    role: str
    is_minor: bool = False
    language: str = "en"


class LoginBody(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class SettingsBody(BaseModel):
    prefs: Dict[str, Any] = Field(default_factory=dict)
    display_name: Optional[str] = Field(default=None, max_length=60)
    language: Optional[str] = Field(default=None, max_length=10)
    consent_mode: Optional[str] = None


class DeleteBody(BaseModel):
    password: str


def seed_user_defaults(db, user_id, role):
    for i, (text, cat, sym) in enumerate(content.DEFAULT_CARDS):
        db.insert("comm_cards", owner_id=user_id, text=text, category=cat, symbol=sym,
                  is_default=1, position=i)
    for item in content.DEFAULT_KIT:
        db.insert("sensory_kit", owner_id=user_id, item=item)
    db.insert("user_settings", user_id=user_id, prefs=json.dumps(DEFAULT_PREFS))


@router.post("/auth/register")
def register(body: RegisterBody, request: Request, db=Depends(get_db)):
    limiter.check(("register", client_key(request)), 10, 3600)
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if body.role not in ("individual", "caregiver"):
        raise HTTPException(status_code=400, detail="Choose 'individual' or 'caregiver'.")
    if body.is_minor and body.role != "individual":
        raise HTTPException(status_code=400, detail="Caregiver accounts are for adults.")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    if db.one("SELECT id FROM users WHERE email=?", (email,)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    uid = db.insert("users", email=email, password_hash=hash_password(body.password),
                    display_name=body.display_name.strip(), role=body.role,
                    is_minor=int(body.is_minor),
                    consent_mode="guardian" if body.is_minor else "self",
                    language=body.language[:10], created_at=now())
    seed_user_defaults(db, uid, body.role)
    db.audit(uid, "register", detail=body.role)
    token = new_session(db, uid)
    user = db.one("SELECT * FROM users WHERE id=?", (uid,))
    return {"token": token, "user": public_user(user)}


@router.post("/auth/login")
def login(body: LoginBody, request: Request, db=Depends(get_db)):
    email = body.email.strip().lower()
    limiter.check(("login", client_key(request), email), 8, 900)
    user = db.one("SELECT * FROM users WHERE email=?", (email,))
    if not user or not verify_password(body.password, user["password_hash"]):
        db.audit(user["id"] if user else None, "login_failed")
        raise HTTPException(status_code=401, detail="Email or password is not right.")
    if user["disabled"]:
        raise HTTPException(status_code=403, detail="This account is disabled.")
    db.audit(user["id"], "login")
    return {"token": new_session(db, user["id"]), "user": public_user(user)}


@router.post("/auth/logout")
def logout(user=Depends(current_user), db=Depends(get_db)):
    db.run("DELETE FROM sessions WHERE token_hash=?", (user["_token_hash"],))
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user), db=Depends(get_db)):
    row = db.one("SELECT prefs FROM user_settings WHERE user_id=?", (user["id"],))
    prefs = {**DEFAULT_PREFS, **(json.loads(row["prefs"]) if row else {})}
    unread = db.one("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND read_at IS NULL",
                    (user["id"],))["n"]
    return {"user": public_user(user), "prefs": prefs, "unread_notifications": unread}


@router.put("/me/settings")
def update_settings(body: SettingsBody, user=Depends(current_user), db=Depends(get_db)):
    row = db.one("SELECT prefs FROM user_settings WHERE user_id=?", (user["id"],))
    prefs = {**DEFAULT_PREFS, **(json.loads(row["prefs"]) if row else {})}
    allowed = set(DEFAULT_PREFS) | {"notifications", "favorite_tools"}
    for k, v in body.prefs.items():
        if k in allowed:
            prefs[k] = v
    with db.connect() as c:
        c.execute("INSERT INTO user_settings (user_id, prefs) VALUES (?,?) ON CONFLICT(user_id) "
                  "DO UPDATE SET prefs=excluded.prefs", (user["id"], json.dumps(prefs)))
    changes = {}
    if body.display_name:
        changes["display_name"] = body.display_name.strip()
    if body.language:
        changes["language"] = body.language
    if body.consent_mode:
        if body.consent_mode not in ("self", "guardian", "supported"):
            raise HTTPException(status_code=400, detail="Unknown consent mode")
        if user["role"] != "individual":
            raise HTTPException(status_code=403, detail="Consent mode applies to individuals.")
        if user["is_minor"] and body.consent_mode == "self":
            raise HTTPException(status_code=403, detail="Accounts for under-18s use guardian "
                                                        "or supported consent.")
        changes["consent_mode"] = body.consent_mode
        db.audit(user["id"], "consent_mode", detail=body.consent_mode)
    db.update("users", "id=?", (user["id"],), **changes)
    if prefs.get("memory_enabled") is False:
        db.audit(user["id"], "memory_disabled")
    return me(user=db.one("SELECT * FROM users WHERE id=?", (user["id"],)) | {"_token_hash": ""},
              db=db)


EXPORT_TABLES = {
    "tasks": "owner_id", "routines": "owner_id", "checkins": "owner_id",
    "journal_entries": "owner_id", "comm_cards": "owner_id", "blueprint_sections": "owner_id",
    "goals": "owner_id", "sensory_strategies": "owner_id", "sensory_diary": "owner_id",
    "sensory_kit": "owner_id", "calendar_events": "owner_id", "focus_sessions": "owner_id",
    "care_journal": "author_id", "care_contacts": "owner_id", "wellbeing_checkins": "owner_id",
    "conversations": "owner_id", "notifications": "user_id", "posts": "author_id",
    "comments": "author_id",
}


@router.get("/me/export")
def export_data(user=Depends(current_user), db=Depends(get_db)):
    from agent.memory.memory_store import get_memories
    out = {"user": public_user(user), "exported_at": now()}
    for table, col in EXPORT_TABLES.items():
        out[table] = db.all(f"SELECT * FROM {table} WHERE {col}=?", (user["id"],))
    out["routine_steps"] = db.all("SELECT s.* FROM routine_steps s JOIN routines r ON "
                                  "r.id=s.routine_id WHERE r.owner_id=?", (user["id"],))
    out["ai_messages"] = db.all("SELECT m.* FROM ai_messages m JOIN conversations c ON "
                                "c.id=m.conversation_id WHERE c.owner_id=?", (user["id"],))
    out["memories"] = get_memories(memory_key(user))
    db.audit(user["id"], "export")
    return out


@router.delete("/me")
def delete_account(body: DeleteBody, user=Depends(current_user), db=Depends(get_db)):
    full = db.one("SELECT * FROM users WHERE id=?", (user["id"],))
    if not verify_password(body.password, full["password_hash"]):
        raise HTTPException(status_code=401, detail="Password is not right.")
    from agent.memory.memory_store import get_memories, delete_memory
    for m in get_memories(memory_key(user)):
        delete_memory(memory_key(user), m.get("key"))
    try:
        import agent.api.app as core
        if core.booking_store is not None:
            core.booking_store.delete_user_data(memory_key(user))
    except Exception:
        pass
    db.audit(user["id"], "account_deleted")
    with db.connect() as c:
        # ON DELETE CASCADE removes everything owned by this user.
        c.execute("DELETE FROM reports WHERE reporter_id=?", (user["id"],))
        c.execute("DELETE FROM users WHERE id=?", (user["id"],))
        c.execute("UPDATE audit_log SET detail=NULL WHERE user_id=?", (user["id"],))
    with db.connect() as c:
        c.execute("PRAGMA secure_delete = ON")
        c.execute("VACUUM")  # rewrite the file so deleted pages are not left behind
    return {"deleted": True}


def memory_key(user):
    """Key used for this user in the agent's memory / booking / event stores."""
    return f"u{user['id']}"
