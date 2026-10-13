# AGENTS.md — Instructions for Antigravity (Gemini Flash / Coding Agents)

Read `PRODUCT.md` first. You are building and maintaining the **Autonomous M5 AI Video Factory**. Follow every rule and verification gate below strictly.

## 1. Hard Execution & Hardware Guardrails (NEVER VIOLATE)

1. **NEVER Run Infinite Daemons Without `--once` in Agent Terminals:**
   - `orchestrator.py` must support a `--once` CLI flag (`python orchestrator.py --once`) that processes at most one job and exits cleanly.
   - **CRITICAL:** When testing or verifying via your terminal tool, ALWAYS use `python orchestrator.py --once` or `pytest`. Never run an unbounded `while True` loop or `streamlit run` in a foreground tool call, or your agent session will hang indefinitely.
2. **Strict Subprocess Isolation (24GB Unified Memory Protection):**
   - Never import `mlx`, `mlx_lm`, `mlx_whisper`, `mflux`, or `kokoro_onnx` inside `orchestrator.py`, `dashboard.py`, or `db.py`.
   - `orchestrator.py` must invoke each `workers/stepX_*.py` script via `subprocess.run([sys.executable, ...], check=True)`. When a worker exits, macOS reclaims 100% of GPU/Unified Memory.
3. **Hybrid Container Boundary:**
   - `Dockerfile.dashboard` and `compose.yaml` must ONLY install lightweight UI packages (`requirements-docker.txt`: `streamlit`, `pandas`, `requests`).
   - Never put `mlx` or Apple Silicon packages inside `Dockerfile.dashboard` (Linux containers cannot run Apple Metal/MLX).
   - Keep `:Z` volume suffixes in `compose.yaml` for Podman and Docker compatibility.
4. **Mandatory `DRY_RUN_AI=1` Mode in All Workers:**
   - Every worker (`step1` through `step3`) MUST check `os.environ.get("DRY_RUN_AI") == "1"`.
   - When `DRY_RUN_AI=1`:
     - `step1_topic_script.py`: Skips Reddit network call and `mlx_lm` load; writes a valid deterministic 3-scene `script_json` to SQLite in under 0.1s.
     - `step2_audio_subs.py`: Generates a valid 3-second `.wav` file using `ffmpeg -y -f lavfi -i "sine=frequency=440:duration=3" ...` and writes a valid 3-line `.ass` subtitle file without loading `mlx-whisper`.
     - `step3_images.py`: Generates valid `768x1344` `.png` files for each scene using `ffmpeg -y -f lavfi -i "color=c=navy:s=768x1344:d=1" -frames:v 1 ...` without loading `mflux`.
     - `step4_render.py`: Always runs the **REAL** FFmpeg `zoompan`, `.ass` burn-in, and video encoding (`h264_videotoolbox` on macOS, with automatic fallback to `libx264` if `h264_videotoolbox` is unavailable).

## 2. Step-by-Step Implementation & Verification Plan

Whenever setting up, auditing, or extending this repository, execute these phases in exact order:

### Phase 1: Core State & Database Layer (`db.py`)
- Ensure `init_db()` enables WAL mode (`conn.execute("PRAGMA journal_mode=WAL;")`).
- Implement `create_job()`, `update_job()`, `get_job()`, `list_jobs()`.
- **Verify:** Run `pytest tests/unit/test_db.py`.

### Phase 2: Worker Scripts with `DRY_RUN_AI=1` & Real MLX Support (`workers/`)
- Implement `step1_topic_script.py`, `step2_audio_subs.py`, `step3_images.py`, and `step4_render.py`.
- Extract pure helper functions (`extract_script_json(raw_text)`, `format_ass_time(seconds)`, `generate_ass_subtitles(segments, ass_path)`) so they can be imported by unit tests without triggering model imports.
- Ensure FFmpeg `.ass` filter path escaping handles colons and spaces safely on macOS.
- **Verify:** Run `pytest tests/unit/test_script_parser.py tests/unit/test_ass_subtitles.py`.

### Phase 3: Orchestrator with `--once` Flag (`orchestrator.py`)
- Implement `process_next_job()` supporting both `auto_mode=1` (full pipeline) and `auto_mode=0` (pauses at `WAITING_SCRIPT_APPROVAL`, resumes when status is `APPROVED_FOR_MEDIA`).
- Add `argparse` support for `--once` (processes one job and exits).
- **Verify:** Run `pytest tests/unit/test_orchestrator_state.py`.

### Phase 4: Streamlit Control Dashboard & Containerization (`dashboard.py`, `compose.yaml`)
- Build the 3-tab Streamlit UI (`Live Pipeline Queue`, `Script Review`, `Completed Videos`) plus Sidebar Job Launcher.
- Ensure `Dockerfile.dashboard` and `compose.yaml` are valid.
- **Verify:** Run `pytest tests/e2e/test_pipeline_fast_e2e.py`.

## 3. Testing Requirements (Definition of Done)

You must maintain 100% passing tests across both suites:

1. **Unit Tests (`tests/unit/`):**
   - `test_db.py`: CRUD, WAL mode check, `source_url` UNIQUE constraint, status updates.
   - `test_script_parser.py`: Valid JSON extraction from LLM markdown blocks, missing key rejection.
   - `test_ass_subtitles.py`: Timestamp formatting (`0:00:00.00`), 3-word uppercase chunking, `.ass` header resolution (`768x1344`).
   - `test_orchestrator_state.py`: Subprocess call order, `auto_mode=0` pause behavior, failure capture (`status='FAILED'`, `error_msg` populated).
2. **End-to-End Tests (`tests/e2e/`):**
   - `test_pipeline_fast_e2e.py`: Sets `DRY_RUN_AI=1` and a temporary SQLite DB, creates a job, runs `orchestrator.process_next_job()`, and uses `ffprobe` to verify `final_short.mp4` exists, is `768x1344`, has `h264` video + `aac` audio streams, and duration greater than 2.0s. Also tests `dashboard.py` using `streamlit.testing.v1.AppTest`.
   - `test_pipeline_full_mlx.py` (marked `@pytest.mark.mlx_hardware`): Runs a full unmocked generation on the M5 GPU.

## 4. Standard Commands for the Agent
```bash
# Run fast unit + E2E suite (takes under 10 seconds, no GPU weight downloads required)
DRY_RUN_AI=1 pytest -v -m "not mlx_hardware"

# Run a single job through the orchestrator in dry-run mode and exit immediately
DRY_RUN_AI=1 python orchestrator.py --once

# Run full M5 hardware E2E test (requires MLX weights downloaded)
pytest -v -m "mlx_hardware"
```
