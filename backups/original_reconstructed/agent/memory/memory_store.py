
import sqlite3, json
from pathlib import Path
from datetime import datetime, timedelta, timezone

MEMORY_DB = Path(__file__).resolve().parents[2] / "data" / "neurobridge_memory.sqlite3"
MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)

def connect():
    conn = sqlite3.connect(MEMORY_DB)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_memory():
    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS user_memories ("
            "memory_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id TEXT NOT NULL, memory_type TEXT NOT NULL, "
            "category TEXT NOT NULL, memory_key TEXT NOT NULL, "
            "memory_value TEXT NOT NULL, source TEXT DEFAULT 'user', "
            "consent INTEGER DEFAULT 0, expires_at TEXT, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "UNIQUE(user_id, memory_type, memory_key))"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_user "
            "ON user_memories(user_id, memory_type)"
        )
    return {"success": True, "database": str(MEMORY_DB)}

def save_memory(user_id, memory_type, category, key, value,
               consent=False, source="user", ttl_days=None):
    if memory_type not in ("long_term", "short_term"):
        raise ValueError("Invalid memory_type")
    if not consent:
        return {"success": False, "reason": "Consent required"}
    if not user_id or not key or value is None:
        raise ValueError("user_id, key and value required")

    now = datetime.now(timezone.utc).isoformat()
    expiry = (
        (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()
        if ttl_days else None
    )
    val = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    with connect() as conn:
        conn.execute(
            "INSERT INTO user_memories "
            "(user_id,memory_type,category,memory_key,memory_value,source,"
            "consent,expires_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,1,?,?,?) "
            "ON CONFLICT(user_id,memory_type,memory_key) DO UPDATE SET "
            "category=excluded.category,memory_value=excluded.memory_value,"
            "source=excluded.source,consent=1,expires_at=excluded.expires_at,"
            "updated_at=excluded.updated_at",
            (user_id,memory_type,category,key,val,source,expiry,now,now)
        )
    return {"success": True, "key": key}

def get_memories(user_id, memory_type=None, category=None):
    now = datetime.now(timezone.utc).isoformat()
    sql = "SELECT * FROM user_memories WHERE user_id=? AND consent=1 AND (expires_at IS NULL OR expires_at>?)"
    params = [user_id, now]
    if memory_type:
        sql += " AND memory_type=?"
        params.append(memory_type)
    if category:
        sql += " AND category=?"
        params.append(category)
    sql += " ORDER BY updated_at DESC"

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        try:
            item["memory_value"] = json.loads(item["memory_value"])
        except Exception:
            pass
        result.append(item)
    return result

def delete_memory(user_id, key, memory_type=None):
    sql = "DELETE FROM user_memories WHERE user_id=? AND memory_key=?"
    params = [user_id, key]
    if memory_type:
        sql += " AND memory_type=?"
        params.append(memory_type)
    with connect() as conn:
        cur = conn.execute(sql, params)
    return {"success": True, "deleted": cur.rowcount}

def clear_short_term_memory(user_id):
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM user_memories WHERE user_id=? AND memory_type='short_term'",
            (user_id,)
        )
    return {"success": True, "cleared": cur.rowcount}

def expire_memories():
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM user_memories WHERE expires_at IS NOT NULL AND expires_at<=?",
            (now,)
        )
    return {"success": True, "expired": cur.rowcount}

def memory_context(user_id):
    memories = get_memories(user_id)
    if not memories:
        return "No saved user memories."

    sections = []
    for kind in ("long_term", "short_term"):
        items = [m for m in memories if m["memory_type"] == kind]
        if items:
            sections.append(kind.upper() + " MEMORY:")
            sections.extend(
                f'{m["category"]} - {m["memory_key"]}: {m["memory_value"]}'
                for m in items
            )
    return "\n".join(sections)
