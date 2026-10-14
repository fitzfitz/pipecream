"""Step 1 — Topic mining + LLM script generation (mlx-lm).

Heavy imports (`mlx_lm`, `requests`) are deferred into the functions that need
them so pure helpers like `extract_script_json` can be unit-tested and
`DRY_RUN_AI=1` never touches the network or loads model weights.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from db import get_conn, get_job, get_job_dir, update_job  # noqa: E402

MODEL_ID = "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
REQUIRED_KEYS = ("title", "narration", "visual_prompts")
MAX_TITLE_CHARS = 70
MIN_SELFTEXT_CHARS = 200

DRY_RUN_SCRIPT = {
    "title": "The Lighthouse Keepers Who Vanished",
    "narration": (
        "Three men vanished from a locked lighthouse and nobody knows why. "
        "In December 1900 a relief ship reached Eilean Mor and found the gate shut, "
        "the beds unmade, and the clocks stopped. "
        "The final logbook entry read simply: God is over all."
    ),
    "visual_prompts": [
        "Cinematic vertical 9:16 photo of a lonely stone lighthouse on a storm-battered cliff, dramatic lighting, 8k",
        "Cinematic vertical 9:16 close up of an open logbook beside a stopped clock, candlelight, 8k",
        "Cinematic vertical 9:16 wide shot of an empty rocky landing at dusk, moody fog, 8k",
    ],
}


def is_dry_run():
    return os.environ.get("DRY_RUN_AI") == "1"


def extract_script_json(raw_text):
    """Extract and validate the script JSON object from raw LLM output.

    Handles ```json fenced blocks and surrounding chatter. Raises ValueError if no
    JSON object is found or the schema contract (PRODUCT.md §5C) is violated.
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("LLM returned empty output")

    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw_text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else raw_text

    match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if not match:
        raise ValueError(f"LLM did not return a JSON object: {raw_text[:300]!r}")

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned malformed JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Script JSON must be an object")

    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"Script JSON missing required key(s): {missing}")

    for key in ("title", "narration"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"Script JSON '{key}' must be a non-empty string")

    prompts = data["visual_prompts"]
    if not isinstance(prompts, list) or not prompts:
        raise ValueError("Script JSON 'visual_prompts' must be a non-empty list")
    if not all(isinstance(p, str) and p.strip() for p in prompts):
        raise ValueError("Every entry in 'visual_prompts' must be a non-empty string")

    data["title"] = data["title"].strip()[:MAX_TITLE_CHARS]
    data["narration"] = data["narration"].strip()
    data["visual_prompts"] = [p.strip() for p in prompts]
    return data


def fetch_unused_reddit_topic(subreddit, job_id):
    import requests  # deferred: not needed in DRY_RUN_AI mode

    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=week&limit=25"
    headers = {"User-Agent": "MacM5VideoBot/1.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        posts = resp.json().get("data", {}).get("children", [])
    except Exception as e:
        print(f"⚠️ Reddit fetch failed ({e}); using fallback topic.", flush=True)
        posts = []

    with get_conn() as conn:
        used_urls = {r["source_url"] for r in conn.execute("SELECT source_url FROM jobs WHERE source_url IS NOT NULL")}

    for p in posts:
        data = p.get("data", {})
        if (
            not data.get("stickied")
            and data.get("is_self", True)
            and data.get("url") not in used_urls
            and len(data.get("selftext", "")) >= MIN_SELFTEXT_CHARS
        ):
            return data["title"], data["selftext"][:2500], data["url"]

    # Fallback URL is per-job so it never collides with the UNIQUE(source_url) constraint.
    return (
        "The Unexplained Disappearance of Flight 19",
        "In December 1945, five Avenger torpedo bombers vanished over the Bermuda Triangle...",
        f"fallback://{subreddit}/{job_id}",
    )


def build_prompt(title, content):
    return f"""You are a viral short-form video scriptwriter. Turn the following story into a gripping 45-second vertical video script.
Story Title: {title}
Source Material: {content}

Respond ONLY with valid JSON in this exact format:
{{
  "title": "Short catchy title",
  "narration": "Full continuous voiceover script (approx 110 words, punchy, strong hook in sentence 1, no stage directions).",
  "visual_prompts": [
    "Cinematic vertical 9:16 dark atmospheric photo of ..., 8k, photorealistic",
    "Cinematic vertical 9:16 close up shot of ..., dramatic lighting",
    "Cinematic vertical 9:16 eerie wide angle of ..., moody fog",
    "Cinematic vertical 9:16 mysterious scene of ..., high contrast",
    "Cinematic vertical 9:16 dramatic final reveal of ..., ultra detailed"
  ]
}}"""


def generate_script_with_mlx(title, content):
    from mlx_lm import generate, load  # deferred: heavy Metal/GPU import

    model, tokenizer = load(MODEL_ID)
    messages = [{"role": "user", "content": build_prompt(title, content)}]
    formatted = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    raw_output = generate(model, tokenizer, prompt=formatted, max_tokens=900, verbose=False)
    return extract_script_json(raw_output)


def main(job_id):
    job = get_job(job_id)
    if job is None:
        raise SystemExit(f"Job #{job_id} not found")
    get_job_dir(job_id).mkdir(parents=True, exist_ok=True)

    if is_dry_run():
        script_data = dict(DRY_RUN_SCRIPT)
        url = job["source_url"] or f"dryrun://{job_id}"
        title = script_data["title"]
    else:
        if job["topic_title"]:
            title, content, url = job["topic_title"], job["topic_title"], f"manual://{job_id}"
        else:
            title, content, url = fetch_unused_reddit_topic(job["subreddit"], job_id)
        script_data = generate_script_with_mlx(title, content)

    update_job(
        job_id,
        topic_title=script_data.get("title", title),
        source_url=url,
        script_json=json.dumps(script_data, indent=2),
    )


if __name__ == "__main__":
    from worker_cli import run_worker_cli
    run_worker_cli(main)
