"""Native-host orchestrator for the M5 AI Video Factory.

Runs every AI/media stage as an isolated `subprocess` so macOS reclaims all
GPU / Unified Memory when a worker exits. NEVER import mlx / mlx_lm /
mlx_whisper / mflux / kokoro_onnx in this module.

Usage:
    python orchestrator.py          # poll forever
    python orchestrator.py --once   # process at most one job, then exit
"""
import argparse
import subprocess
import sys
import time
import traceback
from pathlib import Path

from db import get_conn, get_db_path, get_job, init_db, update_job

PYTHON_BIN = sys.executable
WORKERS_DIR = Path(__file__).resolve().parent / "workers"

STEP1 = "step1_topic_script.py"
STEP2 = "step2_audio_subs.py"
STEP3 = "step3_images.py"
STEP4 = "step4_render.py"

MEDIA_STEPS = [
    ("2_GENERATING_AUDIO_SUBS", STEP2),
    ("3_GENERATING_IMAGES", STEP3),
    ("4_RENDERING_VIDEO", STEP4),
]

POLL_INTERVAL_SECONDS = 4


def run_worker(script_name, job_id):
    print(f"🚀 Running {script_name} for Job #{job_id}...", flush=True)
    subprocess.run([PYTHON_BIN, str(WORKERS_DIR / script_name), "--job_id", str(job_id)], check=True)


def claim_next_job():
    """Atomically pick the oldest runnable job and move it into its first running state.

    Returns (job_id, previous_status) or None. The compare-and-set UPDATE guards
    against the dashboard changing the row between SELECT and UPDATE.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, status FROM jobs WHERE status IN ('QUEUED', 'APPROVED_FOR_MEDIA') "
            "ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        next_status = "1_GENERATING_SCRIPT" if row["status"] == "QUEUED" else MEDIA_STEPS[0][0]
        cur = conn.execute(
            "UPDATE jobs SET status = ?, error_msg = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = ?",
            (next_status, row["id"], row["status"]),
        )
        if cur.rowcount != 1:
            return None
        return row["id"], row["status"]


def process_next_job():
    """Process one job. Returns True if a job was picked up, False if the queue was empty."""
    claimed = claim_next_job()
    if not claimed:
        return False
    job_id, prev_status = claimed

    try:
        if prev_status == "QUEUED":
            run_worker(STEP1, job_id)
            # Re-read: auto_mode may have been edited while the script was generating.
            job = get_job(job_id)
            if job and int(job["auto_mode"]) == 0:
                update_job(job_id, status="WAITING_SCRIPT_APPROVAL")
                print(f"⏸️ Job #{job_id} paused at WAITING_SCRIPT_APPROVAL.", flush=True)
                return True

        for status, script_name in MEDIA_STEPS:
            update_job(job_id, status=status)
            run_worker(script_name, job_id)

        update_job(job_id, status="COMPLETED")
        print(f"✅ Job #{job_id} finished! MP4 is ready.", flush=True)

    except Exception as e:
        print(f"❌ Error in Job #{job_id}: {e}", flush=True)
        # Workers record their own traceback (see workers/worker_cli.py); surface it first.
        job = get_job(job_id) or {}
        worker_error = (job.get("error_msg") or "").strip()
        parts = [f"{type(e).__name__}: {e}"]
        if worker_error:
            parts.append(f"Worker error:\n{worker_error}")
        parts.append(f"Orchestrator traceback:\n{traceback.format_exc()}")
        update_job(job_id, status="FAILED", error_msg="\n\n".join(parts))

    return True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="M5 AI Video Factory Orchestrator")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit immediately")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    init_db()

    if args.once:
        if not process_next_job():
            print("No queued jobs found.")
        return 0

    print(f"🍏 M5 MLX Orchestrator started. Watching {get_db_path()} for jobs...", flush=True)
    try:
        while True:
            if not process_next_job():
                time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n👋 Orchestrator stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())