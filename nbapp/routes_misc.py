"""Notifications, events & groups (in-site bookings), provider directory & appointments,
learning hub, life skills, system status, and admin tools — all bound to the signed-in user.
Bookings reuse the agent's stores, so the AI agent and the pages show the same data."""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nbapp import content
from nbapp.db import now
from nbapp.notify import CATEGORIES, notify, prefs_for
from nbapp.routes_auth import memory_key
from nbapp.security import current_user, get_db, require_role

router = APIRouter(prefix="/api", tags=["misc"])


def _core():
    import agent.api.app as core
    return core


# ----------------------------------------------------------------------------- notifications
@router.get("/notifications")
def notifications(user=Depends(current_user), db=Depends(get_db)):
    return {"notifications": db.all("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC "
                                    "LIMIT 100", (user["id"],)),
            "categories": CATEGORIES, "prefs": prefs_for(db, user["id"])}


@router.post("/notifications/read")
def mark_read(ids: Optional[List[int]] = None, user=Depends(current_user), db=Depends(get_db)):
    if ids:
        marks = ",".join("?" * len(ids))
        db.run(f"UPDATE notifications SET read_at=? WHERE user_id=? AND id IN ({marks})",
               (now(), user["id"], *ids))
    else:
        db.run("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL",
               (now(), user["id"]))
    return {"ok": True}


@router.get("/reminders/due")
def due_reminders(hhmm: Optional[str] = None, user=Depends(current_user), db=Depends(get_db)):
    """Called by the open app about once a minute. Creates gentle routine reminders whose time
    has come (once per routine per day), respecting notification settings."""
    from datetime import datetime
    hhmm = hhmm or datetime.now().strftime("%H:%M")
    today = datetime.now().date().isoformat()
    created = []
    for r in db.all("SELECT * FROM routines WHERE owner_id=? AND reminder_time IS NOT NULL AND "
                    "reminder_time<=?", (user["id"], hhmm)):
        link = f"#/routines/{r['id']}"
        if db.one("SELECT 1 FROM notifications WHERE user_id=? AND link=? AND substr(created_at,1,10)"
                  "=?", (user["id"], link, today)):
            continue
        nid = notify(db, user["id"], "routine", f"{r['name']} is ready when you are",
                     "No pressure — start, skip, or change it.", link)
        if nid:
            created.append(nid)
    return {"created": created}


# ----------------------------------------------------------------------------- events
class EventRegister(BaseModel):
    attendees: int = Field(default=1, ge=1, le=6)
    needs: Optional[str] = Field(default=None, max_length=500)
    approved_details_hash: str
    explicit_approval: bool = False


class EventProposal(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    event_type: str
    description: Optional[str] = Field(default=None, max_length=2000)
    start_time: str
    end_time: str
    capacity: int = Field(ge=1, le=500)
    location: Optional[str] = Field(default=None, max_length=200)
    is_online: bool = False
    fee_amount: float = Field(default=0, ge=0, le=100000)
    accessibility: List[str] = Field(default_factory=list)
    audience: List[str] = Field(default_factory=list)


def _events():
    core = _core()
    if core.event_store is None:
        raise HTTPException(status_code=503, detail="Events are not available right now.")
    return core.event_store


@router.get("/events")
def events(event_type: Optional[str] = None, q: Optional[str] = None, online: Optional[bool] = None,
           accessibility: Optional[str] = None, user=Depends(current_user)):
    r = _events().search_events(event_type=event_type, text=q, online=online,
                                accessibility=accessibility, limit=60)
    if user["is_minor"]:
        r["events"] = [e for e in r["events"] if not any("adult" in a.lower()
                                                          for a in e["audience"])]
    return r


@router.get("/events/{event_id}/prepare")
def prepare(event_id: int, attendees: int = 1, user=Depends(current_user)):
    r = _events().prepare_registration(event_id, attendees)
    if not r.get("success"):
        raise HTTPException(status_code=404, detail=r.get("message"))
    return r


@router.post("/events/{event_id}/register")
def register(event_id: int, body: EventRegister, user=Depends(current_user), db=Depends(get_db)):
    if not body.explicit_approval:
        raise HTTPException(status_code=403, detail="Please confirm the exact details first.")
    r = _events().register(event_id, memory_key(user), body.attendees, body.needs,
                           body.approved_details_hash, explicit_approval=True)
    if not r.get("success"):
        raise HTTPException(status_code=409, detail=r)
    db.audit(user["id"], "event_register", f"event:{event_id}", r.get("status"))
    notify(db, user["id"], "appointment", f"{r['event']}: {r['status']}",
           r.get("confirmation_code"), "#/events")
    return r


@router.get("/events-mine")
def my_events(user=Depends(current_user)):
    return _events().my_registrations(memory_key(user))


@router.post("/events/registrations/{rid}/cancel")
def cancel_event(rid: int, user=Depends(current_user), db=Depends(get_db)):
    r = _events().cancel_registration(rid, memory_key(user))
    if not r.get("success"):
        raise HTTPException(status_code=404, detail=r.get("message"))
    db.audit(user["id"], "event_cancel", f"registration:{rid}")
    return r


@router.post("/events/propose")
def propose_event(body: EventProposal, user=Depends(current_user), db=Depends(get_db)):
    """Adults can propose a gathering, club or meetup. It is only listed after an admin
    reviews it (status pending_review)."""
    if user["is_minor"]:
        raise HTTPException(status_code=403, detail="Event proposals are for adult accounts.")
    from nbapp.moderation import check
    status, _, msg = check(body.title + " " + (body.description or ""))
    if status != "visible":
        raise HTTPException(status_code=400, detail=msg)
    prof = db.one("SELECT handle FROM community_profiles WHERE user_id=?", (user["id"],))
    r = _events().create_event(body.title, body.event_type, body.start_time, body.end_time,
                               body.capacity, description=body.description,
                               organizer=f"@{prof['handle']}" if prof else user["display_name"],
                               location=body.location, is_online=body.is_online,
                               fee_amount=body.fee_amount, accessibility=body.accessibility,
                               audience=body.audience, status="pending_review")
    if not r.get("success"):
        raise HTTPException(status_code=400, detail=r.get("message"))
    db.audit(user["id"], "event_proposed", f"event:{r['event_id']}")
    return {"event_id": r["event_id"], "status": "pending_review",
            "message": "Thanks! An admin will review it before it is listed."}


@router.get("/admin/events/pending")
def pending_events(user=Depends(require_role("admin"))):
    store = _events()
    with store._connect() as c:
        ids = [r[0] for r in c.execute("SELECT event_id FROM events WHERE status='pending_review'")]
        return {"events": [store._row(c, i) for i in ids]}


@router.post("/admin/events/{event_id}/review")
def review_event(event_id: int, approve: bool, user=Depends(require_role("admin")),
                 db=Depends(get_db)):
    _events().update_event(event_id, status="published" if approve else "rejected")
    db.audit(user["id"], "event_review", f"event:{event_id}", str(approve))
    return {"ok": True}


# ----------------------------------------------------------------------------- providers
class ApptRequest(BaseModel):
    slot_id: int
    appointment_type: str = Field(default="consultation", max_length=60)
    notes: Optional[str] = Field(default=None, max_length=1000)
    child_age: Optional[int] = Field(default=None, ge=0, le=120)
    share_contact: bool = False          # let the clinic see the name/phone below
    contact_name: Optional[str] = Field(default=None, max_length=120)
    contact_phone: Optional[str] = Field(default=None, max_length=40)


class ProviderBody(BaseModel):
    provider_name: str = Field(min_length=2, max_length=160)
    profession: str = Field(min_length=2, max_length=80)
    organization: Optional[str] = Field(default=None, max_length=160)
    credentials: Optional[str] = Field(default=None, max_length=200)
    specialties: List[str] = Field(default_factory=list, max_length=20)
    languages: List[str] = Field(default_factory=list, max_length=20)
    age_groups: List[str] = Field(default_factory=list, max_length=10)
    location: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=300)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=160)
    website: Optional[str] = Field(default=None, max_length=300)
    source_url: Optional[str] = Field(default=None, max_length=300)
    about: Optional[str] = Field(default=None, max_length=1000)
    online_consultation: bool = False
    fee_amount: Optional[float] = Field(default=None, ge=0, le=1_000_000)


class VerifyBody(BaseModel):
    verified: bool = True
    note: str = Field(min_length=5, max_length=500)   # what was checked, and how


class SlotBody(BaseModel):
    start_time: str
    end_time: str
    fee_amount: Optional[float] = Field(default=None, ge=0, le=1_000_000)


class ClinicStatusBody(BaseModel):
    status: str
    note: Optional[str] = Field(default=None, max_length=500)


class OutsideBody(BaseModel):
    clinic_name: str = Field(min_length=2, max_length=200)
    profession: Optional[str] = Field(default=None, max_length=80)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=160)
    website: Optional[str] = Field(default=None, max_length=300)
    source_url: Optional[str] = Field(default=None, max_length=300)
    preferred_times: Optional[str] = Field(default=None, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=500)


class OutsideUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


def _booking():
    core = _core()
    if core.booking_store is None:
        raise HTTPException(status_code=503, detail="Provider directory unavailable")
    return core.booking_store


@router.get("/providers")
def providers(profession: Optional[str] = None, specialty: Optional[str] = None,
              language: Optional[str] = None, location: Optional[str] = None,
              user=Depends(current_user)):
    r = _booking().search_providers(profession=profession, specialty=specialty, language=language,
                                    location=location)
    r["notice"] = ("Only providers whose details were checked by a NeuroBridge admin are listed. "
                   "'Verified' means an admin checked the listing, not a clinical endorsement.")
    return r


@router.get("/providers/slots")
def slots(provider_id: Optional[int] = None, user=Depends(current_user)):
    return _booking().find_available_slots(provider_id=provider_id)


@router.post("/appointments")
def request_appt(body: ApptRequest, user=Depends(current_user), db=Depends(get_db)):
    if user["is_minor"]:
        raise HTTPException(status_code=403, detail="Appointments are booked by a guardian.")
    r = _booking().request_appointment(body.slot_id, memory_key(user), child_age=body.child_age,
                                       appointment_type=body.appointment_type,
                                       caregiver_notes=body.notes,
                                       requester_name=body.contact_name or user["display_name"],
                                       requester_phone=body.contact_phone,
                                       share_contact=body.share_contact)
    if not r.get("success"):
        raise HTTPException(status_code=409, detail=r.get("message"))
    db.audit(user["id"], "appointment_request", f"appointment:{r['appointment_id']}")
    return r


@router.post("/appointments/{aid}/approve")
def approve_appt(aid: int, explicit_approval: bool = False, user=Depends(current_user),
                 db=Depends(get_db)):
    r = _booking().approve_appointment(aid, memory_key(user), explicit_approval=explicit_approval)
    if not r.get("success"):
        raise HTTPException(status_code=409, detail=r.get("message"))
    db.audit(user["id"], "appointment_confirm", f"appointment:{aid}")
    notify(db, user["id"], "appointment", "Appointment reserved", r.get("confirmation_code"),
           "#/appointments")
    return r


@router.post("/appointments/{aid}/cancel")
def cancel_appt(aid: int, user=Depends(current_user), db=Depends(get_db)):
    r = _booking().cancel_appointment(aid, memory_key(user))
    if not r.get("success"):
        raise HTTPException(status_code=409, detail=r.get("message"))
    db.audit(user["id"], "appointment_cancel", f"appointment:{aid}")
    return r


@router.get("/appointments")
def my_appts(user=Depends(current_user)):
    r = _booking().get_appointments(memory_key(user))
    r["outside_requests"] = _booking().list_outside_requests(memory_key(user))["requests"]
    return r


# ---- clinics outside the NeuroBridge directory: a tracker, not a booking ----
@router.post("/outside-requests")
def add_outside(body: OutsideBody, user=Depends(current_user), db=Depends(get_db)):
    r = _booking().create_outside_request(memory_key(user), **body.model_dump())
    if not r.get("success"):
        raise HTTPException(status_code=400, detail=r.get("message"))
    db.audit(user["id"], "outside_request_saved", f"outside:{r['request_id']}")
    return r


@router.patch("/outside-requests/{rid}")
def edit_outside(rid: int, body: OutsideUpdate, user=Depends(current_user)):
    r = _booking().update_outside_request(rid, memory_key(user), status=body.status,
                                          notes=body.notes)
    if not r.get("success"):
        raise HTTPException(status_code=404 if "found" in r.get("message", "") else 400,
                            detail=r.get("message"))
    return r


@router.delete("/outside-requests/{rid}")
def del_outside(rid: int, user=Depends(current_user)):
    if not _booking().delete_outside_request(rid, memory_key(user))["success"]:
        raise HTTPException(status_code=404, detail="Request not found.")
    return {"deleted": True}


# ---- admin: the verified provider directory ----
@router.get("/admin/providers")
def admin_providers(user=Depends(require_role("admin"))):
    return _booking().list_providers_admin()


@router.post("/admin/providers")
def admin_add_provider(body: ProviderBody, user=Depends(require_role("admin")),
                       db=Depends(get_db)):
    r = _booking().register_provider(**body.model_dump())
    db.audit(user["id"], "provider_added", f"provider:{r.get('provider_id')}")
    return r


@router.patch("/admin/providers/{pid}")
def admin_edit_provider(pid: int, body: ProviderBody, user=Depends(require_role("admin")),
                        db=Depends(get_db)):
    r = _booking().update_provider(pid, **body.model_dump())
    if not r.get("success"):
        raise HTTPException(status_code=404, detail=r.get("message"))
    db.audit(user["id"], "provider_edited", f"provider:{pid}")
    return r


@router.post("/admin/providers/{pid}/verify")
def admin_verify_provider(pid: int, body: VerifyBody, user=Depends(require_role("admin")),
                          db=Depends(get_db)):
    r = _booking().verify_provider(pid, verified=body.verified, note=body.note,
                                   verified_by=user["email"])
    if not r.get("success"):
        raise HTTPException(status_code=404, detail=r.get("message"))
    db.audit(user["id"], "provider_verified" if body.verified else "provider_rejected",
             f"provider:{pid}")
    return r


@router.get("/admin/providers/{pid}/slots")
def admin_slots(pid: int, user=Depends(require_role("admin"))):
    return _booking().list_slots_admin(pid)


@router.post("/admin/providers/{pid}/slots")
def admin_add_slot(pid: int, body: SlotBody, user=Depends(require_role("admin"))):
    r = _booking().add_availability(pid, body.start_time, body.end_time,
                                    fee_amount=body.fee_amount)
    if not r.get("success"):
        raise HTTPException(status_code=409, detail=r.get("message"))
    return r


@router.delete("/admin/slots/{sid}")
def admin_remove_slot(sid: int, user=Depends(require_role("admin"))):
    r = _booking().remove_slot(sid)
    if not r.get("success"):
        raise HTTPException(status_code=409, detail=r.get("message"))
    return r


@router.get("/admin/appointments")
def admin_appts(user=Depends(require_role("admin"))):
    return _booking().admin_appointments()


@router.post("/admin/appointments/{aid}/clinic-status")
def admin_clinic_status(aid: int, body: ClinicStatusBody, user=Depends(require_role("admin")),
                        db=Depends(get_db)):
    r = _booking().set_clinic_status(aid, body.status, body.note)
    if not r.get("success"):
        raise HTTPException(status_code=409, detail=r.get("message"))
    db.audit(user["id"], "clinic_status", f"appointment:{aid}:{body.status}")
    key = r.get("caregiver_user_id") or ""
    if key.startswith("u") and key[1:].isdigit():
        msg = {"clinic_confirmed": "The clinic confirmed your appointment.",
               "clinic_declined": "The clinic could not take this appointment. The slot was "
                                  "released; you can pick another time.",
               "awaiting_clinic": "Waiting for the clinic to confirm."}[body.status]
        notify(db, int(key[1:]), "appointment", "Appointment update", msg, "#/appointments")
    return r


# ----------------------------------------------------------------------------- content
@router.get("/learn")
def learn(q: Optional[str] = None):
    topics = content.LEARNING_TOPICS
    if q:
        ql = q.lower()
        topics = [t for t in topics if ql in (t["title"] + " " + t["summary"]).lower()]
    return {"topics": topics,
            "notice": "Short general guidance written by NeuroBridge (not research evidence). "
                      "Use 'Research this' for a sourced answer with citations."}


@router.get("/life-skills")
def life_skills():
    return {"skills": [{"title": t, "prompt": p} for t, p in content.LIFE_SKILLS]}


@router.get("/status")
def status():
    core = _core()
    gw = core.gateway
    return {"ai_connected": gw is not None,
            "models": [{"provider": n, "label": core.provider_label(n)} for n in
                       (gw.list_providers() if gw else [])],
            "default_model": gw.default_provider if gw else None,
            "search_providers": core.init_status.get("search_providers", []),
            "agent": core.agent is not None}
