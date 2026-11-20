#!/usr/bin/env python3
"""Download OpenAlex works by keyword and subject category.

Edit YEAR_FROM and SEARCHES below, then run:

    python download_works.py

The API key is read from .env in this folder:

    OPENALEX_API_KEY=your_key_here

Each group is saved under D:/20260928_paper/<name>/. Keywords in one group
are combined, so a paper that matches more than one keyword is stored once.
Metadata JSON is always saved, and a PDF is saved when OpenAlex has one. A
publication date of 2024-09-11 is stored in 202409/11/. Works are requested
newest first. Run the same command again to resume.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Papers published in this year or later.
YEAR_FROM = 2020

# Newest publication date first. The cursor resume only works with this same sort.
SORT = "publication_date:desc"

# OpenAlex subfield ids. Several ids joined by | mean "any of these".
#   2102 Energy Engineering and Power Technology
#   2103 Fuel Technology
#   2105 Renewable Energy, Sustainability and the Environment
#   2208 Electrical and Electronic Engineering
#   2210 Mechanical Engineering
#   1102 Agronomy and Crop Science
#   1110 Plant Science
#   1106 Food Science
#
# keywords: each entry is one search phrase. A paper matching any phrase in
#   the group is saved in that group's folder. Within one phrase, every word
#   must appear in the English title or abstract. Do not use "," or "|"
#   inside a phrase.
# name: folder under data/. One folder per group.
# limit: newest papers to save in that folder. None saves every match.
#   Raising the number and running again continues from where it stopped.
SEARCHES = [
    {
        "name": "hydropower",
        "subfields": "2102|2105|2210|2208",
        "limit": 1500,
        "keywords": [
            "hydropower",
            "hydroelectric",
            "hydro turbine",
            "pumped storage",
        ],
    },
    {
        "name": "thermal_power",
        "subfields": "2102|2103|2210",
        "limit": 1500,
        "keywords": [
            "thermal power plant",
            "steam turbine",
            "combined cycle",
            "power plant efficiency",
            "power plant retrofit",
        ],
    },
    # {
    #     "name": "crops",
    #     "subfields": "1102|1110",
    #     "limit": None,
    #     "keywords": [
    #         "rice yield",
    #         "wheat yield",
    #         "rice cost",
    #         "wheat cost",
    #     ],
    # },
    {
        "name": "dairy",
        "subfields": "1106",
        "limit": 1500,
        "keywords": [
            "dairy processing",
            "milk processing",
            "milk powder",
            "cheese",
            "yogurt",
        ],
    },
]

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = Path("D:/20260928_paper")
sys.path.insert(0, str(ROOT / "src"))

from openalex_cli.api_client import CreditsExhaustedError, OpenAlexAPIClient
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
            f"Name cannot be used: {keyword!r}\n"
            "Use letters, numbers, spaces, '-' and '_'. "
            "Do not include ',' or '|'.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return name


def prepare_searches(searches: list[dict]) -> list[dict]:
    """Check names, keywords, and subfield ids before downloading.

    Two groups that sanitize to the same folder would share a checkpoint
    and skip or abort each other's download, so that case exits.
    """
    folders: dict[str, str] = {}
    prepared: list[dict] = []
    for item in searches:
        raw_name = str(item.get("name", "")).strip()
        raw_keywords = item.get("keywords", [])
        subfields = str(item.get("subfields", "")).strip()
        if not raw_name or not isinstance(raw_keywords, list) or not raw_keywords:
            print(
                "Each group needs a name and at least one keyword.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        keywords: list[str] = []
        for raw_keyword in raw_keywords:
            keyword = str(raw_keyword).strip()
            if not keyword or any(char in keyword for char in ",|"):
                print(
                    f"Keyword cannot be used: {keyword!r}\n"
                    "Do not include ',' or '|'.",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            keywords.append(keyword)
        limit = parse_limit(item.get("limit", None), raw_name)
        if subfields and any(char not in "0123456789|" for char in subfields):
            print(
                f"Subfields cannot be used: {subfields!r}\n"
                "Use OpenAlex subfield ids joined by '|', such as 1102|1110.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        name = folder_name(raw_name)
        # Windows treats Crops and crops as one directory.
        folder_key = name.casefold()
        earlier = folders.get(folder_key)
        if earlier is not None:
            print(
                f"Groups {earlier!r} and {raw_name!r} would both save to the same data folder.\n"
                "Change one name so each download has its own folder.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        folders[folder_key] = raw_name
        prepared.append(
            {"name": name, "keywords": keywords, "subfields": subfields, "limit": limit}
        )
    return prepared


def parse_limit(raw_limit: object, group_name: str) -> int | None:
    """Return a positive cap, or None when this group has no cap."""
    if raw_limit is None:
        return None
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
        print(
            f"Limit for {group_name!r} must be a positive integer or None.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if raw_limit < 1:
        print(
            f"Limit for {group_name!r} must be a positive integer or None.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return raw_limit


def missing_pairs(output_path: Path) -> tuple[list[Path], list[Path]]:
    """Return JSON files with no sibling PDF, and PDFs with no sibling JSON."""
    if not output_path.is_dir():
        return [], []
    json_files = {
        path.with_suffix(""): path
        for path in output_path.rglob("*.json")
        if path.name != ".openalex-checkpoint.json"
    }
    pdf_files = {path.with_suffix(""): path for path in output_path.rglob("*.pdf")}
    json_only = [json_files[key] for key in sorted(json_files.keys() - pdf_files.keys())]
    pdf_only = [pdf_files[key] for key in sorted(pdf_files.keys() - json_files.keys())]
    return json_only, pdf_only


async def _download_pdf_beside_json(client: OpenAlexAPIClient, json_path: Path) -> bool:
    """Save the PDF next to this metadata file. Return False when credits run out."""
    work_id = json_path.stem
    for _attempt in range(5):
        result = await client.download_content(work_id, ContentFormat.PDF)
        if result.error == "Rate limited":
            await asyncio.sleep(2)
            continue
        if result.error == "Credits exhausted":
            return False
        if result.success and result.content:
            json_path.with_suffix(".pdf").write_bytes(result.content)
            print(f"Saved PDF {work_id}")
            return True
        print(f"PDF not saved for {work_id}: {result.error or 'empty file'}")
        return True
    print(f"PDF not saved for {work_id}: rate limited")
    return True


async def _download_json_beside_pdf(client: OpenAlexAPIClient, pdf_path: Path) -> bool:
    """Save metadata next to this PDF. Return False when credits run out."""
    work_id = pdf_path.stem
    try:
        metadata = await client.get_work_metadata(work_id)
    except CreditsExhaustedError:
        return False
    except Exception as error:
        print(f"Metadata not saved for {work_id}: {error}")
        return True
    pdf_path.with_suffix(".json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
    print(f"Saved metadata {work_id}")
    return True


async def fill_missing_files(api_key: str, output_path: Path) -> None:
    """Download whichever of JSON or PDF is missing beside an existing file.

    The main download does not return to these papers once its cursor has moved on.
    """
    json_only, pdf_only = missing_pairs(output_path)
    if not json_only and not pdf_only:
        return
    print(
        f"Filling gaps in {output_path}: "
        f"{len(json_only)} missing PDF, {len(pdf_only)} missing metadata"
    )
    client = OpenAlexAPIClient(api_key=api_key)
    try:
        for json_path in json_only:
            if not await _download_pdf_beside_json(client, json_path):
                print(
                    "OpenAlex credits are exhausted while filling gaps. "
                    "Run this script again after changing the API key.",
                    file=sys.stderr,
                )
                raise SystemExit(1)
        for pdf_path in pdf_only:
            if not await _download_json_beside_pdf(client, pdf_path):
                print(
                    "OpenAlex credits are exhausted while filling gaps. "
                    "Run this script again after changing the API key.",
                    file=sys.stderr,
                )
                raise SystemExit(1)
    finally:
        await client.close()


def filter_for(keywords: list[str], subfields: str) -> str:
    parts = [
        f"publication_year:>{YEAR_FROM - 1}",
        "type:article",
        "title_and_abstract.search:" + "|".join(keywords),
    ]
    if subfields:
        parts.append(f"primary_topic.subfield.id:{subfields}")
    return ",".join(parts)


async def download_one(api_key: str, search: dict) -> None:
    name = search["name"]
    keywords = search["keywords"]
    filter_str = filter_for(keywords, search["subfields"])
    output_path = OUTPUT_ROOT / name
    print(f"\n=== {name} ===")
    print("Keywords: " + " | ".join(keywords))
    print(f"Filter: {filter_str}")
    print(f"Sort: {SORT}")
    print(f"Limit: {search['limit'] if search['limit'] is not None else 'none'}")
    print(f"Output: {output_path}")

    await fill_missing_files(api_key, output_path)

    config = DownloadConfig(
        api_key=api_key,
        output_path=str(output_path),
        filter_str=filter_str,
        sort=SORT,
        max_works=search["limit"],
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
        print(f"\n{name} interrupted. Progress saved. Run this script again to resume.")
        raise
    finally:
        progress.stop()

    if orchestrator.checkpoint_conflict:
        print(
            f"{output_path} already has a download with different settings.\n"
            "Use another folder name, or delete that folder's checkpoint to start over.",
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
    if not SEARCHES:
        print("Add at least one search to SEARCHES in download_works.py.", file=sys.stderr)
        raise SystemExit(1)
    if not SORT.strip():
        print("Set SORT, for example publication_date:desc.", file=sys.stderr)
        raise SystemExit(1)

    prepared = prepare_searches(SEARCHES)
    api_key = api_key_from_env()
    try:
        for search in prepared:
            await download_one(api_key, search)
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    asyncio.run(main())
