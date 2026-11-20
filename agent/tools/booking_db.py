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
    "Reserved in the NeuroBridge provider directory. The clinic confirms separately: the "
    "status changes to 'Clinic confirmed' once a NeuroBridge coordinator has heard back from "
    "them. Until then, please treat the time as provisional."
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
            self._migrate(conn)

    # Columns added in v0.6 (contact details, verification record, clinic confirmation).
    PROVIDER_EXTRA = {"phone": "TEXT", "email": "TEXT", "website": "TEXT", "address": "TEXT",
                      "source_url": "TEXT", "verification_note": "TEXT", "verified_by": "TEXT",
                      "verified_at": "TEXT", "is_demo": "INTEGER DEFAULT 0", "about": "TEXT"}
    APPT_EXTRA = {"clinic_status": "TEXT", "clinic_note": "TEXT", "requester_name": "TEXT",
                  "requester_phone": "TEXT", "share_contact": "INTEGER DEFAULT 0"}
    PROVIDER_EDITABLE = ("provider_name", "organization", "profession", "credentials", "location",
                         "online_consultation", "fee_amount", "phone", "email", "website",
                         "address", "source_url", "about", "specialties", "languages",
                         "age_groups")

    def _migrate(self, conn):
        for table, extra in (("providers", self.PROVIDER_EXTRA), ("appointments", self.APPT_EXTRA)):
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, typ in extra.items():
                if col not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        conn.execute("""CREATE TABLE IF NOT EXISTS outside_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key TEXT NOT NULL,
            clinic_name TEXT NOT NULL,
            profession TEXT,
            phone TEXT, email TEXT, website TEXT, source_url TEXT,
            preferred_times TEXT, reason TEXT,
            status TEXT DEFAULT 'to_contact',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_outside_user ON outside_requests(user_key)")

    def _connect(self, timeout=30):
        conn = sqlite3.connect(str(self.db_path), timeout=timeout)
        conn.row_factory = sqlite3.Row
        return conn

    # ---------------- providers ----------------
    def register_provider(self, provider_name, profession, specialties=None, age_groups=None,
                          languages=None, location=None, organization=None, credentials=None,
                          online_consultation=False, fee_amount=None, user_id=None,
                          phone=None, email=None, website=None, address=None, source_url=None,
                          about=None, is_demo=False):
        """Register a provider. Starts as verification_status='pending', booking disabled."""
        if not provider_name or not profession:
            return {"success": False, "message": "provider_name and profession are required."}
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO providers (user_id, provider_name, organization, profession, "
                "specialties, credentials, age_groups, languages, location, "
                "online_consultation, fee_amount, phone, email, website, address, source_url, "
                "about, is_demo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, provider_name, organization, profession,
                 json.dumps(specialties or []), credentials, json.dumps(age_groups or []),
                 json.dumps(languages or []), location, int(bool(online_consultation)),
                 fee_amount, phone, email, website, address, source_url, about,
                 int(bool(is_demo))))
        return {"success": True, "provider_id": cur.lastrowid, "verification_status": "pending",
                "booking_enabled": False,
                "message": "Registered. Not searchable until verified by an administrator."}

    def verify_provider(self, provider_id, verified=True, enable_booking=True, note=None,
                        verified_by=None):
        """Administrator action. `note` records what was checked (e.g. registration number
        looked up, clinic phoned on a date)."""
        status = "verified" if verified else "rejected"
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE providers SET verification_status=?, booking_enabled=?, "
                "verification_note=COALESCE(?, verification_note), verified_by=?, verified_at=? "
                "WHERE provider_id=?",
                (status, int(bool(verified and enable_booking)), note, verified_by,
                 datetime.now().isoformat(timespec="minutes") if verified else None,
                 provider_id))
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
        matches.sort(key=lambda p: (bool(p.get("is_demo")), p.get("provider_name") or ""))
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
                             language=None, child_age=None, profession=None):
        query = ("SELECT a.slot_id, a.provider_id, a.start_time, a.end_time, "
                 "a.duration_minutes, a.fee_amount, p.provider_name, p.profession, "
                 "p.specialties, p.languages, p.age_groups, p.location, p.online_consultation, "
                 "p.address, p.phone, p.is_demo, p.fee_currency "
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
        if profession:
            query += " AND LOWER(p.profession) LIKE ?"
            params.append(f"%{profession.lower()}%")
        query += " AND a.start_time >= ? ORDER BY a.start_time ASC"
        params.append(datetime.now().isoformat(timespec="minutes"))
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
                            appointment_type="consultation", caregiver_notes=None,
                            requester_name=None, requester_phone=None, share_contact=False):
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
                "caregiver_approved, confirmation_code, caregiver_notes, requester_name, "
                "requester_phone, share_contact) "
                "VALUES (?,?,?,?,?,?,?,'pending_approval',0,NULL,?,?,?,?)",
                (slot["provider_id"], caregiver_user_id, child_age, appointment_type, slot_id,
                 slot["start_time"], slot["end_time"], caregiver_notes,
                 requester_name if share_contact else None,
                 requester_phone if share_contact else None, int(bool(share_contact))))
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
                         "caregiver_approved=1, confirmation_code=?, "
                         "clinic_status='awaiting_clinic' WHERE appointment_id=?",
                         (code, appointment_id))
            conn.commit()
            return {"success": True, "appointment_id": appointment_id,
                    "booking_status": "confirmed", "caregiver_approved": True,
                    "confirmation_code": code, "confirmation_scope": CONFIRMATION_SCOPE,
                    "clinic_status": "awaiting_clinic",
                    "message": "Slot reserved in NeuroBridge. The clinic still has to confirm; "
                               "you will see it here when they do."}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": "Booking transaction failed.", "error": str(exc)}
        finally:
            conn.close()

    def book_slot(self, slot_id, caregiver_user_id, appointment_type="consultation",
                  caregiver_notes=None):
        """Request + reserve in one step. Only for callers that already have the person's
        explicit approval of this exact slot (the agent asks before calling it)."""
        req = self.request_appointment(slot_id, caregiver_user_id,
                                       appointment_type=appointment_type,
                                       caregiver_notes=caregiver_notes)
        if not req.get("success"):
            return req
        res = self.approve_appointment(req["appointment_id"], caregiver_user_id,
                                       explicit_approval=True)
        if not res.get("success"):
            self.cancel_appointment(req["appointment_id"], caregiver_user_id)
            return res
        return {**res, "provider_name": req["provider_name"], "start_time": req["start_time"],
                "end_time": req["end_time"]}

    def get_appointments(self, caregiver_user_id):
        if not caregiver_user_id:
            return {"success": False, "message": "Caregiver ID is required."}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT a.appointment_id, a.provider_id, p.provider_name, p.profession, "
                "a.appointment_type, a.start_time, a.end_time, a.booking_status, "
                "a.caregiver_approved, a.confirmation_code, a.caregiver_notes, a.created_at, "
                "a.clinic_status, a.clinic_note, p.location, p.address, p.phone, p.email, "
                "p.website, p.is_demo "
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

    # ---------------- admin directory management (v0.6) ----------------
    def get_provider(self, provider_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM providers WHERE provider_id=?",
                               (provider_id,)).fetchone()
        if not row:
            return None
        p = dict(row)
        for f in ("specialties", "age_groups", "languages"):
            p[f] = _loads(p.get(f))
        return p

    def list_providers_admin(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT p.*, (SELECT COUNT(*) FROM provider_availability a "
                                "WHERE a.provider_id=p.provider_id AND a.status='available') "
                                "AS open_slots FROM providers p "
                                "ORDER BY p.verification_status, p.provider_name").fetchall()
        out = []
        for r in rows:
            p = dict(r)
            for f in ("specialties", "age_groups", "languages"):
                p[f] = _loads(p.get(f))
            out.append(p)
        return {"success": True, "count": len(out), "providers": out}

    def update_provider(self, provider_id, **fields):
        """Edit listing details. Any edit of a verified listing keeps its status but is
        recorded by the caller in the audit log."""
        sets, vals = [], []
        for k, v in fields.items():
            if k not in self.PROVIDER_EDITABLE or v is None:
                continue
            if k in ("specialties", "languages", "age_groups"):
                v = json.dumps(list(v))
            if k == "online_consultation":
                v = int(bool(v))
            sets.append(f"{k}=?")
            vals.append(v)
        if not sets:
            return {"success": False, "message": "Nothing to update."}
        with self._connect() as conn:
            cur = conn.execute(f"UPDATE providers SET {', '.join(sets)} WHERE provider_id=?",
                               (*vals, provider_id))
        if cur.rowcount != 1:
            return {"success": False, "message": "Provider not found."}
        return {"success": True, "provider": self.get_provider(provider_id)}

    def list_slots_admin(self, provider_id):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM provider_availability WHERE provider_id=? "
                                "ORDER BY start_time", (provider_id,)).fetchall()
        return {"success": True, "slots": [dict(r) for r in rows]}

    def remove_slot(self, slot_id):
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM provider_availability WHERE slot_id=? AND "
                               "status='available'", (slot_id,))
        if cur.rowcount != 1:
            return {"success": False, "message": "Only open (unbooked) slots can be removed."}
        return {"success": True, "slot_id": slot_id}

    def admin_appointments(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT a.appointment_id, a.provider_id, p.provider_name, p.phone AS clinic_phone, "
                "p.email AS clinic_email, a.start_time, a.end_time, a.booking_status, "
                "a.clinic_status, a.clinic_note, a.confirmation_code, a.appointment_type, "
                "a.requester_name, a.requester_phone, a.share_contact, a.caregiver_notes, "
                "a.created_at FROM appointments a JOIN providers p "
                "ON p.provider_id=a.provider_id ORDER BY a.start_time").fetchall()
        return {"success": True, "appointments": [dict(r) for r in rows]}

    CLINIC_STATUSES = ("awaiting_clinic", "clinic_confirmed", "clinic_declined")

    def set_clinic_status(self, appointment_id, status, note=None):
        """Record what the clinic said. Declining frees the slot again."""
        if status not in self.CLINIC_STATUSES:
            return {"success": False, "message": "Unknown clinic status."}
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            appt = conn.execute("SELECT * FROM appointments WHERE appointment_id=? AND "
                                "booking_status='confirmed'", (appointment_id,)).fetchone()
            if not appt:
                conn.rollback()
                return {"success": False, "message": "Only reserved appointments can be updated."}
            conn.execute("UPDATE appointments SET clinic_status=?, clinic_note=? "
                         "WHERE appointment_id=?", (status, note, appointment_id))
            if status == "clinic_declined":
                conn.execute("UPDATE appointments SET booking_status='cancelled' "
                             "WHERE appointment_id=?", (appointment_id,))
                conn.execute("UPDATE provider_availability SET status='available' "
                             "WHERE slot_id=?", (appt["slot_id"],))
            conn.commit()
        finally:
            conn.close()
        return {"success": True, "appointment_id": appointment_id, "clinic_status": status,
                "caregiver_user_id": appt["caregiver_user_id"]}

    # ---------------- requests to clinics outside NeuroBridge (v0.6) ----------------
    OUTSIDE_STATUSES = ("to_contact", "contacted", "booked", "closed")

    def create_outside_request(self, user_key, clinic_name, profession=None, phone=None,
                               email=None, website=None, source_url=None,
                               preferred_times=None, reason=None):
        """A to-do for the user: NeuroBridge cannot book with clinics outside its directory,
        so this only records who to contact and drafts what to say."""
        if not user_key or not (clinic_name or "").strip():
            return {"success": False, "message": "Clinic name is required."}
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO outside_requests (user_key, clinic_name, profession, phone, email, "
                "website, source_url, preferred_times, reason) VALUES (?,?,?,?,?,?,?,?,?)",
                (user_key, clinic_name.strip()[:200], profession, phone, email, website,
                 source_url, preferred_times, reason))
        return {"success": True, "request_id": cur.lastrowid, "status": "to_contact",
                "draft_message": draft_outside_message(clinic_name, profession,
                                                       preferred_times, reason)}

    def list_outside_requests(self, user_key):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM outside_requests WHERE user_key=? "
                                "ORDER BY updated_at DESC", (user_key,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["draft_message"] = draft_outside_message(d["clinic_name"], d["profession"],
                                                       d["preferred_times"], d["reason"])
            out.append(d)
        return {"success": True, "requests": out}

    def update_outside_request(self, request_id, user_key, status=None, notes=None):
        if status and status not in self.OUTSIDE_STATUSES:
            return {"success": False, "message": "Unknown status."}
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE outside_requests SET status=COALESCE(?, status), "
                "notes=COALESCE(?, notes), updated_at=CURRENT_TIMESTAMP "
                "WHERE request_id=? AND user_key=?", (status, notes, request_id, user_key))
        if cur.rowcount != 1:
            return {"success": False, "message": "Request not found."}
        return {"success": True, "request_id": request_id}

    def delete_outside_request(self, request_id, user_key):
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM outside_requests WHERE request_id=? AND user_key=?",
                               (request_id, user_key))
        return {"success": cur.rowcount == 1}

    def delete_user_data(self, user_key):
        """Used by account deletion."""
        with self._connect() as conn:
            conn.execute("DELETE FROM outside_requests WHERE user_key=?", (user_key,))


def draft_outside_message(clinic_name, profession=None, preferred_times=None, reason=None):
    """A short, editable message the user can send or read out on the phone."""
    who = clinic_name or "the clinic"
    lines = [f"Hello {who},", "",
             f"I would like to book an appointment"
             f"{' with a ' + profession.lower() if profession else ''}."]
    if reason:
        lines.append(f"Reason (in brief): {reason}")
    if preferred_times:
        lines.append(f"Times that suit me: {preferred_times}")
    lines += ["Could you tell me the available dates, the consultation fee, and whether "
              "online consultations are possible?",
              "I may need a quiet waiting area or extra time to communicate - please let me "
              "know if that can be arranged.", "", "Thank you."]
    return "\n".join(lines)
