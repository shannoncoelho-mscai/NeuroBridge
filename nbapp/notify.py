"""Notifications that respect the user's settings.

- Categories can be switched off (then nothing is created).
- Quiet hours: notifications are still stored, but marked `silent` (no pop-up).
- Daily cap per category (default 5) to prevent spam. Support requests are never capped
  or silenced, because a person asked for help.
- Wording is neutral: no streaks, no "you missed", no guilt.
"""
import json
from datetime import datetime

from nbapp.db import now

CATEGORIES = {
    "routine": "Routine reminders",
    "appointment": "Appointments and bookings",
    "task": "Task reminders",
    "support_request": "Support requests from your circle",
    "circle": "Circle invitations and sharing changes",
    "community": "Community replies and connection requests",
    "caregiver": "Caregiver reminders",
}
DEFAULT_PREFS = {"disabled": [], "quiet_start": "21:30", "quiet_end": "07:30", "max_per_day": 5}
NEVER_LIMITED = {"support_request"}


def prefs_for(db, user_id):
    row = db.one("SELECT prefs FROM user_settings WHERE user_id=?", (user_id,))
    prefs = json.loads(row["prefs"]) if row else {}
    return {**DEFAULT_PREFS, **(prefs.get("notifications") or {})}


def in_quiet_hours(prefs, at=None):
    at = at or datetime.now()
    hm = at.strftime("%H:%M")
    start, end = prefs.get("quiet_start"), prefs.get("quiet_end")
    if not start or not end or start == end:
        return False
    return (start <= hm or hm < end) if start > end else (start <= hm < end)


def notify(db, user_id, category, title, body=None, link=None, at=None):
    prefs = prefs_for(db, user_id)
    if category in prefs.get("disabled", []) and category not in NEVER_LIMITED:
        return None
    if category not in NEVER_LIMITED:
        today = now()[:10]
        count = db.one("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND category=? AND "
                       "substr(created_at,1,10)=?", (user_id, category, today))["n"]
        if count >= int(prefs.get("max_per_day", 5)):
            return None
    silent = 0 if category in NEVER_LIMITED else int(in_quiet_hours(prefs, at))
    return db.insert("notifications", user_id=user_id, category=category, title=title,
                     body=body, link=link, silent=silent, created_at=now())
