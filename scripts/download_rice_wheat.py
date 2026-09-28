#!/usr/bin/env python3
"""Download rice and wheat articles from 2020 onward.

Metadata JSON is always saved. PDFs are saved for works that have one.
Put your key in the project-root .env file:

    OPENALEX_API_KEY=your_key_here

Run:

    .venv\\Scripts\\python scripts\\download_rice_wheat.py

Run the same command again after a disconnect. Each crop has its own
output folder and checkpoint, so completed works are skipped.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from openalex_cli.downloader import DownloadConfig, DownloadOrchestrator
from openalex_cli.progress import ProgressTracker
from openalex_cli.utils import ContentFormat

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

JOBS = (
    (
        "rice",
        "publication_year:>2019,type:article,title_and_abstract.search:rice",
    ),
    (
        "wheat",
        "publication_year:>2019,type:article,title_and_abstract.search:wheat",
    ),
)


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


async def download_one(api_key: str, name: str, filter_str: str) -> None:
    output_path = ROOT / "data" / name
    print(f"\n=== {name} ===")
    print(f"Filter: {filter_str}")
    print(f"Output: {output_path}")

    config = DownloadConfig(
        api_key=api_key,
        output_path=str(output_path),
        filter_str=filter_str,
        content_format=ContentFormat.PDF,
        nested=True,
        resume=True,
        workers=20,
    )
    progress = ProgressTracker(output_dir=str(output_path))
    orchestrator = DownloadOrchestrator(config)

    try:
        progress.start()
        await orchestrator.run(progress_tracker=progress)
    except KeyboardInterrupt:
        print(f"\n{name} interrupted. Progress saved. Run this script again to resume.")
        raise
    finally:
        progress.stop()

    if orchestrator._credits_exhausted:
        print(
            "OpenAlex credits are exhausted. Progress is saved. "
            "Run this script again after credits reset.",
            file=sys.stderr,
        )
        raise SystemExit(1)


async def main() -> None:
    api_key = api_key_from_env()
    try:
        for name, filter_str in JOBS:
            await download_one(api_key, name, filter_str)
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    asyncio.run(main())
