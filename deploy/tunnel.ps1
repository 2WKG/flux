# Preflight the origin host, then run the Cloudflare Tunnel connector in the
# foreground. Start deploy/serve.ps1 in another shell first.
#
# One-time setup (interactive, owner only) is in
# docs/runbooks/static-origin-and-tunnel.md. This script never creates a tunnel,
# logs in, or changes DNS.

[CmdletBinding()]
param(
  [string]$Tunnel = 'flux-demo',
  [int]$Port = 4173,
  [int]$ApiPort = 8000,
  [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$fail = @()

# 1. Connector binary.
$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($cf) {
  Write-Host "ok   cloudflared: $($cf.Source)" -ForegroundColor Green
} else {
  $fail += "cloudflared is not on PATH. Install it: winget install --id Cloudflare.cloudflared"
}

# 2. Credentials and ingress config, written by the one-time setup.
$cfDir = Join-Path $env:USERPROFILE '.cloudflared'
$config = Join-Path $cfDir 'config.yml'
if (Test-Path $config) {
  Write-Host "ok   config: $config" -ForegroundColor Green
} else {
  $fail += "$config is missing. Copy deploy/cloudflared/config.example.yml there and fill in the credentials path."
}
if ((Test-Path $cfDir) -and (Get-ChildItem $cfDir -Filter '*.json' -ErrorAction SilentlyContinue)) {
  Write-Host "ok   tunnel credentials present in $cfDir" -ForegroundColor Green
} else {
  $fail += "No tunnel credentials in $cfDir. Run: cloudflared tunnel login; cloudflared tunnel create $Tunnel"
}

# 3. Both local origins must answer before the tunnel publishes them. The
# template maps only the API's explicit read paths to the API port.
try {
  $r = Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 5
  Write-Host "ok   origin: http://127.0.0.1:$Port/ returned $($r.StatusCode)" -ForegroundColor Green
} catch {
  $fail += "The static origin is not answering on http://127.0.0.1:$Port/. Start it: ./deploy/serve.ps1"
}

try {
  $r = Invoke-WebRequest "http://127.0.0.1:$ApiPort/health" -UseBasicParsing -TimeoutSec 5
  Write-Host "ok   API health: http://127.0.0.1:$ApiPort/health returned $($r.StatusCode)" -ForegroundColor Green
} catch {
  $status = $_.Exception.Response.StatusCode.value__
  if ($status -eq 503) {
    Write-Host "ok   API health: http://127.0.0.1:$ApiPort/health returned documented unavailable 503" -ForegroundColor Green
  } else {
    $fail += "The API health endpoint is not answering on http://127.0.0.1:$ApiPort/health. Start it: uv run uvicorn copilot.app:app --port $ApiPort"
  }
}

if ($fail.Count -gt 0) {
  Write-Host ''
  foreach ($f in $fail) { Write-Host "FAIL $f" -ForegroundColor Red }
  throw "$($fail.Count) preflight check(s) failed; the tunnel was not started."
}

if ($CheckOnly) { Write-Host "`nAll preflight checks passed." -ForegroundColor Green; return }

Write-Host "`nRunning tunnel '$Tunnel' (Ctrl+C to stop). Verify with: curl.exe -I https://bouncepulse.com/" -ForegroundColor Cyan
cloudflared tunnel run $Tunnel
