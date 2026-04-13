# Phind Credentials Extractor
# Launches Edge with CDP and extracts cookies + nonce from phindai.org

$EdgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$ProfilePath = ".\auth\phind-edge-profile"
$CdpPort = 9223
$OutputFile = ".\auth\phind-creds.json"

Write-Host "Launching Edge with CDP..." -ForegroundColor Cyan
Write-Host ""

# Launch Edge with CDP
$EdgeProcess = Start-Process -FilePath $EdgePath -ArgumentList @(
    "--remote-debugging-port=$CdpPort",
    "--user-data-dir=$ProfilePath",
    "--no-first-run",
    "--no-default-browser-check",
    "https://phindai.org/phind-chat/"
) -PassThru

# Wait for browser to start
Start-Sleep -Seconds 3

Write-Host "Browser launched. Please:" -ForegroundColor Yellow
Write-Host "1. Log in to phindai.org if not already logged in" -ForegroundColor Yellow
Write-Host "2. Press Enter when ready to extract credentials" -ForegroundColor Yellow
Write-Host ""

# Wait for user
Read-Host "Press Enter to continue"

Write-Host ""
Write-Host "Extracting credentials..." -ForegroundColor Cyan

# Run Node.js script to extract credentials
node scripts\get-phind-session.mjs

Write-Host ""
Write-Host "You can now close the browser and use Phind provider" -ForegroundColor Green
Write-Host ""
Write-Host "To use in Vercel, set these environment variables:" -ForegroundColor Cyan
Write-Host "  PHIND_COOKIE=<cookie from $OutputFile>" -ForegroundColor Gray
Write-Host "  PHIND_NONCE=<optional, auto-fetched if not set>" -ForegroundColor Gray
