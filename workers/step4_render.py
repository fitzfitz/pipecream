"""Step 4 — Ken Burns render + ASS caption burn-in + final mux (FFmpeg).

Always runs the REAL FFmpeg pipeline (also in `DRY_RUN_AI=1` mode).
Encoder preference: `h264_videotoolbox` (Apple hardware) -> `libx264` fallback,
either because the encoder isn't compiled in or because it fails at runtime.

Env overrides:
    FFMPEG_BIN / FFPROBE_BIN  path to ffmpeg/ffprobe (e.g. a libass-enabled build)
    VIDEO_ENCODER             force a specific encoder (e.g. libx264)
"""
import functools
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from db import get_job, get_job_dir, update_job  # noqa: E402

FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")
WIDTH, HEIGHT = 768, 1344
FPS = 30
PREFERRED_ENCODERS = ("h264_videotoolbox", "libx264")

_working_encoder = None


# ---------------------------------------------------------------- helpers ---

def escape_filter_path(path):
    """Escape a file path for use as an FFmpeg filter option value inside -vf.

    Level 1 (option value): escape backslash, single quote, colon.
    Level 2 (filtergraph):  escape backslash, single quote, [ ] , ;
    Spaces need no escaping when passed as a single argv element.
    """
    level1 = re.sub(r"([\\':])", r"\\\1", str(path))
    return re.sub(r"([\\'\[\],;])", r"\\\1", level1)


def _ffmpeg_list(flag):
    out = subprocess.run([FFMPEG, "-hide_banner", flag], capture_output=True, text=True, check=True).stdout
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] != "=":  # skip legend rows like " V..... = Video"
            names.add(parts[1])
    return names


@functools.lru_cache(maxsize=None)
def available_encoders():
    return _ffmpeg_list("-encoders")


@functools.lru_cache(maxsize=None)
def available_filters():
    return _ffmpeg_list("-filters")


def require_filters(*names):
    missing = [n for n in names if n not in available_filters()]
    if missing:
        raise RuntimeError(
            f"FFmpeg at '{FFMPEG}' is missing required filter(s) {missing}. "
            "The 'ass' filter needs an FFmpeg build with libass "
            "(e.g. `brew install ffmpeg-full`, then "
            "`export FFMPEG_BIN=/usr/local/opt/ffmpeg-full/bin/ffmpeg "
            "FFPROBE_BIN=/usr/local/opt/ffmpeg-full/bin/ffprobe`)."
        )


def candidate_encoders():
    forced = os.environ.get("VIDEO_ENCODER")
    if forced:
        return [forced]
    if _working_encoder:
        return [_working_encoder]
    encs = available_encoders()
    return [e for e in PREFERRED_ENCODERS if e in encs] or ["libx264"]


def video_codec_args(encoder, bitrate):
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    return ["-c:v", encoder, "-b:v", bitrate]


def run_ffmpeg_encode(build_cmd, bitrate):
    """Run an encode, falling back to the next encoder if one fails at runtime."""
    global _working_encoder
    errors = []
    for enc in candidate_encoders():
        cmd = build_cmd(video_codec_args(enc, bitrate))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            _working_encoder = enc
            return enc
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        print(f"⚠️ Encoder {enc} failed, trying fallback...\n{tail}", flush=True)
        errors.append(f"[{enc}] {tail}")
    raise RuntimeError("FFmpeg encode failed with all encoders:\n" + "\n".join(errors))


def get_audio_duration(wav_path):
    out = subprocess.check_output([
        FFPROBE, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path),
    ]).decode().strip()
    return float(out)


# ----------------------------------------------------------------- render ---

def render_scene_clip(img, clip_out, idx, frames):
    zoom_expr = (
        "min(zoom+0.0012,1.18)" if idx % 2 == 0
        else "if(lte(zoom,1.0),1.18,max(1.001,zoom-0.0012))"
    )
    vf = (
        f"scale={WIDTH * 2}:{HEIGHT * 2},"
        f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        f"format=yuv420p"
    )
    return run_ffmpeg_encode(lambda venc: [
        FFMPEG, "-hide_banner", "-y", "-i", str(img),
        "-vf", vf, "-frames:v", str(frames), *venc, str(clip_out),
    ], bitrate="6M")


def render_final(concat_list, audio_path, subs_path, final_mp4):
    vf = f"ass=filename={escape_filter_path(Path(subs_path).resolve())},format=yuv420p"
    return run_ffmpeg_encode(lambda venc: [
        FFMPEG, "-hide_banner", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", vf, *venc,
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(final_mp4),
    ], bitrate="8M")


def main(job_id):
    job = get_job(job_id)
    if job is None:
        raise SystemExit(f"Job #{job_id} not found")
    if not job.get("audio_path") or not job.get("subs_path"):
        raise RuntimeError(f"Job #{job_id} is missing audio_path/subs_path")

    require_filters("zoompan", "ass")

    job_dir = get_job_dir(job_id)
    images = sorted((job_dir / "images").glob("scene_*.png"))
    if not images:
        raise RuntimeError("No images found to render.")

    audio_dur = get_audio_duration(job["audio_path"])
    frames_per_img = max(1, int(round(audio_dur / len(images) * FPS)))

    clip_paths = []
    for idx, img in enumerate(images):
        clip_out = job_dir / f"clip_{idx:02d}.mp4"
        enc = render_scene_clip(img, clip_out, idx, frames_per_img)
        print(f"🎞️ Rendered {clip_out.name} with {enc}", flush=True)
        clip_paths.append(clip_out)

    concat_list = job_dir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{c.name}'" for c in clip_paths) + "\n", encoding="utf-8")

    final_mp4 = job_dir / "final_short.mp4"
    enc = render_final(concat_list, job["audio_path"], job["subs_path"], final_mp4)
    print(f"🎬 Rendered {final_mp4} with {enc}", flush=True)

    for c in clip_paths:
        c.unlink(missing_ok=True)
    concat_list.unlink(missing_ok=True)

    update_job(job_id, video_path=str(final_mp4))


if __name__ == "__main__":
    from worker_cli import run_worker_cli
    run_worker_cli(main)
