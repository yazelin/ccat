"""Generate a cat image using nanobanana-py, upload as GitHub Release asset. Run by GitHub Actions hourly."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROMPT_META = (
    "You are a professional prompt engineer for AI image generation. "
    "Create a single, detailed English prompt for generating a stunning image. "
    "Requirements: (1) A cat must be the subject or prominently featured "
    "(2) The date and time '{timestamp}' must be visually displayed in the image. "
    "Beyond these two requirements, you have complete creative freedom — surprise me with "
    "varied styles (photography, painting, illustration, etc.), unique scenes, interesting "
    "compositions, lighting, and moods. Do NOT include any resolution keywords "
    "(like 4K, 8K, 16K, etc.) in the prompt.\n\n"
    "{recent_section}"
    "Output ONLY the prompt text, nothing else."
)

REPO = os.environ.get("GITHUB_REPOSITORY", "yazelin/catime")
RELEASE_TAG = "cats"


def get_recent_prompts(n: int = 5) -> list[str]:
    """Return the last n prompts from catlist.json."""
    catlist_path = Path("catlist.json")
    if not catlist_path.exists():
        return []
    cats = json.loads(catlist_path.read_text())
    return [c["prompt"] for c in cats if c.get("prompt")][-n:]


def generate_prompt(timestamp: str) -> str:
    """Use Gemini text model to generate a creative image prompt."""
    recent = get_recent_prompts(5)
    if recent:
        bullets = "\n".join(f"- {p}" for p in recent)
        recent_section = (
            "IMPORTANT: Here are the most recent prompts used. "
            "Avoid similar themes, styles, settings, and compositions:\n"
            f"{bullets}\n\n"
        )
    else:
        recent_section = ""

    print(f"Generating prompt with {len(recent)} recent prompts as context...")
    try:
        from google import genai

        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=PROMPT_META.format(timestamp=timestamp, recent_section=recent_section),
        )
        prompt = response.text.strip()
        if prompt:
            print(f"AI-generated prompt: {prompt[:120]}...")
            return prompt
    except Exception as e:
        print(f"Prompt generation failed ({e}), using fallback.")
    return f"A cute cat with the date and time '{timestamp}' displayed in the image, high quality, detailed"


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


def post_issue_comment(issue_number: str, image_url: str, number: int, timestamp: str, model_used: str, prompt: str = ""):
    """Post a comment on the monthly issue with the cat image."""
    prompt_line = f"**Prompt:** {prompt}\n" if prompt else ""
    body = (
        f"## Cat #{number}\n"
        f"**Time:** {timestamp}\n"
        f"**Model:** `{model_used}`\n"
        f"{prompt_line}\n"
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
    prompt = generate_prompt(timestamp)
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
        "url": image_url,
        "model": model_used,
        "status": "success",
    }
    print("Updating catlist.json...")
    update_catlist_and_push(entry)

    print("Posting issue comment...")
    issue_number = get_or_create_monthly_issue(now)
    print(f"Using monthly issue #{issue_number}")
    post_issue_comment(issue_number, image_url, next_number, timestamp, model_used, prompt)

    print(f"Done! Cat #{next_number}")


if __name__ == "__main__":
    main()
