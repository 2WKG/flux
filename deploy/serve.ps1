# Build and serve the static demo origin. Run this before deploy/tunnel.ps1.
#
# The origin is web/server.mjs serving web/dist/; it exposes no API route.
# See docs/runbooks/static-origin-and-tunnel.md.

[CmdletBinding()]
param(
  [int]$Port = 4173,
  [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

if (-not $SkipBuild) {
  Write-Host "Building web/dist ..." -ForegroundColor Cyan
  npm --prefix "$repo/web" ci
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed (exit $LASTEXITCODE)" }
  npm --prefix "$repo/web" run build
  if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit $LASTEXITCODE)" }
}

if (-not (Test-Path "$repo/web/dist/index.html")) {
  throw "web/dist/index.html is missing. Run without -SkipBuild."
}

$env:PORT = $Port
Write-Host "Serving $repo/web/dist on http://127.0.0.1:$Port (Ctrl+C to stop)" -ForegroundColor Green
node "$repo/web/server.mjs"
