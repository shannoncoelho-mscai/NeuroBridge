"""Seed clearly-labelled DEMO events (is_demo=1) so the events flow can be tried.

    python scripts/seed_demo_events.py            # adds demo events if none exist
    NEUROBRIDGE_SEED_DEMO_EVENTS=1 uvicorn ...     # or let the API do it at startup

These are sample listings, not real events. The UI, agent replies and confirmations all mark
them as demo listings. Remove them with --remove.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.tools.events_db import EventStore  # noqa: E402

ORG = "NeuroBridge demo data"


def _at(days, hour, minute=0):
    d = (datetime.now() + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return d.isoformat()


DEMO = [
    dict(title="Parents of autistic children — support circle", event_type="support_group",
         description="A small, facilitated peer circle for parents and carers of autistic children. Share, listen, or just be there.",
         location="Panjim, Goa (community hall — demo)", is_online=False, days=3, hour=17, hours=1.5, capacity=12,
         accessibility=["quiet_room", "wheelchair_access"], audience=["autism", "caregivers", "parents"], languages=["English", "Konkani"]),
    dict(title="ADHD body-doubling club (online)", event_type="club",
         description="Work alongside others on camera, quietly, in 25-minute focus blocks with short breaks. Cameras optional.",
         is_online=True, days=1, hour=19, hours=2, capacity=20, accessibility=["online", "captioning"],
         audience=["adhd", "adults"], languages=["English", "Hindi"], recurrence="weekly"),
    dict(title="Sensory-friendly art club", event_type="club",
         description="Low-light, low-noise art session. Ear defenders, fidget tools and a quiet corner available.",
         location="Panjim, Goa (art studio — demo)", days=5, hour=11, hours=2, capacity=10,
         accessibility=["sensory_friendly", "quiet_room", "low_lighting"], audience=["autism", "adhd", "teens", "adults"],
         languages=["English"], recurrence="fortnightly"),
    dict(title="Caregivers' coffee morning", event_type="social_gathering",
         description="An informal morning for family carers to meet others who get it. No agenda, no pressure.",
         location="Margao, Goa (café — demo)", days=4, hour=10, hours=1.5, capacity=15,
         accessibility=["wheelchair_access"], audience=["caregivers"], languages=["English", "Konkani", "Marathi"]),
    dict(title="Workshop: preparing for medical appointments", event_type="workshop",
         description="Practical session on writing down concerns, symptoms in your own words and questions to ask.",
         is_online=True, days=6, hour=18, hours=1.5, capacity=40, accessibility=["online", "captioning"],
         audience=["caregivers", "adults"], languages=["English"]),
    dict(title="Hearing Voices peer group (online)", event_type="support_group",
         description="A peer-led space for people who hear voices or have unusual experiences. Not a clinical service.",
         is_online=True, days=2, hour=18, hours=1.5, capacity=10, accessibility=["online"],
         audience=["psychosis", "adults"], languages=["English", "Hindi"]),
    dict(title="Dissociation & DID peer support (online)", event_type="support_group",
         description="A closed, moderated peer group for people with dissociative experiences, including DID. Grounding-focused.",
         is_online=True, days=7, hour=19, hours=1.5, capacity=8, accessibility=["online", "captioning"],
         audience=["did", "dissociation", "adults"], languages=["English"]),
    dict(title="Quiet board-games social", event_type="social_gathering",
         description="Relaxed board games with clear rules cards and a quiet room. Come for 20 minutes or two hours.",
         location="Panjim, Goa (library room — demo)", days=8, hour=16, hours=2, capacity=14,
         accessibility=["sensory_friendly", "quiet_room"], audience=["autism", "adhd", "anxiety", "adults", "teens"],
         languages=["English"]),
    dict(title="Teen social skills club", event_type="club",
         description="Structured, friendly activities for neurodivergent teens, led by trained facilitators.",
         location="Panjim, Goa (youth centre — demo)", days=9, hour=15, hours=1.5, capacity=12,
         accessibility=["sensory_friendly", "quiet_room"], audience=["teens", "autism", "adhd"], languages=["English", "Konkani"]),
    dict(title="Community meeting: accessible public spaces", event_type="community_meeting",
         description="Share ideas on making local spaces more accessible for neurodivergent and disabled people.",
         location="Panjim, Goa (town hall — demo)", days=12, hour=17, hours=1.5, capacity=60,
         accessibility=["wheelchair_access", "captioning", "sign_language"], audience=["community", "caregivers", "adults"],
         languages=["English", "Konkani"]),
    dict(title="Gentle walking group", event_type="activity",
         description="A slow, chatty (or silent!) 45-minute walk. Meet at the gate; predictable route each week.",
         location="Panjim, Goa (Campal gardens — demo)", days=2, hour=7, hours=1, capacity=20,
         accessibility=["sensory_friendly"], audience=["anxiety", "caregivers", "adults"], languages=["English"], recurrence="weekly"),
]


def seed(store):
    existing = store.search_events(limit=500)["events"]
    if any(e["is_demo"] for e in existing):
        return 0
    n = 0
    for d in DEMO:
        d = dict(d)
        days, hour, hours = d.pop("days"), d.pop("hour"), d.pop("hours")
        start = _at(days, hour)
        end = (datetime.fromisoformat(start) + timedelta(hours=hours)).isoformat()
        r = store.create_event(start_time=start, end_time=end, organizer=ORG, is_demo=True, **d)
        n += r["success"]
    return n


def remove(store):
    with store._connect() as c:
        ids = [r[0] for r in c.execute("SELECT event_id FROM events WHERE is_demo=1")]
        c.execute("DELETE FROM event_registrations WHERE event_id IN (SELECT event_id FROM events WHERE is_demo=1)")
        c.execute("DELETE FROM events WHERE is_demo=1")
    return len(ids)


if __name__ == "__main__":
    s = EventStore()
    print(("Removed" if "--remove" in sys.argv else "Seeded"),
          remove(s) if "--remove" in sys.argv else seed(s), "demo events")
