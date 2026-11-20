"""NeuroBridge web application layer: accounts, roles, consent, individual & caregiver
experiences, Community Connect, and the AI assistant that joins chat + agent.

Mounted onto the existing FastAPI app in agent/api/app.py (the agent API is unchanged).
"""
import os
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from nbapp import state
from nbapp.db import Database, now

STATIC = Path(__file__).resolve().parent / "static"


def setup_database(path=None):
    """Create/migrate the app database, seed starter groups, create the admin if configured."""
    state.db = Database(path)
    from nbapp.routes_community import seed_groups
    seed_groups(state.db)
    _bootstrap_admin(state.db)
    return state.db


def _bootstrap_admin(db):
    """Create an admin account from env vars (never hard-coded):
    NEUROBRIDGE_ADMIN_EMAIL and NEUROBRIDGE_ADMIN_PASSWORD."""
    email = (os.environ.get("NEUROBRIDGE_ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("NEUROBRIDGE_ADMIN_PASSWORD") or ""
    if not email or not password:
        return
    if db.one("SELECT id FROM users WHERE email=?", (email,)):
        return
    from nbapp.security import hash_password
    from nbapp.routes_auth import seed_user_defaults
    uid = db.insert("users", email=email, password_hash=hash_password(password),
                    display_name="Admin", role="admin", created_at=now())
    seed_user_defaults(db, uid, "admin")
    db.audit(uid, "admin_bootstrap")


def init_app(app):
    from nbapp import (routes_auth, routes_personal, routes_care, routes_community,
                       routes_misc, assistant)
    for module in (routes_auth, routes_personal, routes_care, routes_community, routes_misc,
                   assistant):
        app.include_router(module.router)
    app.mount("/app-static", StaticFiles(directory=STATIC), name="app-static")

    @app.get("/app", include_in_schema=False)
    def web_app():
        return FileResponse(STATIC / "app.html", headers={"Cache-Control": "no-cache"})
