import time
import sys
import subprocess
from db import init_db, get_conn, update_job

PYTHON_BIN = sys.executable

def run_worker(script_path, job_id):
    print(f"🚀 Running {script_path} for Job #{job_id}...")
    subprocess.run([PYTHON_BIN, script_path, "--job_id", str(job_id)], check=True)

def process_next_job():
    with get_conn() as conn:
        job = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('QUEUED', 'APPROVED_FOR_MEDIA') ORDER BY id ASC LIMIT 1"
        ).fetchone()

    if not job:
        return False

    job_id = job["id"]
    try:
        if job["status"] == "QUEUED":
            update_job(job_id, status="1_GENERATING_SCRIPT", error_msg=None)
            run_worker("workers/step1_topic_script.py", job_id)

            if job["auto_mode"] == 0:
                update_job(job_id, status="WAITING_SCRIPT_APPROVAL")
                return True

        update_job(job_id, status="2_GENERATING_AUDIO_SUBS")
        run_worker("workers/step2_audio_subs.py", job_id)

        update_job(job_id, status="3_GENERATING_IMAGES")
        run_worker("workers/step3_images.py", job_id)

        update_job(job_id, status="4_RENDERING_VIDEO")
        run_worker("workers/step4_render.py", job_id)

        update_job(job_id, status="COMPLETED")
        print(f"✅ Job #{job_id} finished! MP4 is ready.")

    except Exception as e:
        print(f"❌ Error in Job #{job_id}: {e}")
        update_job(job_id, status="FAILED", error_msg=str(e))

    return True

if __name__ == "__main__":
    init_db()
    print("🍏 M5 MLX Orchestrator started. Watching data/factory.db for jobs...")
    while True:
        found = process_next_job()
        if not found:
            time.sleep(4)
