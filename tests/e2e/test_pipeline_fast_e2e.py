"""Fast end-to-end suite (DRY_RUN_AI=1): real subprocess workers + real FFmpeg render.

Requires `ffmpeg`/`ffprobe` on PATH (or FFMPEG_BIN/FFPROBE_BIN) built with libass.
"""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import db
import orchestrator
from workers import step1_topic_script, step3_images

ROOT = Path(__file__).resolve().parents[2]
FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")


@pytest.fixture
def e2e_env(tmp_path, monkeypatch):
    # Space + colon in the artifact path exercises FFmpeg `ass=` filter escaping for real.
    data_dir = tmp_path / "factory data: e2e"
    monkeypatch.setenv("DRY_RUN_AI", "1")
    monkeypatch.setenv("DB_PATH", str(data_dir / "factory.db"))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    db.init_db()
    return data_dir


def ffprobe(path):
    out = subprocess.check_output([
        FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
    ])
    return json.loads(out)


def test_full_pipeline_dry_run_produces_valid_short(e2e_env):
    job_id = db.create_job(subreddit="UnresolvedMysteries", auto_mode=1)

    assert orchestrator.process_next_job() is True

    job = db.get_job(job_id)
    assert job["status"] == "COMPLETED", job["error_msg"]

    job_dir = e2e_env / "jobs" / str(job_id)
    final = Path(job["video_path"])
    assert final == job_dir / "final_short.mp4"
    assert final.exists() and final.stat().st_size > 0

    script = json.loads(job["script_json"])
    assert len(script["visual_prompts"]) == 3
    assert job["source_url"] == f"dryrun://{job_id}"
    assert len(list((job_dir / "images").glob("scene_*.png"))) == 3
    dialogues = [l for l in Path(job["subs_path"]).read_text().splitlines() if l.startswith("Dialogue:")]
    assert len(dialogues) == 3
    assert not list(job_dir.glob("clip_*.mp4")), "intermediate clips should be cleaned up"

    probe = ffprobe(final)
    video = [s for s in probe["streams"] if s["codec_type"] == "video"]
    audio = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    assert len(video) == 1 and len(audio) == 1
    assert video[0]["codec_name"] == "h264"
    assert (video[0]["width"], video[0]["height"]) == (768, 1344)
    assert audio[0]["codec_name"] == "aac"
    assert float(probe["format"]["duration"]) > 2.0


def test_dry_run_assets_are_valid(e2e_env):
    job_id = db.create_job()
    for script in (orchestrator.STEP1, orchestrator.STEP2, orchestrator.STEP3):
        orchestrator.run_worker(script, job_id)

    job = db.get_job(job_id)
    wav = ffprobe(job["audio_path"])
    assert abs(float(wav["format"]["duration"]) - 3.0) < 0.1

    png = ffprobe(e2e_env / "jobs" / str(job_id) / "images" / "scene_00.png")
    assert (png["streams"][0]["width"], png["streams"][0]["height"]) == (768, 1344)


def test_dry_run_worker_time_budgets(e2e_env):
    job_id = db.create_job()

    t0 = time.perf_counter()
    step1_topic_script.main(job_id)
    assert time.perf_counter() - t0 < 0.1

    t0 = time.perf_counter()
    step3_images.main(job_id)
    assert time.perf_counter() - t0 < 0.5


def test_human_in_the_loop_pauses_with_real_script_worker(e2e_env):
    job_id = db.create_job(auto_mode=0)
    assert orchestrator.process_next_job() is True

    job = db.get_job(job_id)
    assert job["status"] == "WAITING_SCRIPT_APPROVAL"
    assert json.loads(job["script_json"])["title"]
    assert job["video_path"] is None


# ------------------------------------------------------------- dashboard ---

def _dashboard():
    return AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=30)


def test_dashboard_renders_tabs_and_jobs(e2e_env):
    db.create_job(topic_title="Existing mystery job")

    at = _dashboard().run()

    assert not at.exception
    assert "Video Factory" in at.title[0].value
    assert len(at.tabs) == 3
    assert any("Existing mystery job" in e.label for e in at.expander)


def test_dashboard_launch_button_queues_job(e2e_env):
    at = _dashboard().run()
    at.sidebar.toggle[0].set_value(False)
    next(b for b in at.sidebar.button if "Launch" in b.label).click().run()

    assert not at.exception
    jobs = db.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "QUEUED"
    assert jobs[0]["auto_mode"] == 0


def test_dashboard_script_approval_sets_approved_for_media(e2e_env):
    job_id = db.create_job(auto_mode=0)
    db.update_job(job_id, status="WAITING_SCRIPT_APPROVAL", topic_title="Needs review",
                  script_json=json.dumps(step1_topic_script.DRY_RUN_SCRIPT))

    at = _dashboard().run()
    at.button(key=f"app_{job_id}").click().run()

    assert not at.exception
    assert db.get_job(job_id)["status"] == "APPROVED_FOR_MEDIA"
