#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "jsonschema==4.25.1",
#   "mypy==1.15.0",
#   "ruff==0.11.13",
#   "types-jsonschema==4.25.1.20250822",
# ]
# ///
"""Run the Python skill checks without a Node/Pi runtime."""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/hypatia/scripts"
TARGETS = [str(SCRIPTS), str(Path(__file__).resolve()), str(ROOT / "tests/test_hypatia.py")]


def main():
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(SCRIPTS)}
    checks = [
        ["ruff", "check", *TARGETS],
        ["mypy", "--check-untyped-defs", *TARGETS],
        ["unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
    ]
    for arguments in checks:
        subprocess.run([sys.executable, "-m", *arguments], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
