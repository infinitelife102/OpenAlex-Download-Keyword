#!/usr/bin/env python3
"""Download OpenAlex works by keyword.

Edit YEAR_FROM and KEYWORDS below, then run:

    python download_works.py

The API key is read from .env in this folder:

    OPENALEX_API_KEY=your_key_here

Each keyword is saved under data/<keyword>/. Metadata JSON is always
saved, and a PDF is saved when OpenAlex has one. A publication date of
2024-09-11 is stored in 202409/11/. Run the same command again to resume.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Papers published in this year or later.
YEAR_FROM = 2020

# One folder per keyword. Search matches the English title and abstract.
KEYWORDS = [
    "rice",
    "wheat",
]

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from openalex_cli.downloader import DownloadConfig, DownloadOrchestrator
from openalex_cli.progress import ProgressTracker
from openalex_cli.utils import ContentFormat

ENV_PATH = ROOT / ".env"


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into the environment without overriding existing vars."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def api_key_from_env() -> str:
    load_dotenv(ENV_PATH)
    api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if not api_key:
        print(
            "OPENALEX_API_KEY is missing.\n"
            f"Add it to {ENV_PATH}:\n"
            "  OPENALEX_API_KEY=your_key_here",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return api_key


def folder_name(keyword: str) -> str:
    """Turn a keyword into a single folder name."""
    cleaned = []
    for char in keyword.strip():
        if char.isalnum() or char in "-_":
            cleaned.append(char)
        elif char.isspace():
            cleaned.append("_")
    name = "".join(cleaned).strip("_")
    if not name or "," in keyword or "|" in keyword:
        print(
            f"Keyword cannot be used: {keyword!r}\n"
            "Use letters, numbers, spaces, '-' and '_'. "
            "Do not include ',' or '|'.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return name


def assign_output_folders(keywords: list[str]) -> list[tuple[str, str]]:
    """Pair each keyword with its own output folder.

    Keywords that sanitize to the same folder would share a checkpoint
    and skip or abort each other's download, so that case exits.
    """
    folders: dict[str, str] = {}
    assigned: list[tuple[str, str]] = []
    for keyword in keywords:
        name = folder_name(keyword)
        earlier = folders.get(name)
        if earlier is not None:
            print(
                f"Keywords {earlier!r} and {keyword!r} would both save to data/{name}/.\n"
                "Change one keyword so each download has its own folder.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        folders[name] = keyword
        assigned.append((keyword, name))
    return assigned


def filter_for(keyword: str) -> str:
    return (
        f"publication_year:>{YEAR_FROM - 1},"
        "type:article,"
        f"title_and_abstract.search:{keyword.strip()}"
    )


async def download_one(api_key: str, keyword: str, name: str) -> None:
    filter_str = filter_for(keyword)
    output_path = ROOT / "data" / name
    print(f"\n=== {keyword} ===")
    print(f"Filter: {filter_str}")
    print(f"Output: {output_path}")

    config = DownloadConfig(
        api_key=api_key,
        output_path=str(output_path),
        filter_str=filter_str,
        content_format=ContentFormat.PDF,
        by_date=True,
        resume=True,
        workers=20,
    )
    progress = ProgressTracker(output_dir=str(output_path))
    orchestrator = DownloadOrchestrator(config)

    try:
        progress.start()
        await orchestrator.run(progress_tracker=progress)
    except KeyboardInterrupt:
        print(f"\n{keyword} interrupted. Progress saved. Run this script again to resume.")
        raise
    finally:
        progress.stop()

    if orchestrator.checkpoint_conflict:
        print(
            f"{output_path} already has a download with different settings.\n"
            "Use another keyword folder, or delete that folder's checkpoint to start over.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if orchestrator._credits_exhausted:
        print(
            "OpenAlex credits are exhausted. Progress is saved. "
            "Run this script again after credits reset.",
            file=sys.stderr,
        )
        raise SystemExit(1)


async def main() -> None:
    if YEAR_FROM < 1:
        print("YEAR_FROM must be a positive year.", file=sys.stderr)
        raise SystemExit(1)
    keywords = [item.strip() for item in KEYWORDS if item.strip()]
    if not keywords:
        print("Add at least one keyword to KEYWORDS in download_works.py.", file=sys.stderr)
        raise SystemExit(1)

    assigned = assign_output_folders(keywords)
    api_key = api_key_from_env()
    try:
        for keyword, name in assigned:
            await download_one(api_key, keyword, name)
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    asyncio.run(main())
