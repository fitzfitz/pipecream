"""Shared CLI entrypoint for worker scripts.

Records the worker's own traceback in `jobs.error_msg` before exiting non-zero,
so the orchestrator/dashboard can show the real root cause (stderr still streams
live to the console, which matters for long MLX progress bars).
"""
import argparse
import traceback

from db import update_job


def run_worker_cli(main):
    parser = argparse.ArgumentParser()
    parser.add_argument("--job_id", type=int, required=True)
    args = parser.parse_args()
    try:
        main(args.job_id)
    except BaseException as e:
        if isinstance(e, SystemExit) and e.code in (0, None):
            raise
        try:
            update_job(args.job_id, error_msg=traceback.format_exc())
        except Exception:
            pass  # never mask the original failure
        raise
