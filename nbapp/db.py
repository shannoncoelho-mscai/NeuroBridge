"""NeuroBridge web-app database (SQLite, stdlib only).

Why SQLite: the existing agent stores (bookings, events, memory) are SQLite and the app must
run in Colab with no database server. Every table has an owner column, foreign keys and
indexes; nothing is stored as one big JSON blob except per-user UI preferences.
Moving to PostgreSQL later means porting the SQL in MIGRATIONS (standard SQL, no
SQLite-only features apart from AUTOINCREMENT / datetime text).

Migrations are numbered and recorded in `schema_migrations`; they only ever add.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "neurobridge_app.sqlite3"

MIGRATIONS = [
    (1, "core accounts, consent, personal support, care, community, notifications, AI", """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('individual','caregiver','admin')),
    is_minor INTEGER NOT NULL DEFAULT 0,
    consent_mode TEXT NOT NULL DEFAULT 'self' CHECK (consent_mode IN ('self','guardian','supported')),
    language TEXT DEFAULT 'en',
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE TABLE user_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    prefs TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_audit_user ON audit_log(user_id, created_at);

-- personal support ------------------------------------------------------------
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo','doing','done','skipped','later')),
    priority INTEGER NOT NULL DEFAULT 2,
    due_date TEXT,
    estimate_min INTEGER,
    plan_date TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    shared INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX idx_tasks_owner ON tasks(owner_id, status);
CREATE TABLE task_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'user',
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'custom',
    reminder_time TEXT,
    shared INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE routine_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    minutes INTEGER,
    optional INTEGER NOT NULL DEFAULT 0,
    alternative TEXT,
    symbol TEXT
);
CREATE TABLE routine_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    done_steps INTEGER NOT NULL DEFAULT 0,
    skipped_steps INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    mood INTEGER, energy INTEGER, stress INTEGER, sensory INTEGER, social INTEGER,
    sleep INTEGER,
    overwhelmed INTEGER,
    needs TEXT,
    note TEXT
);
CREATE INDEX idx_checkins_owner ON checkins(owner_id, created_at);
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    body TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'thought',
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_journal_owner ON journal_entries(owner_id, created_at);
CREATE TABLE comm_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Needs',
    symbol TEXT,
    favorite INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    is_default INTEGER NOT NULL DEFAULT 0,
    uses INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE blueprint_sections (
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    shared INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, section)
);
CREATE TABLE goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    why TEXT,
    next_step TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','achieved','dropped')),
    shared INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE sensory_strategies (
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    strategy_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('liked','disliked','removed','neutral')),
    uses INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_id, strategy_key)
);
CREATE TABLE sensory_diary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    environment TEXT, what_happened TEXT, what_helped TEXT, intensity INTEGER
);
CREATE TABLE sensory_kit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item TEXT NOT NULL,
    packed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    location TEXT,
    notes TEXT,
    kind TEXT NOT NULL DEFAULT 'event',
    about_individual_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    shared INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_cal_owner ON calendar_events(owner_id, start_time);
CREATE TABLE focus_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    minutes INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0
);

-- care circle and consent --------------------------------------------------------
CREATE TABLE care_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    individual_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    caregiver_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    relationship TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending','active','declined','revoked')),
    invited_by INTEGER NOT NULL,
    is_guardian INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (individual_id, caregiver_id)
);
CREATE TABLE link_permissions (
    link_id INTEGER NOT NULL REFERENCES care_links(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('requested','granted','revoked')),
    updated_by INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (link_id, scope)
);
CREATE TABLE consent_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id INTEGER NOT NULL,
    scope TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE support_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent','seen','on_my_way','resolved')),
    reply TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE care_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    individual_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    occurred_at TEXT NOT NULL,
    context TEXT, environment TEXT, what_happened TEXT NOT NULL, factors TEXT,
    support_offered TEXT, what_helped TEXT, followup TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    visible_to_individual INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE care_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    individual_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assignee_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done')),
    created_at TEXT NOT NULL
);
CREATE TABLE support_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    individual_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ('note','handover')),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE care_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL, role TEXT, phone TEXT, email TEXT, notes TEXT
);
CREATE TABLE wellbeing_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    stress INTEGER, rest INTEGER, supported INTEGER, note TEXT
);

-- community connect --------------------------------------------------------------
CREATE TABLE community_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    handle TEXT NOT NULL UNIQUE,
    bio TEXT,
    interests TEXT NOT NULL DEFAULT '[]',
    open_to_connect INTEGER NOT NULL DEFAULT 0,
    guidelines_accepted_at TEXT
);
CREATE TABLE community_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    topic TEXT NOT NULL,
    audience TEXT NOT NULL DEFAULT 'everyone',
    minor_safe INTEGER NOT NULL DEFAULT 0,
    is_official INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE group_members (
    group_id INTEGER NOT NULL REFERENCES community_groups(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member','moderator')),
    joined_at TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id)
);
CREATE TABLE posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES community_groups(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'discussion',
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible','held','removed')),
    hold_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_posts_group ON posts(group_id, status, created_at);
CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible','held','removed')),
    hold_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE post_reactions (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('support','same','helpful')),
    PRIMARY KEY (post_id, user_id, kind)
);
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK (target_type IN ('post','comment','message','user')),
    target_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    details TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','actioned','dismissed')),
    resolved_by INTEGER,
    resolution TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE blocks (
    blocker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (blocker_id, blocked_id)
);
CREATE TABLE connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    addressee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending','accepted','declined')),
    note TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (requester_id, addressee_id)
);
CREATE TABLE direct_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible','held','removed')),
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX idx_dm_pair ON direct_messages(sender_id, recipient_id, created_at);

-- notifications ------------------------------------------------------------------
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    link TEXT,
    silent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX idx_notif_user ON notifications(user_id, read_at);

-- AI assistant -------------------------------------------------------------------
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    about_individual_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    mode TEXT,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE ai_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES ai_messages(id) ON DELETE CASCADE,
    ref TEXT, title TEXT, url TEXT, published TEXT
);
CREATE TABLE agent_runs (
    run_id TEXT PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    status TEXT,
    created_at TEXT NOT NULL
);
"""),
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Thin wrapper: one connection per call, foreign keys on, rows as dicts."""

    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("NEUROBRIDGE_APP_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.migrate()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self):
        with self._lock, self.connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY,"
                      " description TEXT, applied_at TEXT)")
            done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
            for version, desc, sql in MIGRATIONS:
                if version in done:
                    continue
                c.executescript(sql)
                c.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (version, desc, now()))

    # helpers -----------------------------------------------------------------
    def all(self, sql, params=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        with self.connect() as c:
            r = c.execute(sql, params).fetchone()
            return dict(r) if r else None

    def run(self, sql, params=()):
        with self.connect() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid if cur.lastrowid else cur.rowcount

    def insert(self, table, **values):
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        return self.run(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))

    def update(self, table, where, params, **values):
        if not values:
            return 0
        sets = ", ".join(f"{k} = ?" for k in values)
        with self.connect() as c:
            return c.execute(f"UPDATE {table} SET {sets} WHERE {where}",
                             tuple(values.values()) + tuple(params)).rowcount

    def audit(self, user_id, action, target=None, detail=None):
        # Never put message bodies, journal text or passwords in `detail`.
        self.insert("audit_log", user_id=user_id, action=action, target=target,
                    detail=detail, created_at=now())
