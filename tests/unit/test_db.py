import sqlite3

import pytest

import db


def test_init_db_enables_wal_mode(temp_db):
    with db.get_conn() as conn:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"


def test_schema_matches_product_contract(temp_db):
    with db.get_conn() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert cols == db.JOB_COLUMNS | {"id", "created_at", "updated_at"}


def test_create_job_defaults(temp_db):
    job_id = db.create_job()
    job = db.get_job(job_id)
    assert job["status"] == "QUEUED"
    assert job["auto_mode"] == 1
    assert job["subreddit"] == "UnresolvedMysteries"
    assert job["video_format"] == "short_9_16"
    assert job["source_url"] is None
    assert job["error_msg"] is None


def test_crud_lifecycle(temp_db):
    job_id = db.create_job(subreddit="TrueOffMyChest", topic_title="A dilemma", auto_mode=0)
    assert db.get_job(job_id)["topic_title"] == "A dilemma"

    db.update_job(job_id, status="1_GENERATING_SCRIPT", script_json='{"title": "x"}')
    job = db.get_job(job_id)
    assert job["status"] == "1_GENERATING_SCRIPT"
    assert job["script_json"] == '{"title": "x"}'
    assert job["auto_mode"] == 0

    db.update_job(job_id, status="FAILED", error_msg="boom")
    assert db.get_job(job_id)["error_msg"] == "boom"

    db.update_job(job_id, status="QUEUED", error_msg=None)
    assert db.get_job(job_id)["error_msg"] is None


def test_get_job_missing_returns_none(temp_db):
    assert db.get_job(9999) is None


def test_list_jobs_newest_first_and_status_filter(temp_db):
    a = db.create_job(topic_title="a")
    b = db.create_job(topic_title="b")
    db.update_job(a, status="COMPLETED")

    assert [j["id"] for j in db.list_jobs()] == [b, a]
    assert [j["id"] for j in db.list_jobs(status="COMPLETED")] == [a]
    assert [j["id"] for j in db.list_jobs(status="QUEUED")] == [b]


def test_source_url_unique_constraint_on_insert(temp_db):
    db.create_job(source_url="https://reddit.com/r/x/1")
    with pytest.raises(sqlite3.IntegrityError):
        db.create_job(source_url="https://reddit.com/r/x/1")


def test_source_url_unique_constraint_on_update(temp_db):
    a = db.create_job()
    b = db.create_job()
    db.update_job(a, source_url="https://reddit.com/r/x/2")
    with pytest.raises(sqlite3.IntegrityError):
        db.update_job(b, source_url="https://reddit.com/r/x/2")


def test_multiple_null_source_urls_allowed(temp_db):
    db.create_job()
    db.create_job()
    assert len(db.list_jobs()) == 2


def test_update_job_rejects_unknown_columns(temp_db):
    job_id = db.create_job()
    with pytest.raises(ValueError):
        db.update_job(job_id, **{"status = 'x'; --": 1})


def test_update_job_bumps_updated_at(temp_db):
    job_id = db.create_job()
    with db.get_conn() as conn:
        conn.execute("UPDATE jobs SET updated_at = '2000-01-01 00:00:00' WHERE id = ?", (job_id,))
    db.update_job(job_id, status="COMPLETED")
    assert db.get_job(job_id)["updated_at"] != "2000-01-01 00:00:00"


def test_init_db_migrates_legacy_table_without_video_format(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, subreddit TEXT, "
                 "source_url TEXT UNIQUE, topic_title TEXT, status TEXT DEFAULT 'QUEUED', "
                 "auto_mode INTEGER DEFAULT 1, script_json TEXT, audio_path TEXT, subs_path TEXT, "
                 "video_path TEXT, error_msg TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)")
    conn.commit()
    conn.close()

    db.init_db()
    job_id = db.create_job()
    assert db.get_job(job_id)["video_format"] == "short_9_16"


def test_job_dir_follows_data_dir(temp_db):
    assert db.get_job_dir(7) == temp_db / "jobs" / "7"
