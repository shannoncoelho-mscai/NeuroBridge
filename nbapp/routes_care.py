"""Circle of Support, consent, shared views, support requests, and caregiver tools
(care journal, coordination, handover notes, contacts, wellbeing, dashboard)."""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nbapp import consent
from nbapp.db import now
from nbapp.notify import notify
from nbapp.security import current_user, get_db, require_role

router = APIRouter(prefix="/api", tags=["care"])
SUPPORT_MESSAGES = ["I need help.", "I need quiet.", "Can you check on me?", "I need a break.",
                    "I need help with a task.", "Please call me.", "I'm OK, just letting you know."]


# ----------------------------------------------------------------------------- circle
class InviteBody(BaseModel):
    email: str = Field(max_length=200)
    relationship: Optional[str] = Field(default=None, max_length=60)
    is_guardian: bool = False


class LinkAction(BaseModel):
    action: str  # accept | decline | revoke


class ScopeBody(BaseModel):
    state: str  # requested | granted | revoked


@router.get("/circle")
def my_circle(user=Depends(current_user), db=Depends(get_db)):
    if user["role"] == "individual":
        links = consent.circle_for_individual(db, user["id"])
    else:
        links = consent.people_for_caregiver(db, user["id"])
    for l in links:
        l["waiting_for_me"] = l["status"] == "pending" and l["invited_by"] != user["id"]
    return {"links": links, "scopes": consent.SCOPES, "never_shared": list(consent.NEVER_SHARED),
            "support_messages": SUPPORT_MESSAGES}


@router.post("/circle/invite")
def invite(body: InviteBody, user=Depends(current_user), db=Depends(get_db)):
    generic = {"message": "If that person has a NeuroBridge account of the right type, they "
                          "will see your invitation. Nothing is shared until they accept and "
                          "the person chooses what to share."}
    other = db.one("SELECT * FROM users WHERE email=?", (body.email.strip().lower(),))
    if user["role"] == "individual":
        if not other or other["role"] != "caregiver":
            return generic
        individual_id, caregiver_id = user["id"], other["id"]
    elif user["role"] == "caregiver":
        if not other or other["role"] != "individual":
            return generic
        individual_id, caregiver_id = other["id"], user["id"]
    else:
        raise HTTPException(status_code=403, detail="Not available")
    existing = db.one("SELECT * FROM care_links WHERE individual_id=? AND caregiver_id=?",
                      (individual_id, caregiver_id))
    ts = now()
    if existing and existing["status"] in ("pending", "active"):
        return generic
    if existing:
        db.update("care_links", "id=?", (existing["id"],), status="pending", invited_by=user["id"],
                  is_guardian=int(body.is_guardian), relationship=body.relationship,
                  updated_at=ts)
        link_id = existing["id"]
        db.run("DELETE FROM link_permissions WHERE link_id=?", (link_id,))
    else:
        link_id = db.insert("care_links", individual_id=individual_id, caregiver_id=caregiver_id,
                            relationship=body.relationship, status="pending",
                            invited_by=user["id"], is_guardian=int(body.is_guardian),
                            created_at=ts, updated_at=ts)
    db.audit(user["id"], "circle_invite", f"link:{link_id}")
    notify(db, other["id"], "circle", f"{user['display_name']} invited you to connect",
           "Open Circle to accept or decline.", "#/circle")
    return generic


@router.post("/circle/{link_id}")
def link_action(link_id: int, body: LinkAction, user=Depends(current_user), db=Depends(get_db)):
    link = db.one("SELECT * FROM care_links WHERE id=?", (link_id,))
    if not link or user["id"] not in (link["individual_id"], link["caregiver_id"]):
        raise HTTPException(status_code=404, detail="Not found")
    other_id = link["caregiver_id"] if user["id"] == link["individual_id"] else link["individual_id"]
    if body.action in ("accept", "decline"):
        if link["status"] != "pending" or link["invited_by"] == user["id"]:
            raise HTTPException(status_code=409, detail="Nothing to accept here.")
        status = "active" if body.action == "accept" else "declined"
    elif body.action == "revoke":
        status = "revoked"
        db.run("UPDATE link_permissions SET state='revoked', updated_by=?, updated_at=? WHERE "
               "link_id=?", (user["id"], now(), link_id))
    else:
        raise HTTPException(status_code=400, detail="Unknown action")
    db.update("care_links", "id=?", (link_id,), status=status, updated_at=now())
    db.audit(user["id"], f"circle_{body.action}", f"link:{link_id}")
    notify(db, other_id, "circle", f"{user['display_name']} {body.action}ed the connection"
           if body.action != "revoke" else f"{user['display_name']} ended the connection",
           None, "#/circle")
    return my_circle(user=user, db=db)


@router.put("/circle/{link_id}/scopes/{scope}")
def change_scope(link_id: int, scope: str, body: ScopeBody, user=Depends(current_user),
                 db=Depends(get_db)):
    link = db.one("SELECT * FROM care_links WHERE id=?", (link_id,))
    if not link or user["id"] not in (link["individual_id"], link["caregiver_id"]):
        raise HTTPException(status_code=404, detail="Not found")
    if body.state not in ("requested", "granted", "revoked"):
        raise HTTPException(status_code=400, detail="Unknown state")
    result = consent.set_scope(db, user, link, scope, body.state)
    other_id = link["caregiver_id"] if user["id"] == link["individual_id"] else link["individual_id"]
    label = consent.SCOPES[scope]
    msg = {"requested": f"{user['display_name']} asked to see: {label}",
           "granted": f"{user['display_name']} shared: {label}",
           "revoked": f"Sharing stopped: {label}"}[result]
    notify(db, other_id, "circle", msg, None, "#/circle")
    return my_circle(user=user, db=db)


@router.get("/circle/{link_id}/history")
def consent_history(link_id: int, user=Depends(current_user), db=Depends(get_db)):
    link = db.one("SELECT * FROM care_links WHERE id=?", (link_id,))
    if not link or user["id"] not in (link["individual_id"], link["caregiver_id"]):
        raise HTTPException(status_code=404, detail="Not found")
    return {"records": db.all("SELECT r.*, u.display_name actor FROM consent_records r JOIN users u"
                              " ON u.id=r.actor_id WHERE link_id=? ORDER BY r.id DESC", (link_id,))}


# ----------------------------------------------------------------------------- shared view
@router.get("/shared/{individual_id}")
def shared_view(individual_id: int, user=Depends(require_role("caregiver")), db=Depends(get_db)):
    """What this caregiver may see about one person. Each section is checked separately."""
    link = consent.link_between(db, individual_id, user["id"])
    if not link:
        raise HTTPException(status_code=403, detail="You are not connected to this person.")
    scopes = consent.granted_scopes(db, link["id"])
    person = db.one("SELECT id, display_name FROM users WHERE id=?", (individual_id,))
    out = {"person": person, "scopes": sorted(scopes), "sections": {}}
    from nbapp.routes_personal import blueprint_for, routine_full
    if "blueprint" in scopes:
        out["sections"]["blueprint"] = blueprint_for(db, individual_id, shared_only=True)
    if "routines" in scopes:
        out["sections"]["routines"] = [routine_full(db, r) for r in db.all(
            "SELECT * FROM routines WHERE owner_id=? AND shared=1", (individual_id,))]
    if "goals" in scopes:
        out["sections"]["goals"] = db.all("SELECT id, title, why, next_step, status FROM goals "
                                          "WHERE owner_id=? AND shared=1", (individual_id,))
    if "tasks" in scopes:
        out["sections"]["tasks"] = db.all("SELECT id, title, status, due_date FROM tasks WHERE "
                                          "owner_id=? AND shared=1 AND status!='done'",
                                          (individual_id,))
    if "calendar" in scopes:
        out["sections"]["calendar"] = db.all("SELECT id, title, start_time, end_time, location "
                                             "FROM calendar_events WHERE owner_id=? AND shared=1 "
                                             "AND start_time>=? ORDER BY start_time",
                                             (individual_id, datetime.now().date().isoformat()))
    if "checkin_summary" in scopes:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
        rows = db.all("SELECT mood, energy, stress FROM checkins WHERE owner_id=? AND "
                      "created_at>=?", (individual_id, since))

        def avg(k):
            vals = [r[k] for r in rows if r[k]]
            return round(sum(vals) / len(vals), 1) if vals else None
        out["sections"]["checkin_summary"] = {"count_7d": len(rows), "mood_avg": avg("mood"),
                                              "energy_avg": avg("energy"),
                                              "stress_avg": avg("stress"),
                                              "notice": "Averages only; notes stay private."}
    if "coordination" in scopes:
        out["sections"]["coordination"] = True
    return out


# ----------------------------------------------------------------------------- support requests
class SupportBody(BaseModel):
    message: str = Field(min_length=1, max_length=300)
    to: List[int] = Field(default_factory=list)  # caregiver ids; empty = everyone active


class SupportUpdate(BaseModel):
    status: str
    reply: Optional[str] = Field(default=None, max_length=300)


@router.post("/support-requests")
def send_support(body: SupportBody, user=Depends(require_role("individual")), db=Depends(get_db)):
    active = [l for l in consent.circle_for_individual(db, user["id"]) if l["status"] == "active"]
    targets = [l["caregiver_id"] for l in active if not body.to or l["caregiver_id"] in body.to]
    if not targets:
        raise HTTPException(status_code=409, detail="You don't have anyone in your circle yet. "
                                                    "If you are in danger, call 112.")
    ids = []
    for cid in targets:
        ts = now()
        ids.append(db.insert("support_requests", from_id=user["id"], to_id=cid,
                             message=body.message, created_at=ts, updated_at=ts))
        notify(db, cid, "support_request", f"{user['display_name']}: {body.message}",
               "Open Support requests to reply.", "#/requests")
    db.audit(user["id"], "support_request_sent", detail=str(len(ids)))
    return {"sent_to": len(ids), "ids": ids}


@router.get("/support-requests")
def list_support(user=Depends(current_user), db=Depends(get_db)):
    col = "from_id" if user["role"] == "individual" else "to_id"
    other = "to_id" if col == "from_id" else "from_id"
    return {"requests": db.all(f"SELECT r.*, u.display_name other_name FROM support_requests r "
                               f"JOIN users u ON u.id=r.{other} WHERE r.{col}=? ORDER BY "
                               f"r.created_at DESC LIMIT 100", (user["id"],))}


@router.patch("/support-requests/{rid}")
def update_support(rid: int, body: SupportUpdate, user=Depends(current_user), db=Depends(get_db)):
    r = db.one("SELECT * FROM support_requests WHERE id=?", (rid,))
    if not r or user["id"] not in (r["to_id"], r["from_id"]):
        raise HTTPException(status_code=404, detail="Not found")
    if body.status not in ("seen", "on_my_way", "resolved"):
        raise HTTPException(status_code=400, detail="Unknown status")
    db.update("support_requests", "id=?", (rid,), status=body.status,
              reply=body.reply if body.reply is not None else r["reply"], updated_at=now())
    if user["id"] == r["to_id"]:
        words = {"seen": "has seen your message", "on_my_way": "is on the way",
                 "resolved": "marked your request as done"}[body.status]
        notify(db, r["from_id"], "support_request", f"{user['display_name']} {words}",
               body.reply, "#/home")
    return {"ok": True}


# ----------------------------------------------------------------------------- care journal
class CareJournalBody(BaseModel):
    individual_id: Optional[int] = None
    occurred_at: Optional[str] = None
    context: Optional[str] = Field(default=None, max_length=500)
    environment: Optional[str] = Field(default=None, max_length=500)
    what_happened: str = Field(min_length=1, max_length=5000)
    factors: Optional[str] = Field(default=None, max_length=2000)
    support_offered: Optional[str] = Field(default=None, max_length=2000)
    what_helped: Optional[str] = Field(default=None, max_length=2000)
    followup: Optional[str] = Field(default=None, max_length=2000)
    tags: List[str] = Field(default_factory=list)
    visible_to_individual: bool = False


def _check_person(db, user, individual_id):
    if individual_id and not consent.link_between(db, individual_id, user["id"]):
        raise HTTPException(status_code=403, detail="You are not connected to this person.")


@router.get("/care/journal")
def list_care_journal(individual_id: Optional[int] = None, user=Depends(current_user),
                      db=Depends(get_db)):
    if user["role"] == "individual":
        rows = db.all("SELECT j.*, u.display_name author FROM care_journal j JOIN users u ON "
                      "u.id=j.author_id WHERE j.individual_id=? AND j.visible_to_individual=1 "
                      "ORDER BY occurred_at DESC", (user["id"],))
    else:
        sql, params = "SELECT * FROM care_journal WHERE author_id=?", [user["id"]]
        if individual_id:
            sql += " AND individual_id=?"
            params.append(individual_id)
        rows = db.all(sql + " ORDER BY occurred_at DESC", params)
    for r in rows:
        r["tags"] = json.loads(r["tags"] or "[]")
    return {"entries": rows}


@router.post("/care/journal")
def add_care_journal(body: CareJournalBody, user=Depends(require_role("caregiver")),
                     db=Depends(get_db)):
    _check_person(db, user, body.individual_id)
    d = body.model_dump()
    d["occurred_at"] = d["occurred_at"] or now()
    d["tags"] = json.dumps([t.strip()[:30] for t in d["tags"][:10] if t.strip()])
    d["visible_to_individual"] = int(d["visible_to_individual"])
    jid = db.insert("care_journal", author_id=user["id"], created_at=now(), **d)
    return db.one("SELECT * FROM care_journal WHERE id=?", (jid,))


@router.delete("/care/journal/{jid}")
def delete_care_journal(jid: int, user=Depends(require_role("caregiver")), db=Depends(get_db)):
    r = db.one("SELECT * FROM care_journal WHERE id=?", (jid,))
    if not r or r["author_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Not found")
    db.run("DELETE FROM care_journal WHERE id=?", (jid,))
    return {"deleted": True}


def observation_patterns(entries):
    """Count what appears together. Deliberately no causal language."""
    if not entries:
        return {"observations": 0, "items": [], "notice": "No observations yet."}
    tags = Counter(t for e in entries for t in e["tags"])
    contexts = Counter((e.get("context") or "").strip().lower() for e in entries
                       if (e.get("context") or "").strip())
    helped = Counter((e.get("what_helped") or "").strip().lower() for e in entries
                     if (e.get("what_helped") or "").strip())
    hours = Counter()
    for e in entries:
        try:
            h = int(e["occurred_at"][11:13])
            hours["morning" if h < 12 else "afternoon" if h < 17 else "evening"] += 1
        except (ValueError, TypeError):
            pass
    items = []
    for t, n in tags.most_common(5):
        if n > 1:
            items.append(f"'{t}' was noted in {n} of {len(entries)} observations.")
    for c, n in contexts.most_common(3):
        if n > 1:
            items.append(f"The context '{c}' came up {n} times.")
    for h, n in helped.most_common(3):
        if n > 1:
            items.append(f"'{h}' was recorded as helpful {n} times.")
    if hours:
        part, n = hours.most_common(1)[0]
        if n > 1:
            items.append(f"{n} observations were in the {part}.")
    return {"observations": len(entries), "items": items,
            "notice": "These are counts from your own notes. They can show what appeared "
                      "together, not what caused what. With few notes, patterns are unreliable. "
                      "Ask the person what they think — they know their experience best."}


@router.get("/care/journal/patterns")
def care_patterns(individual_id: Optional[int] = None, user=Depends(require_role("caregiver")),
                  db=Depends(get_db)):
    entries = list_care_journal(individual_id=individual_id, user=user, db=db)["entries"]
    return observation_patterns(entries)


# ----------------------------------------------------------------------------- coordination
class CareTaskBody(BaseModel):
    individual_id: int
    title: str = Field(min_length=1, max_length=200)
    assignee_id: Optional[int] = None
    due_date: Optional[str] = None


class NoteBody(BaseModel):
    individual_id: int
    body: str = Field(min_length=1, max_length=4000)
    kind: str = "note"


def _coordination_access(db, user, individual_id):
    """Coordination data is about the individual: they always see it; caregivers need an
    active link with the 'coordination' scope."""
    if user["id"] == individual_id:
        return
    consent.require_view(db, user, individual_id, "coordination")


def _team(db, individual_id):
    ids = [individual_id] + [l["caregiver_id"] for l in consent.circle_for_individual(db, individual_id)
                             if l["status"] == "active" and "coordination" in
                             consent.granted_scopes(db, l["id"])]
    return ids


@router.get("/care/coordination/{individual_id}")
def coordination(individual_id: int, user=Depends(current_user), db=Depends(get_db)):
    _coordination_access(db, user, individual_id)
    team_ids = _team(db, individual_id)
    marks = ",".join("?" * len(team_ids))
    team = db.all(f"SELECT id, display_name, role FROM users WHERE id IN ({marks})", team_ids)
    tasks = db.all("SELECT t.*, u.display_name assignee FROM care_tasks t LEFT JOIN users u ON "
                   "u.id=t.assignee_id WHERE individual_id=? ORDER BY status, due_date",
                   (individual_id,))
    notes = db.all("SELECT n.*, u.display_name author FROM support_notes n JOIN users u ON "
                   "u.id=n.author_id WHERE individual_id=? ORDER BY n.created_at DESC LIMIT 50",
                   (individual_id,))
    load = Counter(t["assignee"] or "Unassigned" for t in tasks if t["status"] == "open")
    return {"team": team, "tasks": tasks, "notes": notes, "open_task_load": dict(load)}


@router.post("/care/tasks")
def add_care_task(body: CareTaskBody, user=Depends(current_user), db=Depends(get_db)):
    _coordination_access(db, user, body.individual_id)
    if body.assignee_id and body.assignee_id not in _team(db, body.individual_id):
        raise HTTPException(status_code=400, detail="That person is not in this support team.")
    tid = db.insert("care_tasks", individual_id=body.individual_id, created_by=user["id"],
                    assignee_id=body.assignee_id, title=body.title, due_date=body.due_date,
                    created_at=now())
    if body.assignee_id and body.assignee_id != user["id"]:
        notify(db, body.assignee_id, "caregiver", f"New care task: {body.title}", None,
               "#/coordination")
    return db.one("SELECT * FROM care_tasks WHERE id=?", (tid,))


@router.patch("/care/tasks/{tid}")
def update_care_task(tid: int, status: str, user=Depends(current_user), db=Depends(get_db)):
    t = db.one("SELECT * FROM care_tasks WHERE id=?", (tid,))
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    _coordination_access(db, user, t["individual_id"])
    if status not in ("open", "done"):
        raise HTTPException(status_code=400, detail="Unknown status")
    db.update("care_tasks", "id=?", (tid,), status=status)
    return {"ok": True}


@router.post("/care/notes")
def add_note(body: NoteBody, user=Depends(current_user), db=Depends(get_db)):
    _coordination_access(db, user, body.individual_id)
    if body.kind not in ("note", "handover"):
        raise HTTPException(status_code=400, detail="Unknown note type")
    nid = db.insert("support_notes", individual_id=body.individual_id, author_id=user["id"],
                    kind=body.kind, body=body.body, created_at=now())
    return db.one("SELECT * FROM support_notes WHERE id=?", (nid,))


# ----------------------------------------------------------------------------- contacts
class ContactBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=1000)


@router.get("/care/contacts")
def contacts(user=Depends(current_user), db=Depends(get_db)):
    return {"contacts": db.all("SELECT * FROM care_contacts WHERE owner_id=? ORDER BY name",
                               (user["id"],))}


@router.post("/care/contacts")
def add_contact(body: ContactBody, user=Depends(current_user), db=Depends(get_db)):
    db.insert("care_contacts", owner_id=user["id"], **body.model_dump())
    return contacts(user=user, db=db)


@router.delete("/care/contacts/{cid}")
def delete_contact(cid: int, user=Depends(current_user), db=Depends(get_db)):
    db.run("DELETE FROM care_contacts WHERE id=? AND owner_id=?", (cid, user["id"]))
    return contacts(user=user, db=db)


# ----------------------------------------------------------------------------- wellbeing
class WellbeingBody(BaseModel):
    stress: Optional[int] = Field(default=None, ge=1, le=5)
    rest: Optional[int] = Field(default=None, ge=1, le=5)
    supported: Optional[int] = Field(default=None, ge=1, le=5)
    note: Optional[str] = Field(default=None, max_length=2000)


def wellbeing_message(stress, rest, supported):
    if stress and stress >= 4 and (rest or 3) <= 2:
        return ("That sounds like a lot to carry. You don't have to fix it with self-care alone — "
                "could one task go to someone else this week? If you feel unable to cope, "
                "Tele-MANAS (14416) is free and confidential.")
    if supported and supported <= 2:
        return ("Feeling unsupported is hard. The Coordination page lets you share tasks with "
                "others in the circle.")
    return "Thanks for checking in with yourself."


@router.post("/care/wellbeing")
def add_wellbeing(body: WellbeingBody, user=Depends(current_user), db=Depends(get_db)):
    db.insert("wellbeing_checkins", owner_id=user["id"], created_at=now(), **body.model_dump())
    return {"message": wellbeing_message(body.stress, body.rest, body.supported),
            **list_wellbeing(user=user, db=db)}


@router.get("/care/wellbeing")
def list_wellbeing(user=Depends(current_user), db=Depends(get_db)):
    return {"checkins": db.all("SELECT * FROM wellbeing_checkins WHERE owner_id=? ORDER BY "
                               "created_at DESC LIMIT 60", (user["id"],))}


# ----------------------------------------------------------------------------- dashboard
@router.get("/care/dashboard")
def caregiver_dashboard(user=Depends(require_role("caregiver")), db=Depends(get_db)):
    people = [p for p in consent.people_for_caregiver(db, user["id"])]
    pending_requests = db.all("SELECT r.*, u.display_name other_name FROM support_requests r JOIN "
                              "users u ON u.id=r.from_id WHERE r.to_id=? AND r.status IN "
                              "('sent','seen','on_my_way') ORDER BY r.created_at DESC",
                              (user["id"],))
    my_tasks = db.all("SELECT t.*, u.display_name person FROM care_tasks t JOIN users u ON "
                      "u.id=t.individual_id WHERE t.assignee_id=? AND t.status='open' ORDER BY "
                      "due_date", (user["id"],))
    upcoming = db.all("SELECT * FROM calendar_events WHERE owner_id=? AND start_time>=? ORDER BY "
                      "start_time LIMIT 5", (user["id"], datetime.now().date().isoformat()))
    last_wb = db.one("SELECT * FROM wellbeing_checkins WHERE owner_id=? ORDER BY created_at DESC "
                     "LIMIT 1", (user["id"],))
    return {"people": people, "support_requests": pending_requests, "my_care_tasks": my_tasks,
            "upcoming": upcoming, "last_wellbeing": last_wb}
