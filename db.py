"""SQLite state layer for the M5 AI Video Factory.

Shared by the host orchestrator, the worker subprocesses, and the containerised
Streamlit dashboard. Must stay dependency-free (stdlib only) and must NEVER
import any MLX / model packages.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "data/factory.db")

JOB_COLUMNS = {
    "video_format", "subreddit", "source_url", "topic_title", "status",
    "auto_mode", "script_json", "audio_path", "subs_path", "video_path",
    "error_msg",
}

SCHEMA = """
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_format TEXT DEFAULT 'short_9_16',
        subreddit TEXT DEFAULT 'UnresolvedMysteries',
        source_url TEXT UNIQUE,
        topic_title TEXT,
        status TEXT DEFAULT 'QUEUED',
        auto_mode INTEGER DEFAULT 1,
        script_json TEXT,
        audio_path TEXT,
        subs_path TEXT,
        video_path TEXT,
        error_msg TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""


def get_db_path():
    """Resolve the DB path at call time so tests/containers can override DB_PATH."""
    return os.environ.get("DB_PATH", DB_PATH)


def get_data_dir():
    """Root for job artifacts. Defaults to the directory containing the DB."""
    return Path(os.environ.get("DATA_DIR") or Path(get_db_path()).parent)


def get_job_dir(job_id):
    return get_data_dir() / "jobs" / str(job_id)


def _connect():
    db_path = get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


@contextmanager
def get_conn():
    """Yield a connection that commits on success, rolls back on error, and always closes."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(SCHEMA)
        # Lightweight migration for DBs created before `video_format` existed.
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        if "video_format" not in existing:
            conn.execute("ALTER TABLE jobs ADD COLUMN video_format TEXT DEFAULT 'short_9_16'")


def create_job(subreddit="UnresolvedMysteries", topic_title=None, auto_mode=1,
               source_url=None, video_format="short_9_16"):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (video_format, subreddit, source_url, topic_title, status, auto_mode) "
            "VALUES (?, ?, ?, ?, 'QUEUED', ?)",
            (video_format, subreddit, source_url, topic_title, int(auto_mode)),
        )
        return cur.lastrowid


def update_job(job_id, **kwargs):
    if not kwargs:
        return
    unknown = set(kwargs) - JOB_COLUMNS
    if unknown:
        raise ValueError(f"Unknown job column(s): {sorted(unknown)}")
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [job_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)


def get_job(job_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(status=None):
    with get_conn() as conn:
        if status is None:
            rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
        return [dict(r) for r in rows]
