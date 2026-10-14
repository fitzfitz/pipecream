"""Step 2 — Voiceover (Kokoro / macOS `say`) + word-level captions (mlx-whisper).

`mlx_whisper` / `kokoro_onnx` are imported lazily so the pure ASS helpers can be
unit-tested and `DRY_RUN_AI=1` never loads model weights.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from db import get_job, get_job_dir, update_job  # noqa: E402

FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
WHISPER_REPO = "mlx-community/whisper-base-mlx"
CHUNK_SIZE = 3
DRY_RUN_DURATION = 3.0
DRY_RUN_WORDS = 9  # 9 words / 3 per chunk = 3 subtitle lines

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 768
PlayResY: 1344
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,62,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""


def is_dry_run():
    return os.environ.get("DRY_RUN_AI") == "1"


def format_ass_time(seconds):
    """Format seconds as ASS `H:MM:SS.cc` (centiseconds)."""
    total_cs = int(round(max(0.0, float(seconds)) * 100))
    hrs, rem = divmod(total_cs, 360000)
    mins, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"


def _clean_word(word):
    # Strip ASS override-tag braces so caption text can't inject styling.
    return word.strip().replace("{", "").replace("}", "")


def build_ass_dialogue_lines(segments, chunk_size=CHUNK_SIZE):
    words = []
    for seg in segments:
        words.extend(w for w in seg.get("words", []) if _clean_word(w.get("word", "")))

    lines = []
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        start = format_ass_time(chunk[0]["start"])
        end = format_ass_time(chunk[-1]["end"])
        text = " ".join(_clean_word(w["word"]) for w in chunk).upper()
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return lines


def generate_ass_subtitles(segments, ass_path):
    """Write a 768x1344 ASS file with 3-word uppercase caption chunks."""
    content = "\n".join([ASS_HEADER] + build_ass_dialogue_lines(segments)) + "\n"
    Path(ass_path).write_text(content, encoding="utf-8")
    return ass_path


def build_dry_run_segments(narration, duration=DRY_RUN_DURATION, n_words=DRY_RUN_WORDS):
    """Evenly spaced synthetic word timestamps (stand-in for whisper output)."""
    words = narration.split()[:n_words]
    filler = ["DRY", "RUN", "MODE"]
    while len(words) < n_words:
        words.append(filler[len(words) % len(filler)])
    step = duration / n_words
    timed = [
        {"word": w, "start": round(i * step, 3), "end": round((i + 1) * step, 3)}
        for i, w in enumerate(words)
    ]
    return [{"start": 0.0, "end": duration, "words": timed}]


def synthesize_dry_run_audio(wav_path, duration=DRY_RUN_DURATION):
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration:g}",
        "-ar", "44100", "-ac", "1", str(wav_path),
    ], check=True)


def synthesize_voice(narration, wav_path, job_dir):
    kokoro_model = Path("assets/kokoro-v1.0.onnx")
    kokoro_voices = Path("assets/voices-v1.0.bin")

    if kokoro_model.exists() and kokoro_voices.exists():
        import soundfile as sf
        from kokoro_onnx import Kokoro
        kokoro = Kokoro(str(kokoro_model), str(kokoro_voices))
        samples, sample_rate = kokoro.create(narration, voice="af_bella", speed=1.05, lang="en-us")
        sf.write(str(wav_path), samples, sample_rate)
    else:
        aiff_path = job_dir / "temp.aiff"
        subprocess.run(["say", "-r", "185", "-o", str(aiff_path), narration], check=True)
        subprocess.run([FFMPEG, "-y", "-i", str(aiff_path), str(wav_path)], check=True)
        aiff_path.unlink(missing_ok=True)


def transcribe_words(wav_path):
    import mlx_whisper  # deferred: heavy Metal/GPU import

    result = mlx_whisper.transcribe(str(wav_path), path_or_hf_repo=WHISPER_REPO, word_timestamps=True)
    return result.get("segments", [])


def main(job_id):
    job = get_job(job_id)
    if job is None or not job.get("script_json"):
        raise SystemExit(f"Job #{job_id} has no script_json")
    narration = json.loads(job["script_json"])["narration"]

    job_dir = get_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    wav_path = job_dir / "voice.wav"
    ass_path = job_dir / "subs.ass"

    if is_dry_run():
        synthesize_dry_run_audio(wav_path)
        segments = build_dry_run_segments(narration)
    else:
        synthesize_voice(narration, wav_path, job_dir)
        segments = transcribe_words(wav_path)

    generate_ass_subtitles(segments, ass_path)
    update_job(job_id, audio_path=str(wav_path), subs_path=str(ass_path))


if __name__ == "__main__":
    from worker_cli import run_worker_cli
    run_worker_cli(main)
