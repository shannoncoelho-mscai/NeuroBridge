"""Community Connect: interest groups, discussions, supportive reactions, peer connections,
private messages between connected adults, report, block, and moderation.

Safety design (project brief §8):
- You must create a community profile and accept the guidelines before posting.
- Under-18 accounts can only join groups marked minor_safe, cannot be found in the people
  directory, and cannot send or receive connection requests or private messages.
- Adult-only and caregiver-only groups are enforced on join.
- Blocking hides the other person everywhere and stops connections and messages both ways.
- Automatic checks HOLD content for a moderator (never silent deletion). 3 open reports on
  one item also hold it. Moderators (admins, group moderators) approve or remove.
- Nothing from your private journal, check-ins, blueprint or AI chats is ever posted
  automatically.
"""
import json
import re
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from nbapp import content, moderation
from nbapp.db import now
from nbapp.notify import notify
from nbapp.security import current_user, get_db, limiter

router = APIRouter(prefix="/api/community", tags=["community"])
HANDLE_RE = re.compile(r"^[a-z0-9_]{3,24}$")
REPORT_HOLD_THRESHOLD = 3
GUIDELINES = [
    "Be kind. Different brains, different ways of communicating — assume good intent.",
    "Share your experience, not medical advice. No diagnosing others.",
    "Keep personal details (phone, address, school) out of posts.",
    "No harassment, hate, sexual content or selling.",
    "Under-18 members are protected: adults may not contact them privately.",
    "If someone is in danger, call 112. This community is not a crisis service.",
    "Use Report and Block — moderators review every report.",
]


def seed_groups(db):
    for slug, name, desc, topic, audience, minor_safe in content.STARTER_GROUPS:
        if not db.one("SELECT id FROM community_groups WHERE slug=?", (slug,)):
            db.insert("community_groups", slug=slug, name=name, description=desc, topic=topic,
                      audience=audience, minor_safe=minor_safe, is_official=1, created_at=now())


def _blocked_ids(db, uid):
    rows = db.all("SELECT blocked_id x FROM blocks WHERE blocker_id=? UNION SELECT blocker_id x "
                  "FROM blocks WHERE blocked_id=?", (uid, uid))
    return {r["x"] for r in rows}


def _profile(db, uid):
    return db.one("SELECT * FROM community_profiles WHERE user_id=?", (uid,))


def _require_profile(db, user):
    p = _profile(db, user["id"])
    if not p or not p["guidelines_accepted_at"]:
        raise HTTPException(status_code=428, detail="Please set up your community profile and "
                                                    "accept the guidelines first.")
    return p


def _is_moderator(db, user, group_id=None):
    if user["role"] == "admin":
        return True
    if group_id is None:
        return False
    m = db.one("SELECT role FROM group_members WHERE group_id=? AND user_id=?",
               (group_id, user["id"]))
    return bool(m and m["role"] == "moderator")


def _can_join(user, group):
    if user["is_minor"] and not group["minor_safe"]:
        return False, "This group is for adults. Groups marked 'Under-18 friendly' are open to you."
    if group["audience"] == "adults" and user["is_minor"]:
        return False, "This group is for adults."
    if group["audience"] == "caregivers" and user["role"] != "caregiver":
        return False, "This group is for parents and caregivers."
    return True, None


# ----------------------------------------------------------------------------- profile
class ProfileBody(BaseModel):
    handle: str
    bio: Optional[str] = Field(default=None, max_length=300)
    interests: List[str] = Field(default_factory=list)
    open_to_connect: bool = False
    accept_guidelines: bool = False


@router.get("/guidelines")
def guidelines():
    return {"guidelines": GUIDELINES}


@router.get("/profile")
def get_profile(user=Depends(current_user), db=Depends(get_db)):
    p = _profile(db, user["id"])
    if p:
        p["interests"] = json.loads(p["interests"])
        p["open_to_connect"] = bool(p["open_to_connect"])
    return {"profile": p, "guidelines": GUIDELINES, "is_minor": bool(user["is_minor"])}


@router.put("/profile")
def put_profile(body: ProfileBody, user=Depends(current_user), db=Depends(get_db)):
    handle = body.handle.strip().lower()
    if not HANDLE_RE.match(handle):
        raise HTTPException(status_code=400, detail="Handle: 3–24 letters, numbers or _. Don't "
                                                    "use your real full name.")
    if not body.accept_guidelines:
        raise HTTPException(status_code=400, detail="Please accept the community guidelines.")
    taken = db.one("SELECT user_id FROM community_profiles WHERE handle=?", (handle,))
    if taken and taken["user_id"] != user["id"]:
        raise HTTPException(status_code=409, detail="That handle is taken.")
    open_flag = 0 if user["is_minor"] else int(body.open_to_connect)
    interests = json.dumps([i.strip()[:30] for i in body.interests[:12] if i.strip()])
    with db.connect() as c:
        c.execute("INSERT INTO community_profiles (user_id, handle, bio, interests, open_to_connect,"
                  " guidelines_accepted_at) VALUES (?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                  "handle=excluded.handle, bio=excluded.bio, interests=excluded.interests, "
                  "open_to_connect=excluded.open_to_connect, guidelines_accepted_at="
                  "excluded.guidelines_accepted_at",
                  (user["id"], handle, body.bio, interests, open_flag, now()))
    return get_profile(user=user, db=db)


# ----------------------------------------------------------------------------- groups
class GroupBody(BaseModel):
    name: str = Field(min_length=3, max_length=60)
    description: Optional[str] = Field(default=None, max_length=300)
    topic: str = Field(default="hobbies", max_length=30)
    audience: str = "everyone"
    minor_safe: bool = False


@router.get("/groups")
def list_groups(q: Optional[str] = None, user=Depends(current_user), db=Depends(get_db)):
    rows = db.all("SELECT g.*, (SELECT COUNT(*) FROM group_members m WHERE m.group_id=g.id) members,"
                  " EXISTS(SELECT 1 FROM group_members m WHERE m.group_id=g.id AND m.user_id=?) "
                  "joined FROM community_groups g ORDER BY is_official DESC, name", (user["id"],))
    if q:
        ql = q.lower()
        rows = [g for g in rows if ql in (g["name"] + " " + (g["description"] or "") + " " +
                                          g["topic"]).lower()]
    for g in rows:
        ok, why = _can_join(user, g)
        g["can_join"], g["join_note"] = ok, why
        g["joined"] = bool(g["joined"])
    return {"groups": rows}


@router.post("/groups")
def create_group(body: GroupBody, user=Depends(current_user), db=Depends(get_db)):
    _require_profile(db, user)
    if user["is_minor"]:
        raise HTTPException(status_code=403, detail="Under-18 accounts can join groups but not "
                                                    "create them.")
    if body.audience not in ("everyone", "adults", "caregivers"):
        raise HTTPException(status_code=400, detail="Unknown audience")
    slug = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")[:40]
    if db.one("SELECT id FROM community_groups WHERE slug=?", (slug,)):
        raise HTTPException(status_code=409, detail="A group with that name exists.")
    status, reason, msg = moderation.check(body.name + " " + (body.description or ""))
    if status != "visible":
        raise HTTPException(status_code=400, detail=msg)
    # Only admins can mark a new group as under-18 friendly (it needs active moderation).
    gid = db.insert("community_groups", slug=slug, name=body.name, description=body.description,
                    topic=body.topic, audience=body.audience,
                    minor_safe=int(body.minor_safe and user["role"] == "admin"),
                    created_by=user["id"], created_at=now())
    db.insert("group_members", group_id=gid, user_id=user["id"], role="moderator", joined_at=now())
    return db.one("SELECT * FROM community_groups WHERE id=?", (gid,))


def _group(db, gid):
    g = db.one("SELECT * FROM community_groups WHERE id=?", (gid,))
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    return g


def _member(db, gid, uid):
    return db.one("SELECT * FROM group_members WHERE group_id=? AND user_id=?", (gid, uid))


@router.post("/groups/{gid}/join")
def join_group(gid: int, user=Depends(current_user), db=Depends(get_db)):
    _require_profile(db, user)
    g = _group(db, gid)
    ok, why = _can_join(user, g)
    if not ok:
        raise HTTPException(status_code=403, detail=why)
    if not _member(db, gid, user["id"]):
        db.insert("group_members", group_id=gid, user_id=user["id"], joined_at=now())
    return {"joined": True}


@router.post("/groups/{gid}/leave")
def leave_group(gid: int, user=Depends(current_user), db=Depends(get_db)):
    db.run("DELETE FROM group_members WHERE group_id=? AND user_id=?", (gid, user["id"]))
    return {"joined": False}


def _post_out(db, p, uid):
    p["reactions"] = {r["kind"]: r["n"] for r in db.all(
        "SELECT kind, COUNT(*) n FROM post_reactions WHERE post_id=? GROUP BY kind", (p["id"],))}
    p["my_reactions"] = [r["kind"] for r in db.all(
        "SELECT kind FROM post_reactions WHERE post_id=? AND user_id=?", (p["id"], uid))]
    p["mine"] = p["author_id"] == uid
    return p


@router.get("/groups/{gid}/posts")
def group_posts(gid: int, user=Depends(current_user), db=Depends(get_db)):
    g = _group(db, gid)
    ok, why = _can_join(user, g)
    if not ok:
        raise HTTPException(status_code=403, detail=why)
    blocked = _blocked_ids(db, user["id"])
    rows = db.all("SELECT p.*, cp.handle FROM posts p LEFT JOIN community_profiles cp ON "
                  "cp.user_id=p.author_id WHERE p.group_id=? AND (p.status='visible' OR "
                  "(p.status='held' AND p.author_id=?)) ORDER BY p.created_at DESC LIMIT 100",
                  (gid, user["id"]))
    posts = []
    for p in rows:
        if p["author_id"] in blocked:
            continue
        p["comments"] = [c for c in db.all(
            "SELECT c.*, cp.handle FROM comments c LEFT JOIN community_profiles cp ON "
            "cp.user_id=c.author_id WHERE post_id=? AND (c.status='visible' OR (c.status='held' AND "
            "c.author_id=?)) ORDER BY c.created_at", (p["id"], user["id"]))
            if c["author_id"] not in blocked]
        posts.append(_post_out(db, p, user["id"]))
    return {"group": g, "joined": bool(_member(db, gid, user["id"])), "posts": posts,
            "is_moderator": _is_moderator(db, user, gid)}


class PostBody(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    kind: str = "discussion"  # discussion | question | experience | resource | win


@router.post("/groups/{gid}/posts")
def create_post(gid: int, body: PostBody, user=Depends(current_user), db=Depends(get_db)):
    _require_profile(db, user)
    limiter.check(("post", user["id"]), 20, 3600)
    if not _member(db, gid, user["id"]):
        raise HTTPException(status_code=403, detail="Join the group to post.")
    if body.kind not in ("discussion", "question", "experience", "resource", "win"):
        raise HTTPException(status_code=400, detail="Unknown post type")
    status, reason, msg = moderation.check(body.body, bool(user["is_minor"]))
    pid = db.insert("posts", group_id=gid, author_id=user["id"], kind=body.kind, body=body.body,
                    status=status, hold_reason=reason, created_at=now())
    return {"post_id": pid, "status": status, "message": msg}


class CommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


@router.post("/posts/{pid}/comments")
def comment(pid: int, body: CommentBody, user=Depends(current_user), db=Depends(get_db)):
    _require_profile(db, user)
    limiter.check(("comment", user["id"]), 60, 3600)
    p = db.one("SELECT * FROM posts WHERE id=? AND status='visible'", (pid,))
    if not p or not _member(db, p["group_id"], user["id"]):
        raise HTTPException(status_code=404, detail="Post not found or you're not in this group")
    if p["author_id"] in _blocked_ids(db, user["id"]):
        raise HTTPException(status_code=404, detail="Post not found")
    status, reason, msg = moderation.check(body.body, bool(user["is_minor"]))
    cid = db.insert("comments", post_id=pid, author_id=user["id"], body=body.body, status=status,
                    hold_reason=reason, created_at=now())
    if status == "visible" and p["author_id"] != user["id"]:
        notify(db, p["author_id"], "community", "Someone replied to your post", None,
               f"#/community/group/{p['group_id']}")
    return {"comment_id": cid, "status": status, "message": msg}


@router.post("/posts/{pid}/react")
def react(pid: int, kind: str, user=Depends(current_user), db=Depends(get_db)):
    if kind not in ("support", "same", "helpful"):
        raise HTTPException(status_code=400, detail="Unknown reaction")
    p = db.one("SELECT * FROM posts WHERE id=? AND status='visible'", (pid,))
    if not p or not _member(db, p["group_id"], user["id"]):
        raise HTTPException(status_code=404, detail="Post not found")
    if db.one("SELECT 1 FROM post_reactions WHERE post_id=? AND user_id=? AND kind=?",
              (pid, user["id"], kind)):
        db.run("DELETE FROM post_reactions WHERE post_id=? AND user_id=? AND kind=?",
               (pid, user["id"], kind))
    else:
        db.insert("post_reactions", post_id=pid, user_id=user["id"], kind=kind)
    return _post_out(db, p, user["id"])


@router.delete("/posts/{pid}")
def delete_post(pid: int, user=Depends(current_user), db=Depends(get_db)):
    p = db.one("SELECT * FROM posts WHERE id=?", (pid,))
    if not p or (p["author_id"] != user["id"] and not _is_moderator(db, user, p["group_id"])):
        raise HTTPException(status_code=404, detail="Not found")
    db.update("posts", "id=?", (pid,), status="removed")
    return {"removed": True}


# ----------------------------------------------------------------------------- people
@router.get("/people")
def people(q: Optional[str] = None, user=Depends(current_user), db=Depends(get_db)):
    """Adults who chose 'open to connect'. Minors never appear, and never see this list."""
    if user["is_minor"]:
        return {"people": [], "notice": "Private connections are for adults only."}
    blocked = _blocked_ids(db, user["id"])
    rows = db.all("SELECT cp.user_id, cp.handle, cp.bio, cp.interests FROM community_profiles cp "
                  "JOIN users u ON u.id=cp.user_id WHERE cp.open_to_connect=1 AND u.is_minor=0 AND "
                  "u.disabled=0 AND cp.user_id!=?", (user["id"],))
    out = []
    for r in rows:
        if r["user_id"] in blocked:
            continue
        r["interests"] = json.loads(r["interests"])
        if q and q.lower() not in (r["handle"] + " " + (r["bio"] or "") + " " +
                                   " ".join(r["interests"])).lower():
            continue
        out.append(r)
    return {"people": out}


class ConnectBody(BaseModel):
    user_id: int
    note: Optional[str] = Field(default=None, max_length=200)


def _adult_pair_ok(db, a, b_id):
    b = db.one("SELECT * FROM users WHERE id=?", (b_id,))
    if not b or b["disabled"]:
        raise HTTPException(status_code=404, detail="Person not found")
    if a["is_minor"] or b["is_minor"]:
        raise HTTPException(status_code=403, detail="Private connections are for adults only.")
    if b_id in _blocked_ids(db, a["id"]):
        raise HTTPException(status_code=404, detail="Person not found")
    return b


@router.get("/connections")
def connections(user=Depends(current_user), db=Depends(get_db)):
    rows = db.all("SELECT c.*, cp1.handle requester_handle, cp2.handle addressee_handle FROM "
                  "connections c LEFT JOIN community_profiles cp1 ON cp1.user_id=c.requester_id "
                  "LEFT JOIN community_profiles cp2 ON cp2.user_id=c.addressee_id WHERE "
                  "(requester_id=? OR addressee_id=?) AND status!='declined'",
                  (user["id"], user["id"]))
    blocked = _blocked_ids(db, user["id"])
    out = []
    for r in rows:
        other = r["addressee_id"] if r["requester_id"] == user["id"] else r["requester_id"]
        if other in blocked:
            continue
        r["other_id"] = other
        r["other_handle"] = r["addressee_handle"] if r["requester_id"] == user["id"] else \
            r["requester_handle"]
        r["incoming"] = r["addressee_id"] == user["id"] and r["status"] == "pending"
        out.append(r)
    return {"connections": out}


@router.post("/connections")
def request_connection(body: ConnectBody, user=Depends(current_user), db=Depends(get_db)):
    _require_profile(db, user)
    limiter.check(("connect", user["id"]), 20, 86400)
    if body.user_id == user["id"]:
        raise HTTPException(status_code=400, detail="That's you!")
    _adult_pair_ok(db, user, body.user_id)
    target = _profile(db, body.user_id)
    if not target or not target["open_to_connect"]:
        raise HTTPException(status_code=403, detail="This person isn't accepting connections.")
    existing = db.one("SELECT * FROM connections WHERE (requester_id=? AND addressee_id=?) OR "
                      "(requester_id=? AND addressee_id=?)",
                      (user["id"], body.user_id, body.user_id, user["id"]))
    if existing:
        return {"status": existing["status"]}
    db.insert("connections", requester_id=user["id"], addressee_id=body.user_id,
              status="pending", note=body.note, created_at=now())
    notify(db, body.user_id, "community", "New connection request", None, "#/community/people")
    return {"status": "pending"}


@router.post("/connections/{cid}")
def answer_connection(cid: int, accept: bool, user=Depends(current_user), db=Depends(get_db)):
    c = db.one("SELECT * FROM connections WHERE id=?", (cid,))
    if not c or c["addressee_id"] != user["id"] or c["status"] != "pending":
        raise HTTPException(status_code=404, detail="Not found")
    db.update("connections", "id=?", (cid,), status="accepted" if accept else "declined")
    if accept:
        notify(db, c["requester_id"], "community", "Your connection request was accepted", None,
               "#/community/people")
    return connections(user=user, db=db)


def _connected(db, a, b):
    return bool(db.one("SELECT 1 FROM connections WHERE status='accepted' AND ((requester_id=? AND "
                       "addressee_id=?) OR (requester_id=? AND addressee_id=?))", (a, b, b, a)))


class MessageBody(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


@router.get("/messages/{other_id}")
def thread(other_id: int, user=Depends(current_user), db=Depends(get_db)):
    _adult_pair_ok(db, user, other_id)
    if not _connected(db, user["id"], other_id):
        raise HTTPException(status_code=403, detail="You can message people you're connected with.")
    rows = db.all("SELECT * FROM direct_messages WHERE ((sender_id=? AND recipient_id=?) OR "
                  "(sender_id=? AND recipient_id=?)) AND (status='visible' OR sender_id=?) "
                  "ORDER BY created_at", (user["id"], other_id, other_id, user["id"], user["id"]))
    db.run("UPDATE direct_messages SET read_at=? WHERE recipient_id=? AND sender_id=? AND read_at "
           "IS NULL", (now(), user["id"], other_id))
    return {"messages": rows}


@router.post("/messages/{other_id}")
def send_message(other_id: int, body: MessageBody, user=Depends(current_user), db=Depends(get_db)):
    _require_profile(db, user)
    limiter.check(("dm", user["id"]), 60, 3600)
    _adult_pair_ok(db, user, other_id)
    if not _connected(db, user["id"], other_id):
        raise HTTPException(status_code=403, detail="You can message people you're connected with.")
    status, reason, msg = moderation.check(body.body)
    # Contact details between connected adults are allowed in private messages.
    if reason == "personal_info":
        status, msg = "visible", None
    mid = db.insert("direct_messages", sender_id=user["id"], recipient_id=other_id, body=body.body,
                    status=status, created_at=now())
    if status == "visible":
        notify(db, other_id, "community", "New message", None, f"#/community/messages/{user['id']}")
    return {"message_id": mid, "status": status, "message": msg}


# ----------------------------------------------------------------------------- safety tools
class BlockBody(BaseModel):
    user_id: int


@router.post("/blocks")
def block(body: BlockBody, user=Depends(current_user), db=Depends(get_db)):
    if body.user_id == user["id"]:
        raise HTTPException(status_code=400, detail="You can't block yourself.")
    with db.connect() as c:
        c.execute("INSERT OR IGNORE INTO blocks (blocker_id, blocked_id, created_at) VALUES (?,?,?)",
                  (user["id"], body.user_id, now()))
        c.execute("UPDATE connections SET status='declined' WHERE (requester_id=? AND "
                  "addressee_id=?) OR (requester_id=? AND addressee_id=?)",
                  (user["id"], body.user_id, body.user_id, user["id"]))
    db.audit(user["id"], "block", f"user:{body.user_id}")
    return {"blocked": True}


@router.get("/blocks")
def my_blocks(user=Depends(current_user), db=Depends(get_db)):
    return {"blocks": db.all("SELECT b.blocked_id, cp.handle FROM blocks b LEFT JOIN "
                             "community_profiles cp ON cp.user_id=b.blocked_id WHERE blocker_id=?",
                             (user["id"],))}


@router.delete("/blocks/{uid}")
def unblock(uid: int, user=Depends(current_user), db=Depends(get_db)):
    db.run("DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?", (user["id"], uid))
    return {"blocked": False}


class ReportBody(BaseModel):
    target_type: str
    target_id: int
    reason: str = Field(max_length=40)
    details: Optional[str] = Field(default=None, max_length=1000)


TARGET_TABLE = {"post": "posts", "comment": "comments", "message": "direct_messages"}


@router.post("/reports")
def report(body: ReportBody, user=Depends(current_user), db=Depends(get_db)):
    limiter.check(("report", user["id"]), 30, 3600)
    if body.target_type not in ("post", "comment", "message", "user"):
        raise HTTPException(status_code=400, detail="Unknown target")
    if body.target_type == "message":
        m = db.one("SELECT * FROM direct_messages WHERE id=?", (body.target_id,))
        if not m or user["id"] not in (m["sender_id"], m["recipient_id"]):
            raise HTTPException(status_code=404, detail="Not found")
    db.insert("reports", reporter_id=user["id"], target_type=body.target_type,
              target_id=body.target_id, reason=body.reason, details=body.details, created_at=now())
    if body.target_type in TARGET_TABLE:
        n = db.one("SELECT COUNT(*) n FROM reports WHERE target_type=? AND target_id=? AND "
                   "status='open'", (body.target_type, body.target_id))["n"]
        if n >= REPORT_HOLD_THRESHOLD or body.target_type == "message":
            db.run(f"UPDATE {TARGET_TABLE[body.target_type]} SET status='held' WHERE id=? AND "
                   f"status='visible'", (body.target_id,))
    db.audit(user["id"], "report", f"{body.target_type}:{body.target_id}", body.reason)
    return {"message": "Thank you. A moderator will look at this. You can also block this "
                       "person so you don't see them."}


# ----------------------------------------------------------------------------- moderation
@router.get("/moderation")
def moderation_queue(user=Depends(current_user), db=Depends(get_db)):
    if user["role"] == "admin":
        group_ids = None
    else:
        group_ids = [r["group_id"] for r in db.all("SELECT group_id FROM group_members WHERE "
                                                   "user_id=? AND role='moderator'", (user["id"],))]
        if not group_ids:
            raise HTTPException(status_code=403, detail="Moderators only")
    held_posts = db.all("SELECT * FROM posts WHERE status='held' ORDER BY created_at")
    held_comments = db.all("SELECT c.*, p.group_id FROM comments c JOIN posts p ON p.id=c.post_id "
                           "WHERE c.status='held'")
    if group_ids is not None:
        held_posts = [p for p in held_posts if p["group_id"] in group_ids]
        held_comments = [c for c in held_comments if c["group_id"] in group_ids]
    reports = db.all("SELECT * FROM reports WHERE status='open' ORDER BY created_at") \
        if user["role"] == "admin" else []
    held_messages = db.all("SELECT * FROM direct_messages WHERE status='held'") \
        if user["role"] == "admin" else []
    return {"held_posts": held_posts, "held_comments": held_comments, "reports": reports,
            "held_messages": held_messages}


class ModAction(BaseModel):
    target_type: str
    target_id: int
    action: str  # approve | remove | dismiss_report | disable_user
    report_id: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=300)


@router.post("/moderation")
def moderate(body: ModAction, user=Depends(current_user), db=Depends(get_db)):
    group_id = None
    if body.target_type == "post":
        row = db.one("SELECT group_id FROM posts WHERE id=?", (body.target_id,))
        group_id = row and row["group_id"]
    elif body.target_type == "comment":
        row = db.one("SELECT p.group_id FROM comments c JOIN posts p ON p.id=c.post_id WHERE c.id=?",
                     (body.target_id,))
        group_id = row and row["group_id"]
    if not _is_moderator(db, user, group_id):
        raise HTTPException(status_code=403, detail="Moderators only")
    if body.action in ("approve", "remove"):
        if body.target_type not in TARGET_TABLE:
            raise HTTPException(status_code=400, detail="Unknown target")
        db.run(f"UPDATE {TARGET_TABLE[body.target_type]} SET status=? WHERE id=?",
               ("visible" if body.action == "approve" else "removed", body.target_id))
        db.run("UPDATE reports SET status='actioned', resolved_by=?, resolution=? WHERE "
               "target_type=? AND target_id=? AND status='open'",
               (user["id"], body.action, body.target_type, body.target_id))
    elif body.action == "dismiss_report" and body.report_id:
        db.run("UPDATE reports SET status='dismissed', resolved_by=?, resolution=? WHERE id=?",
               (user["id"], body.note, body.report_id))
    elif body.action == "disable_user":
        if user["role"] != "admin" or body.target_type != "user":
            raise HTTPException(status_code=403, detail="Admins only")
        db.update("users", "id=?", (body.target_id,), disabled=1)
        db.run("DELETE FROM sessions WHERE user_id=?", (body.target_id,))
    else:
        raise HTTPException(status_code=400, detail="Unknown action")
    db.audit(user["id"], f"moderation_{body.action}", f"{body.target_type}:{body.target_id}")
    return {"ok": True}
