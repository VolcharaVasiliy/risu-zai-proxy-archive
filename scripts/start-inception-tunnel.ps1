param(
  [int]$Port = 3001,
  [string]$CredsFile = '',
  [string]$Scope = 'spichekkorobok500-1532s-projects',
  [string]$LatestAlias = 'risu-zai-proxy-virid-eight.vercel.app',
  [string]$RootAlias = 'risu-zai-proxy-virid.vercel.app',
  [switch]$UpdateVercel,
  [switch]$Redeploy
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = 'F:\DevTools\Python311\python.exe'
$nodeExe = 'F:\DevTools\Portable\NodeJS\node.exe'
$cloudflaredExe = 'F:\DevTools\Portable\bin\cloudflared.exe'
$vercelCliScript = Join-Path $projectRoot 'node_modules\vercel\dist\index.js'
$serverScript = Join-Path $projectRoot 'py\inception_tunnel_server.py'
$projectPydeps = Join-Path $projectRoot 'pydeps'
$runRoot = Join-Path $projectRoot 'run'
$stateFile = Join-Path $runRoot 'inception-tunnel-state.json'
$serverLog = Join-Path $runRoot 'inception-tunnel-server.out.log'
$serverErrLog = Join-Path $runRoot 'inception-tunnel-server.err.log'
$tunnelLog = Join-Path $runRoot 'inception-tunnel-cloudflared.out.log'
$tunnelErrLog = Join-Path $runRoot 'inception-tunnel-cloudflared.err.log'

if (-not $CredsFile) {
  $CredsFile = Join-Path $projectRoot 'auth\inception-creds.json'
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
  throw "Python not found at $pythonExe"
}
if (-not (Test-Path -LiteralPath $nodeExe)) {
  throw "Node not found at $nodeExe"
}
if (-not (Test-Path -LiteralPath $cloudflaredExe)) {
  throw "cloudflared not found at $cloudflaredExe"
}
if (-not (Test-Path -LiteralPath $vercelCliScript)) {
  throw "Vercel CLI entrypoint not found at $vercelCliScript"
}
if (-not (Test-Path -LiteralPath $serverScript)) {
  throw "Server script not found: $serverScript"
}
if (-not (Test-Path -LiteralPath $CredsFile)) {
  throw "Inception credentials file not found: $CredsFile"
}

New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

function Stop-MatchingProcess {
  param([string]$Marker)
  Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$Marker*" } |
    ForEach-Object {
      try {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
      }
      catch {}
    }
}

function Wait-HttpReady {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [int]$TimeoutSeconds = 60
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
      if ($response.StatusCode -eq 200) {
        return $true
      }
    }
    catch {}
    Start-Sleep -Seconds 1
  }
  return $false
}

function Wait-TunnelUrl {
  param(
    [string[]]$LogPaths,
    [int]$TimeoutSeconds = 60
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    foreach ($path in $LogPaths) {
      if (Test-Path -LiteralPath $path) {
        $match = Select-String -Path $path -Pattern 'https://[-0-9a-z]+\.trycloudflare\.com' -AllMatches -ErrorAction SilentlyContinue |
          ForEach-Object { $_.Matches } |
          ForEach-Object { $_.Value } |
          Select-Object -First 1
        if ($match) {
          return $match
        }
      }
    }
    Start-Sleep -Seconds 1
  }
  return ''
}

$creds = Get-Content -LiteralPath $CredsFile -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($creds.inception_session_token)) {
  throw "Missing inception_session_token in $CredsFile"
}

Stop-MatchingProcess -Marker 'py\inception_tunnel_server.py'
Stop-MatchingProcess -Marker 'cloudflared.exe tunnel --url http://127.0.0.1:3001'
Stop-MatchingProcess -Marker ("cloudflared.exe tunnel --url http://127.0.0.1:{0}" -f $Port)

Remove-Item -LiteralPath $serverLog -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $serverErrLog -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $tunnelLog -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $tunnelErrLog -Force -ErrorAction SilentlyContinue

$previousCookie = $env:INCEPTION_COOKIE
$previousToken = $env:INCEPTION_SESSION_TOKEN
$previousEdgeUrl = $env:INCEPTION_EDGE_URL
$previousForceEdge = $env:INCEPTION_FORCE_EDGE
$previousPort = $env:INCEPTION_TUNNEL_PORT
$previousHost = $env:INCEPTION_TUNNEL_HOST
$previousPythonPath = $env:PYTHONPATH

$env:INCEPTION_COOKIE = [string]$creds.inception_cookie
$env:INCEPTION_SESSION_TOKEN = [string]$creds.inception_session_token
$env:INCEPTION_EDGE_URL = ''
$env:INCEPTION_FORCE_EDGE = ''
$env:INCEPTION_TUNNEL_PORT = [string]$Port
$env:INCEPTION_TUNNEL_HOST = '127.0.0.1'
$env:PYTHONPATH = "$projectRoot;$projectPydeps"

try {
  $serverProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'py.inception_tunnel_server') -RedirectStandardOutput $serverLog -RedirectStandardError $serverErrLog -PassThru -WindowStyle Hidden
}
finally {
  $env:INCEPTION_COOKIE = $previousCookie
  $env:INCEPTION_SESSION_TOKEN = $previousToken
  $env:INCEPTION_EDGE_URL = $previousEdgeUrl
  $env:INCEPTION_FORCE_EDGE = $previousForceEdge
  $env:INCEPTION_TUNNEL_PORT = $previousPort
  $env:INCEPTION_TUNNEL_HOST = $previousHost
  $env:PYTHONPATH = $previousPythonPath
}

if (-not (Wait-HttpReady -Url "http://127.0.0.1:$Port/health" -TimeoutSeconds 60)) {
  throw "Local Inception tunnel server did not become healthy on port $Port"
}

$tunnelArgs = @(
  'tunnel',
  '--no-autoupdate',
  '--url', "http://127.0.0.1:$Port"
)
$tunnelProcess = Start-Process -FilePath $cloudflaredExe -ArgumentList $tunnelArgs -RedirectStandardOutput $tunnelLog -RedirectStandardError $tunnelErrLog -PassThru -WindowStyle Hidden
$tunnelUrl = Wait-TunnelUrl -LogPaths @($tunnelLog, $tunnelErrLog) -TimeoutSeconds 90
if (-not $tunnelUrl) {
  throw "Could not detect trycloudflare URL in $tunnelLog"
}

$state = [ordered]@{
  started_at = (Get-Date).ToString('o')
  port = $Port
  local_url = "http://127.0.0.1:$Port"
  tunnel_url = $tunnelUrl
  server_pid = $serverProcess.Id
  tunnel_pid = $tunnelProcess.Id
  creds_file = $CredsFile
  server_log = $serverLog
  server_err_log = $serverErrLog
  tunnel_log = $tunnelLog
  tunnel_err_log = $tunnelErrLog
}
$state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $stateFile -Encoding UTF8

if (-not (Wait-HttpReady -Url "$tunnelUrl/health" -TimeoutSeconds 180)) {
  Write-Warning "Tunnel health check did not return 200 before timeout: $tunnelUrl"
}

if ($UpdateVercel -or $Redeploy) {
  & $nodeExe $vercelCliScript env add INCEPTION_EDGE_URL production --value $tunnelUrl --yes --force --non-interactive --scope $Scope | Out-Host
  & $nodeExe $vercelCliScript env add INCEPTION_FORCE_EDGE production --value true --yes --force --non-interactive --scope $Scope | Out-Host
}

if ($Redeploy) {
  & $nodeExe $vercelCliScript deploy --prod -y --force --non-interactive --scope $Scope | Out-Host
  if ($LatestAlias -and $RootAlias) {
    & $nodeExe $vercelCliScript alias set $LatestAlias $RootAlias --scope $Scope | Out-Host
  }
}

Write-Output "Local Inception tunnel server: http://127.0.0.1:$Port"
Write-Output "Cloudflare quick tunnel: $tunnelUrl"
Write-Output "State file: $stateFile"
exit 0
