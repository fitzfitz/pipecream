import argparse
import json
import subprocess
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from db import get_job

def main(job_id):
    job = get_job(job_id)
    script = json.loads(job["script_json"])
    prompts = script.get("visual_prompts", [])

    job_dir = Path(f"data/jobs/{job_id}/images")
    job_dir.mkdir(parents=True, exist_ok=True)

    for idx, prompt in enumerate(prompts):
        out_file = job_dir / f"scene_{idx:02d}.png"
        if out_file.exists():
            continue
        cmd = [
            "mflux-generate",
            "--model", "schnell",
            "--quantize", "4",
            "--steps", "4",
            "--width", "768",
            "--height", "1344",
            "--prompt", prompt,
            "--output", str(out_file)
        ]
        subprocess.run(cmd, check=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job_id", type=int, required=True)
    args = parser.parse_args()
    main(args.job_id)
