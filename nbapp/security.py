"""Passwords, sessions, rate limiting, and the `current_user` dependency.

- Passwords: PBKDF2-HMAC-SHA256, 310 000 iterations, 16-byte random salt (stdlib hashlib).
- Sessions: random 32-byte bearer token; only its SHA-256 is stored, so a leaked database
  does not leak live sessions. Default lifetime 14 days (NEUROBRIDGE_SESSION_DAYS).
- Rate limiting: in-memory sliding window per (client, bucket). Good enough for one process;
  use a shared store (e.g. Redis) if you run several workers.
"""
import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request

ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(ITERATIONS, base64.b64encode(salt).decode(),
                                          base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64),
                                 int(iters))
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def password_problem(password: str):
    if len(password) < 10:
        return "Use at least 10 characters."
    if password.lower() == password and password.isalpha():
        return "Add a number, symbol or capital letter."
    return None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(db, user_id):
    token = secrets.token_urlsafe(32)
    days = int(os.environ.get("NEUROBRIDGE_SESSION_DAYS", "14"))
    created = datetime.now(timezone.utc)
    db.insert("sessions", token_hash=token_hash(token), user_id=user_id,
              created_at=created.isoformat(timespec="seconds"),
              expires_at=(created + timedelta(days=days)).isoformat(timespec="seconds"))
    return token


class RateLimiter:
    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key, limit, window_s):
        t = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and t - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                raise HTTPException(status_code=429,
                                    detail="Too many requests. Please wait a moment and try again.")
            q.append(t)

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_key(request: Request):
    return request.client.host if request.client else "unknown"


def get_db():
    from nbapp import state
    if state.db is None:
        raise HTTPException(status_code=503, detail="App database not initialised")
    return state.db


def current_user(authorization: str = Header(default=None), db=Depends(get_db)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please sign in.")
    token = authorization.split(" ", 1)[1].strip()
    row = db.one("SELECT s.expires_at, u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                 "WHERE s.token_hash = ?", (token_hash(token),))
    if not row:
        raise HTTPException(status_code=401, detail="Your session has ended. Please sign in again.")
    if row["expires_at"] < datetime.now(timezone.utc).isoformat(timespec="seconds"):
        db.run("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        raise HTTPException(status_code=401, detail="Your session has ended. Please sign in again.")
    if row["disabled"]:
        raise HTTPException(status_code=403, detail="This account is disabled.")
    row.pop("password_hash", None)
    row["_token_hash"] = token_hash(token)
    return row


def require_role(*roles):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="This page is not available for your "
                                                        "account type.")
        return user
    return dep


def public_user(u):
    return {"id": u["id"], "email": u["email"], "display_name": u["display_name"],
            "role": u["role"], "is_minor": bool(u["is_minor"]),
            "consent_mode": u["consent_mode"], "language": u.get("language") or "en"}
