# PRODUCT.md — Autonomous M5 AI Video Factory

## 1. Executive Summary & Vision
An end-to-end, zero-variable-cost (\$0/month) autonomous video creation factory engineered specifically for **Apple Silicon (MacBook Pro M5 with 24GB Unified Memory)**.
- **Phase 1 (Current Target):** High-retention vertical short-form videos (`768x1344`, 9:16, 40–60 seconds) for YouTube Shorts, TikTok, and Reels.
- **Phase 2 (Future Scale):** Horizontal long-form video essays (`1920x1080`, 16:9, 8–15 minutes) using chaptered script generation and multi-scene batch rendering.

## 2. Content Strategy & Viral Story Engine
Short-form algorithms optimize for **completion rate (greater than 80%)** and **comment velocity**.

### Story Sources (Automated Mining)
1. **Reddit JSON API (`https://www.reddit.com/r/<subreddit>/top.json?t=week&limit=25`):**
   - Custom `User-Agent: MacM5VideoBot/1.0` to avoid HTTP 429 blocks.
   - Deduplicated against `jobs.source_url` (UNIQUE in SQLite).
   - Filters out stickied posts, non-text posts, and posts with fewer than 200 characters.
2. **Public Domain / Wikipedia / Custom Prompts:** Direct user input or curated historical hooks via the Dashboard.

### Target Niches
- **Niche A — Dark History & Unresolved Mysteries:** `r/UnresolvedMysteries`, historical disappearances, bizarre events.
- **Niche B — First-Person Confessions & Moral Dilemmas:** `r/TrueOffMyChest`, polarizing interpersonal dilemmas that spark comment debates.
- **Niche C — Liminal & Surreal Sci-Fi/Horror:** Atmospheric micro-fiction optimized for uncanny AI visuals.

## 3. Hardware & Hybrid Architecture (MacBook Pro M5 24GB)
- **Usable Unified Memory Pool:** ~18–20GB after macOS overhead.
- **Hybrid Container + Host Execution Model:**
  - **Why:** Docker/Podman on macOS runs inside a Linux VM that **cannot** access Apple's Metal GPU, Neural Accelerators, or `MLX`.
  - **Container Layer (`compose.yaml`):** Runs `dashboard` (Streamlit on port `8501`) and `n8n` (port `5678`). Mounts `./data:/app/data:Z`.
  - **Native Host Layer (`orchestrator.py`):** Runs natively on macOS in `.venv` to execute all AI/media workers via isolated OS subprocesses.

## 4. Exact AI Stack & Model Specifications
| Stage | Worker Script | Model / Tool | Peak RAM | Output Artifact |
| :--- | :--- | :--- | :--- | :--- |
| **1. Script & Prompts** | `workers/step1_topic_script.py` | `mlx-community/Meta-Llama-3.1-8B-Instruct-4bit` (`mlx-lm`) | ~5.5 GB | `jobs.script_json` in SQLite |
| **2. Voice & Captions** | `workers/step2_audio_subs.py` | `kokoro-onnx` (`Kokoro-82M` / macOS `say` fallback) + `mlx-community/whisper-base-mlx` | ~2.0 GB | `data/jobs/<id>/voice.wav` & `subs.ass` |
| **3. Visuals (9:16)** | `workers/step3_images.py` | `mflux-generate` (`--model schnell --quantize 4 --steps 4 --width 768 --height 1344`) | ~10.0 GB | `data/jobs/<id>/images/scene_XX.png` |
| **4. Video Render** | `workers/step4_render.py` | `ffmpeg` (`zoompan` + `ass` filter + `-c:v h264_videotoolbox`) | ~2.0 GB | `data/jobs/<id>/final_short.mp4` |

## 5. Data Contracts & Schemas

### A. SQLite Database Schema (`data/factory.db`)
Must run with `PRAGMA journal_mode=WAL;` and `timeout=30.0` for container-to-host concurrency:
```sql
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_format TEXT DEFAULT 'short_9_16',
    subreddit TEXT DEFAULT 'UnresolvedMysteries',
    source_url TEXT UNIQUE,
    topic_title TEXT,
    status TEXT DEFAULT 'QUEUED',
    auto_mode INTEGER DEFAULT 1,
    script_json TEXT,
    audio_path TEXT,
    subs_path TEXT,
    video_path TEXT,
    error_msg TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### B. State Machine Transitions
- **Full Auto (`auto_mode = 1`):**
  `QUEUED` -> `1_GENERATING_SCRIPT` -> `2_GENERATING_AUDIO_SUBS` -> `3_GENERATING_IMAGES` -> `4_RENDERING_VIDEO` -> `COMPLETED`
- **Human-in-the-Loop (`auto_mode = 0`):**
  `QUEUED` -> `1_GENERATING_SCRIPT` -> `WAITING_SCRIPT_APPROVAL` -> `APPROVED_FOR_MEDIA` -> `2_GENERATING_AUDIO_SUBS` -> `3_GENERATING_IMAGES` -> `4_RENDERING_VIDEO` -> `COMPLETED`
- **Error Handling:** Any exception in any step transitions `status` to `FAILED` and records the traceback/error in `error_msg`.

### C. Strict LLM JSON Output Contract (`jobs.script_json`)
```json
{
  "title": "String (max 70 chars)",
  "narration": "String (90-130 words, strong 3-second hook in sentence 1, pure spoken text without stage directions)",
  "visual_prompts": [
    "Cinematic vertical 9:16 photo of ..., dramatic lighting, 8k",
    "... (5 to 8 scene prompts total)"
  ]
}
```
