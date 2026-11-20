"""Create clearly-labelled DEMO accounts and sample data so you can try the web app.

    python scripts/seed_demo_app.py --password "choose-a-password-1"

Creates (emails end in @demo.neurobridge.local so they are obviously not real people):
  asha@demo.neurobridge.local   individual (sample tasks, routine, blueprint, cards)
  ravi@demo.neurobridge.local   caregiver, connected to Asha with Blueprint + Routines +
                                Calendar + Coordination shared
  mod@demo.neurobridge.local    admin (moderation, event review)
plus demo events (scripts/seed_demo_events.py) and four demo providers (psychiatrists, a
psychologist, an OT) with open slots. Every demo item is labelled as a demo.

Never run this on a real deployment. Remove demo users by deleting their accounts in the app.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--password", default=os.environ.get("NEUROBRIDGE_DEMO_PASSWORD"))
    args = ap.parse_args()
    if not args.password or len(args.password) < 10:
        sys.exit("Give --password (10+ characters) or set NEUROBRIDGE_DEMO_PASSWORD.")

    from nbapp import setup_database
    from nbapp.db import now
    from nbapp.security import hash_password
    from nbapp.routes_auth import seed_user_defaults
    from agent.tools.booking_db import BookingStore
    from agent.tools.events_db import EventStore
    from seed_demo_events import seed as seed_events

    db = setup_database()

    def user(email, name, role):
        row = db.one("SELECT id FROM users WHERE email=?", (email,))
        if row:
            return row["id"]
        uid = db.insert("users", email=email, password_hash=hash_password(args.password),
                        display_name=name, role=role, created_at=now())
        seed_user_defaults(db, uid, role)
        return uid

    asha = user("asha@demo.neurobridge.local", "Asha (demo)", "individual")
    ravi = user("ravi@demo.neurobridge.local", "Ravi (demo)", "caregiver")
    user("mod@demo.neurobridge.local", "Moderator (demo)", "admin")

    ts, today = now(), datetime.now().date().isoformat()
    if not db.one("SELECT 1 FROM tasks WHERE owner_id=?", (asha,)):
        for title, est, pri in [("Reply to college email", 10, 1), ("Tidy desk", 15, 2),
                                ("Buy headphones batteries", 5, 3)]:
            db.insert("tasks", owner_id=asha, title=title, estimate_min=est, priority=pri,
                      plan_date=today, created_at=ts, updated_at=ts)
        rid = db.insert("routines", owner_id=asha, name="Morning", kind="morning",
                        reminder_time="08:30", shared=1, created_at=ts)
        for i, (t, m) in enumerate([("Drink water", 1), ("Wash face", 3), ("Get dressed", 10),
                                    ("Breakfast", 15), ("Check today's plan", 2)]):
            db.insert("routine_steps", routine_id=rid, position=i, text=t, minutes=m)
        for sec, text in [("communicate", "I prefer text to phone calls. Give me time to answer."),
                          ("helps", "Headphones, a quiet corner, clear written plans."),
                          ("overwhelms", "Crowds, sudden plan changes, bright lights."),
                          ("respond", "Fewer words, no touching, let me step out.")]:
            db.insert("blueprint_sections", owner_id=asha, section=sec, content=text, shared=1,
                      updated_at=ts)
        db.insert("calendar_events", owner_id=asha, title="OT appointment (demo)",
                  start_time=(datetime.now() + timedelta(days=2)).replace(hour=11, minute=0,
                                                                          second=0, microsecond=0).isoformat(),
                  location="Panjim", shared=1, created_at=ts)
    if not db.one("SELECT 1 FROM care_links WHERE individual_id=? AND caregiver_id=?", (asha, ravi)):
        lid = db.insert("care_links", individual_id=asha, caregiver_id=ravi, relationship="Brother",
                        status="active", invited_by=asha, created_at=ts, updated_at=ts)
        for scope in ("blueprint", "routines", "calendar", "coordination"):
            db.insert("link_permissions", link_id=lid, scope=scope, state="granted",
                      updated_by=asha, updated_at=ts)
            db.insert("consent_records", link_id=lid, scope=scope, action="granted", actor_id=asha,
                      created_at=ts)

    bookings = BookingStore(os.environ.get("NEUROBRIDGE_BOOKING_DB") or None)
    demo = [
        ("Demo Psychiatry Clinic (demo listing)", "Psychiatrist", "MD Psychiatry (demo)",
         ["ADHD", "autism", "anxiety", "adult assessment"], ["18+"], "Panaji, Goa", True, 1000),
        ("Demo Child & Adolescent Psychiatry (demo listing)", "Psychiatrist", "DPM (demo)",
         ["autism", "ADHD", "children"], ["children 6-17"], "Margao, Goa", False, 1200),
        ("Demo Psychology Practice (demo listing)", "Psychologist", "M.Phil Clinical Psychology (demo)",
         ["CBT", "autism-affirming therapy", "caregiver support"], ["all ages"], "Mapusa, Goa", True, 800),
        ("Demo Occupational Therapy Clinic (demo listing)", "Occupational therapist", None,
         ["sensory processing"], ["adults", "children 3-12"], "Panaji, Goa", False, 900),
    ]
    have = {p["provider_name"] for p in bookings.list_providers_admin()["providers"]}
    for name, prof, cred, spec, ages, loc, online, fee in demo:
        if name in have:
            continue
        p = bookings.register_provider(name, prof, credentials=cred, specialties=spec, age_groups=ages,
                                       languages=["English", "Konkani", "Hindi"], location=loc,
                                       online_consultation=online, fee_amount=fee, is_demo=True,
                                       about="Sample listing for trying NeuroBridge. Not a real clinic.")
        bookings.verify_provider(p["provider_id"], note="Demo listing created by the seed script - "
                                                        "not a real clinic.", verified_by="seed script")
        for d in (2, 3, 5, 8):
            start = (datetime.now() + timedelta(days=d)).replace(hour=10 + d % 3, minute=0, second=0,
                                                                 microsecond=0)
            bookings.add_availability(p["provider_id"], start.isoformat(),
                                      (start + timedelta(minutes=45)).isoformat(), fee_amount=fee)
    seed_events(EventStore(bookings.db_path))
    print("Demo data ready. Sign in at /app with:\n  asha@demo.neurobridge.local (individual)\n"
          "  ravi@demo.neurobridge.local (caregiver)\n  mod@demo.neurobridge.local (admin)\n"
          "using the password you gave.")


if __name__ == "__main__":
    main()
