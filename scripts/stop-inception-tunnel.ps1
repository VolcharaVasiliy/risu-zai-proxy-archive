param()

$projectRoot = Split-Path -Parent $PSScriptRoot
$stateFile = Join-Path $projectRoot 'run\inception-tunnel-state.json'

function Stop-PidIfRunning {
  param([int]$Pid)
  try {
    Stop-Process -Id $Pid -Force -ErrorAction Stop
  }
  catch {}
}

if (Test-Path -LiteralPath $stateFile) {
  $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
  if ($state.server_pid) {
    Stop-PidIfRunning -Pid ([int]$state.server_pid)
  }
  if ($state.tunnel_pid) {
    Stop-PidIfRunning -Pid ([int]$state.tunnel_pid)
  }
  Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
}

Get-CimInstance Win32_Process |
  Where-Object {
    $_.CommandLine -and (
      $_.CommandLine -like '*py\inception_tunnel_server.py*' -or
      $_.CommandLine -like '*cloudflared.exe tunnel --url http://127.0.0.1:3001*'
    )
  } |
  ForEach-Object {
    try {
      Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
    }
    catch {}
  }
