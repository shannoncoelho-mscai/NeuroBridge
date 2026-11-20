"""Web application tests: accounts, roles, data isolation, consent, privacy, community safety,
assistant (chat + agent + safety + approvals), notifications, bookings, deletion."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fakes import make_gateway, FakeSearch, FakeReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
PW = "Correct-horse-9"


@pytest.fixture
def events(tmp_path):
    from agent.tools.events_db import EventStore
    from seed_demo_events import seed
    s = EventStore(tmp_path / "events.sqlite3")
    seed(s)
    return s


@pytest.fixture
def app(tmp_path, store, events):
    import agent.api.app as api
    import nbapp
    from nbapp.security import limiter
    from agent.tools.builtin import build_tool_registry
    limiter.reset()
    nbapp.setup_database(tmp_path / "app.sqlite3")
    gw, llm = make_gateway()
    reg = build_tool_registry(booking_store=store, search_fn=FakeSearch(), reader_fn=FakeReader(),
                              event_store=events)
    api.initialize(gw, tools=reg, store=store, events=events, agent_options={"retry_backoff": 0})
    c = TestClient(api.app)
    c.llm = llm
    return c


def register(c, email, role="individual", name=None, minor=False):
    r = c.post("/api/auth/register", json={"email": email, "password": PW, "role": role,
                                           "display_name": name or email.split("@")[0],
                                           "is_minor": minor})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"], "_id": r.json()["user"]["id"]}


def H(h):
    return {"Authorization": h["Authorization"]}


def link(c, ind, care, scopes=()):
    c.post("/api/circle/invite", json={"email": "care@x.org"}, headers=H(ind))
    lid = c.get("/api/circle", headers=H(care)).json()["links"][0]["id"]
    assert c.post(f"/api/circle/{lid}", json={"action": "accept"}, headers=H(care)).status_code == 200
    for s in scopes:
        assert c.put(f"/api/circle/{lid}/scopes/{s}", json={"state": "granted"},
                     headers=H(ind)).status_code == 200
    return lid


# ------------------------------------------------------------------ auth
def test_register_login_logout_and_password_rules(app):
    assert app.post("/api/auth/register", json={"email": "a@x.org", "password": "short", "role": "individual",
                                                "display_name": "A"}).status_code == 400
    h = register(app, "a@x.org")
    assert app.post("/api/auth/register", json={"email": "A@x.org", "password": PW, "role": "individual",
                                                "display_name": "A"}).status_code == 409
    assert app.post("/api/auth/login", json={"email": "a@x.org", "password": "wrong-pass-1"}).status_code == 401
    tok = app.post("/api/auth/login", json={"email": "a@x.org", "password": PW}).json()["token"]
    hh = {"Authorization": "Bearer " + tok}
    assert app.get("/api/me", headers=hh).json()["user"]["role"] == "individual"
    app.post("/api/auth/logout", headers=hh)
    assert app.get("/api/me", headers=hh).status_code == 401
    assert app.get("/api/me").status_code == 401
    assert app.get("/api/me", headers=H(h)).status_code == 200  # other session still valid


def test_admin_cannot_self_register_and_minor_cannot_be_caregiver(app):
    assert app.post("/api/auth/register", json={"email": "x@x.org", "password": PW, "role": "admin",
                                                "display_name": "X"}).status_code == 400
    assert app.post("/api/auth/register", json={"email": "y@x.org", "password": PW, "role": "caregiver",
                                                "display_name": "Y", "is_minor": True}).status_code == 400


def test_passwords_are_hashed_and_sessions_stored_hashed(app):
    import nbapp.state as st
    h = register(app, "a@x.org")
    row = st.db.one("SELECT password_hash FROM users WHERE email='a@x.org'")
    assert PW not in row["password_hash"] and row["password_hash"].startswith("pbkdf2_sha256$")
    token = h["Authorization"].split()[1]
    assert not st.db.one("SELECT 1 FROM sessions WHERE token_hash=?", (token,))


def test_login_rate_limited(app):
    register(app, "a@x.org")
    codes = [app.post("/api/auth/login", json={"email": "a@x.org", "password": "nope-nope-1"}).status_code
             for _ in range(10)]
    assert 429 in codes


# ------------------------------------------------------------------ isolation & roles
def test_users_cannot_touch_each_others_data(app):
    a, b = register(app, "a@x.org"), register(app, "b@x.org")
    t = app.post("/api/tasks", json={"title": "secret task"}, headers=H(a)).json()
    j = app.post("/api/journal", json={"body": "private thought"}, headers=H(a)).json()
    assert app.get("/api/tasks", headers=H(b)).json()["tasks"] == []
    assert app.patch(f"/api/tasks/{t['id']}", json={"status": "done"}, headers=H(b)).status_code == 404
    assert app.delete(f"/api/journal/{j['id']}", headers=H(b)).status_code == 404
    assert app.get("/api/journal", headers=H(b)).json()["entries"] == []


def test_caregiver_only_and_individual_only_routes(app):
    ind, care = register(app, "i@x.org"), register(app, "care@x.org", "caregiver")
    assert app.get("/api/care/dashboard", headers=H(ind)).status_code == 403
    assert app.post("/api/support-requests", json={"message": "hi"}, headers=H(care)).status_code == 403
    assert app.post("/api/care/journal", json={"what_happened": "x"}, headers=H(ind)).status_code == 403


# ------------------------------------------------------------------ consent
def test_link_grants_nothing_until_individual_shares(app):
    ind, care = register(app, "i@x.org"), register(app, "care@x.org", "caregiver")
    app.put("/api/blueprint/helps", json={"content": "headphones", "shared": True}, headers=H(ind))
    lid = link(app, ind, care)
    v = app.get(f"/api/shared/{ind['_id']}", headers=H(care)).json()
    assert v["sections"] == {} and v["scopes"] == []
    # caregiver cannot grant themselves access
    assert app.put(f"/api/circle/{lid}/scopes/blueprint", json={"state": "granted"},
                   headers=H(care)).status_code == 403
    app.put(f"/api/circle/{lid}/scopes/blueprint", json={"state": "requested"}, headers=H(care))
    assert app.get(f"/api/shared/{ind['_id']}", headers=H(care)).json()["sections"] == {}
    app.put(f"/api/circle/{lid}/scopes/blueprint", json={"state": "granted"}, headers=H(ind))
    bp = app.get(f"/api/shared/{ind['_id']}", headers=H(care)).json()["sections"]["blueprint"]
    assert [s["content"] for s in bp] == ["headphones"]
    hist = app.get(f"/api/circle/{lid}/history", headers=H(ind)).json()["records"]
    assert {r["action"] for r in hist} == {"requested", "granted"}


def test_only_items_marked_shared_are_visible(app):
    ind, care = register(app, "i@x.org"), register(app, "care@x.org", "caregiver")
    link(app, ind, care, ["blueprint", "tasks", "routines"])
    app.put("/api/blueprint/helps", json={"content": "shared bit", "shared": True}, headers=H(ind))
    app.put("/api/blueprint/boundaries", json={"content": "private bit", "shared": False}, headers=H(ind))
    app.post("/api/tasks", json={"title": "shared task", "shared": True}, headers=H(ind))
    app.post("/api/tasks", json={"title": "private task"}, headers=H(ind))
    s = app.get(f"/api/shared/{ind['_id']}", headers=H(care)).json()["sections"]
    assert [b["content"] for b in s["blueprint"]] == ["shared bit"]
    assert [t["title"] for t in s["tasks"]] == ["shared task"]


def test_revoking_and_disconnecting_stops_access(app):
    ind, care = register(app, "i@x.org"), register(app, "care@x.org", "caregiver")
    lid = link(app, ind, care, ["goals"])
    app.put(f"/api/circle/{lid}/scopes/goals", json={"state": "revoked"}, headers=H(ind))
    assert "goals" not in app.get(f"/api/shared/{ind['_id']}", headers=H(care)).json()["sections"]
    app.put(f"/api/circle/{lid}/scopes/goals", json={"state": "granted"}, headers=H(ind))
    app.post(f"/api/circle/{lid}", json={"action": "revoke"}, headers=H(ind))
    assert app.get(f"/api/shared/{ind['_id']}", headers=H(care)).status_code == 403


def test_journal_and_memory_are_never_shareable(app):
    ind, care = register(app, "i@x.org"), register(app, "care@x.org", "caregiver")
    lid = link(app, ind, care)
    for scope in ("journal", "memory", "conversations"):
        assert app.put(f"/api/circle/{lid}/scopes/{scope}", json={"state": "granted"},
                       headers=H(ind)).status_code == 400
    app.post("/api/journal", json={"body": "very private"}, headers=H(ind))
    assert app.get("/api/journal", headers=H(care)).json()["entries"] == []


def test_guardian_mode_for_minor(app):
    kid = register(app, "kid@x.org", minor=True)
    parent = register(app, "care@x.org", "caregiver")
    me = app.get("/api/me", headers=H(kid)).json()["user"]
    assert me["consent_mode"] == "guardian"
    assert app.put("/api/me/settings", json={"consent_mode": "self"}, headers=H(kid)).status_code == 403
    app.post("/api/circle/invite", json={"email": "kid@x.org", "is_guardian": True}, headers=H(parent))
    lid = app.get("/api/circle", headers=H(kid)).json()["links"][0]["id"]
    app.post(f"/api/circle/{lid}", json={"action": "accept"}, headers=H(kid))
    assert app.put(f"/api/circle/{lid}/scopes/calendar", json={"state": "granted"},
                   headers=H(parent)).status_code == 200
    # the young person sees the change
    assert app.get("/api/circle", headers=H(kid)).json()["links"][0]["permissions"]["calendar"] == "granted"
    # in supported mode the guardian can no longer grant
    app.put("/api/me/settings", json={"consent_mode": "supported"}, headers=H(kid))
    assert app.put(f"/api/circle/{lid}/scopes/goals", json={"state": "granted"},
                   headers=H(parent)).status_code == 403


def test_invite_does_not_reveal_whether_email_exists(app):
    ind = register(app, "i@x.org")
    a = app.post("/api/circle/invite", json={"email": "nobody@x.org"}, headers=H(ind)).json()
    register(app, "care@x.org", "caregiver")
    b = app.post("/api/circle/invite", json={"email": "care@x.org"}, headers=H(ind)).json()
    assert a == b


def test_support_request_reaches_only_active_circle_and_replies_come_back(app):
    ind, care = register(app, "i@x.org"), register(app, "care@x.org", "caregiver")
    other = register(app, "other@x.org", "caregiver")
    assert app.post("/api/support-requests", json={"message": "I need quiet."}, headers=H(ind)).status_code == 409
    link(app, ind, care)
    assert app.post("/api/support-requests", json={"message": "I need quiet."}, headers=H(ind)).json()["sent_to"] == 1
    reqs = app.get("/api/care/dashboard", headers=H(care)).json()["support_requests"]
    assert reqs[0]["message"] == "I need quiet."
    assert app.get("/api/care/dashboard", headers=H(other)).json()["support_requests"] == []
    app.patch(f"/api/support-requests/{reqs[0]['id']}", json={"status": "on_my_way"}, headers=H(care))
    notes = app.get("/api/notifications", headers=H(ind)).json()["notifications"]
    assert any("on the way" in n["title"] for n in notes)


def test_coordination_requires_scope(app):
    ind, care = register(app, "i@x.org"), register(app, "care@x.org", "caregiver")
    lid = link(app, ind, care)
    assert app.get(f"/api/care/coordination/{ind['_id']}", headers=H(care)).status_code == 403
    app.put(f"/api/circle/{lid}/scopes/coordination", json={"state": "granted"}, headers=H(ind))
    app.post("/api/care/tasks", json={"individual_id": ind["_id"], "title": "Pick up",
                                      "assignee_id": care["_id"]}, headers=H(care))
    c = app.get(f"/api/care/coordination/{ind['_id']}", headers=H(ind)).json()
    assert c["tasks"][0]["title"] == "Pick up" and c["open_task_load"]


def test_care_journal_private_by_default_and_patterns_avoid_causal_claims(app):
    ind, care = register(app, "i@x.org"), register(app, "care@x.org", "caregiver")
    link(app, ind, care)
    for vis in (False, True):
        app.post("/api/care/journal", json={"individual_id": ind["_id"], "what_happened": "upset",
                                            "context": "after school", "tags": ["noise"],
                                            "visible_to_individual": vis}, headers=H(care))
    assert len(app.get("/api/care/journal", headers=H(ind)).json()["entries"]) == 1
    pat = app.get("/api/care/journal/patterns", headers=H(care)).json()
    text = " ".join(pat["items"]).lower()
    assert "noise" in text and "caus" not in text and "because" not in text
    assert "not what caused" in pat["notice"]


# ------------------------------------------------------------------ personal features
def test_task_flow_steps_next_and_help_start(app):
    a = register(app, "a@x.org")
    t1 = app.post("/api/tasks", json={"title": "Big thing", "priority": 3}, headers=H(a)).json()
    t2 = app.post("/api/tasks", json={"title": "Urgent", "priority": 1}, headers=H(a)).json()
    assert app.get("/api/tasks/next", headers=H(a)).json()["task"]["id"] == t2["id"]
    r = app.post("/api/assistant/task-help", json={"task_id": t1["id"]}, headers=H(a)).json()
    assert r["source"] == "ai" and r["step"]
    steps = app.get("/api/tasks", headers=H(a)).json()["tasks"]
    assert any(s["source"] == "ai" for t in steps for s in t["steps"])


def test_help_start_without_ai_is_labelled_rule(app):
    import agent.api.app as api
    a = register(app, "a@x.org")
    t = app.post("/api/tasks", json={"title": "Laundry"}, headers=H(a)).json()
    gw = api.gateway
    api.gateway = None
    try:
        r = app.post("/api/assistant/task-help", json={"task_id": t["id"]}, headers=H(a)).json()
    finally:
        api.gateway = gw
    assert r["source"] == "rule" and "no AI" in r["note"]


def test_routines_templates_runs_and_no_streaks(app):
    a = register(app, "a@x.org")
    r = app.post("/api/routines", json={"name": "Morning", "template": "morning"}, headers=H(a)).json()
    assert len(r["steps"]) == 5
    run = app.post(f"/api/routines/{r['id']}/runs", headers=H(a)).json()
    msg = app.post(f"/api/routines/{r['id']}/runs/{run['run_id']}/finish",
                   json={"done_steps": 3, "skipped_steps": 2}, headers=H(a)).json()["message"]
    assert "fine" in msg and "streak" not in msg.lower()


def test_checkins_cards_blueprint_goals_sensory_calendar(app):
    a = register(app, "a@x.org")
    assert app.post("/api/checkins", json={"mood": 6}, headers=H(a)).status_code == 422
    app.post("/api/checkins", json={"mood": 3, "needs": ["Quiet"]}, headers=H(a))
    assert "not a diagnosis" in app.get("/api/checkins", headers=H(a)).json()["notice"]
    cards = app.get("/api/cards", headers=H(a)).json()["cards"]
    assert any(c["text"] == "I need a break." for c in cards)
    app.patch(f"/api/cards/{cards[0]['id']}", json={"favorite": True, "used": True}, headers=H(a))
    app.put("/api/blueprint/strengths", json={"content": "Pattern spotting"}, headers=H(a))
    assert "Pattern spotting" in app.get("/api/blueprint/export", headers=H(a)).json()["markdown"]
    assert app.put("/api/blueprint/nonsense", json={"content": "x"}, headers=H(a)).status_code == 404
    app.post("/api/goals", json={"title": "Cook once a week"}, headers=H(a))
    app.put("/api/sensory/strategies/headphones", json={"status": "liked", "used": True}, headers=H(a))
    s = app.get("/api/sensory", headers=H(a)).json()
    assert s["strategies"][0]["key"] == "headphones"
    app.post("/api/calendar", json={"title": "OT", "start_time": "2030-01-01T10:00:00"}, headers=H(a))
    ins = app.get("/api/insights", headers=H(a)).json()
    assert ins["helpful_strategies"] and "not causes" in ins["notice"]


# ------------------------------------------------------------------ community
def _profile(c, h, handle, open_=True):
    return c.put("/api/community/profile", json={"handle": handle, "open_to_connect": open_,
                                                 "accept_guidelines": True}, headers=H(h))


def test_community_requires_profile_and_guidelines(app):
    a = register(app, "a@x.org")
    gid = app.get("/api/community/groups", headers=H(a)).json()["groups"][0]["id"]
    assert app.post(f"/api/community/groups/{gid}/join", headers=H(a)).status_code == 428
    assert app.put("/api/community/profile", json={"handle": "asha_1"}, headers=H(a)).status_code == 400
    assert _profile(app, a, "asha_1").status_code == 200


def test_posts_with_personal_info_or_crisis_are_held(app):
    a, b = register(app, "a@x.org"), register(app, "b@x.org")
    _profile(app, a, "aaa"); _profile(app, b, "bbb")
    gid = [g for g in app.get("/api/community/groups", headers=H(a)).json()["groups"] if g["minor_safe"]][0]["id"]
    for h in (a, b):
        app.post(f"/api/community/groups/{gid}/join", headers=H(h))
    ok = app.post(f"/api/community/groups/{gid}/posts", json={"body": "Headphones help me"}, headers=H(a)).json()
    phone = app.post(f"/api/community/groups/{gid}/posts", json={"body": "call 98765 43210"}, headers=H(a)).json()
    crisis = app.post(f"/api/community/groups/{gid}/posts", json={"body": "I want to kill myself"}, headers=H(a)).json()
    assert ok["status"] == "visible" and phone["status"] == "held" and crisis["status"] == "held"
    assert "112" in crisis["message"]
    seen_by_b = [p["body"] for p in app.get(f"/api/community/groups/{gid}/posts", headers=H(b)).json()["posts"]]
    assert seen_by_b == ["Headphones help me"]
    seen_by_a = app.get(f"/api/community/groups/{gid}/posts", headers=H(a)).json()["posts"]
    assert len(seen_by_a) == 3  # author sees their own held posts


def test_minor_protections(app):
    kid, adult = register(app, "kid@x.org", minor=True), register(app, "ad@x.org")
    _profile(app, kid, "kiddo"); _profile(app, adult, "grownup")
    groups = app.get("/api/community/groups", headers=H(kid)).json()["groups"]
    adult_only = [g for g in groups if not g["minor_safe"]][0]
    assert not adult_only["can_join"]
    assert app.post(f"/api/community/groups/{adult_only['id']}/join", headers=H(kid)).status_code == 403
    assert app.get("/api/community/people", headers=H(kid)).json()["people"] == []
    assert all(p["handle"] != "kiddo" for p in app.get("/api/community/people", headers=H(adult)).json()["people"])
    assert app.post("/api/community/connections", json={"user_id": kid["_id"]}, headers=H(adult)).status_code == 403
    assert app.get(f"/api/community/messages/{adult['_id']}", headers=H(kid)).status_code == 403


def test_connections_messages_block_and_report(app):
    a, b = register(app, "a@x.org"), register(app, "b@x.org")
    _profile(app, a, "aaa"); _profile(app, b, "bbb")
    assert app.post(f"/api/community/messages/{b['_id']}", json={"body": "hi"}, headers=H(a)).status_code == 403
    app.post("/api/community/connections", json={"user_id": b["_id"]}, headers=H(a))
    cid = app.get("/api/community/connections", headers=H(b)).json()["connections"][0]["id"]
    app.post(f"/api/community/connections/{cid}?accept=true", headers=H(b))
    m = app.post(f"/api/community/messages/{b['_id']}", json={"body": "hello!"}, headers=H(a)).json()
    assert m["status"] == "visible"
    app.post("/api/community/reports", json={"target_type": "message", "target_id": m["message_id"],
                                             "reason": "Harassment"}, headers=H(b))
    assert app.get(f"/api/community/messages/{a['_id']}", headers=H(b)).json()["messages"] == []
    app.post("/api/community/blocks", json={"user_id": a["_id"]}, headers=H(b))
    assert app.post(f"/api/community/messages/{b['_id']}", json={"body": "?"}, headers=H(a)).status_code == 404
    assert all(p["user_id"] != b["_id"] for p in app.get("/api/community/people", headers=H(a)).json()["people"])


def test_three_reports_hold_a_post_and_only_moderators_act(app, monkeypatch):
    import nbapp
    import nbapp.state as st
    monkeypatch.setenv("NEUROBRIDGE_ADMIN_EMAIL", "admin@x.org")
    monkeypatch.setenv("NEUROBRIDGE_ADMIN_PASSWORD", PW)
    nbapp._bootstrap_admin(st.db)
    admin = {"Authorization": "Bearer " + app.post("/api/auth/login", json={"email": "admin@x.org", "password": PW}).json()["token"]}
    users = [register(app, f"u{i}@x.org") for i in range(4)]
    for i, u in enumerate(users):
        _profile(app, u, f"user_{i}")
    gid = [g for g in app.get("/api/community/groups", headers=H(users[0])).json()["groups"] if g["minor_safe"]][0]["id"]
    for u in users:
        app.post(f"/api/community/groups/{gid}/join", headers=H(u))
    pid = app.post(f"/api/community/groups/{gid}/posts", json={"body": "hello"}, headers=H(users[0])).json()["post_id"]
    for u in users[1:]:
        app.post("/api/community/reports", json={"target_type": "post", "target_id": pid, "reason": "Spam"}, headers=H(u))
    assert app.get(f"/api/community/groups/{gid}/posts", headers=H(users[1])).json()["posts"] == []
    assert app.post("/api/community/moderation", json={"target_type": "post", "target_id": pid,
                                                       "action": "approve"}, headers=H(users[1])).status_code == 403
    q = app.get("/api/community/moderation", headers=H(admin)).json()
    assert [p["id"] for p in q["held_posts"]] == [pid] and len(q["reports"]) == 3
    app.post("/api/community/moderation", json={"target_type": "post", "target_id": pid, "action": "approve"}, headers=H(admin))
    assert len(app.get(f"/api/community/groups/{gid}/posts", headers=H(users[1])).json()["posts"]) == 1


# ------------------------------------------------------------------ assistant
def test_assistant_routing():
    from nbapp.assistant import decide_mode
    assert decide_mode("I have to clean my room and I can't start.") == "chat"
    assert decide_mode("Help me write a message to my boss") == "chat"
    assert decide_mode("Find a child psychologist in Panjim") == "agent"
    assert decide_mode("What does the research say about body doubling? Give sources") == "agent"
    assert decide_mode("Find an online ADHD club and sign me up") == "agent"
    assert decide_mode("I feel sad today") == "chat"


def test_assistant_chat_saves_conversation_and_uses_only_permitted_context(app):
    ind, care = register(app, "i@x.org", name="Asha"), register(app, "care@x.org", "caregiver")
    app.put("/api/blueprint/helps", json={"content": "SECRET-PRIVATE-NOTE", "shared": False}, headers=H(ind))
    app.put("/api/blueprint/respond", json={"content": "SHARED-PREF", "shared": True}, headers=H(ind))
    lid = link(app, ind, care)
    r = app.post("/api/assistant/message", json={"message": "How can I help her today?", "mode": "chat",
                                                 "about_individual_id": ind["_id"]}, headers=H(care)).json()
    assert r["mode"] == "chat"
    sp = app.llm.calls[-1]["system_prompt"]
    assert "SHARED-PREF" not in sp and "SECRET-PRIVATE-NOTE" not in sp   # blueprint scope not granted
    app.put(f"/api/circle/{lid}/scopes/blueprint", json={"state": "granted"}, headers=H(ind))
    app.post("/api/assistant/message", json={"message": "And now?", "mode": "chat",
                                             "about_individual_id": ind["_id"]}, headers=H(care))
    sp = app.llm.calls[-1]["system_prompt"]
    assert "SHARED-PREF" in sp and "SECRET-PRIVATE-NOTE" not in sp
    convs = app.get("/api/assistant/conversations", headers=H(care)).json()["conversations"]
    assert len(convs) == 2
    assert app.get(f"/api/assistant/conversations/{convs[0]['id']}", headers=H(ind)).status_code == 404


def test_assistant_emergency_bypasses_llm(app):
    a = register(app, "a@x.org")
    n = len(app.llm.calls)
    r = app.post("/api/assistant/message", json={"message": "my dad is choking right now"}, headers=H(a)).json()
    assert r["mode"] == "safety" and "112" in r["reply"] and r["meta"]["llm_called"] is False
    assert len(app.llm.calls) == n


def test_assistant_agent_research_returns_sources(app):
    a = register(app, "a@x.org")
    r = app.post("/api/assistant/message", json={"message": "Research caregiver stress coping strategies with sources",
                                                 "mode": "agent"}, headers=H(a)).json()
    assert r["mode"] == "agent" and r["sources"] and r["meta"]["activity"]
    msgs = app.get(f"/api/assistant/conversations/{r['conversation_id']}", headers=H(a)).json()["messages"]
    assert msgs[-1]["sources"]


def test_assistant_booking_needs_owner_approval_and_lands_in_my_events(app, events):
    a, b = register(app, "a@x.org"), register(app, "b@x.org")
    r = app.post("/api/assistant/message", json={"message": "Find an online ADHD club and sign me up",
                                                 "mode": "agent", "allow_actions": True}, headers=H(a)).json()
    assert r["meta"]["status"] == "WAITING_APPROVAL"
    ap = r["meta"]["approvals"][0]
    assert app.get("/api/events-mine", headers=H(a)).json()["count"] == 0
    # another user cannot approve it
    assert app.post(f"/api/assistant/runs/{r['meta']['run_id']}/approve",
                    json={"approval_id": ap["approval_id"], "approved": True}, headers=H(b)).status_code == 404
    r2 = app.post(f"/api/assistant/runs/{r['meta']['run_id']}/approve",
                  json={"approval_id": ap["approval_id"], "approved": True}, headers=H(a)).json()
    assert r2["meta"]["status"] == "COMPLETED"
    regs = app.get("/api/events-mine", headers=H(a)).json()["registrations"]
    assert regs and regs[0]["status"] == "confirmed"


def test_assistant_without_permission_does_not_book(app):
    a = register(app, "a@x.org")
    r = app.post("/api/assistant/message", json={"message": "Find an online ADHD club and sign me up",
                                                 "mode": "agent"}, headers=H(a)).json()
    if r["meta"]["status"] == "WAITING_APPROVAL":
        ap = r["meta"]["approvals"][0]
        app.post(f"/api/assistant/runs/{r['meta']['run_id']}/approve",
                 json={"approval_id": ap["approval_id"], "approved": True}, headers=H(a))
    assert app.get("/api/events-mine", headers=H(a)).json()["count"] == 0


def test_memory_respects_switch_and_isolation(app):
    a, b = register(app, "a@x.org"), register(app, "b@x.org")
    cid = app.post("/api/assistant/message", json={"message": "I prefer short answers", "mode": "chat"},
                   headers=H(a)).json()["conversation_id"]
    cand = [{"key": "style", "value": "short answers", "category": "communication"}]
    assert app.post("/api/assistant/memory/save", json={"candidates": cand, "approved_keys": []},
                    headers=H(a)).json()["saved"] == []
    assert app.post("/api/assistant/memory/save", json={"candidates": cand, "approved_keys": ["style"]},
                    headers=H(a)).json()["saved"] == ["style"]
    assert app.get("/api/assistant/memory", headers=H(b)).json()["memories"] == []
    assert app.get("/api/assistant/memory", headers=H(a)).json()["memories"]
    app.put("/api/me/settings", json={"prefs": {"memory_enabled": False}}, headers=H(a))
    assert app.post("/api/assistant/memory/suggest", json={"conversation_id": cid}, headers=H(a)).status_code == 409
    app.post("/api/assistant/message", json={"message": "hi", "mode": "chat", "conversation_id": cid}, headers=H(a))
    assert "short answers" not in app.llm.calls[-1]["system_prompt"]


def test_sensitive_memory_needs_separate_approval(app):
    a = register(app, "a@x.org")
    cand = [{"key": "diagnosis", "value": "has an autism diagnosis", "sensitive": True}]
    r = app.post("/api/assistant/memory/save", json={"candidates": cand, "approved_keys": ["diagnosis"]},
                 headers=H(a)).json()
    assert r["saved"] == [] and r["rejected"]


# ------------------------------------------------------------------ events & appointments via /api
def test_event_booking_is_bound_to_signed_in_user_and_exact_details(app, events):
    a = register(app, "a@x.org")
    ev = app.get("/api/events", headers=H(a)).json()["events"][0]
    prep = app.get(f"/api/events/{ev['event_id']}/prepare", headers=H(a)).json()
    assert app.post(f"/api/events/{ev['event_id']}/register", json={"approved_details_hash": prep["details_hash"]},
                    headers=H(a)).status_code == 403
    events.update_event(ev["event_id"], location="Somewhere else")
    stale = app.post(f"/api/events/{ev['event_id']}/register", json={"approved_details_hash": prep["details_hash"],
                                                                     "explicit_approval": True}, headers=H(a))
    assert stale.status_code == 409 and stale.json()["detail"]["approval_stale"]
    prep = app.get(f"/api/events/{ev['event_id']}/prepare", headers=H(a)).json()
    ok = app.post(f"/api/events/{ev['event_id']}/register", json={"approved_details_hash": prep["details_hash"],
                                                                  "explicit_approval": True}, headers=H(a)).json()
    assert ok["status"] == "confirmed"
    assert events.my_registrations(f"u{a['_id']}")["count"] == 1


def test_proposed_events_wait_for_admin_review(app):
    a = register(app, "a@x.org")
    r = app.post("/api/events/propose", json={"title": "Lego club", "event_type": "club",
                                              "start_time": "2030-02-01T16:00:00",
                                              "end_time": "2030-02-01T18:00:00", "capacity": 8},
                 headers=H(a)).json()
    assert r["status"] == "pending_review"
    assert all(e["title"] != "Lego club" for e in app.get("/api/events", headers=H(a)).json()["events"])
    assert app.get("/api/admin/events/pending", headers=H(a)).status_code == 403


def test_appointment_request_then_explicit_confirm(app, verified_provider):
    a = register(app, "care@x.org", "caregiver")
    r = app.post("/api/appointments", json={"slot_id": verified_provider["slot_id"]}, headers=H(a)).json()
    assert r["booking_status"] == "pending_approval"
    assert app.post(f"/api/appointments/{r['appointment_id']}/approve", headers=H(a)).status_code == 409
    ok = app.post(f"/api/appointments/{r['appointment_id']}/approve?explicit_approval=true", headers=H(a)).json()
    assert ok["booking_status"] == "confirmed" and ok["confirmation_code"]
    other = register(app, "x@x.org", "caregiver")
    assert app.get("/api/appointments", headers=H(other)).json()["appointments"] == []


# ------------------------------------------------------------------ notifications, export, deletion
def test_quiet_hours_window_wraps_midnight():
    from datetime import datetime
    from nbapp.notify import in_quiet_hours
    assert in_quiet_hours({"quiet_start": "21:30", "quiet_end": "07:30"}, datetime(2030, 1, 1, 23, 0))
    assert not in_quiet_hours({"quiet_start": "21:30", "quiet_end": "07:30"}, datetime(2030, 1, 1, 12, 0))


def test_notifications_settings_enforced(app):
    import nbapp.state as st
    from nbapp.notify import notify
    a = register(app, "a@x.org")
    app.put("/api/me/settings", json={"prefs": {"notifications": {"disabled": ["community"], "max_per_day": 2,
                                                                  "quiet_start": "00:00", "quiet_end": "00:00"}}},
            headers=H(a))
    assert notify(st.db, a["_id"], "community", "x") is None
    ids = [notify(st.db, a["_id"], "task", f"t{i}") for i in range(4)]
    assert ids[2] is None and ids[3] is None
    assert all(notify(st.db, a["_id"], "support_request", f"s{i}") for i in range(5))


def test_export_and_secure_delete(app):
    import nbapp.state as st
    a = register(app, "a@x.org")
    app.post("/api/journal", json={"body": "to be deleted"}, headers=H(a))
    ex = app.get("/api/me/export", headers=H(a)).json()
    assert ex["journal_entries"][0]["body"] == "to be deleted" and "password_hash" not in str(ex["user"])
    assert app.request("DELETE", "/api/me", json={"password": "wrong-pass-1"}, headers=H(a)).status_code == 401
    assert app.request("DELETE", "/api/me", json={"password": PW}, headers=H(a)).json()["deleted"]
    assert st.db.one("SELECT COUNT(*) n FROM journal_entries")["n"] == 0
    assert app.get("/api/me", headers=H(a)).status_code == 401


def test_web_app_served_and_legacy_api_can_be_disabled(app, monkeypatch):
    page = app.get("/app")
    assert page.status_code == 200 and "NeuroBridge" in page.text
    assert app.get("/app-static/app.js").status_code == 200
    monkeypatch.setenv("NEUROBRIDGE_DISABLE_LEGACY_API", "1")
    assert app.post("/chat", json={"message": "hi"}).status_code == 404
    assert app.get("/api/status").status_code == 200
