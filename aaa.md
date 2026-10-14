# ARCHITECTURE.md — Crispfee Autonomous Clipper System

## 1. System Mission & Scope

`crispfee` is an autonomous clipping engine designed to monitor live streams (YouTube Live, TikTok Live, Instagram Live) and ingest long-form VODs (YouTube podcasts, interviews, stream replays). It identifies high-retention viral segments, dynamically crops 16:9 widescreen footage to 9:16 vertical video using active-speaker computer vision (single-subject tracking or dual-speaker vertical stack), burns kinetic word-level subtitles, and produces ready-to-post short-form vertical videos.

`crispfee` is a standalone system decoupled from synthetic generation tools, optimized exclusively for media processing, signal analysis, computer vision, and video compositing.

---

## 2. Infrastructure Target & Resource Budgets

### Target Environment: Linux VPS (No Dedicated GPU)

- **CPU:** 4 vCPU Cores
- **RAM:** 8 GB
- **Storage:** 100 GB SSD
- **Network:** 200 Mbit/s port, unmetered traffic
- **Runtime:** 100% containerized via Docker / Podman (`compose.yaml`)

### Memory & Process Guardrails

- **Max Peak System RAM:** ≤ 3.5 GB (leaves > 4.5 GB headroom for the OS and kernel buffers).
- **RAM Disk Buffering:** In-memory `/dev/shm` ring buffer for live stream segments to prevent SSD wear and disk I/O thrashing.
- **Offloaded LLM Processing:** Semantic transcript hook scoring is offloaded to fast cloud APIs (Gemini 2.5 Flash / Groq) via HTTPS (0 MB VPS RAM, ~0.4s response time).
- **Worker Concurrency:** Strictly 1 active FFmpeg render task at a time to keep CPU utilization within 4 vCPUs without queue stalling.

---

## 3. Technology Stack & Component Selection

| Subsystem                      | Technology / Library                                 | Execution Configuration                                                                                         | Memory Footprint              |
| :----------------------------- | :--------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------- | :---------------------------- |
| **Stream & VOD Ingestion**     | `yt-dlp`, `streamlink`, `TikTokLive`                 | Byte-range downloading (`--download-sections`), metadata & heatmap parsing (`--dump-json`), live HLS segmenting | ~90 MB                        |
| **Live Stream Buffer**         | Linux `/dev/shm` (tmpfs)                             | 5-minute rolling ring buffer of 10s `.ts` video chunks                                                          | ~250–350 MB per active stream |
| **Signal & Spike Detection**   | `numpy`, `scipy` (audio RMS), WebSocket chat clients | Rolling Z-score calculation on chat velocity (messages/sec) and audio peak energy                               | ~120 MB                       |
| **Speech-to-Text & Subtitles** | `faster-whisper` (CTranslate2)                       | `model_size="base"` or `"small"`, `compute_type="int8"`, `cpu_threads=3`, `vad_filter=True` (Silero VAD)        | ~850 MB                       |
| **Hook Scoring & Selection**   | Gemini 2.5 Flash API / Groq (`llama-3.3-70b`)        | JSON structured response extraction over HTTPS                                                                  | ~30 MB                        |
| **Face & Speaker Tracking**    | MediaPipe Face Detection (`BlazeFace`)               | Frame-subsampled processing (every 5th frame) + Exponential Moving Average (EMA) coordinate smoothing           | ~450 MB                       |
| **Compositing & Subtitles**    | `FFmpeg` + `.ass` (SubStation Alpha)                 | `-c:v libx264 -preset veryfast -crf 23`, dynamic cropping / `vstack`, kinetic 3-word pop-in text                | ~650 MB                       |
| **State & Persistence**        | `SQLite 3` (WAL Mode)                                | `PRAGMA journal_mode=WAL;` with 30s connection timeout                                                          | ~25 MB                        |
| **Dashboard UI**               | `Streamlit`                                          | Web UI exposed on port `8501`                                                                                   | ~300 MB                       |

---

## 4. End-to-End System Architecture

```text
                          ┌────────────────────────────────────────────────────────┐
                          │                    INGESTION LAYER                     │
                          │                                                        │
                          │   [YouTube/TikTok/IG Live]       [YouTube VOD / URL]   │
                          │              │                            │            │
                          │              ▼                            ▼            │
                          │     streamlink / TikTokLive        yt-dlp metadata     │
                          │              │                     & auto-subtitles    │
                          └──────────────┼────────────────────────────┼────────────┘
                                         │                            │
                                         ▼                            ▼
                          ┌──────────────────────────┐  ┌──────────────────────────┐
                          │  /dev/shm Rolling Buffer │  │  Heatmap Spike Analysis  │
                          │  (5-min circular FIFO)   │  │  + Transcript Extraction │
                          └──────────────┬───────────┘  └─────────────┬────────────┘
                                         │                            │
                                         ▼                            ▼
                          ┌──────────────────────────┐  ┌──────────────────────────┐
                          │  Chat & Audio RMS Spike  │  │   Gemini Flash API       │
                          │  Trigger (Z-score > 3.0) │  │   Viral Hook Selector    │
                          └──────────────┬───────────┘  └─────────────┬────────────┘
                                         │                            │
                                         └──────────────┬─────────────┘
                                                        │
                                                        ▼
                                         ┌─────────────────────────────┐
                                         │   Candidate Video Slices    │
                                         │   (30s–60s raw .mp4 clips)  │
                                         └──────────────┬──────────────┘
                                                        │
                                                        ▼
                                         ┌─────────────────────────────┐
                                         │       faster-whisper        │
                                         │  (int8, Silero VAD filter)  │
                                         │  -> Word-level timestamps   │
                                         └──────────────┬──────────────┘
                                                        │
                                                        ▼
                                         ┌─────────────────────────────┐
                                         │    MediaPipe Face Tracker   │
                                         │    - 1 Speaker: Smooth Pan  │
                                         │    - 2 Speakers: vstack     │
                                         └──────────────┬──────────────┘
                                                        │
                                                        ▼
                                         ┌─────────────────────────────┐
                                         │     FFmpeg Compositor       │
                                         │  - Crop / Layout execution  │
                                         │  - Kinetic .ass subtitle in │
                                         │  - libx264 veryfast encode  │
                                         └──────────────┬──────────────┘
                                                        │
                                                        ▼
                                         ┌─────────────────────────────┐
                                         │     Streamlit Dashboard     │
                                         │  Review, Preview, & Export  │
                                         └─────────────────────────────┘
```

---

## 5. Core Processing Workflows

### Workflow A: Pre-Recorded VOD Processing (YouTube Podcast / Video -> Shorts)

1. **Metadata & Heatmap Scan:**

- Worker queries `yt-dlp --dump-json --skip-download <url>`.
- Extracts YouTube "Most Replayed" curve (`heatmap` data array) and auto-caption transcripts.
- If auto-captions do not exist, worker streams low-bitrate audio (`-f 140` / 64kbps mono) and processes it via `faster-whisper` (`int8`).

2. **Hook Selection:**

- Sends the transcript with timestamped heatmap peaks to Gemini Flash API.
- The LLM returns a structured JSON list of the top $N$ viral segments (start time, end time, hook title, virality score).

3. **Partial Byte-Range Download:**

- Uses `yt-dlp --download-sections "*start_time-end_time"` to fetch only the required 30–60 second video chunks, saving network bandwidth and disk space.

4. **Subtitles & Reframing:**

- Transcribes the slice using `faster-whisper` to obtain exact word boundaries and builds an `.ass` subtitle file.
- Evaluates frame topology with MediaPipe to determine single-speaker crop vs. two-speaker vertical split.
- FFmpeg renders the final `768x1344` 9:16 `.mp4`.

### Workflow B: Live Stream Monitoring (YouTube, TikTok, Instagram Live)

1. **Ring Buffer Storage:**

- Streams are captured into `/dev/shm/crispfee/<stream_id>/` in continuous 10-second `.ts` chunks.
- A cleanup worker purges chunks older than 5 minutes to keep RAM usage constant.

2. **Multi-Signal Spike Detection:**

- **Audio Channel:** Computes Root Mean Square (RMS) volume and spectral flatness in 2-second windows to flag shouting, cheering, or sudden audio surges.
- **Chat Channel:** Connects via chat scraper/WebSocket. Monitors messages-per-second velocity. A rolling Z-score $> 3.0$ combined with emoji bursts (`💀`, `🔥`, `LMAO`, `W`, `L`) triggers an event.

3. **Clip Packaging:**

- When a spike fires, the engine stitches the preceding 45 seconds and following 15 seconds from `/dev/shm` into an `.mp4` candidate.
- The candidate enters the transcription, face-tracking, and rendering pipeline.

## 6. Active-Speaker Computer Vision & Cropping Logic

Standard center-cropping cuts off subjects in 16:9 widescreen footage. `crispfee` applies adaptive framing based on MediaPipe face detections:

```text
Source Frame (16:9)
┌────────────────────────────────────────────────────────┐
│         [Speaker A]                [Speaker B]         │
└────────────────────────────────────────────────────────┘

```

### Scenario 1: Single Speaker Detected

- The target crop window is calculated with a 9:16 aspect ratio:

$$\text{crop\_width} = \text{height} \times \frac{9}{16}$$

- Let $X_{\text{raw}}$ be the horizontal center of the detected face bounding box.
- To prevent camera jitter, the horizontal crop coordinate $X_t$ is smoothed over time $t$ via an Exponential Moving Average (EMA):

$$X_t = \alpha \cdot X_{\text{raw}} + (1 - \alpha) \cdot X_{t-1} \quad (\text{where } \alpha \approx 0.15)$$

- If no face is detected in an individual frame, $X_t$ holds its previous position.

### Scenario 2: Two Distinct Speakers Detected (Podcast / Interview Setup)

- If two primary faces are detected separated by more than 35% of the frame width:
- **Top Half (`768x672`):** Cropped around Speaker A.
- **Bottom Half (`768x672`):** Cropped around Speaker B.
- Assembled using the FFmpeg filter `[top][bottom]vstack=inputs=2`.
- Word-level animated captions are centered directly over the dividing line between the two video feeds.

---

## 7. Database State Machine (`db.py`)

SQLite runs in WAL mode to allow non-blocking concurrent reads and writes between the Streamlit UI and background processing workers:

```sql
-- Tracked live streams or long-form video sources
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,         -- 'youtube_vod', 'youtube_live', 'tiktok_live', 'ig_live', 'upload'
    url TEXT UNIQUE,
    title TEXT,
    channel_name TEXT,
    status TEXT DEFAULT 'ACTIVE',      -- 'ACTIVE', 'IDLE', 'OFFLINE', 'COMPLETED'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Generated candidate and final clips
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES sources(id),
    title TEXT,
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    virality_score INTEGER,
    trigger_reason TEXT,               -- 'heatmap_peak', 'chat_spike', 'audio_surge', 'manual'
    status TEXT DEFAULT 'QUEUED',      -- 'QUEUED', 'TRANSCRIBING', 'CROPPING', 'RENDERING', 'READY', 'FAILED'
    raw_slice_path TEXT,
    transcript_json TEXT,
    subs_path TEXT,
    final_video_path TEXT,
    error_msg TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

```

---

## 8. Docker Deployment Blueprint (`compose.yaml`)

```yaml
version: "3.9"

services:
  crispfee:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: crispfee_engine
    restart: unless-stopped
    ports:
      - "8501:8501"
    volumes:
      - ./data:/app/data:Z
      - /dev/shm:/dev/shm:Z # Access to host RAM disk for live stream chunks
    environment:
      - DB_PATH=/app/data/crispfee.db
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - GROQ_API_KEY=${GROQ_API_KEY}
      - WHISPER_MODEL=base
      - WHISPER_THREADS=3
      - PYTHONUNBUFFERED=1
    deploy:
      resources:
        limits:
          cpus: "3.80"
          memory: 6.5G
```

---

## 9. Directory Structure Contract

```text
crispfee/
├── ARCHITECTURE.md               # This architectural specification
├── PRODUCT.md                    # Functional requirements & user stories
├── AGENTS.md                     # Agent coding rules, guardrails, & testing requirements
├── compose.yaml                  # Docker Compose configuration
├── Dockerfile                    # Python 3.11 + FFmpeg + CTranslate2 dependencies
├── requirements.txt              # Production Python package manifest
├── config.py                     # Global paths, API keys, and parameter thresholds
├── db.py                         # SQLite interface with WAL mode and schema setup
├── app.py                        # Streamlit web UI (VOD input, Live monitor, Clip review)
├── orchestrator.py               # Worker queue scheduler supporting the --once CLI flag
├── core/
│   ├── metadata_extractor.py     # yt-dlp metadata, heatmap, and subtitle fetcher
│   ├── viral_scorer.py           # Gemini/Groq prompt runner for timestamp selection
│   ├── transcriber.py            # faster-whisper int8 worker producing word timestamps
│   ├── face_tracker.py           # MediaPipe face detection and EMA coordinate smoothing
│   ├── subtitle_builder.py       # Kinetic 3-word pop-in .ass subtitle generator
│   └── compositor.py             # FFmpeg dynamic cropping (single pan vs dual-stack vstack)
├── live/
│   ├── stream_recorder.py        # Streamlink live stream HLS ring buffer manager in /dev/shm
│   └── spike_detector.py         # Audio RMS and chat rate spike detection engine
└── tests/
    ├── conftest.py               # Temporary test DB fixtures and mock video generators
    ├── unit/
    │   ├── test_db.py
    │   ├── test_viral_scorer.py
    │   ├── test_face_tracker.py
    │   └── test_subtitle_builder.py
    └── e2e/
        ├── test_vod_pipeline_fast.py
        └── test_live_slice_fast.py

```

```

```

```

```
