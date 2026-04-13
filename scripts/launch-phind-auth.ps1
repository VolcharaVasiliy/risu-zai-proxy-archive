#!/usr/bin/env pwsh
# Launch Edge browser with dedicated Phind profile for authentication

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ProfilePath = Join-Path $ProjectRoot "auth\phind-edge-profile"

# Create profile directory if it doesn't exist
if (-not (Test-Path $ProfilePath)) {
    New-Item -ItemType Directory -Path $ProfilePath -Force | Out-Null
    Write-Host "Created profile directory: $ProfilePath"
}

# Find Edge executable
$EdgePaths = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe",
    "${env:LOCALAPPDATA}\Microsoft\Edge\Application\msedge.exe"
)

$EdgeExe = $null
foreach ($path in $EdgePaths) {
    if (Test-Path $path) {
        $EdgeExe = $path
        break
    }
}

if (-not $EdgeExe) {
    Write-Error "Microsoft Edge not found. Please install Edge or update the script with your browser path."
    exit 1
}

Write-Host "Launching Edge with Phind profile..."
Write-Host "Profile: $ProfilePath"
Write-Host ""
Write-Host "Instructions:"
Write-Host "1. Navigate to https://www.phind.com"
Write-Host "2. Log in to your Phind account (or use as guest)"
Write-Host "3. After login, close the browser"
Write-Host "4. Run scripts\get-phind-creds.py to extract cookies"
Write-Host ""

# Launch Edge with dedicated profile
& $EdgeExe `
    --user-data-dir="$ProfilePath" `
    --no-first-run `
    --no-default-browser-check `
    "https://www.phind.com"

Write-Host ""
Write-Host "Browser closed. You can now extract credentials with:"
Write-Host "  python scripts\get-phind-creds.py"
