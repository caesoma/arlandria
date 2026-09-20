$ErrorActionPreference = "Stop"
# Arlandria installer: installs the npm package and ensures `uv`, which provisions the Python
# primitives' dependencies on first run (PEP 723 - no pip, no requirements.txt, no venv).
Write-Host "==> Checking Node (need 22.19-24)"
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Write-Error "Node not found. Install Node 22.19-24 and re-run."
  exit 1
}
$nodeVersion = [version](node -p "process.versions.node")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($nodeVersion -lt [version]"22.19.0" -or $nodeVersion.Major -gt 24) {
  Write-Error "Need Node 22.19-24 (detected $nodeVersion)"
  exit 1
}
Write-Host "==> Checking uv (provisions the Python primitives - PEP 723)"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Error "uv not found. Install it, then re-run:  irm https://astral.sh/uv/install.ps1 | iex  (docs: https://docs.astral.sh/uv/)"
  exit 1
}
Write-Host "==> Installing arlandria (npm, global)"
npm install -g arlandria
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "==> Done. Run:  arlandria `"review the literature on <your topic>`""
