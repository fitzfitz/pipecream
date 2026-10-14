# 🎬 Autonomous M5 AI Video Factory

An end-to-end, zero-variable-cost ($0/month) autonomous vertical video factory engineered specifically for **Apple Silicon (MacBook Pro M5 with 24GB Unified Memory)**.

Generates high-retention vertical short-form videos (**9:16 vertical, 768×1344**, 40–60s) for YouTube Shorts, TikTok, and Instagram Reels with **100% local AI models** on Apple Metal GPU.

---

## 🏗️ Architecture

```
                       ┌──────────────────────────────────────────────┐
                       │           CONTAINER LAYER (Podman)           │
                       │                                              │
                       │   Streamlit Dashboard (8501)    n8n (5678)   │
                       └──────────────────────┬───────────────────────┘
                                              │ mounts ./data (:Z)
                                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      NATIVE MACOS HOST (.venv)                      │
│                                                                     │
│                           SQLite Database                           │
│                         (data/factory.db)                           │
│                                 ▲                                   │
│                                 │ claims jobs                       │
│                        orchestrator.py                              │
│                                 │ executes isolated subprocesses    │
│                                 ▼                                   │
│  ┌──────────────────────┬─────────────────────┬──────────────────┐  │
│  │ Step 1: Script       │ Step 2: Audio & Subs│ Step 3: Images   │  │
│  │ Llama 3.1 8B 4-bit   │ Kokoro + Whisper    │ FLUX.1-schnell   │  │
│  │ (mlx-lm) ~5.5 GB     │ (mlx-whisper) ~2 GB │ (mflux) ~10 GB   │  │
│  └──────────────────────┴─────────────────────┴──────────────────┘  │
│                                 │                                   │
│                                 ▼                                   │
│                      Step 4: Video Render                           │
│                  FFmpeg + VideoToolbox (h264)                       │
│                     (data/jobs/<id>/final_short.mp4)                │
└─────────────────────────────────────────────────────────────────────┘
```

### Why Hybrid Host + Container?
- **Unified Memory Protection**: On Apple Silicon, RAM is shared between CPU and GPU. Models are isolated into separate subprocesses so macOS reclaims 100% of GPU/Unified Memory after each step completes.
- **Metal Acceleration**: Docker/Podman on macOS runs in a Linux VM without access to Apple's Metal GPU accelerators. Heavy AI workers run natively on macOS, while lightweight web UIs run in rootless Podman containers.

---

## 📋 Prerequisites

1. **Apple Silicon Mac** (M1/M2/M3/M4/M5 with 16GB+ Unified Memory, 24GB recommended).
2. **Homebrew & FFmpeg** (compiled with `libass` and `videotoolbox`):
   ```bash
   brew install ffmpeg
   ```
3. **Podman** (or Docker Desktop):
   ```bash
   brew install podman podman-compose
   ```
4. **Python 3.10+** (Python 3.11 or 3.12 recommended).

---

## 🚀 Quick Setup Guide

### 1. Start the Container Services (Podman)
```bash
# Start your Podman machine if not already running
podman machine start

# Launch the Streamlit Dashboard and n8n services
podman compose up -d
```
- **Streamlit Control Dashboard**: [http://localhost:8501](http://localhost:8501)
- **n8n Automation Engine**: [http://localhost:5678](http://localhost:5678)

### 2. Set Up the Native Python Environment
```bash
# Run the automated setup script
chmod +x start_mac.sh
./start_mac.sh

# Or setup manually:
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-mac.txt
pip install -r requirements-dev.txt
```

### 3. (Optional) Kokoro TTS Voice Weights
If using Kokoro ONNX high-quality TTS instead of macOS `say`:
- Place `kokoro-v1.0.onnx` into `assets/`
- Place `voices-v1.0.bin` into `assets/`

---

## 🧪 Testing & Verification

### Run Fast Test Suite (Takes ~5s, No Weights Needed)
The repository includes deterministic dry-run mode (`DRY_RUN_AI=1`) that tests the entire pipeline using synthetic sine audio and solid frames:

```bash
# Run all unit tests and fast E2E tests
DRY_RUN_AI=1 pytest -v -m "not mlx_hardware"
```

### Run a Single Job in Dry-Run Mode
```bash
# Queue and process at most one job, then exit
DRY_RUN_AI=1 python orchestrator.py --once
```

---

## 🎬 Production Usage

### 1. Launch the Orchestrator Daemon
On your macOS host terminal (with `.venv` active):
```bash
python orchestrator.py
```
The orchestrator continuously monitors `data/factory.db` for new jobs.

### 2. Queueing Jobs via Dashboard
Open [http://localhost:8501](http://localhost:8501):
- **Topic Source**: Choose **Auto-Scrape Reddit** (e.g. `r/UnresolvedMysteries`, `r/TrueOffMyChest`) or **Custom Topic / Idea**.
- **Execution Mode**:
  - **Full Auto-Pilot (`auto_mode=1`)**: Pipeline runs autonomously from topic discovery to the final `.mp4`.
  - **Human-in-the-Loop (`auto_mode=0`)**: Orchestrator pauses after Step 1 at `WAITING_SCRIPT_APPROVAL`. Review, edit script JSON & image prompts in the **Script Review** tab, and click **Approve & Render Video** to resume.

---

## 📁 Project Structure

```
├── compose.yaml                # Podman/Docker Compose config (:Z volume flags)
├── Dockerfile.dashboard        # Lightweight container image for Streamlit UI
├── dashboard.py                # 3-tab Streamlit web application
├── orchestrator.py             # Subprocess orchestrator with --once flag
├── db.py                       # SQLite state layer with WAL mode
├── requirements-mac.txt        # Native Apple Silicon MLX & AI dependencies
├── requirements-docker.txt     # Lightweight UI container dependencies
├── requirements-dev.txt        # Test dependencies (pytest)
├── pytest.ini                  # Pytest configuration & markers
├── workers/
│   ├── step1_topic_script.py   # Reddit scraping + Llama 3.1 8B (mlx-lm)
│   ├── step2_audio_subs.py     # Kokoro/say TTS + Whisper word timings (mlx-whisper)
│   ├── step3_images.py         # 9:16 vertical images via FLUX.1-schnell (mflux)
│   ├── step4_render.py         # Ken Burns zoompan + ASS subtitle burn-in (FFmpeg)
│   └── worker_cli.py           # Shared worker CLI error handler
└── tests/
    ├── conftest.py             # Shared fixtures (temp_db)
    ├── unit/                   # Unit test suite
    └── e2e/                    # Fast E2E & MLX hardware tests
```

---

## ⚙️ Environment Variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `DRY_RUN_AI` | `0` | Set to `1` to run synthetic fast pipeline without loading MLX weights. |
| `DB_PATH` | `data/factory.db` | Path to the SQLite database file. |
| `DATA_DIR` | `data` | Directory where job artifacts (audio, images, video) are saved. |
| `FFMPEG_BIN` | `ffmpeg` | Path to `ffmpeg` binary (useful if using custom Homebrew keg). |
| `FFPROBE_BIN` | `ffprobe` | Path to `ffprobe` binary. |
| `VIDEO_ENCODER` | Auto (`h264_videotoolbox` -> `libx264`) | Override FFmpeg video encoder. |
