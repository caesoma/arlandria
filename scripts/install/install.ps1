$ErrorActionPreference = "Stop"
# Callimachus installer: installs the npm package and ensures `uv`, which provisions the Python
# primitives' dependencies on first run (PEP 723 - no pip, no requirements.txt, no venv).
Write-Host "==> Checking uv (provisions the Python primitives - PEP 723)"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Error "uv not found. Install it, then re-run:  irm https://astral.sh/uv/install.ps1 | iex  (docs: https://docs.astral.sh/uv/)"
  exit 1
}
Write-Host "==> Installing callimachus (npm, global)"
npm install -g callimachus
Write-Host "==> Done. Run:  cal `"review the literature on <your topic>`""
