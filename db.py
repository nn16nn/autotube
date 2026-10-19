import json
import os
import sqlite3
import threading
import time

from config import DATA_DIR

_DB = os.path.join(DATA_DIR, "app.db")
_lock = threading.Lock()

JOB_COLS = [
    "topic", "script", "kind", "lang", "voice", "style", "auto_upload",
    "privacy", "publish_at", "run_at",
]


def _conn():
    c = sqlite3.connect(_DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created REAL, topic TEXT, script TEXT, kind TEXT, lang TEXT,
                voice TEXT, style TEXT, auto_upload INTEGER DEFAULT 0,
                privacy TEXT DEFAULT 'private', publish_at TEXT, run_at REAL,
                status TEXT DEFAULT 'queued', stage TEXT DEFAULT '', progress INTEGER DEFAULT 0,
                title TEXT, description TEXT, tags TEXT, video_path TEXT, thumb_path TEXT,
                youtube_id TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            """
        )
        # a restart kills any running job: put it back in the queue
        c.execute("UPDATE jobs SET status='queued', stage='Қайта басталады', progress=0 WHERE status='running'")


def create_job(**kw):
    cols = ["created"] + JOB_COLS
    vals = [time.time()] + [kw.get(k) for k in JOB_COLS]
    with _lock, _conn() as c:
        cur = c.execute(
            f"INSERT INTO jobs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals
        )
        return cur.lastrowid


def update_job(job_id, **kw):
    if not kw:
        return
    if "tags" in kw and not isinstance(kw["tags"], str):
        kw["tags"] = json.dumps(kw["tags"], ensure_ascii=False)
    sets = ",".join(f"{k}=?" for k in kw)
    with _lock, _conn() as c:
        c.execute(f"UPDATE jobs SET {sets} WHERE id=?", list(kw.values()) + [job_id])


def _row(r):
    if r is None:
        return None
    d = dict(r)
    try:
        d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
    except Exception:
        d["tags"] = []
    return d


def get_job(job_id):
    with _lock, _conn() as c:
        return _row(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def list_jobs(limit=100):
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def delete_job(job_id):
    with _lock, _conn() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def next_due_job():
    with _lock, _conn() as c:
        r = c.execute(
            "SELECT * FROM jobs WHERE status='queued' AND (run_at IS NULL OR run_at<=?) ORDER BY id LIMIT 1",
            (time.time(),),
        ).fetchone()
    return _row(r)


def get_setting(key, default=None):
    with _lock, _conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(key, value):
    with _lock, _conn() as c:
        if value is None:
            c.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
