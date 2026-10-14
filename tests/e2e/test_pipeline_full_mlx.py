"""Full unmocked generation on Apple Silicon. Run with: pytest -v -m mlx_hardware"""
import importlib.util
import json
import platform
import subprocess
from pathlib import Path

import pytest

import db
import orchestrator

pytestmark = [
    pytest.mark.mlx_hardware,
    pytest.mark.skipif(
        platform.system() != "Darwin" or platform.machine() != "arm64"
        or importlib.util.find_spec("mlx_lm") is None,
        reason="requires Apple Silicon with mlx-lm installed",
    ),
]


def test_full_mlx_pipeline(tmp_path, monkeypatch):
    monkeypatch.delenv("DRY_RUN_AI", raising=False)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "factory.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    job_id = db.create_job(topic_title="The 1872 Mary Celeste ghost ship found adrift with no crew", auto_mode=1)

    assert orchestrator.process_next_job() is True

    job = db.get_job(job_id)
    assert job["status"] == "COMPLETED", job["error_msg"]
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", job["video_path"],
    ]))
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (768, 1344)
    assert float(probe["format"]["duration"]) > 20.0
    assert Path(job["video_path"]).exists()
