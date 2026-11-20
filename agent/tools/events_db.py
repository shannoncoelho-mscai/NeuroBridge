"""In-site events: support groups, workshops, social gatherings, clubs, community meetings,
activities. Registration with explicit, detail-bound approval.

Approval binding (project brief §7): a registration is approved against a fingerprint of the
exact event title, time, place, fee and number of attendees. If any of these change before
the booking executes, it is refused and must be approved again.

Events are NeuroBridge platform listings created by organisers/admins. Demo listings
(is_demo=1) are clearly marked everywhere they appear.
"""
import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agent.tools.booking_db import DEFAULT_DB

EVENT_TYPES = {"support_group", "workshop", "social_gathering", "club", "community_meeting",
               "activity", "clinic_session"}
ACCESSIBILITY = {"sensory_friendly", "quiet_room", "wheelchair_access", "captioning",
                 "sign_language", "low_lighting", "online"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT,
    organizer TEXT,
    location TEXT,
    is_online INTEGER DEFAULT 0,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    capacity INTEGER NOT NULL,
    fee_amount REAL DEFAULT 0,
    fee_currency TEXT DEFAULT 'INR',
    accessibility TEXT DEFAULT '[]',
    audience TEXT DEFAULT '[]',
    languages TEXT DEFAULT '[]',
    recurrence TEXT,
    status TEXT DEFAULT 'published',
    is_demo INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS event_registrations (
    registration_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    attendees INTEGER DEFAULT 1,
    needs TEXT,
    status TEXT NOT NULL,
    details_hash TEXT NOT NULL,
    confirmation_code TEXT UNIQUE,
    created_at TEXT,
    decided_at TEXT,
    FOREIGN KEY (event_id) REFERENCES events(event_id)
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(status, start_time);
CREATE INDEX IF NOT EXISTS idx_reg_event ON event_registrations(event_id, status);
"""
SCOPE = "Registered in the NeuroBridge events system. The organiser sees your registration; " \
        "please contact them for changes."


def _now():
    return datetime.now(timezone.utc).isoformat()


def _loads(v):
    try:
        return json.loads(v or "[]")
    except Exception:
        return []


def details_fingerprint(event, attendees):
    """Hash of everything the person is agreeing to."""
    payload = json.dumps([event["event_id"], event["title"], event["start_time"], event["end_time"],
                          event["location"], bool(event["is_online"]), float(event["fee_amount"] or 0),
                          event["fee_currency"], int(attendees)], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class EventStore:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path or DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as c:
            c.executescript(SCHEMA)

    def _connect(self):
        c = sqlite3.connect(str(self.db_path), timeout=30)
        c.row_factory = sqlite3.Row
        return c

    # ------------------------------------------------------------- organisers / admin
    def create_event(self, title, event_type, start_time, end_time, capacity, description=None,
                     organizer=None, location=None, is_online=False, fee_amount=0.0,
                     accessibility=None, audience=None, languages=None, recurrence=None,
                     is_demo=False, status="published"):
        if event_type not in EVENT_TYPES:
            return {"success": False, "message": f"event_type must be one of {sorted(EVENT_TYPES)}"}
        bad = set(accessibility or []) - ACCESSIBILITY
        if bad:
            return {"success": False, "message": f"Unknown accessibility options: {sorted(bad)}"}
        try:
            s, e = datetime.fromisoformat(start_time), datetime.fromisoformat(end_time)
        except ValueError:
            return {"success": False, "message": "Times must be ISO-8601."}
        if e <= s or int(capacity) < 1:
            return {"success": False, "message": "End must be after start and capacity >= 1."}
        with self._connect() as c:
            cur = c.execute(
                "INSERT INTO events (title,event_type,description,organizer,location,is_online,start_time,"
                "end_time,capacity,fee_amount,accessibility,audience,languages,recurrence,status,is_demo,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (title, event_type, description, organizer, location, int(bool(is_online)), s.isoformat(),
                 e.isoformat(), int(capacity), float(fee_amount or 0), json.dumps(sorted(accessibility or [])),
                 json.dumps(audience or []), json.dumps(languages or []), recurrence, status,
                 int(bool(is_demo)), _now()))
        return {"success": True, "event_id": cur.lastrowid}

    def update_event(self, event_id, **changes):
        allowed = {"title", "start_time", "end_time", "location", "fee_amount", "capacity", "status",
                   "description", "is_online"}
        sets = {k: v for k, v in changes.items() if k in allowed}
        if not sets:
            return {"success": False, "message": "Nothing to update."}
        with self._connect() as c:
            cur = c.execute(f"UPDATE events SET {', '.join(f'{k}=?' for k in sets)} WHERE event_id=?",
                            (*sets.values(), event_id))
        return {"success": cur.rowcount == 1}

    # ------------------------------------------------------------- reading
    def _row(self, c, event_id):
        row = c.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        if not row:
            return None
        ev = dict(row)
        for f in ("accessibility", "audience", "languages"):
            ev[f] = _loads(ev[f])
        taken = c.execute("SELECT COALESCE(SUM(attendees),0) FROM event_registrations WHERE event_id=? "
                          "AND status='confirmed'", (event_id,)).fetchone()[0]
        ev["seats_left"] = max(0, ev["capacity"] - taken)
        ev["is_demo"] = bool(ev["is_demo"])
        ev["is_online"] = bool(ev["is_online"])
        return ev

    def get_event(self, event_id):
        with self._connect() as c:
            ev = self._row(c, event_id)
        return {"success": bool(ev), "event": ev} if ev else {"success": False, "message": "Event not found."}

    def search_events(self, event_type=None, audience=None, location=None, text=None, online=None,
                      accessibility=None, date_from=None, date_to=None, include_full=True, limit=20):
        q = "SELECT event_id FROM events WHERE status='published' AND start_time >= ?"
        params = [date_from or _now()[:19]]
        if date_to:
            q += " AND start_time <= ?"
            params.append(date_to)
        if event_type:
            q += " AND event_type = ?"
            params.append(event_type)
        if online is not None:
            q += " AND is_online = ?"
            params.append(int(bool(online)))
        if location:
            q += " AND LOWER(location) LIKE ?"
            params.append(f"%{location.lower()}%")
        if text:
            q += " AND (LOWER(title) LIKE ? OR LOWER(description) LIKE ?)"
            params += [f"%{text.lower()}%"] * 2
        q += " ORDER BY start_time ASC"
        with self._connect() as c:
            ids = [r[0] for r in c.execute(q, params).fetchall()]
            events = [self._row(c, i) for i in ids]
        if audience:
            events = [e for e in events if any(audience.lower() in a.lower() for a in e["audience"])]
        if accessibility:
            need = set(accessibility if isinstance(accessibility, list) else [accessibility])
            events = [e for e in events if need <= set(e["accessibility"])]
        if not include_full:
            events = [e for e in events if e["seats_left"] > 0]
        return {"success": True, "count": len(events[:limit]), "events": events[:limit],
                "note": "Listings marked is_demo are sample data, not real events." if any(
                    e["is_demo"] for e in events) else None}

    # ------------------------------------------------------------- registration
    def prepare_registration(self, event_id, attendees=1):
        """Return the exact details the person must approve, plus their fingerprint."""
        with self._connect() as c:
            ev = self._row(c, event_id)
        if not ev or ev["status"] != "published":
            return {"success": False, "message": "Event not found or not open for registration."}
        attendees = int(attendees)
        if attendees < 1 or attendees > 6:
            return {"success": False, "message": "attendees must be between 1 and 6."}
        return {"success": True, "event_id": event_id, "details_hash": details_fingerprint(ev, attendees),
                "summary": {"title": ev["title"], "type": ev["event_type"], "start": ev["start_time"],
                            "end": ev["end_time"], "where": "Online" if ev["is_online"] else ev["location"],
                            "fee": f"{ev['fee_amount']:.0f} {ev['fee_currency']}" if ev["fee_amount"] else "Free",
                            "attendees": attendees, "seats_left": ev["seats_left"],
                            "organizer": ev["organizer"], "demo_listing": ev["is_demo"]}}

    def register(self, event_id, user_id, attendees=1, needs=None, approved_details_hash=None,
                 explicit_approval=False):
        """Execute an approved registration. Confirms if seats remain, else waitlists."""
        if not user_id:
            return {"success": False, "message": "A user account is required."}
        if explicit_approval is not True or not approved_details_hash:
            return {"success": False, "message": "Explicit approval of the exact event details is required."}
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            ev = self._row(conn, event_id)
            if not ev or ev["status"] != "published":
                conn.rollback()
                return {"success": False, "message": "Event not found or not open for registration."}
            current = details_fingerprint(ev, attendees)
            if current != approved_details_hash:
                conn.rollback()
                return {"success": False, "approval_stale": True,
                        "message": "The event details changed after you approved (time, place, fee or "
                                   "attendees). Please review and approve again.",
                        "current_details_hash": current}
            dup = conn.execute("SELECT registration_id FROM event_registrations WHERE event_id=? AND user_id=? "
                               "AND status IN ('confirmed','waitlisted')", (event_id, user_id)).fetchone()
            if dup:
                conn.rollback()
                return {"success": False, "message": "You are already registered for this event.",
                        "registration_id": dup[0]}
            status = "confirmed" if ev["seats_left"] >= int(attendees) else "waitlisted"
            code = "NBE-" + secrets.token_hex(4).upper() if status == "confirmed" else None
            cur = conn.execute(
                "INSERT INTO event_registrations (event_id,user_id,attendees,needs,status,details_hash,"
                "confirmation_code,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (event_id, user_id, int(attendees), needs, status, current, code, _now(), _now()))
            conn.commit()
            return {"success": True, "registration_id": cur.lastrowid, "status": status,
                    "confirmation_code": code, "event": ev["title"], "start": ev["start_time"],
                    "demo_listing": ev["is_demo"], "scope": SCOPE,
                    "message": "You're registered." if status == "confirmed"
                    else "The event is full; you're on the waitlist and will be confirmed if a seat frees up."}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": "Registration failed.", "error": str(exc)}
        finally:
            conn.close()

    def cancel_registration(self, registration_id, user_id):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            reg = conn.execute("SELECT * FROM event_registrations WHERE registration_id=? AND user_id=?",
                               (registration_id, user_id)).fetchone()
            if not reg or reg["status"] not in ("confirmed", "waitlisted"):
                conn.rollback()
                return {"success": False, "message": "Registration not found or already cancelled."}
            conn.execute("UPDATE event_registrations SET status='cancelled', decided_at=? WHERE registration_id=?",
                         (_now(), registration_id))
            promoted = None
            if reg["status"] == "confirmed":
                ev = self._row(conn, reg["event_id"])
                nxt = conn.execute("SELECT * FROM event_registrations WHERE event_id=? AND status='waitlisted' "
                                   "ORDER BY created_at ASC LIMIT 1", (reg["event_id"],)).fetchone()
                if nxt and ev["seats_left"] >= nxt["attendees"]:
                    conn.execute("UPDATE event_registrations SET status='confirmed', confirmation_code=?, "
                                 "decided_at=? WHERE registration_id=?",
                                 ("NBE-" + secrets.token_hex(4).upper(), _now(), nxt["registration_id"]))
                    promoted = nxt["registration_id"]
            conn.commit()
            return {"success": True, "registration_id": registration_id, "status": "cancelled",
                    "promoted_from_waitlist": promoted}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": "Cancellation failed.", "error": str(exc)}
        finally:
            conn.close()

    def my_registrations(self, user_id):
        with self._connect() as c:
            rows = c.execute("SELECT r.*, e.title, e.start_time, e.end_time, e.location, e.is_online, "
                             "e.event_type, e.is_demo FROM event_registrations r JOIN events e "
                             "ON e.event_id=r.event_id WHERE r.user_id=? ORDER BY e.start_time",
                             (user_id,)).fetchall()
        regs = [dict(r) for r in rows]
        for r in regs:
            r["is_demo"] = bool(r["is_demo"])
            r["is_online"] = bool(r["is_online"])
        return {"success": True, "count": len(regs), "registrations": regs}
