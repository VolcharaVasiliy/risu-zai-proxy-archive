param(
[string]$ProfileRoot = 'F:\Projects\risu-zai-proxy-archive\auth\grok-edge-profile',
  [string]$Url = 'https://grok.com/'
)

$profileRootResolved = [System.IO.Path]::GetFullPath($ProfileRoot)
$profileParent = Split-Path -Parent $profileRootResolved

if (-not (Test-Path -LiteralPath $profileParent)) {
  New-Item -ItemType Directory -Path $profileParent -Force | Out-Null
}

if (-not (Test-Path -LiteralPath $profileRootResolved)) {
  New-Item -ItemType Directory -Path $profileRootResolved -Force | Out-Null
}

$browserCandidates = @(
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
)

$browserPath = $browserCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $browserPath) {
  throw 'No supported Chromium browser found. Install Edge or Chrome, or edit scripts\launch-grok-auth.ps1.'
}

Start-Process -FilePath $browserPath -ArgumentList @(
  '--new-window',
  "--user-data-dir=$profileRootResolved",
  $Url
)

Write-Output "Browser started: $browserPath"
Write-Output "Profile root: $profileRootResolved"
Write-Output 'After you finish logging in, extract Grok cookies with:'
Write-Output "F:\DevTools\Python311\python.exe F:\Projects\risu-zai-proxy-archive\scripts\get-grok-creds.py --profile-root $profileRootResolved --output F:\Projects\risu-zai-proxy-archive\auth\grok-creds.json"
