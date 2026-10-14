"""Step 3 — 9:16 scene images via `mflux-generate` (FLUX.1-schnell, 4-bit).

In `DRY_RUN_AI=1` mode a single solid-navy 768x1344 PNG is rendered with FFmpeg
and copied for every scene (well under 0.5s, no model weights touched).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from db import get_job, get_job_dir  # noqa: E402

FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
WIDTH, HEIGHT = 768, 1344


def is_dry_run():
    return os.environ.get("DRY_RUN_AI") == "1"


def scene_path(img_dir, idx):
    return img_dir / f"scene_{idx:02d}.png"


def generate_dry_run_images(prompts, img_dir):
    first = scene_path(img_dir, 0)
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=navy:s={WIDTH}x{HEIGHT}:d=1",
        "-frames:v", "1", "-update", "1", str(first),
    ], check=True)
    for idx in range(1, len(prompts)):
        shutil.copyfile(first, scene_path(img_dir, idx))


def generate_mflux_images(prompts, img_dir):
    for idx, prompt in enumerate(prompts):
        out_file = scene_path(img_dir, idx)
        if out_file.exists():
            continue  # resume support: skip scenes already rendered
        subprocess.run([
            "mflux-generate",
            "--model", "schnell",
            "--quantize", "4",
            "--steps", "4",
            "--width", str(WIDTH),
            "--height", str(HEIGHT),
            "--prompt", prompt,
            "--output", str(out_file),
        ], check=True)


def main(job_id):
    job = get_job(job_id)
    if job is None or not job.get("script_json"):
        raise SystemExit(f"Job #{job_id} has no script_json")
    prompts = json.loads(job["script_json"]).get("visual_prompts", [])
    if not prompts:
        raise SystemExit(f"Job #{job_id} has no visual_prompts")

    img_dir = get_job_dir(job_id) / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    if is_dry_run():
        generate_dry_run_images(prompts, img_dir)
    else:
        generate_mflux_images(prompts, img_dir)


if __name__ == "__main__":
    from worker_cli import run_worker_cli
    run_worker_cli(main)
