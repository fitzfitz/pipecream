import argparse
import json
import subprocess
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from db import get_job, update_job
import mlx_whisper

def format_ass_time(seconds):
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"

def generate_ass_subtitles(segments, ass_path):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 768
PlayResY: 1344

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,62,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    words = []
    for seg in segments:
        words.extend(seg.get("words", []))

    chunk_size = 3
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i+chunk_size]
        if not chunk:
            continue
        start = format_ass_time(chunk[0]["start"])
        end = format_ass_time(chunk[-1]["end"])
        text = " ".join(w["word"].strip() for w in chunk).upper()
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    Path(ass_path).write_text("\n".join(lines), encoding="utf-8")

def main(job_id):
    job = get_job(job_id)
    script = json.loads(job["script_json"])
    narration = script["narration"]

    job_dir = Path(f"data/jobs/{job_id}")
    wav_path = job_dir / "voice.wav"
    ass_path = job_dir / "subs.ass"

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
        subprocess.run(["ffmpeg", "-y", "-i", str(aiff_path), str(wav_path)], check=True)
        aiff_path.unlink(missing_ok=True)

    result = mlx_whisper.transcribe(
        str(wav_path),
        path_or_hf_repo="mlx-community/whisper-base-mlx",
        word_timestamps=True
    )
    generate_ass_subtitles(result.get("segments", []), ass_path)

    update_job(job_id, audio_path=str(wav_path), subs_path=str(ass_path))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job_id", type=int, required=True)
    args = parser.parse_args()
    main(args.job_id)
