"""v0.6: real-provider directory, agent booking with psychiatrists, clinic confirmation,
and the tracker for clinics outside NeuroBridge."""
from datetime import datetime, timedelta

import pytest

from conftest import make_agent
from test_webapp import H, PW, register, app, events  # noqa: F401  (fixtures)


def _future(days=7, hour=10):
    d = (datetime.now() + timedelta(days=days)).date().isoformat()
    return f"{d}T{hour:02d}:00", f"{d}T{hour + 1:02d}:00"


@pytest.fixture
def psychiatrist(store):
    p = store.register_provider("Dr Asha Kamat", "Psychiatrist", specialties=["ADHD", "autism"],
                                languages=["English", "Konkani"], location="Panaji, Goa",
                                address="12 Example Road, Panaji", phone="+91 832 555 0101",
                                source_url="https://clinic.example.org", fee_amount=900)
    store.verify_provider(p["provider_id"], note="Registration checked; clinic phoned",
                          verified_by="admin@x.org")
    s, e = _future()
    slot = store.add_availability(p["provider_id"], s, e, fee_amount=900)
    return {"provider_id": p["provider_id"], "slot_id": slot["slot_id"]}


# ------------------------------------------------------------------ agent
def test_agent_finds_real_info_and_books_listed_psychiatrist_after_exact_approval(store, psychiatrist):
    agent, llm, search, _ = make_agent(store=store)
    r = agent.run("Find a psychiatrist in Panaji and book an appointment", user_id="u1",
                  granted_permissions={"booking:write"})
    tools = [t["tool"] for t in r["tasks"]]
    assert "web_search" in tools                      # real-world research happens too
    assert any("Psychiatrist Panaji" in q for q in search.calls)
    assert {"provider_search", "find_slots", "book_appointment"} <= set(tools)
    assert r["status"] == "WAITING_APPROVAL"
    ap = r["approvals"][0]
    assert "Dr Asha Kamat" in ap["reason"] and "₹900" in ap["reason"]
    assert "clinic will still confirm" in ap["reason"]
    assert store.get_appointments("u1")["count"] == 0  # nothing before approval
    r2 = agent.resume(r["run_id"], ap["approval_id"], approved=True)
    appts = store.get_appointments("u1")["appointments"]
    assert len(appts) == 1 and appts[0]["booking_status"] == "confirmed"
    assert appts[0]["clinic_status"] == "awaiting_clinic"
    assert "Booked in NeuroBridge" in r2["answer"] and "still has to confirm" in r2["answer"]


def test_agent_books_nothing_when_no_listed_provider_and_points_to_tracker(store):
    agent, *_ = make_agent(store=store)
    r = agent.run("Book an appointment with a psychiatrist in Margao", user_id="u1",
                  granted_permissions={"booking:write"})
    assert r["status"] != "WAITING_APPROVAL" and not r["approvals"]
    assert store.get_appointments("u1")["count"] == 0
    assert "Nothing was booked" in r["answer"] and "Track this clinic" in r["answer"]
    assert r["sources"]                                # web results are still shown


def test_declined_approval_books_nothing(store, psychiatrist):
    agent, *_ = make_agent(store=store)
    r = agent.run("Find a psychiatrist in Panaji and book an appointment", user_id="u1",
                  granted_permissions={"booking:write"})
    agent.resume(r["run_id"], r["approvals"][0]["approval_id"], approved=False)
    assert store.get_appointments("u1")["count"] == 0
    assert store.find_available_slots(provider_id=psychiatrist["provider_id"])["count"] == 1


def test_agent_never_books_for_someone_else(store, psychiatrist):
    agent, *_ = make_agent(store=store)
    r = agent.run("Find a psychiatrist in Panaji and book an appointment", user_id="u1",
                  granted_permissions={"booking:write"})
    assert r["approvals"][0]["arguments"]["caregiver_user_id"] == "u1"


def test_past_slots_are_not_offered(store):
    p = store.register_provider("Dr Past", "Psychiatrist")
    store.verify_provider(p["provider_id"])
    store.add_availability(p["provider_id"], "2020-01-01T10:00", "2020-01-01T11:00")
    assert store.find_available_slots(profession="psychiatrist")["count"] == 0


def test_profession_filter_on_slots(store, psychiatrist):
    assert store.find_available_slots(profession="psychiatrist")["count"] == 1
    assert store.find_available_slots(profession="speech therapist")["count"] == 0


# ------------------------------------------------------------------ admin directory + clinic
def _admin(app, monkeypatch):
    import nbapp
    import nbapp.state as st
    monkeypatch.setenv("NEUROBRIDGE_ADMIN_EMAIL", "admin@x.org")
    monkeypatch.setenv("NEUROBRIDGE_ADMIN_PASSWORD", PW)
    nbapp._bootstrap_admin(st.db)
    tok = app.post("/api/auth/login", json={"email": "admin@x.org", "password": PW}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_admin_directory_flow_and_clinic_confirmation(app, monkeypatch):
    admin = _admin(app, monkeypatch)
    user = register(app, "lisa@x.org", name="Lisa")
    body = {"provider_name": "Dr Real Example", "profession": "Psychiatrist",
            "location": "Panaji, Goa", "phone": "+91 832 555 0199",
            "source_url": "https://clinic.example.org", "specialties": ["ADHD"]}
    assert app.post("/api/admin/providers", json=body, headers=H(user)).status_code == 403
    pid = app.post("/api/admin/providers", json=body, headers=H(admin)).json()["provider_id"]
    assert app.get("/api/providers", headers=H(user)).json()["count"] == 0   # not listed yet
    assert app.post(f"/api/admin/providers/{pid}/verify", json={"note": ""},
                    headers=H(admin)).status_code == 422                     # a note is required
    assert app.post(f"/api/admin/providers/{pid}/verify",
                    json={"note": "NMC register checked; clinic phoned 20 Nov"},
                    headers=H(admin)).status_code == 200
    listed = app.get("/api/providers?profession=psychiatrist", headers=H(user)).json()["providers"]
    assert listed[0]["phone"] == "+91 832 555 0199"
    assert listed[0]["verification_note"].startswith("NMC register")
    s, e = _future()
    sid = app.post(f"/api/admin/providers/{pid}/slots", json={"start_time": s, "end_time": e},
                   headers=H(admin)).json()["slot_id"]
    aid = app.post("/api/appointments", json={"slot_id": sid, "share_contact": True,
                                              "contact_phone": "98220 00000"},
                   headers=H(user)).json()["appointment_id"]
    assert app.post(f"/api/appointments/{aid}/approve?explicit_approval=true",
                    headers=H(user)).status_code == 200
    row = [x for x in app.get("/api/admin/appointments", headers=H(admin)).json()["appointments"]
           if x["appointment_id"] == aid][0]
    assert row["clinic_status"] == "awaiting_clinic" and row["requester_phone"] == "98220 00000"
    assert row["requester_name"] == "Lisa"
    assert app.post(f"/api/admin/appointments/{aid}/clinic-status", json={"status": "clinic_confirmed"},
                    headers=H(user)).status_code == 403
    app.post(f"/api/admin/appointments/{aid}/clinic-status",
             json={"status": "clinic_confirmed", "note": "Arrive 10 min early"}, headers=H(admin))
    mine = app.get("/api/appointments", headers=H(user)).json()["appointments"][0]
    assert mine["clinic_status"] == "clinic_confirmed" and mine["clinic_note"] == "Arrive 10 min early"
    notes = app.get("/api/notifications", headers=H(user)).json()["notifications"]
    assert any("confirmed your appointment" in (n["body"] or "") for n in notes)


def test_contact_not_shared_unless_chosen_and_decline_frees_slot(app, monkeypatch):
    admin = _admin(app, monkeypatch)
    user = register(app, "m@x.org")
    pid = app.post("/api/admin/providers", json={"provider_name": "Dr B", "profession": "Psychologist"},
                   headers=H(admin)).json()["provider_id"]
    app.post(f"/api/admin/providers/{pid}/verify", json={"note": "RCI number checked"}, headers=H(admin))
    s, e = _future(days=3)
    sid = app.post(f"/api/admin/providers/{pid}/slots", json={"start_time": s, "end_time": e},
                   headers=H(admin)).json()["slot_id"]
    aid = app.post("/api/appointments", json={"slot_id": sid, "contact_phone": "123"},
                   headers=H(user)).json()["appointment_id"]
    app.post(f"/api/appointments/{aid}/approve?explicit_approval=true", headers=H(user))
    row = app.get("/api/admin/appointments", headers=H(admin)).json()["appointments"][0]
    assert row["requester_phone"] is None and not row["share_contact"]
    app.post(f"/api/admin/appointments/{aid}/clinic-status", json={"status": "clinic_declined"},
             headers=H(admin))
    assert app.get("/api/appointments", headers=H(user)).json()["appointments"][0]["booking_status"] == "cancelled"
    assert app.get(f"/api/providers/slots?provider_id={pid}", headers=H(user)).json()["count"] == 1


def test_minor_cannot_book_directly(app):
    kid = register(app, "kid@x.org", minor=True)
    assert app.post("/api/appointments", json={"slot_id": 1}, headers=H(kid)).status_code == 403


# ------------------------------------------------------------------ clinics outside NeuroBridge
def test_outside_requests_are_private_and_drafted(app):
    a, b = register(app, "a@x.org"), register(app, "b@x.org")
    r = app.post("/api/outside-requests", json={"clinic_name": "Sunrise Mind Clinic", "profession": "Psychiatrist",
                                                "phone": "+91 99999 00000", "preferred_times": "weekday mornings",
                                                "source_url": "https://sunrise.example.org"},
                 headers=H(a)).json()
    assert "psychiatrist" in r["draft_message"] and "weekday mornings" in r["draft_message"]
    rid = r["request_id"]
    assert app.get("/api/appointments", headers=H(b)).json()["outside_requests"] == []
    assert app.patch(f"/api/outside-requests/{rid}", json={"status": "contacted"}, headers=H(b)).status_code == 404
    assert app.patch(f"/api/outside-requests/{rid}", json={"status": "nonsense"}, headers=H(a)).status_code == 400
    app.patch(f"/api/outside-requests/{rid}", json={"status": "contacted", "notes": "Called, call back Monday"},
              headers=H(a))
    mine = app.get("/api/appointments", headers=H(a)).json()["outside_requests"][0]
    assert mine["status"] == "contacted" and mine["notes"].startswith("Called")
    assert app.delete(f"/api/outside-requests/{rid}", headers=H(b)).status_code == 404
    assert app.delete(f"/api/outside-requests/{rid}", headers=H(a)).status_code == 200


def test_account_deletion_removes_outside_requests(app, store):
    a = register(app, "a@x.org")
    app.post("/api/outside-requests", json={"clinic_name": "Clinic X"}, headers=H(a))
    assert store.list_outside_requests(f"u{a['_id']}")["requests"]
    app.request("DELETE", "/api/me", json={"password": PW}, headers=H(a))
    assert store.list_outside_requests(f"u{a['_id']}")["requests"] == []


def test_assistant_endpoint_books_psychiatrist_with_owner_approval(app, store, psychiatrist):
    a, b = register(app, "a@x.org"), register(app, "b@x.org")
    r = app.post("/api/assistant/message", json={"message": "Find a psychiatrist in Panaji and book an appointment",
                                                 "mode": "agent", "allow_actions": True}, headers=H(a)).json()
    assert r["meta"]["status"] == "WAITING_APPROVAL"
    ap = r["meta"]["approvals"][0]
    assert ap.get("summary", {}).get("provider") == "Dr Asha Kamat"
    assert app.post(f"/api/assistant/runs/{r['meta']['run_id']}/approve",
                    json={"approval_id": ap["approval_id"], "approved": True}, headers=H(b)).status_code == 404
    app.post(f"/api/assistant/runs/{r['meta']['run_id']}/approve",
             json={"approval_id": ap["approval_id"], "approved": True}, headers=H(a))
    appts = app.get("/api/appointments", headers=H(a)).json()["appointments"]
    assert appts and appts[0]["provider_name"] == "Dr Asha Kamat"
    assert appts[0]["clinic_status"] == "awaiting_clinic"


def test_agent_prefers_real_listing_and_specialty_over_earlier_demo(store, psychiatrist):
    d = store.register_provider("Demo Psychiatry (demo listing)", "Psychiatrist", location="Panaji, Goa",
                                specialties=["sleep"], is_demo=True)
    store.verify_provider(d["provider_id"], note="demo")
    s, e = _future(days=1)                      # earlier than the real listing's slot
    store.add_availability(d["provider_id"], s, e)
    agent, *_ = make_agent(store=store)
    r = agent.run("Find a psychiatrist in Panaji for adult ADHD and book an appointment", user_id="u1",
                  granted_permissions={"booking:write"})
    assert r["approvals"][0]["summary"]["provider"] == "Dr Asha Kamat"
    assert not r["approvals"][0]["summary"]["demo_listing"]
    assert store.search_providers(profession="psychiatrist")["providers"][0]["provider_name"] == "Dr Asha Kamat"
