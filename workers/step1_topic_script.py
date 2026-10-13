import argparse
import json
import re
import requests
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from db import get_job, update_job, get_conn
from mlx_lm import load, generate

MODEL_ID = "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"

def fetch_unused_reddit_topic(subreddit):
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=week&limit=25"
    headers = {"User-Agent": "MacM5VideoBot/1.0"}
    resp = requests.get(url, headers=headers, timeout=15)
    posts = resp.json().get("data", {}).get("children", [])

    with get_conn() as conn:
        used_urls = {r["source_url"] for r in conn.execute("SELECT source_url FROM jobs WHERE source_url IS NOT NULL")}

    for p in posts:
        data = p["data"]
        if not data.get("stickied") and data.get("url") not in used_urls and len(data.get("selftext", "")) > 200:
            return data["title"], data["selftext"][:2500], data["url"]

    return "The Unexplained Disappearance of Flight 19", "In December 1945, five Avenger torpedo bombers vanished over the Bermuda Triangle...", f"custom://{subreddit}"

def main(job_id):
    job = get_job(job_id)
    job_dir = Path(f"data/jobs/{job_id}")
    job_dir.mkdir(parents=True, exist_ok=True)

    if job["topic_title"]:
        title, content, url = job["topic_title"], job["topic_title"], f"manual://{job_id}"
    else:
        title, content, url = fetch_unused_reddit_topic(job["subreddit"])

    model, tokenizer = load(MODEL_ID)

    prompt = f"""You are a viral short-form video scriptwriter. Turn the following story into a gripping 45-second vertical video script.
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

    messages = [{"role": "user", "content": prompt}]
    formatted = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    raw_output = generate(model, tokenizer, prompt=formatted, max_tokens=900, verbose=False)

    match = re.search(r"\{.*\}", raw_output, re.DOTALL)
    if not match:
        raise ValueError(f"LLM did not return valid JSON: {raw_output}")

    script_data = json.loads(match.group(0))
    update_job(
        job_id,
        topic_title=script_data.get("title", title),
        source_url=url,
        script_json=json.dumps(script_data, indent=2)
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job_id", type=int, required=True)
    args = parser.parse_args()
    main(args.job_id)
