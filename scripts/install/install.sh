#!/bin/sh
set -eu
# Callimachus installer: installs the npm package and ensures `uv`, which provisions the Python
# primitives' dependencies on first run (PEP 723 - no pip, no requirements.txt, no venv).
# Requires Node 20.19-24; `uv` manages its own Python.
step() { printf '==> %s\n' "$1"; }

step "Checking Node (need 20.19-24)"
node -e 'const v=process.versions.node.split(".").map(Number); if(v[0]<20||(v[0]===20&&v[1]<19)||v[0]>24){console.error("Need Node 20.19-24");process.exit(1)}'

step "Checking uv (provisions the Python primitives - PEP 723)"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Install it, then re-run:" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "Docs: https://docs.astral.sh/uv/" >&2
  exit 1
fi

step "Installing callimachus (npm, global)"
npm install -g callimachus

step "Done. Run:  cal \"review the literature on <your topic>\""
