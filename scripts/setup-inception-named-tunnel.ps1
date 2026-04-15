param(
  [string]$TunnelName = 'risu-inception-local',
  [string]$Hostname = '',
  [int]$Port = 3001,
  [string]$CredsFile = '',
  [string]$Scope = 'spichekkorobok500-1532s-projects',
  [string]$LatestAlias = 'risu-zai-proxy-virid-eight.vercel.app',
  [string]$RootAlias = 'risu-zai-proxy-virid.vercel.app',
  [switch]$LaunchLogin,
  [switch]$UpdateVercel,
  [switch]$Redeploy
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$cloudflaredExe = 'F:\DevTools\Portable\bin\cloudflared.exe'
$nodeExe = 'F:\DevTools\Portable\NodeJS\node.exe'
$vercelCliScript = Join-Path $projectRoot 'node_modules\vercel\dist\index.js'
$startQuickTunnelScript = Join-Path $projectRoot 'scripts\start-inception-tunnel.ps1'
$runRoot = Join-Path $projectRoot 'run'
$stateFile = Join-Path $runRoot 'inception-named-tunnel-state.json'
$defaultCredsFile = Join-Path $projectRoot 'auth\inception-creds.json'
$defaultConfigPath = Join-Path $projectRoot 'auth\inception-named-tunnel.yml'
$originCert = $env:TUNNEL_ORIGIN_CERT

if (-not $CredsFile) {
  $CredsFile = $defaultCredsFile
}
if (-not $originCert) {
  $candidate = Join-Path $env:USERPROFILE '.cloudflared\cert.pem'
  if (Test-Path -LiteralPath $candidate) {
    $originCert = $candidate
  }
}

if (-not (Test-Path -LiteralPath $cloudflaredExe)) {
  throw "cloudflared not found at $cloudflaredExe"
}
if (-not (Test-Path -LiteralPath $CredsFile)) {
  throw "Inception credentials file not found: $CredsFile"
}

New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

if (-not $originCert) {
  if ($LaunchLogin) {
    Start-Process -FilePath $cloudflaredExe -ArgumentList @('tunnel', 'login')
    Start-Sleep -Seconds 5
    $candidate = Join-Path $env:USERPROFILE '.cloudflared\cert.pem'
    if (Test-Path -LiteralPath $candidate) {
      $originCert = $candidate
    }
  }

  if (-not $originCert) {
    $fallbackArgs = @(
      '-NoProfile',
      '-ExecutionPolicy', 'Bypass',
      '-File', $startQuickTunnelScript,
      '-Port', $Port,
      '-CredsFile', $CredsFile
    )
    if ($UpdateVercel) {
      $fallbackArgs += '-UpdateVercel'
    }
    if ($Redeploy) {
      $fallbackArgs += '-Redeploy'
    }
    & powershell @fallbackArgs
    throw 'Named tunnel is blocked: Cloudflare cert.pem is missing. quick tunnel fallback was started instead. Run `cloudflared tunnel login`, pick a zone in the browser, then rerun this script with -Hostname.'
  }
}

if (-not $Hostname) {
  throw 'Named tunnel setup requires -Hostname once cert.pem is available, for example -Hostname inception.example.com'
}

$config = @"
tunnel: $TunnelName
credentials-file: $env:USERPROFILE\.cloudflared\$TunnelName.json

ingress:
  - hostname: $Hostname
    service: http://127.0.0.1:$Port
  - service: http_status:404
"@
$config | Set-Content -LiteralPath $defaultConfigPath -Encoding ASCII

$state = [ordered]@{
  tunnel_name = $TunnelName
  hostname = $Hostname
  port = $Port
  creds_file = $CredsFile
  origin_cert = $originCert
  config_path = $defaultConfigPath
}
$state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $stateFile -Encoding UTF8

if ($UpdateVercel -or $Redeploy) {
  & $nodeExe $vercelCliScript env add INCEPTION_EDGE_URL production --value "https://$Hostname" --yes --force --non-interactive --scope $Scope | Out-Host
  & $nodeExe $vercelCliScript env add INCEPTION_FORCE_EDGE production --value true --yes --force --non-interactive --scope $Scope | Out-Host
}

if ($Redeploy) {
  & $nodeExe $vercelCliScript deploy --prod -y --force --non-interactive --scope $Scope | Out-Host
  if ($LatestAlias -and $RootAlias) {
    & $nodeExe $vercelCliScript alias set $LatestAlias $RootAlias --scope $Scope | Out-Host
  }
}

Write-Output "Prepared named tunnel config: $defaultConfigPath"
Write-Output "Hostname: https://$Hostname"
Write-Output "State file: $stateFile"
