"""CLI entry point for catime - view AI-generated hourly cats."""

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

CATLIST_URL = "https://raw.githubusercontent.com/{repo}/main/catlist.json"
DEFAULT_REPO = "yazelin/catime"


def fetch_catlist(repo: str) -> list[dict]:
    url = CATLIST_URL.format(repo=repo)
    resp = httpx.get(url, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def load_local_catlist() -> list[dict]:
    p = Path(__file__).resolve().parent.parent.parent / "catlist.json"
    if p.exists():
        return json.loads(p.read_text())
    return []


def print_cat(cat: dict, index: int | None = None):
    """Print a single cat entry."""
    num = cat.get("number") or index
    status = cat.get("status", "success")
    if status == "failed":
        print(f"Cat #{num or '?':>4}  [FAILED]  {cat['timestamp']}  error: {cat.get('error', '?')}")
    else:
        print(f"Cat #{num:>4}  {cat['timestamp']}  model: {cat.get('model', '?')}")
        print(f"  URL: {cat['url']}")


def filter_by_query(cats: list[dict], query: str) -> list[dict]:
    """Filter cats by time query: date, date+hour, today, yesterday."""
    now = datetime.now(timezone.utc)

    if query == "today":
        target_date = now.strftime("%Y-%m-%d")
        return [c for c in cats if c["timestamp"].startswith(target_date)]

    if query == "yesterday":
        target_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        return [c for c in cats if c["timestamp"].startswith(target_date)]

    # date+hour: 2026-01-30T05 or 2026-01-30 05
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{1,2})$", query)
    if m:
        date_str, hour_str = m.group(1), m.group(2).zfill(2)
        prefix = f"{date_str} {hour_str}:"
        return [c for c in cats if c["timestamp"].startswith(prefix)]

    # date only: 2026-01-30
    if re.match(r"^\d{4}-\d{2}-\d{2}$", query):
        return [c for c in cats if c["timestamp"].startswith(query)]

    return []


def cmd_view(args):
    """Serve the cat gallery locally in a browser."""
    import http.server
    import functools
    import threading
    import webbrowser

    docs_dir = Path(__file__).resolve().parent / "docs"
    if not docs_dir.exists():
        # Fallback: project root docs/
        docs_dir = Path(__file__).resolve().parent.parent.parent / "docs"
    if not docs_dir.exists():
        print("Error: docs/ directory not found.", file=sys.stderr)
        sys.exit(1)

    port = args.port
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(docs_dir))
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Serving cat gallery at {url}")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    # Handle 'view' subcommand separately to avoid argparse conflicts
    if len(sys.argv) >= 2 and sys.argv[1] == "view":
        view_parser = argparse.ArgumentParser(prog="catime view")
        view_parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
        cmd_view(view_parser.parse_args(sys.argv[2:]))
        return

    parser = argparse.ArgumentParser(
        prog="catime",
        description="View AI-generated hourly cat images",
    )
    parser.add_argument(
        "query", nargs="?",
        help="Cat number (e.g. 42), date (2026-01-30), date+hour (2026-01-30T05), 'today', 'yesterday', or 'view'.",
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo owner/name")
    parser.add_argument("--local", action="store_true", help="Use local catlist.json")
    parser.add_argument("--list", action="store_true", help="List all cats")
    args = parser.parse_args()

    try:
        cats = load_local_catlist() if args.local else fetch_catlist(args.repo)
    except Exception as e:
        print(f"Error loading cat list: {e}", file=sys.stderr)
        sys.exit(1)

    if not cats:
        print("No cats yet! Check back in an hour.")
        return

    if args.list:
        for i, cat in enumerate(cats, 1):
            print_cat(cat, i)
        return

    if args.query is None:
        print(f"Total cats: {len(cats)}")
        print(f"Latest: #{len(cats):04d}  {cats[-1]['timestamp']}")
        print()
        print("Usage:")
        print("  catime 42              View cat #42")
        print("  catime today           List today's cats")
        print("  catime yesterday       List yesterday's cats")
        print("  catime 2026-01-30      List all cats from a date")
        print("  catime 2026-01-30T05   View the cat from a specific hour")
        print("  catime latest          View the latest cat")
        print("  catime --list          List all cats")
        print("  catime view            Open cat gallery in browser")
        return

    # latest
    if args.query == "latest":
        print_cat(cats[-1], len(cats))
        return

    # Try as number first
    if args.query.isdigit():
        idx = int(args.query) - 1
        if idx < 0 or idx >= len(cats):
            print(f"Cat #{args.query} not found. Available: 1-{len(cats)}", file=sys.stderr)
            sys.exit(1)
        print_cat(cats[idx], int(args.query))
        return

    # Try as time query
    matched = filter_by_query(cats, args.query)
    if not matched:
        print(f"No cats found for '{args.query}'.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(matched)} cat(s) for '{args.query}':\n")
    for cat in matched:
        print_cat(cat)
        print()
