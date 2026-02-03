"""Generate a cat image using nanobanana-py, upload as GitHub Release asset. Run by GitHub Actions hourly."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROMPT_META = (
    "You are a creative storyteller AND prompt engineer for AI image generation. "
    "Your task is to create both a story and an image prompt that match each other.\n\n"
    "Requirements:\n"
    "(1) A cat must be the subject or prominently featured in the image\n"
    "(2) The date and time '{timestamp}' must be visually displayed in the image\n"
    "(3) The image content MUST match the story - if the story describes a scene, the image should show that scene\n"
    "(4) Use varied styles (photography, painting, illustration, etc.), unique scenes, interesting compositions\n"
    "(5) Do NOT include any resolution keywords (like 4K, 8K, 16K, etc.) in the prompt\n"
    "(6) If previous stories are provided, your new story should SUBTLY CONTINUE or EXTEND the narrative - "
    "perhaps the cat goes somewhere new, meets someone, or the next moment in their journey. "
    "However, the cat's appearance and art style MUST be different from previous images.\n\n"
    "{recent_section}"
    "Output a JSON object with exactly this format:\n"
    '{{"prompt": "English image prompt here", "story": "繁體中文短故事，2-3句"}}\n\n'
    "The story should be in Traditional Chinese, 2-3 sentences, describing what the cat is doing in the scene. "
    "The image prompt should create a visual that matches the story content."
)

REPO = os.environ.get("GITHUB_REPOSITORY", "yazelin/catime")
RELEASE_TAG = "cats"


def get_recent_context(n: int = 10) -> dict:
    """Return the last n prompts and stories from catlist.json."""
    catlist_path = Path("catlist.json")
    if not catlist_path.exists():
        return {'prompts': [], 'stories': []}
    cats = json.loads(catlist_path.read_text())
    valid_cats = [c for c in cats if c.get("prompt")][-n:]
    return {
        'prompts': [c["prompt"] for c in valid_cats],
        'stories': [c.get("story", "") for c in valid_cats if c.get("story")]
    }


def parse_ai_response(text: str) -> dict:
    """Parse AI response that may contain JSON with prompt and story."""
    import re
    text = text.strip()

    # Try to extract JSON from markdown code block
    code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if code_block_match:
        text = code_block_match.group(1)

    # Try to parse as JSON
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "prompt" in data:
            return {
                'prompt': data.get("prompt", ""),
                'story': data.get("story", "")
            }
    except json.JSONDecodeError:
        pass

    # Fallback: treat entire text as prompt
    return {'prompt': text, 'story': ''}


def generate_prompt_and_story(timestamp: str) -> dict:
    """Use Gemini text model to generate a creative image prompt and story."""
    context = get_recent_context(10)
    recent_prompts = context['prompts']
    recent_stories = context['stories']

    recent_section = ""
    if recent_prompts:
        bullets = "\n".join(f"- {p}" for p in recent_prompts)
        recent_section = (
            "IMPORTANT: Here are the most recent prompts used. "
            "Avoid similar themes, styles, settings, and compositions:\n"
            f"{bullets}\n\n"
        )
    if recent_stories:
        story_bullets = "\n".join(f"- {s}" for s in recent_stories[-5:])
        recent_section += (
            "Here are recent stories. You may subtly extend the narrative thread, "
            "but the cat's appearance and art style should be different:\n"
            f"{story_bullets}\n\n"
        )

    print(f"Generating prompt with {len(recent_prompts)} recent prompts and {len(recent_stories)} stories as context...")
    try:
        from google import genai

        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=PROMPT_META.format(timestamp=timestamp, recent_section=recent_section),
        )
        result = parse_ai_response(response.text)
        if result['prompt']:
            print(f"AI-generated prompt: {result['prompt'][:120]}...")
            if result['story']:
                print(f"AI-generated story: {result['story'][:80]}...")
            return result
    except Exception as e:
        print(f"Prompt generation failed ({e}), using fallback.")

    return {
        'prompt': f"A cute cat with the date and time '{timestamp}' displayed in the image, high quality, detailed",
        'story': "一隻可愛的貓咪正在享受美好的一天。"
    }


async def generate_cat_image(output_dir: str, timestamp: str, prompt: str) -> dict:
    """Use nanobanana-py's ImageGenerator to generate a cat image."""
    from nanobanana_py.image_generator import ImageGenerator
    from nanobanana_py.types import ImageGenerationRequest

    generator = ImageGenerator()

    request = ImageGenerationRequest(
        prompt=prompt,
        filename=f"cat_{timestamp.replace(' ', '_').replace(':', '')}",
        resolution="1K",
        file_format="png",
        parallel=1,
        output_count=1,
    )

    os.environ["NANOBANANA_OUTPUT_DIR"] = output_dir
    response = await generator.generate_text_to_image(request)

    if not response.success:
        return {
            "file_path": None,
            "model_used": None,
            "status": "failed",
            "error": f"{response.message} - {response.error}",
        }

    model_info = response.model_used or "unknown"
    if response.used_fallback:
        model_info += f" (fallback from {response.primary_model}, reason: {response.fallback_reason})"

    return {
        "file_path": response.generated_files[0],
        "model_used": model_info,
        "status": "success",
    }


def ensure_release_exists():
    """Create the 'cats' release if it doesn't exist."""
    result = subprocess.run(
        ["gh", "release", "view", RELEASE_TAG, "--repo", REPO],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        subprocess.run(
            [
                "gh", "release", "create", RELEASE_TAG,
                "--repo", REPO,
                "--title", "Cat Images",
                "--notes", "Auto-generated cat images, one every hour.",
            ],
            check=True,
        )


def upload_image_as_release_asset(image_path: str) -> str:
    """Upload image as a GitHub Release asset. Returns the public download URL."""
    filename = Path(image_path).name

    subprocess.run(
        [
            "gh", "release", "upload", RELEASE_TAG,
            image_path,
            "--repo", REPO,
            "--clobber",
        ],
        check=True,
    )

    # Release asset URL format
    return f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{filename}"


def get_or_create_monthly_issue(now: datetime) -> str:
    """Get or create a monthly issue for cat images. Returns issue number as string."""
    month_label = now.strftime("%Y-%m")
    title = f"Cat Gallery - {month_label}"

    # Search for existing issue with this title
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--search", f'"{title}" in:title', "--json", "number,title", "--limit", "10"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        issues = json.loads(result.stdout)
        for issue in issues:
            if issue["title"] == title:
                return str(issue["number"])

    # Create new monthly issue
    result = subprocess.run(
        ["gh", "issue", "create", "--repo", REPO, "--title", title, "--body", f"Auto-generated cat images for {month_label}."],
        capture_output=True, text=True, check=True,
    )
    # Extract issue number from URL output
    url = result.stdout.strip()
    return url.split("/")[-1]


def post_issue_comment(issue_number: str, image_url: str, number: int, timestamp: str, model_used: str, prompt: str = "", story: str = ""):
    """Post a comment on the monthly issue with the cat image."""
    prompt_line = f"**Prompt:** {prompt}\n" if prompt else ""
    story_line = f"**Story:** {story}\n" if story else ""
    body = (
        f"## Cat #{number}\n"
        f"**Time:** {timestamp}\n"
        f"**Model:** `{model_used}`\n"
        f"{prompt_line}"
        f"{story_line}\n"
        f"![cat-{number}]({image_url})"
    )
    subprocess.run(
        ["gh", "issue", "comment", issue_number, "--repo", REPO, "--body", body],
        check=True,
    )


def update_catlist_and_push(entry: dict) -> int:
    """Update catlist.json, commit and push (only JSON, no images)."""
    catlist_path = Path("catlist.json")
    cats = json.loads(catlist_path.read_text()) if catlist_path.exists() else []
    cats.append(entry)
    catlist_path.write_text(json.dumps(cats, indent=2, ensure_ascii=False) + "\n")

    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=True,
    )
    subprocess.run(["git", "add", "catlist.json"], check=True)

    status = entry["status"]
    number = entry.get("number")
    timestamp = entry["timestamp"]
    msg = f"Add cat #{number} - {timestamp}" if status == "success" else f"Failed cat - {timestamp}"
    subprocess.run(["git", "commit", "-m", msg], check=True)

    # Retry push with rebase in case of concurrent pushes
    for attempt in range(3):
        result = subprocess.run(["git", "push"], capture_output=True, text=True)
        if result.returncode == 0:
            break
        print(f"Push failed (attempt {attempt + 1}), rebasing...")
        subprocess.run(["git", "pull", "--rebase"], check=True)
    else:
        raise RuntimeError("Failed to push after 3 attempts")
    return number or 0


def already_has_cat_this_hour(now: datetime) -> bool:
    """Check if a successful cat already exists for the current hour."""
    catlist_path = Path("catlist.json")
    if not catlist_path.exists():
        return False
    cats = json.loads(catlist_path.read_text())
    hour_prefix = now.strftime("%Y-%m-%d %H:")
    return any(
        c.get("status", "success") == "success" and c["timestamp"].startswith(hour_prefix)
        for c in cats
    )


def main():
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")

    # Skip if this hour already has a successful cat
    if already_has_cat_this_hour(now):
        print(f"Cat already exists for hour {now.strftime('%Y-%m-%d %H')} UTC, skipping.")
        return

    print(f"Generating cat for {timestamp}...")
    prompt_data = generate_prompt_and_story(timestamp)
    prompt = prompt_data['prompt']
    story = prompt_data['story']
    result = asyncio.run(generate_cat_image("/tmp", timestamp, prompt))

    # Read current count for numbering
    catlist_path = Path("catlist.json")
    cats = json.loads(catlist_path.read_text()) if catlist_path.exists() else []
    next_number = len(cats) + 1

    if result["status"] == "failed":
        print(f"Generation failed: {result['error']}", file=sys.stderr)
        entry = {
            "number": None,
            "timestamp": timestamp,
            "url": None,
            "model": "all failed",
            "status": "failed",
            "error": result["error"],
        }
        update_catlist_and_push(entry)
        sys.exit(1)

    image_path = result["file_path"]
    model_used = result["model_used"]
    print(f"Model used: {model_used}")

    print("Ensuring release exists...")
    ensure_release_exists()

    print("Uploading image as release asset...")
    image_url = upload_image_as_release_asset(image_path)
    print(f"Image URL: {image_url}")

    entry = {
        "number": next_number,
        "timestamp": timestamp,
        "prompt": prompt,
        "story": story,
        "url": image_url,
        "model": model_used,
        "status": "success",
    }
    print("Updating catlist.json...")
    update_catlist_and_push(entry)

    print("Posting issue comment...")
    issue_number = get_or_create_monthly_issue(now)
    print(f"Using monthly issue #{issue_number}")
    post_issue_comment(issue_number, image_url, next_number, timestamp, model_used, prompt, story)

    print(f"Done! Cat #{next_number}")


if __name__ == "__main__":
    main()
