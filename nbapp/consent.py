"""Care-circle consent.

Rules (project brief §7, §11, §17):
- A caregiver link starts with NO access. Being linked does not grant anything.
- Each kind of information is a separate scope. A caregiver may *request* a scope; only the
  individual can *grant* it — except in `guardian` consent mode (e.g. a minor), where a
  link marked as guardian may also grant. The individual always sees every grant.
- The private journal, AI memories and AI conversations are never shareable scopes.
- Every change is written to consent_records and the audit log.
"""
from fastapi import HTTPException

from nbapp.db import now

SCOPES = {
    "blueprint": "Shared parts of My Support Blueprint",
    "routines": "Routines you mark as shared",
    "calendar": "Calendar events you mark as shared",
    "goals": "Goals you mark as shared",
    "tasks": "Tasks you mark as shared",
    "checkin_summary": "A weekly summary of check-ins (not the notes)",
    "coordination": "Care tasks and shared support notes about you",
}
NEVER_SHARED = ("journal", "memory", "conversations")


def link_between(db, individual_id, caregiver_id, active_only=True):
    row = db.one("SELECT * FROM care_links WHERE individual_id=? AND caregiver_id=?",
                 (individual_id, caregiver_id))
    if row and active_only and row["status"] != "active":
        return None
    return row


def granted_scopes(db, link_id):
    return {r["scope"] for r in db.all("SELECT scope FROM link_permissions WHERE link_id=? AND "
                                        "state='granted'", (link_id,))}


def can_view(db, viewer, individual_id, scope):
    """True if `viewer` may see `scope` data of `individual_id`."""
    if viewer["id"] == individual_id:
        return True
    if scope not in SCOPES:
        return False
    link = link_between(db, individual_id, viewer["id"])
    return bool(link) and scope in granted_scopes(db, link["id"])


def require_view(db, viewer, individual_id, scope):
    if not can_view(db, viewer, individual_id, scope):
        raise HTTPException(status_code=403, detail="You don't have permission to see this. "
                                                    "The person can share it from their "
                                                    "Circle settings.")


def set_scope(db, actor, link, scope, state):
    if scope not in SCOPES:
        raise HTTPException(status_code=400, detail=f"Unknown or unshareable scope: {scope}")
    if link["status"] != "active":
        raise HTTPException(status_code=409, detail="This connection is not active.")
    individual = db.one("SELECT * FROM users WHERE id=?", (link["individual_id"],))
    is_individual = actor["id"] == link["individual_id"]
    is_guardian = (actor["id"] == link["caregiver_id"] and link["is_guardian"]
                   and individual["consent_mode"] == "guardian")
    if state == "granted" and not (is_individual or is_guardian):
        raise HTTPException(status_code=403, detail="Only the person themselves can share this.")
    if state == "requested" and actor["id"] != link["caregiver_id"]:
        raise HTTPException(status_code=403, detail="Only the supporter can request access.")
    if state == "revoked" and not (is_individual or is_guardian or
                                   actor["id"] == link["caregiver_id"]):
        raise HTTPException(status_code=403, detail="Not allowed.")
    if state == "requested":
        current = db.one("SELECT state FROM link_permissions WHERE link_id=? AND scope=?",
                         (link["id"], scope))
        if current and current["state"] == "granted":
            return "granted"
    with db.connect() as c:
        c.execute("INSERT INTO link_permissions (link_id, scope, state, updated_by, updated_at) "
                  "VALUES (?,?,?,?,?) ON CONFLICT(link_id, scope) DO UPDATE SET state=excluded.state,"
                  " updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                  (link["id"], scope, state, actor["id"], now()))
        c.execute("INSERT INTO consent_records (link_id, scope, action, actor_id, created_at) "
                  "VALUES (?,?,?,?,?)", (link["id"], scope, state, actor["id"], now()))
    db.audit(actor["id"], f"consent_{state}", f"link:{link['id']}", scope)
    return state


def circle_for_individual(db, individual_id):
    rows = db.all("SELECT l.*, u.display_name, u.email FROM care_links l JOIN users u ON "
                  "u.id=l.caregiver_id WHERE l.individual_id=? AND l.status IN ('pending','active')",
                  (individual_id,))
    for r in rows:
        r["permissions"] = {p["scope"]: p["state"] for p in
                            db.all("SELECT scope, state FROM link_permissions WHERE link_id=?",
                                   (r["id"],))}
    return rows


def people_for_caregiver(db, caregiver_id):
    rows = db.all("SELECT l.*, u.display_name, u.email, u.consent_mode, u.is_minor FROM care_links l "
                  "JOIN users u ON u.id=l.individual_id WHERE l.caregiver_id=? AND "
                  "l.status IN ('pending','active')", (caregiver_id,))
    for r in rows:
        r["permissions"] = {p["scope"]: p["state"] for p in
                            db.all("SELECT scope, state FROM link_permissions WHERE link_id=?",
                                   (r["id"],))}
    return rows
