import subprocess
import sys

import pytest

import db
import orchestrator


class FakeRunner:
    """Stand-in for subprocess.run that records worker calls and the job status at call time."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, cmd, check=False, **kwargs):
        script = cmd[1].rsplit("/", 1)[-1]
        job_id = int(cmd[cmd.index("--job_id") + 1])
        self.calls.append({"cmd": cmd, "script": script, "status": db.get_job(job_id)["status"]})
        if self.fail_on and script == self.fail_on:
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    @property
    def scripts(self):
        return [c["script"] for c in self.calls]


@pytest.fixture
def runner(temp_db, monkeypatch):
    fake = FakeRunner()
    monkeypatch.setattr(orchestrator.subprocess, "run", fake)
    return fake


ALL_STEPS = [orchestrator.STEP1, orchestrator.STEP2, orchestrator.STEP3, orchestrator.STEP4]


def test_empty_queue_returns_false(runner):
    assert orchestrator.process_next_job() is False
    assert runner.calls == []


def test_auto_mode_runs_all_workers_in_order(runner):
    job_id = db.create_job(auto_mode=1)

    assert orchestrator.process_next_job() is True

    assert runner.scripts == ALL_STEPS
    assert [c["status"] for c in runner.calls] == [
        "1_GENERATING_SCRIPT", "2_GENERATING_AUDIO_SUBS", "3_GENERATING_IMAGES", "4_RENDERING_VIDEO",
    ]
    assert db.get_job(job_id)["status"] == "COMPLETED"


def test_workers_invoked_as_isolated_subprocesses(runner):
    job_id = db.create_job()
    orchestrator.process_next_job()

    for call in runner.calls:
        cmd = call["cmd"]
        assert cmd[0] == sys.executable
        assert cmd[1] == str(orchestrator.WORKERS_DIR / call["script"])
        assert cmd[2:] == ["--job_id", str(job_id)]


def test_auto_mode_zero_pauses_after_script(runner):
    job_id = db.create_job(auto_mode=0)

    assert orchestrator.process_next_job() is True
    assert runner.scripts == [orchestrator.STEP1]
    assert db.get_job(job_id)["status"] == "WAITING_SCRIPT_APPROVAL"

    # A paused job is not picked up again until a human approves it.
    assert orchestrator.process_next_job() is False
    assert runner.scripts == [orchestrator.STEP1]


def test_approved_job_resumes_media_steps_only(runner):
    job_id = db.create_job(auto_mode=0)
    orchestrator.process_next_job()
    db.update_job(job_id, status="APPROVED_FOR_MEDIA")

    assert orchestrator.process_next_job() is True

    assert runner.scripts == ALL_STEPS
    assert runner.calls[1]["status"] == "2_GENERATING_AUDIO_SUBS"
    assert db.get_job(job_id)["status"] == "COMPLETED"


def test_failure_marks_job_failed_and_stops_pipeline(temp_db, monkeypatch):
    fake = FakeRunner(fail_on=orchestrator.STEP3)
    monkeypatch.setattr(orchestrator.subprocess, "run", fake)
    job_id = db.create_job()

    assert orchestrator.process_next_job() is True

    assert fake.scripts == [orchestrator.STEP1, orchestrator.STEP2, orchestrator.STEP3]
    job = db.get_job(job_id)
    assert job["status"] == "FAILED"
    assert "CalledProcessError" in job["error_msg"]
    assert orchestrator.STEP3 in job["error_msg"]
    assert "Traceback" in job["error_msg"]


def test_failed_job_is_not_retried_automatically(temp_db, monkeypatch):
    monkeypatch.setattr(orchestrator.subprocess, "run", FakeRunner(fail_on=orchestrator.STEP1))
    db.create_job()
    orchestrator.process_next_job()
    assert orchestrator.process_next_job() is False


def test_requeued_job_clears_error_and_completes(temp_db, monkeypatch):
    monkeypatch.setattr(orchestrator.subprocess, "run", FakeRunner(fail_on=orchestrator.STEP2))
    job_id = db.create_job()
    orchestrator.process_next_job()
    assert db.get_job(job_id)["status"] == "FAILED"

    db.update_job(job_id, status="QUEUED")  # dashboard "Retry" keeps old error until claimed
    monkeypatch.setattr(orchestrator.subprocess, "run", FakeRunner())
    orchestrator.process_next_job()

    job = db.get_job(job_id)
    assert job["status"] == "COMPLETED"
    assert job["error_msg"] is None


def test_jobs_processed_fifo(runner):
    first = db.create_job()
    second = db.create_job()
    orchestrator.process_next_job()
    assert db.get_job(first)["status"] == "COMPLETED"
    assert db.get_job(second)["status"] == "QUEUED"


def test_once_flag_processes_single_job_and_exits(runner):
    first = db.create_job()
    second = db.create_job()

    assert orchestrator.main(["--once"]) == 0

    assert runner.scripts == ALL_STEPS
    assert db.get_job(first)["status"] == "COMPLETED"
    assert db.get_job(second)["status"] == "QUEUED"


def test_once_flag_with_empty_queue_exits_cleanly(runner, capsys):
    assert orchestrator.main(["--once"]) == 0
    assert "No queued jobs" in capsys.readouterr().out
    assert runner.calls == []


def test_once_flag_never_enters_poll_loop(runner, monkeypatch):
    def boom(*_):
        raise AssertionError("--once must not sleep/poll")
    monkeypatch.setattr(orchestrator.time, "sleep", boom)
    assert orchestrator.main(["--once"]) == 0
