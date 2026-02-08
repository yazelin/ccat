"""Generate a cat image using nanobanana-py, upload as GitHub Release asset. Run by GitHub Actions hourly."""

import asyncio
import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SUMMARY_PROMPT = (
    "You are analyzing recent AI-generated cat image prompts to identify repetitive patterns.\n\n"
    "Here are the most recent prompts and stories:\n{entries}\n\n"
    "Identify overused themes, settings, styles, poses, lighting, and vocabulary.\n"
    "Output a JSON object with exactly this format:\n"
    '{{"avoid_list": ["繁體中文短語 1", "繁體中文短語 2", ...]}}\n\n'
    "Rules:\n"
    "- Each item should be a short phrase in 繁體中文 (e.g. '生物發光森林', '貓凝望月亮', '宇宙空靈光芒')\n"
    "- List 8-15 items that appear too frequently\n"
    "- Focus on specific repeated combos, not generic concepts"
)

NEWS_PROMPT = (
    "Search for today's interesting world news and current events.\n\n"
    "Pick 3-5 news items that are:\n"
    "- Fun, heartwarming, quirky, cultural, scientific, sports, weather, travel, tourism, or lifestyle related\n"
    "- From DIFFERENT regions of the world\n"
    "- AVOID: war, terrorism, political controversy, violent crime, natural disasters with casualties\n\n"
    "For each item, write a 1-sentence summary in 繁體中文. MUST include the city/country where it happened.\n\n"
    "Output a JSON object with exactly this format:\n"
    '{{"news": ["繁體中文摘要 1", "繁體中文摘要 2", ...]}}'
)

IDEA_PROMPT = (
    "You are a wildly creative storyteller and visual director inventing a unique scene for an AI cat image.\n\n"
    "{news_section}"
    "{avoid_section}"
    "Requirements:\n"
    "(1) A cat must be the subject or prominently featured\n"
    "(2) The cat MUST be DOING something specific (cooking, skateboarding, repairing a clock, reading a map, etc.)\n"
    "(3) The scene MUST be set in a specific, concrete place (a 1950s diner, a Tokyo subway car, a greenhouse, a lighthouse, etc.)\n"
    "(4) Be wildly creative - surprise me with unexpected combinations\n"
    "{style_section}"
    "(5) Use the visual style specified in TODAY'S STYLE PALETTE above. If none provided, pick any creative style.\n"
    "(6) For photography styles: describe the scene realistically - real cats in real places. "
    "Do NOT add fantasy or magical elements. Think like a photographer, not a painter.\n"
    "(7) Vary the scene composition - sometimes include other characters (people, other animals, crowds) "
    "or objects the cat interacts with. A lone cat is fine occasionally, but don't default to it every time.\n\n"
    "Output a JSON object with exactly this format:\n"
    '{{"idea": "繁體中文場景描述，1-2句，包含藝術風格", "story": "繁體中文短故事，2-3句", "title": "作品名稱，3-6個字的繁體中文", "inspiration": "original 或引用的新聞摘要"}}\n\n'
    "The title should be poetic, evocative, and concise (3-6 Chinese characters). Like a painting title.\n"
    "Examples: 晨光裡的守望、雨巷漫步、星空下的琴音、午後的秘密\n\n"
    "For the 'inspiration' field:\n"
    "- If your idea was inspired by one of the news items, copy that exact news summary as the value.\n"
    "- If your idea is purely from imagination (not based on any news), set it to \"original\".\n\n"
    "idea, story, title, and inspiration should all be in Traditional Chinese (except 'original' stays English)."
)

RENDER_PROMPT = (
    "You are a prompt engineer converting a creative idea into a concise image generation prompt.\n\n"
    "Idea: {idea}\n"
    "Story: {story}\n"
    "{style_snippets_section}\n"
    "Requirements:\n"
    "(1) The date and time '{timestamp}' MUST be visually displayed in the image\n"
    "(2) Include specific art style, composition, lighting, and color details\n"
    "(3) Do NOT include any resolution keywords (like 4K, 8K, 16K, etc.)\n"
    "(4) The image must clearly show a cat doing the described activity\n"
    "(5) CRITICAL - match the prompt style to the medium:\n"
    "    - If PHOTOGRAPHY: use camera terms (e.g. '35mm lens, f/1.8, natural light, shallow depth of field, "
    "grain, candid shot'). The output MUST look like a real photograph, NOT a painting or digital art. "
    "Do NOT use words like 'breathtaking', 'intricate', 'ethereal', 'brushstrokes', or 'palette'.\n"
    "    - If ILLUSTRATION/ART: describe artistic medium, technique, and visual style.\n"
    "(6) If style reference snippets are provided below, incorporate them into the prompt.\n\n"
    "Output a JSON object with exactly this format:\n"
    '{{"prompt": "English image prompt here"}}'
)

def load_style_reference() -> dict:
    """Load style_reference.json, return empty dict if not found."""
    style_path = Path(__file__).parent / "style_reference.json"
    if not style_path.exists():
        return {}
    try:
        return json.loads(style_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def pick_random_styles() -> dict:
    """Pick one random style from each category. Returns {category: {zh, en, prompt}}."""
    styles = load_style_reference()
    if not styles:
        return {}
    picks = {}
    for category, entries in styles.items():
        if entries:
            picks[category] = random.choice(entries)
    return picks


def format_style_suggestion(picks: dict) -> str:
    """Format picked styles into a prompt section for IDEA_PROMPT."""
    if not picks:
        return ""
    lines = []
    for category, style in picks.items():
        lines.append(f"- {category}: {style['zh']} ({style['en']})")
    style_list = "\n".join(lines)
    return (
        "TODAY'S STYLE PALETTE (use these as your visual direction):\n"
        f"{style_list}\n"
        "You MUST use the art_style pick as your visual style. "
        "Incorporate the other picks (composition, lighting, texture, color_palette) naturally.\n\n"
    )


def format_style_prompt_snippet(picks: dict) -> str:
    """Get the combined prompt snippets from picked styles for RENDER_PROMPT."""
    if not picks:
        return ""
    snippets = [style["prompt"] for style in picks.values()]
    return ", ".join(snippets)


REPO = os.environ.get("GITHUB_REPOSITORY", "yazelin/catime")
RELEASE_TAG = "cats"


def get_recent_context(n: int = 10) -> dict:
    """Return the last n prompts and stories from catlist.json.

    Note: This function is no longer used by the main two-stage pipeline.
    It is kept for backwards compatibility and debugging purposes.
    The two-stage pipeline uses creative_notes (avoid_list) instead of
    feeding full historical prompts to prevent style imitation.
    """
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


def parse_ai_response_generic(text: str, required_keys: list) -> dict | None:
    """Parse AI response JSON with flexible required keys.

    Returns the parsed dict if all required_keys are present, or None on failure.
    """
    text = text.strip()

    # Try to extract JSON from markdown code block
    code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if code_block_match:
        text = code_block_match.group(1)

    try:
        data = json.loads(text)
        if isinstance(data, dict) and all(k in data for k in required_keys):
            return data
    except json.JSONDecodeError:
        pass

    return None


def load_creative_notes() -> dict:
    """Load creative_notes.json, return empty structure if not found."""
    notes_path = Path("creative_notes.json")
    if not notes_path.exists():
        return {"avoid_list": [], "updated_at": None}
    try:
        return json.loads(notes_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"avoid_list": [], "updated_at": None}


def load_monthly_detail(month: str) -> list:
    """Load a monthly detail file (cats/YYYY-MM.json). Returns [] if not found."""
    month_path = Path("cats") / f"{month}.json"
    if not month_path.exists():
        return []
    try:
        return json.loads(month_path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def maybe_update_creative_notes(cat_number: int) -> dict:
    """Update creative_notes.json every 5 cats. Returns current notes."""
    notes = load_creative_notes()

    if cat_number % 5 != 0:
        return notes

    print(f"Cat #{cat_number} is a multiple of 5, updating creative notes...")
    catlist_path = Path("catlist.json")
    if not catlist_path.exists():
        return notes

    cats = json.loads(catlist_path.read_text())
    # Collect recent months from index timestamps (newest last)
    months = sorted({c["timestamp"][:7] for c in cats if c.get("status", "success") == "success"})
    # Load details from recent months until we have enough entries
    all_details = []
    for month in reversed(months):
        all_details = load_monthly_detail(month) + all_details
        if sum(1 for c in all_details if c.get("prompt")) >= 10:
            break
    recent = [c for c in all_details if c.get("prompt")][-10:]
    if not recent:
        return notes

    entries_text = "\n".join(
        f"- Prompt: {c['prompt']}\n  Story: {c.get('story', '')}\n  Idea: {c.get('idea', '')}"
        for c in recent
    )

    try:
        from google import genai

        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=SUMMARY_PROMPT.format(entries=entries_text),
        )
        result = parse_ai_response_generic(response.text, ["avoid_list"])
        if result and isinstance(result["avoid_list"], list):
            notes = {
                "avoid_list": result["avoid_list"],
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            }
            Path("creative_notes.json").write_text(
                json.dumps(notes, indent=2, ensure_ascii=False) + "\n"
            )
            print(f"Creative notes updated with {len(notes['avoid_list'])} avoid items.")
            return notes
        print("Summary response missing avoid_list, keeping old notes.")
    except Exception as e:
        print(f"Creative notes update failed ({e}), keeping old notes.")

    return notes


def fetch_news_inspiration() -> list[str]:
    """Use Gemini with Google Search grounding to fetch today's interesting news.

    Returns a list of short news summaries, or empty list on failure.
    """
    print("Stage 0: Fetching today's news for inspiration...")
    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=NEWS_PROMPT,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
        result = parse_ai_response_generic(response.text, ["news"])
        if result and isinstance(result["news"], list):
            news = result["news"][:5]
            for i, item in enumerate(news, 1):
                print(f"  News {i}: {item[:80]}...")
            return news
        print("  News parse failed, skipping news inspiration.")
    except Exception as e:
        print(f"  News fetch failed ({e}), skipping news inspiration.")
    return []


def generate_prompt_and_story(timestamp: str, creative_notes: dict) -> dict:
    """Three-stage prompt generation: news -> idea -> render.

    Stage 0: NEWS_PROMPT + Google Search -> [news summaries] (optional inspiration)
    Stage 1: IDEA_PROMPT + avoid_list + news -> {"idea": ..., "story": ...}
    Stage 2: RENDER_PROMPT + idea + story + timestamp -> {"prompt": ...}

    Returns: {'prompt': str, 'story': str, 'idea': str, 'avoid_list': list, 'news_inspiration': list}
    """
    avoid_list = creative_notes.get("avoid_list", [])
    avoid_section = ""
    if avoid_list:
        bullets = "\n".join(f"- {item}" for item in avoid_list)
        avoid_section = (
            "IMPORTANT: Avoid these overused themes and patterns:\n"
            f"{bullets}\n\n"
        )

    # Stage 0: Fetch news inspiration
    news = fetch_news_inspiration()
    news_section = ""
    if news:
        bullets = "\n".join(f"- {item}" for item in news)
        news_section = (
            "Here are some current world events for inspiration. "
            "You MAY creatively incorporate one into the cat scene, or ignore them entirely. "
            "Aim for roughly half news-inspired, half pure imagination.\n"
            f"{bullets}\n\n"
        )

    # Pick random styles from style_reference.json
    style_picks = pick_random_styles()
    style_section = format_style_suggestion(style_picks)
    style_snippets = format_style_prompt_snippet(style_picks)
    style_snippets_section = f"Style reference snippets: {style_snippets}\n" if style_snippets else ""

    if style_picks:
        print(f"Style picks: {', '.join(s['en'] for s in style_picks.values())}")

    fallback = {
        'prompt': f"A cute cat with the date and time '{timestamp}' displayed in the image, high quality, detailed",
        'story': "一隻可愛的貓咪正在享受美好的一天。",
        'idea': '',
        'title': '貓咪日常',
        'inspiration': 'original',
        'avoid_list': avoid_list,
        'news_inspiration': news,
        'style_picks': {k: v['en'] for k, v in style_picks.items()},
    }

    # Stage 1: Generate idea and story
    print(f"Stage 1: Generating idea (avoid_list has {len(avoid_list)} items, news has {len(news)} items)...")
    idea = ""
    story = ""
    title = ""
    inspiration = "original"
    try:
        from google import genai

        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=IDEA_PROMPT.format(news_section=news_section, avoid_section=avoid_section, style_section=style_section),
        )
        result = parse_ai_response_generic(response.text, ["idea", "story"])
        if result:
            idea = result["idea"]
            story = result["story"]
            title = result.get("title", "")
            inspiration = result.get("inspiration", "original")
            print(f"Title: {title}")
            print(f"Inspiration: {'🎨 原創' if inspiration == 'original' else '📰 ' + inspiration[:60]}")
            print(f"Idea: {idea[:120]}...")
            print(f"Story: {story[:80]}...")
        else:
            print("Stage 1 parse failed, using fallback.")
            return fallback
    except Exception as e:
        print(f"Stage 1 failed ({e}), using fallback.")
        return fallback

    # Stage 2: Convert idea to image prompt
    print("Stage 2: Converting idea to image prompt...")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=RENDER_PROMPT.format(idea=idea, story=story, timestamp=timestamp, style_snippets_section=style_snippets_section),
        )
        result = parse_ai_response_generic(response.text, ["prompt"])
        if result:
            prompt = result["prompt"]
            print(f"Prompt: {prompt[:120]}...")
            return {
                'prompt': prompt,
                'story': story,
                'idea': idea,
                'title': title or '貓咪日常',
                'inspiration': inspiration,
                'avoid_list': avoid_list,
                'news_inspiration': news,
                'style_picks': {k: v['en'] for k, v in style_picks.items()},
            }
        else:
            print("Stage 2 parse failed, using idea as prompt fallback.")
            return {
                'prompt': f"{idea}. The date and time '{timestamp}' is visually displayed in the image. {style_snippets}",
                'story': story,
                'idea': idea,
                'title': title or '貓咪日常',
                'inspiration': inspiration,
                'avoid_list': avoid_list,
                'news_inspiration': news,
                'style_picks': {k: v['en'] for k, v in style_picks.items()},
            }
    except Exception as e:
        print(f"Stage 2 failed ({e}), using idea as prompt fallback.")
        return {
            'prompt': f"{idea}. The date and time '{timestamp}' is visually displayed in the image. {style_snippets}",
            'story': story,
            'idea': idea,
                'title': title or '貓咪日常',
                'inspiration': inspiration,
            'avoid_list': avoid_list,
            'news_inspiration': news,
            'style_picks': {k: v['en'] for k, v in style_picks.items()},
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

    # Convert PNG to WebP for smaller file size
    png_path = response.generated_files[0]
    webp_path = png_path.rsplit(".", 1)[0] + ".webp"
    try:
        from PIL import Image

        img = Image.open(png_path)
        img.save(webp_path, "WEBP", quality=90)
        os.remove(png_path)
        print(f"Converted to WebP: {os.path.getsize(webp_path) / 1024:.0f}KB")
        final_path = webp_path
    except Exception as e:
        print(f"WebP conversion failed ({e}), using PNG")
        final_path = png_path

    return {
        "file_path": final_path,
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


def post_issue_comment(issue_number: str, image_url: str, number: int, timestamp: str, model_used: str, prompt: str = "", story: str = "", idea: str = "", title: str = "", inspiration: str = "") -> int | None:
    """Post a comment on the monthly issue with the cat image. Returns comment_id or None."""
    prompt_line = f"**Prompt:** {prompt}\n" if prompt else ""
    story_line = f"**Story:** {story}\n" if story else ""
    idea_line = f"**Idea:** {idea}\n" if idea else ""
    title_display = f" — {title}" if title else ""
    if inspiration and inspiration != "original":
        inspiration_line = f"**靈感來源:** 📰 {inspiration}\n"
    elif inspiration == "original":
        inspiration_line = "**靈感來源:** 🎨 AI 原創\n"
    else:
        inspiration_line = ""
    body = (
        f"## Cat #{number}{title_display}\n"
        f"**Time:** {timestamp}\n"
        f"**Model:** `{model_used}`\n"
        f"{inspiration_line}"
        f"{idea_line}"
        f"{prompt_line}"
        f"{story_line}\n"
        f"![cat-{number}]({image_url})"
    )
    result = subprocess.run(
        ["gh", "issue", "comment", issue_number, "--repo", REPO, "--body", body],
        capture_output=True, text=True, check=True,
    )
    # gh issue comment prints the comment URL, e.g. https://github.com/.../issues/3#issuecomment-123456
    comment_url = result.stdout.strip()
    match = re.search(r"issuecomment-(\d+)", comment_url)
    if match:
        return int(match.group(1))
    return None


def update_catlist_and_push(entry: dict) -> int:
    """Update catlist.json and monthly detail file, commit and push."""
    index_fields = {"number", "timestamp", "url", "model", "status", "error", "title", "inspiration"}
    detail_fields = {"number", "prompt", "story", "idea", "title", "inspiration", "news_inspiration", "avoid_list", "style_picks", "comment_id"}

    # Write lightweight index entry to catlist.json
    catlist_path = Path("catlist.json")
    cats = json.loads(catlist_path.read_text()) if catlist_path.exists() else []
    index_entry = {k: entry[k] for k in index_fields if k in entry}
    cats.append(index_entry)
    catlist_path.write_text(json.dumps(cats, indent=2, ensure_ascii=False) + "\n")

    git_add_files = ["catlist.json"]

    # Write detail entry to monthly file (only for successful cats with detail data)
    has_detail = any(entry.get(k) for k in detail_fields if k != "number")
    if has_detail:
        month = entry["timestamp"][:7]  # "YYYY-MM"
        cats_dir = Path("cats")
        cats_dir.mkdir(exist_ok=True)
        month_path = cats_dir / f"{month}.json"
        monthly = json.loads(month_path.read_text()) if month_path.exists() else []
        detail_entry = {k: entry[k] for k in detail_fields if k in entry}
        monthly.append(detail_entry)
        month_path.write_text(json.dumps(monthly, indent=2, ensure_ascii=False) + "\n")
        git_add_files.append(str(month_path))

    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=True,
    )

    if Path("creative_notes.json").exists():
        git_add_files.append("creative_notes.json")
    subprocess.run(["git", "add"] + git_add_files, check=True)

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

    # Read current count for numbering (needed before creative notes update)
    catlist_path = Path("catlist.json")
    cats = json.loads(catlist_path.read_text()) if catlist_path.exists() else []
    next_number = len(cats) + 1

    # Update creative notes if needed (every 5 cats)
    creative_notes = maybe_update_creative_notes(next_number)

    print(f"Generating cat #{next_number} for {timestamp}...")
    prompt_data = generate_prompt_and_story(timestamp, creative_notes)
    prompt = prompt_data['prompt']
    story = prompt_data['story']
    idea = prompt_data.get('idea', '')
    avoid_list = prompt_data.get('avoid_list', [])
    news_inspiration = prompt_data.get('news_inspiration', [])
    style_picks = prompt_data.get('style_picks', {})
    title = prompt_data.get('title', '貓咪日常')
    inspiration = prompt_data.get('inspiration', 'original')
    result = asyncio.run(generate_cat_image("/tmp", timestamp, prompt))

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

    print("Posting issue comment...")
    comment_id = None
    try:
        issue_number = get_or_create_monthly_issue(now)
        print(f"Using monthly issue #{issue_number}")
        comment_id = post_issue_comment(issue_number, image_url, next_number, timestamp, model_used, prompt, story, idea, title, inspiration)
        if comment_id:
            print(f"Comment ID: {comment_id}")
    except Exception as e:
        print(f"Issue comment failed ({e}), continuing without comment_id.")

    entry = {
        "number": next_number,
        "timestamp": timestamp,
        "prompt": prompt,
        "story": story,
        "idea": idea,
        "avoid_list": avoid_list,
        "title": title,
        "inspiration": inspiration,
        "news_inspiration": news_inspiration,
        "style_picks": style_picks,
        "url": image_url,
        "model": model_used,
        "status": "success",
    }
    if comment_id:
        entry["comment_id"] = comment_id

    print("Updating catlist.json...")
    update_catlist_and_push(entry)

    print(f"Done! Cat #{next_number}")


if __name__ == "__main__":
    main()
