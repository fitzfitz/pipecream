import argparse
import subprocess
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from db import get_job, update_job

def get_audio_duration(wav_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path)
    ]
    out = subprocess.check_output(cmd).decode().strip()
    return float(out)

def main(job_id):
    job = get_job(job_id)
    job_dir = Path(f"data/jobs/{job_id}")
    img_dir = job_dir / "images"
    images = sorted(img_dir.glob("scene_*.png"))

    if not images:
        raise RuntimeError("No images found to render.")

    audio_dur = get_audio_duration(job["audio_path"])
    dur_per_img = audio_dur / len(images)
    fps = 30
    frames_per_img = int(dur_per_img * fps)

    clip_paths = []
    for idx, img in enumerate(images):
        clip_out = job_dir / f"clip_{idx:02d}.mp4"
        zoom_expr = "min(zoom+0.0012,1.18)" if idx % 2 == 0 else "if(eq(on,1),1.18,max(1.0,zoom-0.0012))"
        vf = (
            f"scale=1536:2688,"
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames_per_img}:s=768x1344:fps={fps}"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(img),
            "-vf", vf, "-t", f"{dur_per_img:.2f}",
            "-c:v", "h264_videotoolbox", "-b:v", "6M", "-pix_fmt", "yuv420p",
            str(clip_out)
        ], check=True)
        clip_paths.append(clip_out)

    concat_list = job_dir / "concat.txt"
    concat_list.write_text("\n".join([f"file '{c.name}'" for c in clip_paths]), encoding="utf-8")

    final_mp4 = job_dir / "final_short.mp4"
    subs_escaped = str(Path(job["subs_path"]).resolve()).replace(":", "\\:")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-i", str(job["audio_path"]),
        "-vf", f"ass='{subs_escaped}'",
        "-c:v", "h264_videotoolbox", "-b:v", "8M",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        str(final_mp4)
    ], check=True)

    update_job(job_id, video_path=str(final_mp4))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job_id", type=int, required=True)
    args = parser.parse_args()
    main(args.job_id)
