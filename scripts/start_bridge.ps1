# Starts the linked-phone WhatsApp bridge (demo route, WA_PROVIDER=wweb).
# First run: a QR code appears here and in bridge\qr.png. On the Debye phone:
#   WhatsApp -> Settings -> Linked Devices -> Link a Device -> scan.
# The session is kept in bridge\auth\ (gitignored). Delete that folder to link another phone.
param(
    [string]$BackendUrl = "http://localhost:8000",
    [int]$Port = 3010
)
$ErrorActionPreference = "Stop"
$bridge = Join-Path $PSScriptRoot "..\bridge"
Set-Location $bridge

if (-not (Test-Path (Join-Path $bridge "node_modules"))) {
    Write-Host "Installing bridge dependencies (first run)..."
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { npm install --no-audit --no-fund }
}

$env:WWEB_BACKEND_URL = $BackendUrl
$env:WWEB_BRIDGE_PORT = "$Port"
Write-Host "Bridge on http://127.0.0.1:$Port -> backend $BackendUrl (set WA_PROVIDER=wweb and WWEB_SECRET in .env)"
node index.mjs
