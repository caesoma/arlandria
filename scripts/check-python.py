#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "jsonschema==4.25.1",
#   "mypy==1.15.0",
#   "ruff==0.11.13",
#   "types-jsonschema==4.25.1.20250822",
#   "coverage==7.10.7",
#   "defusedxml==0.7.1",
#   "pypdf==4.3.1",
#   "requests==2.32.5",
#   "types-requests==2.32.4.20250809",
#   "types-defusedxml==0.7.0.20250822",
# ]
# ///
"""Run the Python skill checks without a Node/Pi runtime."""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [ROOT / f"skills/{skill}/scripts" for skill in ("hypatia", "callimachus")]
TARGETS = [str(SCRIPTS[0]), str(Path(__file__).resolve()), *map(str, (ROOT / "tests").glob("*.py"))]


def main():
    paths = os.pathsep.join(map(str, SCRIPTS))
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": paths, "MYPYPATH": paths}
    checks = [
        ["ruff", "check", *TARGETS],
        ["ruff", "check", "--select", "E9,F63,F7,F82", str(SCRIPTS[1])],
        ["mypy", "--check-untyped-defs", *TARGETS],
        ["coverage", "erase"],
        ["coverage", "run", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
        ["coverage", "combine"],
        ["coverage", "report", "--show-missing"],
        ["coverage", "json", "-o", "coverage/python.json"],
        ["coverage", "html", "-d", "coverage/python"],
    ]
    for arguments in checks:
        subprocess.run([sys.executable, "-m", *arguments], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
