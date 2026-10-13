import sqlite3
import os
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "data/factory.db")

def get_conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        """)
        conn.commit()

def create_job(subreddit="UnresolvedMysteries", topic_title=None, auto_mode=1):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (subreddit, topic_title, status, auto_mode) VALUES (?, ?, 'QUEUED', ?)",
            (subreddit, topic_title, auto_mode)
        )
        conn.commit()
        return cur.lastrowid

def update_job(job_id, **kwargs):
    fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
    values = list(kwargs.values()) + [job_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        conn.commit()

def get_job(job_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

def list_jobs():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
