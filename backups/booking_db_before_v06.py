"""NeuroBridge provider booking store (ported from notebook cells 169-175, which were
previously notebook-only).

IMPORTANT — scope of a "confirmed" booking: this is NeuroBridge's own local registry. A
confirmation means the slot was reserved in this database after explicit caregiver
approval. NeuroBridge does not contact the provider, and no external booking system is
involved. Every booking result says so in `confirmation_scope`.

Only providers with verification_status='verified' AND booking_enabled=1 are searchable
or bookable. New registrations start as 'pending'.
"""
import json
import re
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "neurobridge_bookings.sqlite3"

CONFIRMATION_SCOPE = (
    "Reserved in the NeuroBridge local provider registry only. NeuroBridge has not "
    "contacted the provider; please confirm directly with the provider."
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS providers (
    provider_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT UNIQUE,
    provider_name TEXT NOT NULL,
    organization TEXT,
    profession TEXT NOT NULL,
    specialties TEXT,
    credentials TEXT,
    verification_status TEXT DEFAULT 'pending',
    age_groups TEXT,
    languages TEXT,
    location TEXT,
    online_consultation INTEGER DEFAULT 0,
    fee_amount REAL,
    fee_currency TEXT DEFAULT 'INR',
    booking_enabled INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS provider_availability (
    slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_minutes INTEGER,
    fee_amount REAL,
    status TEXT DEFAULT 'available',
    FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL,
    caregiver_user_id TEXT,
    child_age INTEGER,
    appointment_type TEXT,
    slot_id INTEGER,
    start_time TEXT,
    end_time TEXT,
    booking_status TEXT DEFAULT 'pending_approval',
    caregiver_approved INTEGER DEFAULT 0,
    confirmation_code TEXT UNIQUE,
    caregiver_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provider_id) REFERENCES providers(provider_id),
    FOREIGN KEY (slot_id) REFERENCES provider_availability(slot_id)
);
CREATE INDEX IF NOT EXISTS idx_provider_specialty
    ON providers(profession, verification_status, booking_enabled);
CREATE INDEX IF NOT EXISTS idx_provider_slots
    ON provider_availability(provider_id, status, start_time);
CREATE INDEX IF NOT EXISTS idx_appointments_status
    ON appointments(booking_status, provider_id);
"""


def age_group_match(child_age, age_groups):
    if child_age is None:
        return True
    for group in age_groups or []:
        text = str(group).lower().strip()
        if "all age" in text:
            return True
        if any(t in text for t in ["child", "children", "teen", "adolescent", "infant"]) \
                and child_age < 18:
            return True
        m = re.search(r"(under|below)\s*(\d+)", text)
        if m and child_age < int(m.group(2)):
            return True
        m = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)", text)
        if m and int(m.group(1)) <= child_age <= int(m.group(2)):
            return True
        m = re.search(r"(\d+)\s*\+", text)
        if m and child_age >= int(m.group(1)):
            return True
    return False


def _loads(value):
    try:
        return json.loads(value or "[]")
    except Exception:
        return []


class BookingStore:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path or DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self, timeout=30):
        conn = sqlite3.connect(str(self.db_path), timeout=timeout)
        conn.row_factory = sqlite3.Row
        return conn

    # ---------------- providers ----------------
    def register_provider(self, provider_name, profession, specialties=None, age_groups=None,
                          languages=None, location=None, organization=None, credentials=None,
                          online_consultation=False, fee_amount=None, user_id=None):
        """Register a provider. Starts as verification_status='pending', booking disabled."""
        if not provider_name or not profession:
            return {"success": False, "message": "provider_name and profession are required."}
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO providers (user_id, provider_name, organization, profession, "
                "specialties, credentials, age_groups, languages, location, "
                "online_consultation, fee_amount) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, provider_name, organization, profession,
                 json.dumps(specialties or []), credentials, json.dumps(age_groups or []),
                 json.dumps(languages or []), location, int(bool(online_consultation)),
                 fee_amount))
        return {"success": True, "provider_id": cur.lastrowid, "verification_status": "pending",
                "booking_enabled": False,
                "message": "Registered. Not searchable until verified by an administrator."}

    def verify_provider(self, provider_id, verified=True, enable_booking=True):
        """Administrator action (the API protects this with NEUROBRIDGE_ADMIN_TOKEN)."""
        status = "verified" if verified else "rejected"
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE providers SET verification_status=?, booking_enabled=? "
                "WHERE provider_id=?",
                (status, int(bool(verified and enable_booking)), provider_id))
        if cur.rowcount != 1:
            return {"success": False, "message": "Provider not found."}
        return {"success": True, "provider_id": provider_id, "verification_status": status}

    def search_providers(self, profession=None, specialty=None, language=None, location=None,
                         child_age=None, online_only=False):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM providers WHERE verification_status='verified' "
                                "AND booking_enabled=1").fetchall()
        matches = []
        for row in rows:
            p = dict(row)
            for f in ("specialties", "age_groups", "languages"):
                p[f] = _loads(p.get(f))
            if profession and profession.lower() not in (p.get("profession") or "").lower():
                continue
            if specialty and not any(specialty.lower() in s.lower() for s in p["specialties"]):
                continue
            if language and not any(language.lower() in s.lower() for s in p["languages"]):
                continue
            if location and location.lower() not in (p.get("location") or "").lower():
                continue
            if online_only and not p.get("online_consultation"):
                continue
            if not age_group_match(child_age, p["age_groups"]):
                continue
            matches.append(p)
        return {"success": True, "count": len(matches), "providers": matches,
                "message": "Verified and booking-enabled providers in the NeuroBridge registry only."}

    # ---------------- availability ----------------
    def add_availability(self, provider_id, start_time, end_time, duration_minutes=60,
                         fee_amount=None):
        with self._connect() as conn:
            ok = conn.execute("SELECT provider_id FROM providers WHERE provider_id=? AND "
                              "verification_status='verified' AND booking_enabled=1",
                              (provider_id,)).fetchone()
            if not ok:
                return {"success": False,
                        "message": "Provider is not verified or booking is not enabled."}
            try:
                start, end = datetime.fromisoformat(start_time), datetime.fromisoformat(end_time)
            except ValueError:
                return {"success": False, "message": "Times must be ISO-8601."}
            if end <= start:
                return {"success": False, "message": "End time must be after start time."}
            if duration_minutes <= 0:
                return {"success": False, "message": "Duration must be positive."}
            cur = conn.execute(
                "INSERT INTO provider_availability (provider_id, start_time, end_time, "
                "duration_minutes, fee_amount, status) VALUES (?,?,?,?,?,'available')",
                (provider_id, start.isoformat(), end.isoformat(), duration_minutes, fee_amount))
        return {"success": True, "slot_id": cur.lastrowid, "provider_id": provider_id,
                "start_time": start.isoformat(), "end_time": end.isoformat(),
                "status": "available"}

    def find_available_slots(self, provider_id=None, location=None, specialty=None,
                             language=None, child_age=None):
        query = ("SELECT a.slot_id, a.provider_id, a.start_time, a.end_time, "
                 "a.duration_minutes, a.fee_amount, p.provider_name, p.profession, "
                 "p.specialties, p.languages, p.age_groups, p.location, p.online_consultation "
                 "FROM provider_availability a JOIN providers p ON p.provider_id=a.provider_id "
                 "WHERE a.status='available' AND p.verification_status='verified' "
                 "AND p.booking_enabled=1")
        params = []
        if provider_id is not None:
            query += " AND a.provider_id=?"
            params.append(provider_id)
        if location:
            query += " AND LOWER(p.location) LIKE ?"
            params.append(f"%{location.lower()}%")
        query += " ORDER BY a.start_time ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        slots = []
        for row in rows:
            item = dict(row)
            for f in ("specialties", "languages", "age_groups"):
                item[f] = _loads(item[f])
            if specialty and not any(specialty.lower() in s.lower() for s in item["specialties"]):
                continue
            if language and not any(language.lower() in s.lower() for s in item["languages"]):
                continue
            if not age_group_match(child_age, item["age_groups"]):
                continue
            slots.append(item)
        return {"success": True, "count": len(slots), "slots": slots}

    # ---------------- appointments ----------------
    def request_appointment(self, slot_id, caregiver_user_id, child_age=None,
                            appointment_type="consultation", caregiver_notes=None):
        """Create a pending request. Does NOT reserve the slot."""
        if not caregiver_user_id:
            return {"success": False, "message": "Caregiver account is required."}
        with self._connect() as conn:
            slot = conn.execute(
                "SELECT a.*, p.provider_name FROM provider_availability a JOIN providers p "
                "ON p.provider_id=a.provider_id WHERE a.slot_id=? AND a.status='available' "
                "AND p.verification_status='verified' AND p.booking_enabled=1",
                (slot_id,)).fetchone()
            if not slot:
                return {"success": False, "message": "This slot is no longer available."}
            cur = conn.execute(
                "INSERT INTO appointments (provider_id, caregiver_user_id, child_age, "
                "appointment_type, slot_id, start_time, end_time, booking_status, "
                "caregiver_approved, confirmation_code, caregiver_notes) "
                "VALUES (?,?,?,?,?,?,?,'pending_approval',0,NULL,?)",
                (slot["provider_id"], caregiver_user_id, child_age, appointment_type, slot_id,
                 slot["start_time"], slot["end_time"], caregiver_notes))
        return {"success": True, "appointment_id": cur.lastrowid,
                "booking_status": "pending_approval", "caregiver_approved": False,
                "provider_name": slot["provider_name"], "start_time": slot["start_time"],
                "end_time": slot["end_time"],
                "message": "Appointment request created. Caregiver approval is required."}

    def approve_appointment(self, appointment_id, caregiver_user_id, explicit_approval=False):
        """Reserve the slot transactionally. Requires explicit_approval=True."""
        if explicit_approval is not True:
            return {"success": False, "message": "Explicit caregiver approval is required."}
        code = "NB-" + secrets.token_hex(4).upper()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            appt = conn.execute(
                "SELECT * FROM appointments WHERE appointment_id=? AND caregiver_user_id=? "
                "AND booking_status='pending_approval' AND caregiver_approved=0",
                (appointment_id, caregiver_user_id)).fetchone()
            if not appt:
                conn.rollback()
                return {"success": False,
                        "message": "Appointment not found or approval is not permitted."}
            cur = conn.execute("UPDATE provider_availability SET status='booked' "
                               "WHERE slot_id=? AND status='available'", (appt["slot_id"],))
            if cur.rowcount != 1:
                conn.rollback()
                return {"success": False, "message": "Sorry, this slot has already been taken."}
            conn.execute("UPDATE appointments SET booking_status='confirmed', "
                         "caregiver_approved=1, confirmation_code=? WHERE appointment_id=?",
                         (code, appointment_id))
            conn.commit()
            return {"success": True, "appointment_id": appointment_id,
                    "booking_status": "confirmed", "caregiver_approved": True,
                    "confirmation_code": code, "confirmation_scope": CONFIRMATION_SCOPE,
                    "message": "Slot reserved in the NeuroBridge registry."}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": "Booking transaction failed.", "error": str(exc)}
        finally:
            conn.close()

    def get_appointments(self, caregiver_user_id):
        if not caregiver_user_id:
            return {"success": False, "message": "Caregiver ID is required."}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT a.appointment_id, a.provider_id, p.provider_name, p.profession, "
                "a.appointment_type, a.start_time, a.end_time, a.booking_status, "
                "a.caregiver_approved, a.confirmation_code, a.caregiver_notes, a.created_at "
                "FROM appointments a JOIN providers p ON p.provider_id=a.provider_id "
                "WHERE a.caregiver_user_id=? ORDER BY a.start_time DESC",
                (caregiver_user_id,)).fetchall()
        appts = [dict(r) for r in rows]
        return {"success": True, "count": len(appts), "appointments": appts,
                "confirmation_scope": CONFIRMATION_SCOPE}

    def cancel_appointment(self, appointment_id, caregiver_user_id):
        if not caregiver_user_id:
            return {"success": False, "message": "Caregiver authentication is required."}
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            appt = conn.execute("SELECT * FROM appointments WHERE appointment_id=? AND "
                                "caregiver_user_id=?",
                                (appointment_id, caregiver_user_id)).fetchone()
            if not appt:
                conn.rollback()
                return {"success": False, "message": "Appointment not found or access denied."}
            status = appt["booking_status"]
            if status not in ("confirmed", "pending_approval"):
                conn.rollback()
                return {"success": False,
                        "message": f"Appointment cannot be cancelled from status: {status}"}
            if status == "confirmed":
                conn.execute("UPDATE provider_availability SET status='available' "
                             "WHERE slot_id=? AND status='booked'", (appt["slot_id"],))
            conn.execute("UPDATE appointments SET booking_status='cancelled' WHERE "
                         "appointment_id=? AND caregiver_user_id=?",
                         (appointment_id, caregiver_user_id))
            conn.commit()
            return {"success": True, "appointment_id": appointment_id,
                    "booking_status": "cancelled", "slot_released": status == "confirmed",
                    "message": "Appointment cancelled."}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": "Cancellation failed.", "error": str(exc)}
        finally:
            conn.close()
