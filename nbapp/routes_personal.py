"""Individual support: My Day, tasks, routines, check-ins, journal, communication cards,
Support Blueprint, goals, sensory toolkit, calendar, focus sessions, insights.

Every query is filtered by owner_id = current user. Caregiver views of shared items live in
routes_care.py and go through consent.can_view().
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from nbapp import content
from nbapp.db import now
from nbapp.security import current_user, get_db

router = APIRouter(prefix="/api", tags=["personal"])


def _owned(db, table, item_id, user, col="owner_id"):
    row = db.one(f"SELECT * FROM {table} WHERE id=?", (item_id,))
    if not row or row[col] != user["id"]:
        raise HTTPException(status_code=404, detail="Not found")
    return row


def _today():
    return datetime.now().date().isoformat()


# ----------------------------------------------------------------------------- tasks
class TaskBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=4000)
    priority: int = Field(default=2, ge=1, le=3)
    due_date: Optional[str] = None
    estimate_min: Optional[int] = Field(default=None, ge=1, le=1440)
    plan_date: Optional[str] = None
    shared: bool = False
    steps: List[str] = Field(default_factory=list)


class TaskPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=4000)
    status: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=1, le=3)
    due_date: Optional[str] = None
    estimate_min: Optional[int] = None
    plan_date: Optional[str] = None
    position: Optional[int] = None
    shared: Optional[bool] = None


class StepBody(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    source: str = "user"


def task_with_steps(db, task):
    task["steps"] = db.all("SELECT * FROM task_steps WHERE task_id=? ORDER BY position, id",
                           (task["id"],))
    task["shared"] = bool(task["shared"])
    return task


@router.get("/tasks")
def list_tasks(status: Optional[str] = None, user=Depends(current_user), db=Depends(get_db)):
    sql, params = "SELECT * FROM tasks WHERE owner_id=?", [user["id"]]
    if status:
        sql += " AND status=?"
        params.append(status)
    rows = db.all(sql + " ORDER BY status='done', position, priority, due_date IS NULL, due_date, id",
                  params)
    return {"tasks": [task_with_steps(db, t) for t in rows]}


@router.post("/tasks")
def create_task(body: TaskBody, user=Depends(current_user), db=Depends(get_db)):
    ts = now()
    tid = db.insert("tasks", owner_id=user["id"], title=body.title.strip(), notes=body.notes,
                    priority=body.priority, due_date=body.due_date,
                    estimate_min=body.estimate_min, plan_date=body.plan_date,
                    shared=int(body.shared), created_at=ts, updated_at=ts)
    for i, s in enumerate(body.steps[:30]):
        db.insert("task_steps", task_id=tid, text=s[:300], position=i)
    return task_with_steps(db, db.one("SELECT * FROM tasks WHERE id=?", (tid,)))


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskPatch, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "tasks", task_id, user)
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if "status" in changes:
        if changes["status"] not in ("todo", "doing", "done", "skipped", "later"):
            raise HTTPException(status_code=400, detail="Unknown status")
        changes["completed_at"] = now() if changes["status"] == "done" else None
    if "shared" in changes:
        changes["shared"] = int(changes["shared"])
    changes["updated_at"] = now()
    db.update("tasks", "id=?", (task_id,), **changes)
    return task_with_steps(db, db.one("SELECT * FROM tasks WHERE id=?", (task_id,)))


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "tasks", task_id, user)
    db.run("DELETE FROM tasks WHERE id=?", (task_id,))
    return {"deleted": True}


@router.post("/tasks/{task_id}/steps")
def add_step(task_id: int, body: StepBody, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "tasks", task_id, user)
    pos = db.one("SELECT COALESCE(MAX(position),-1)+1 p FROM task_steps WHERE task_id=?",
                 (task_id,))["p"]
    db.insert("task_steps", task_id=task_id, text=body.text, position=pos,
              source=body.source if body.source in ("user", "ai", "rule") else "user")
    return task_with_steps(db, db.one("SELECT * FROM tasks WHERE id=?", (task_id,)))


@router.patch("/tasks/{task_id}/steps/{step_id}")
def toggle_step(task_id: int, step_id: int, done: bool = True, user=Depends(current_user),
                db=Depends(get_db)):
    _owned(db, "tasks", task_id, user)
    db.update("task_steps", "id=? AND task_id=?", (step_id, task_id), done=int(done))
    return task_with_steps(db, db.one("SELECT * FROM tasks WHERE id=?", (task_id,)))


@router.delete("/tasks/{task_id}/steps/{step_id}")
def delete_step(task_id: int, step_id: int, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "tasks", task_id, user)
    db.run("DELETE FROM task_steps WHERE id=? AND task_id=?", (step_id, task_id))
    return task_with_steps(db, db.one("SELECT * FROM tasks WHERE id=?", (task_id,)))


def pick_next_task(tasks, today=None):
    """Deterministic 'what next?': open tasks only; overdue/due-today first, then high
    priority, then the smallest estimate (easier to start). Returns (task, reason)."""
    today = today or _today()
    open_tasks = [t for t in tasks if t["status"] in ("todo", "doing")]
    if not open_tasks:
        return None, "You have nothing open right now. That's OK."

    def key(t):
        due = t.get("due_date") or "9999"
        return (0 if t["status"] == "doing" else 1, 0 if due <= today else 1, t["priority"],
                t.get("estimate_min") or 30, t["id"])
    t = sorted(open_tasks, key=key)[0]
    if t["status"] == "doing":
        reason = "You already started this one."
    elif (t.get("due_date") or "9999") <= today:
        reason = "This one is due today or earlier."
    elif t["priority"] == 1:
        reason = "You marked this as important."
    else:
        reason = "This looks like a small one to start with."
    return t, reason


@router.get("/tasks/next")
def next_task(user=Depends(current_user), db=Depends(get_db)):
    rows = db.all("SELECT * FROM tasks WHERE owner_id=?", (user["id"],))
    t, reason = pick_next_task(rows)
    return {"task": task_with_steps(db, t) if t else None, "reason": reason}


# ----------------------------------------------------------------------------- my day
@router.get("/myday")
def my_day(user=Depends(current_user), db=Depends(get_db)):
    today = _today()
    tasks = db.all("SELECT * FROM tasks WHERE owner_id=? AND (plan_date=? OR (due_date<=? AND "
                   "status IN ('todo','doing')) OR (status='doing')) ORDER BY position, priority",
                   (user["id"], today, today))
    done_today = db.all("SELECT id, title FROM tasks WHERE owner_id=? AND status='done' AND "
                        "substr(completed_at,1,10)=?", (user["id"], today))
    events = db.all("SELECT * FROM calendar_events WHERE owner_id=? AND substr(start_time,1,10)"
                    " BETWEEN ? AND ? ORDER BY start_time",
                    (user["id"], today, (datetime.now().date() + timedelta(days=7)).isoformat()))
    routines = db.all("SELECT * FROM routines WHERE owner_id=? ORDER BY reminder_time IS NULL, "
                      "reminder_time", (user["id"],))
    last_checkin = db.one("SELECT * FROM checkins WHERE owner_id=? ORDER BY created_at DESC "
                          "LIMIT 1", (user["id"],))
    nxt, reason = pick_next_task(db.all("SELECT * FROM tasks WHERE owner_id=?", (user["id"],)))
    return {"date": today, "tasks": [task_with_steps(db, t) for t in tasks],
            "accomplishments": done_today, "events": events, "routines": routines,
            "last_checkin": last_checkin,
            "suggested_next": {"task": nxt, "reason": reason} if nxt else None}


# ----------------------------------------------------------------------------- routines
class RoutineStep(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    minutes: Optional[int] = Field(default=None, ge=0, le=600)
    optional: bool = False
    alternative: Optional[str] = Field(default=None, max_length=200)
    symbol: Optional[str] = Field(default=None, max_length=8)


class RoutineBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = "custom"
    reminder_time: Optional[str] = None
    shared: bool = False
    steps: List[RoutineStep] = Field(default_factory=list)
    template: Optional[str] = None


def routine_full(db, r):
    r["steps"] = db.all("SELECT * FROM routine_steps WHERE routine_id=? ORDER BY position, id",
                        (r["id"],))
    r["shared"] = bool(r["shared"])
    r["runs"] = db.one("SELECT COUNT(*) n, SUM(finished_at IS NOT NULL) finished FROM "
                       "routine_runs WHERE routine_id=?", (r["id"],))
    return r


@router.get("/routines/templates")
def routine_templates():
    return {"templates": [{"key": k, "name": n, "steps": [{"text": t, "minutes": m} for t, m in s]}
                          for k, (n, s) in content.ROUTINE_TEMPLATES.items()]}


@router.get("/routines")
def list_routines(user=Depends(current_user), db=Depends(get_db)):
    return {"routines": [routine_full(db, r) for r in
                         db.all("SELECT * FROM routines WHERE owner_id=? ORDER BY id",
                                (user["id"],))]}


def _write_steps(db, rid, steps):
    db.run("DELETE FROM routine_steps WHERE routine_id=?", (rid,))
    for i, s in enumerate(steps[:40]):
        db.insert("routine_steps", routine_id=rid, position=i, text=s.text, minutes=s.minutes,
                  optional=int(s.optional), alternative=s.alternative, symbol=s.symbol)


@router.post("/routines")
def create_routine(body: RoutineBody, user=Depends(current_user), db=Depends(get_db)):
    steps = body.steps
    kind = body.kind
    if body.template:
        if body.template not in content.ROUTINE_TEMPLATES:
            raise HTTPException(status_code=400, detail="Unknown template")
        _, tsteps = content.ROUTINE_TEMPLATES[body.template]
        steps = steps or [RoutineStep(text=t, minutes=m) for t, m in tsteps]
        kind = body.template
    rid = db.insert("routines", owner_id=user["id"], name=body.name, kind=kind,
                    reminder_time=body.reminder_time, shared=int(body.shared), created_at=now())
    _write_steps(db, rid, steps)
    return routine_full(db, db.one("SELECT * FROM routines WHERE id=?", (rid,)))


@router.put("/routines/{rid}")
def replace_routine(rid: int, body: RoutineBody, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "routines", rid, user)
    db.update("routines", "id=?", (rid,), name=body.name, reminder_time=body.reminder_time,
              shared=int(body.shared))
    _write_steps(db, rid, body.steps)
    return routine_full(db, db.one("SELECT * FROM routines WHERE id=?", (rid,)))


@router.delete("/routines/{rid}")
def delete_routine(rid: int, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "routines", rid, user)
    db.run("DELETE FROM routines WHERE id=?", (rid,))
    return {"deleted": True}


class RunFinish(BaseModel):
    done_steps: int = Field(ge=0)
    skipped_steps: int = Field(default=0, ge=0)


@router.post("/routines/{rid}/runs")
def start_run(rid: int, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "routines", rid, user)
    return {"run_id": db.insert("routine_runs", routine_id=rid, owner_id=user["id"],
                                started_at=now())}


@router.post("/routines/{rid}/runs/{run_id}/finish")
def finish_run(rid: int, run_id: int, body: RunFinish, user=Depends(current_user),
               db=Depends(get_db)):
    run = _owned(db, "routine_runs", run_id, user)
    if run["routine_id"] != rid:
        raise HTTPException(status_code=404, detail="Not found")
    db.update("routine_runs", "id=?", (run_id,), finished_at=now(), done_steps=body.done_steps,
              skipped_steps=body.skipped_steps)
    # No streaks, no scores: just a kind acknowledgement.
    n = body.done_steps
    msg = f"Nice. You did {n} step{'s' if n != 1 else ''}."
    if body.skipped_steps:
        msg += " Skipping steps is completely fine."
    return {"message": msg}


# ----------------------------------------------------------------------------- check-ins
class CheckinBody(BaseModel):
    mood: Optional[int] = Field(default=None, ge=1, le=5)
    energy: Optional[int] = Field(default=None, ge=1, le=5)
    stress: Optional[int] = Field(default=None, ge=1, le=5)
    sensory: Optional[int] = Field(default=None, ge=1, le=5)
    social: Optional[int] = Field(default=None, ge=1, le=5)
    sleep: Optional[int] = Field(default=None, ge=1, le=5)
    overwhelmed: Optional[bool] = None
    needs: List[str] = Field(default_factory=list)
    note: Optional[str] = Field(default=None, max_length=2000)


@router.post("/checkins")
def create_checkin(body: CheckinBody, user=Depends(current_user), db=Depends(get_db)):
    d = body.model_dump()
    d["needs"] = json.dumps(d["needs"][:10])
    d["overwhelmed"] = None if d["overwhelmed"] is None else int(d["overwhelmed"])
    cid = db.insert("checkins", owner_id=user["id"], created_at=now(), **d)
    return db.one("SELECT * FROM checkins WHERE id=?", (cid,))


@router.get("/checkins")
def list_checkins(days: int = Query(default=30, ge=1, le=365), user=Depends(current_user),
                  db=Depends(get_db)):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = db.all("SELECT * FROM checkins WHERE owner_id=? AND created_at>=? ORDER BY created_at",
                  (user["id"], since))
    for r in rows:
        r["needs"] = json.loads(r["needs"] or "[]")
    return {"checkins": rows, "notice": "These are your own notes over time, not a diagnosis."}


@router.delete("/checkins/{cid}")
def delete_checkin(cid: int, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "checkins", cid, user)
    db.run("DELETE FROM checkins WHERE id=?", (cid,))
    return {"deleted": True}


# ----------------------------------------------------------------------------- journal
class JournalBody(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    kind: str = Field(default="thought", max_length=30)
    tags: List[str] = Field(default_factory=list)


@router.get("/journal")
def list_journal(q: Optional[str] = None, tag: Optional[str] = None, user=Depends(current_user),
                 db=Depends(get_db)):
    sql, params = "SELECT * FROM journal_entries WHERE owner_id=?", [user["id"]]
    if q:
        sql += " AND (body LIKE ? OR title LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    rows = db.all(sql + " ORDER BY created_at DESC", params)
    for r in rows:
        r["tags"] = json.loads(r["tags"] or "[]")
    if tag:
        rows = [r for r in rows if tag in r["tags"]]
    return {"entries": rows, "privacy": "Your journal is private. It is never shared with your "
                                        "circle and there is no setting that shares it."}


@router.post("/journal")
def create_journal(body: JournalBody, user=Depends(current_user), db=Depends(get_db)):
    ts = now()
    jid = db.insert("journal_entries", owner_id=user["id"], title=body.title, body=body.body,
                    kind=body.kind, tags=json.dumps([t.strip()[:30] for t in body.tags[:10] if
                                                     t.strip()]), created_at=ts, updated_at=ts)
    return db.one("SELECT * FROM journal_entries WHERE id=?", (jid,))


@router.put("/journal/{jid}")
def update_journal(jid: int, body: JournalBody, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "journal_entries", jid, user)
    db.update("journal_entries", "id=?", (jid,), title=body.title, body=body.body, kind=body.kind,
              tags=json.dumps(body.tags[:10]), updated_at=now())
    return db.one("SELECT * FROM journal_entries WHERE id=?", (jid,))


@router.delete("/journal/{jid}")
def delete_journal(jid: int, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "journal_entries", jid, user)
    db.run("DELETE FROM journal_entries WHERE id=?", (jid,))
    return {"deleted": True}


# ----------------------------------------------------------------------------- cards
class CardBody(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    category: str = Field(default="My cards", max_length=40)
    symbol: Optional[str] = Field(default=None, max_length=8)


class CardPatch(BaseModel):
    favorite: Optional[bool] = None
    hidden: Optional[bool] = None
    text: Optional[str] = Field(default=None, max_length=200)
    category: Optional[str] = Field(default=None, max_length=40)
    symbol: Optional[str] = Field(default=None, max_length=8)
    used: Optional[bool] = None


@router.get("/cards")
def list_cards(user=Depends(current_user), db=Depends(get_db)):
    return {"cards": db.all("SELECT * FROM comm_cards WHERE owner_id=? ORDER BY favorite DESC, "
                            "category, position, id", (user["id"],))}


@router.post("/cards")
def create_card(body: CardBody, user=Depends(current_user), db=Depends(get_db)):
    cid = db.insert("comm_cards", owner_id=user["id"], text=body.text, category=body.category,
                    symbol=body.symbol, position=999)
    return db.one("SELECT * FROM comm_cards WHERE id=?", (cid,))


@router.patch("/cards/{cid}")
def update_card(cid: int, body: CardPatch, user=Depends(current_user), db=Depends(get_db)):
    card = _owned(db, "comm_cards", cid, user)
    changes = {k: (int(v) if isinstance(v, bool) else v) for k, v in body.model_dump().items()
               if v is not None and k != "used"}
    if body.used:
        changes["uses"] = card["uses"] + 1
    db.update("comm_cards", "id=?", (cid,), **changes)
    return db.one("SELECT * FROM comm_cards WHERE id=?", (cid,))


@router.delete("/cards/{cid}")
def delete_card(cid: int, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "comm_cards", cid, user)
    db.run("DELETE FROM comm_cards WHERE id=?", (cid,))
    return {"deleted": True}


# ----------------------------------------------------------------------------- blueprint
class BlueprintBody(BaseModel):
    content: str = Field(default="", max_length=5000)
    shared: bool = False


def blueprint_for(db, owner_id, shared_only=False):
    rows = {r["section"]: r for r in db.all("SELECT * FROM blueprint_sections WHERE owner_id=?",
                                             (owner_id,))}
    out = []
    for key, title in content.BLUEPRINT_SECTIONS:
        r = rows.get(key)
        if shared_only and not (r and r["shared"]):
            continue
        out.append({"section": key, "title": title, "content": r["content"] if r else "",
                    "shared": bool(r["shared"]) if r else False,
                    "updated_at": r["updated_at"] if r else None})
    return out


@router.get("/blueprint")
def get_blueprint(user=Depends(current_user), db=Depends(get_db)):
    return {"sections": blueprint_for(db, user["id"])}


@router.put("/blueprint/{section}")
def put_blueprint(section: str, body: BlueprintBody, user=Depends(current_user),
                  db=Depends(get_db)):
    if section not in content.BLUEPRINT_KEYS:
        raise HTTPException(status_code=404, detail="Unknown section")
    with db.connect() as c:
        c.execute("INSERT INTO blueprint_sections (owner_id, section, content, shared, updated_at)"
                  " VALUES (?,?,?,?,?) ON CONFLICT(owner_id, section) DO UPDATE SET "
                  "content=excluded.content, shared=excluded.shared, updated_at=excluded.updated_at",
                  (user["id"], section, body.content, int(body.shared), now()))
    return {"sections": blueprint_for(db, user["id"])}


@router.get("/blueprint/export")
def export_blueprint(user=Depends(current_user), db=Depends(get_db)):
    lines = [f"# {user['display_name']} — My Support Blueprint", ""]
    for s in blueprint_for(db, user["id"]):
        if s["content"].strip():
            lines += [f"## {s['title']}", s["content"].strip(), ""]
    return {"markdown": "\n".join(lines)}


# ----------------------------------------------------------------------------- goals
class GoalBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    why: Optional[str] = Field(default=None, max_length=1000)
    next_step: Optional[str] = Field(default=None, max_length=300)
    status: str = "active"
    shared: bool = False


@router.get("/goals")
def list_goals(user=Depends(current_user), db=Depends(get_db)):
    return {"goals": db.all("SELECT * FROM goals WHERE owner_id=? ORDER BY status='active' DESC, "
                            "id DESC", (user["id"],))}


@router.post("/goals")
def create_goal(body: GoalBody, user=Depends(current_user), db=Depends(get_db)):
    ts = now()
    gid = db.insert("goals", owner_id=user["id"], title=body.title, why=body.why,
                    next_step=body.next_step, status="active", shared=int(body.shared),
                    created_at=ts, updated_at=ts)
    return db.one("SELECT * FROM goals WHERE id=?", (gid,))


@router.put("/goals/{gid}")
def update_goal(gid: int, body: GoalBody, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "goals", gid, user)
    if body.status not in ("active", "paused", "achieved", "dropped"):
        raise HTTPException(status_code=400, detail="Unknown status")
    db.update("goals", "id=?", (gid,), title=body.title, why=body.why, next_step=body.next_step,
              status=body.status, shared=int(body.shared), updated_at=now())
    return db.one("SELECT * FROM goals WHERE id=?", (gid,))


@router.delete("/goals/{gid}")
def delete_goal(gid: int, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "goals", gid, user)
    db.run("DELETE FROM goals WHERE id=?", (gid,))
    return {"deleted": True}


# ----------------------------------------------------------------------------- sensory
class StrategyPref(BaseModel):
    status: str
    used: bool = False


class DiaryBody(BaseModel):
    environment: Optional[str] = Field(default=None, max_length=500)
    what_happened: Optional[str] = Field(default=None, max_length=2000)
    what_helped: Optional[str] = Field(default=None, max_length=1000)
    intensity: Optional[int] = Field(default=None, ge=1, le=5)


class KitItem(BaseModel):
    item: str = Field(min_length=1, max_length=100)


@router.get("/sensory")
def sensory(user=Depends(current_user), db=Depends(get_db)):
    prefs = {r["strategy_key"]: r for r in db.all("SELECT * FROM sensory_strategies WHERE "
                                                   "owner_id=?", (user["id"],))}
    strategies = []
    for s in content.SENSORY_STRATEGIES:
        p = prefs.get(s["key"])
        status = p["status"] if p else "neutral"
        strategies.append({**s, "status": status, "uses": p["uses"] if p else 0})
    order = {"liked": 0, "neutral": 1, "disliked": 2, "removed": 3}
    strategies.sort(key=lambda s: order[s["status"]])
    return {"strategies": strategies,
            "kit": db.all("SELECT * FROM sensory_kit WHERE owner_id=? ORDER BY id", (user["id"],)),
            "diary": db.all("SELECT * FROM sensory_diary WHERE owner_id=? ORDER BY created_at DESC"
                            " LIMIT 50", (user["id"],))}


@router.put("/sensory/strategies/{key}")
def set_strategy(key: str, body: StrategyPref, user=Depends(current_user), db=Depends(get_db)):
    if key not in content.SENSORY_KEYS or body.status not in ("liked", "disliked", "removed",
                                                               "neutral"):
        raise HTTPException(status_code=400, detail="Unknown strategy or status")
    with db.connect() as c:
        c.execute("INSERT INTO sensory_strategies (owner_id, strategy_key, status, uses) VALUES "
                  "(?,?,?,?) ON CONFLICT(owner_id, strategy_key) DO UPDATE SET "
                  "status=excluded.status, uses=uses+?", (user["id"], key, body.status,
                                                         int(body.used), int(body.used)))
    return sensory(user=user, db=db)


@router.post("/sensory/diary")
def add_diary(body: DiaryBody, user=Depends(current_user), db=Depends(get_db)):
    db.insert("sensory_diary", owner_id=user["id"], created_at=now(), **body.model_dump())
    return sensory(user=user, db=db)


@router.post("/sensory/kit")
def add_kit(body: KitItem, user=Depends(current_user), db=Depends(get_db)):
    db.insert("sensory_kit", owner_id=user["id"], item=body.item)
    return sensory(user=user, db=db)


@router.patch("/sensory/kit/{kid}")
def toggle_kit(kid: int, packed: bool, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "sensory_kit", kid, user)
    db.update("sensory_kit", "id=?", (kid,), packed=int(packed))
    return sensory(user=user, db=db)


@router.delete("/sensory/kit/{kid}")
def delete_kit(kid: int, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "sensory_kit", kid, user)
    db.run("DELETE FROM sensory_kit WHERE id=?", (kid,))
    return sensory(user=user, db=db)


# ----------------------------------------------------------------------------- calendar
class CalBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_time: str
    end_time: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)
    kind: str = "event"
    about_individual_id: Optional[int] = None
    shared: bool = False


@router.get("/calendar")
def list_calendar(start: Optional[str] = None, end: Optional[str] = None,
                  user=Depends(current_user), db=Depends(get_db)):
    start = start or (datetime.now().date() - timedelta(days=7)).isoformat()
    end = end or (datetime.now().date() + timedelta(days=60)).isoformat()
    own = db.all("SELECT * FROM calendar_events WHERE owner_id=? AND substr(start_time,1,10) "
                 "BETWEEN ? AND ? ORDER BY start_time", (user["id"], start, end))
    for e in own:
        e["owner"] = "me"
    shared = []
    if user["role"] == "caregiver":
        from nbapp.consent import people_for_caregiver, granted_scopes
        for link in people_for_caregiver(db, user["id"]):
            if link["status"] == "active" and "calendar" in granted_scopes(db, link["id"]):
                for e in db.all("SELECT * FROM calendar_events WHERE owner_id=? AND shared=1 AND "
                                "substr(start_time,1,10) BETWEEN ? AND ?",
                                (link["individual_id"], start, end)):
                    e["owner"] = link["display_name"]
                    shared.append(e)
    return {"events": sorted(own + shared, key=lambda e: e["start_time"])}


@router.post("/calendar")
def create_calendar(body: CalBody, user=Depends(current_user), db=Depends(get_db)):
    if body.about_individual_id:
        from nbapp.consent import link_between
        if not link_between(db, body.about_individual_id, user["id"]):
            raise HTTPException(status_code=403, detail="You are not connected to this person.")
    eid = db.insert("calendar_events", owner_id=user["id"], created_at=now(),
                    **{**body.model_dump(), "shared": int(body.shared)})
    return db.one("SELECT * FROM calendar_events WHERE id=?", (eid,))


@router.delete("/calendar/{eid}")
def delete_calendar(eid: int, user=Depends(current_user), db=Depends(get_db)):
    _owned(db, "calendar_events", eid, user)
    db.run("DELETE FROM calendar_events WHERE id=?", (eid,))
    return {"deleted": True}


# ----------------------------------------------------------------------------- focus
class FocusBody(BaseModel):
    minutes: int = Field(ge=1, le=180)
    task_id: Optional[int] = None
    completed: bool = True


@router.post("/focus")
def log_focus(body: FocusBody, user=Depends(current_user), db=Depends(get_db)):
    if body.task_id:
        _owned(db, "tasks", body.task_id, user)
    db.insert("focus_sessions", owner_id=user["id"], task_id=body.task_id, minutes=body.minutes,
              started_at=now(), completed=int(body.completed))
    return {"ok": True}


# ----------------------------------------------------------------------------- insights
@router.get("/insights")
def insights(user=Depends(current_user), db=Depends(get_db)):
    """Gentle, non-judgemental patterns from the user's OWN data. No scores, no rankings,
    no comparisons with other people, no causal claims."""
    uid = user["id"]
    routines = db.all("SELECT r.name, COUNT(rr.id) runs, SUM(rr.finished_at IS NOT NULL) finished "
                      "FROM routines r LEFT JOIN routine_runs rr ON rr.routine_id=r.id WHERE "
                      "r.owner_id=? GROUP BY r.id ORDER BY runs DESC", (uid,))
    strategies = db.all("SELECT strategy_key, uses FROM sensory_strategies WHERE owner_id=? AND "
                        "status='liked' ORDER BY uses DESC LIMIT 5", (uid,))
    cards = db.all("SELECT text, uses FROM comm_cards WHERE owner_id=? AND uses>0 ORDER BY uses "
                   "DESC LIMIT 5", (uid,))
    done = db.one("SELECT COUNT(*) n FROM tasks WHERE owner_id=? AND status='done' AND "
                  "completed_at >= ?", (uid, (datetime.now(timezone.utc) - timedelta(days=7))
                                        .isoformat(timespec="seconds")))["n"]
    focus = db.one("SELECT COALESCE(SUM(minutes),0) m FROM focus_sessions WHERE owner_id=? AND "
                   "started_at >= ?", (uid, (datetime.now(timezone.utc) - timedelta(days=7))
                                       .isoformat(timespec="seconds")))["m"]
    titles = {s["key"]: s["title"] for s in content.SENSORY_STRATEGIES}
    return {"routines": routines, "helpful_strategies": [{"title": titles.get(s["strategy_key"]),
                                                          "uses": s["uses"]} for s in strategies],
            "most_used_cards": cards, "tasks_done_7d": done, "focus_minutes_7d": focus,
            "notice": "Only you can see this. Patterns are not causes, and nothing here is a "
                      "diagnosis or a score."}
