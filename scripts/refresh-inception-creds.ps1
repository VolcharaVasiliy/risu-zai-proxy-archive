param(
  [string]$OutputFile = '',
  [string]$ProfileRoot = '',
  [string]$DesktopCookieExport = '',
  [switch]$RestartTunnel,
  [switch]$UpdateVercel,
  [switch]$Redeploy
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = 'F:\DevTools\Python311\python.exe'
$extractorScript = Join-Path $projectRoot 'scripts\get-inception-creds.py'
$startScript = Join-Path $projectRoot 'scripts\start-inception-tunnel.ps1'

if (-not $OutputFile) {
  $OutputFile = Join-Path $projectRoot 'auth\inception-creds.json'
}

if (-not $DesktopCookieExport) {
  $desktopDir = [Environment]::GetFolderPath('Desktop')
  $desktopCandidate = Get-ChildItem -LiteralPath $desktopDir -Filter '*.txt' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Where-Object {
      try {
        $text = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction Stop
        $text -match '"name"\s*:\s*"session"' -and $text -match '"name"\s*:\s*"_vcrcs"'
      }
      catch {
        $false
      }
    } |
    Select-Object -First 1
  if ($desktopCandidate) {
    $DesktopCookieExport = $desktopCandidate.FullName
  }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFile) | Out-Null

function Write-CredsFromDesktopExport {
  param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath,
    [Parameter(Mandatory = $true)]
    [string]$TargetPath
  )

  $cookies = Get-Content -LiteralPath $SourcePath -Raw | ConvertFrom-Json
  $pairs = @()
  foreach ($item in $cookies) {
    if ($item.name -and $item.value) {
      $pairs += ('{0}={1}' -f [string]$item.name, [string]$item.value)
    }
  }

  $session = ($cookies | Where-Object { $_.name -eq 'session' } | Select-Object -First 1).value
  if ([string]::IsNullOrWhiteSpace([string]$session)) {
    throw "session cookie not found in $SourcePath"
  }

  $payload = [ordered]@{
    inception_cookie = ($pairs -join '; ')
    inception_session_token = [string]$session
  }
  $payload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $TargetPath -Encoding UTF8
}

if ($ProfileRoot) {
  & $pythonExe $extractorScript --profile-root $ProfileRoot --output $OutputFile
}
elseif (Test-Path -LiteralPath $DesktopCookieExport) {
  Write-CredsFromDesktopExport -SourcePath $DesktopCookieExport -TargetPath $OutputFile
}
else {
  throw "No Inception source found. Provide -ProfileRoot or place a cookie export at $DesktopCookieExport"
}

Write-Output "Updated Inception credentials: $OutputFile"

if ($RestartTunnel) {
  $args = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', $startScript,
    '-CredsFile', $OutputFile
  )
  if ($UpdateVercel) {
    $args += '-UpdateVercel'
  }
  if ($Redeploy) {
    $args += '-Redeploy'
  }
  & powershell @args
}
