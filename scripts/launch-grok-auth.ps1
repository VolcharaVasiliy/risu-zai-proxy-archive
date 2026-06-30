param(
  [string]$ProfileRoot = '',
  [string]$Url = 'https://grok.com/'
)

. "$PSScriptRoot\path-config.ps1"

if (-not $ProfileRoot) {
  $ProfileRoot = Get-RzaiAuthProfile -Name 'grok' -DefaultFolder 'grok-edge-profile'
}
$profileRootResolved = [System.IO.Path]::GetFullPath($ProfileRoot)
$profileParent = Split-Path -Parent $profileRootResolved

if (-not (Test-Path -LiteralPath $profileParent)) {
  New-Item -ItemType Directory -Path $profileParent -Force | Out-Null
}

if (-not (Test-Path -LiteralPath $profileRootResolved)) {
  New-Item -ItemType Directory -Path $profileRootResolved -Force | Out-Null
}

$browserPath = Resolve-RzaiBrowser

Start-Process -FilePath $browserPath -ArgumentList @(
  '--new-window',
  "--user-data-dir=$profileRootResolved",
  $Url
)

Write-Output "Browser started: $browserPath"
Write-Output "Profile root: $profileRootResolved"
Write-Output 'After you finish logging in, extract Grok cookies with:'
Write-Output "python scripts\get-grok-creds.py --profile-root `"$profileRootResolved`" --output `"$(Get-RzaiAuthOutput -Name 'grok' -DefaultFile 'grok-creds.json')`""
