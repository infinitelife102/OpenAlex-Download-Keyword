#!/usr/bin/env python3
"""Run the project-root download script."""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "download_works.py"),
    run_name="__main__",
)
