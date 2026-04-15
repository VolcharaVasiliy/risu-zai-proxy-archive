param(
  [string]$TaskName = 'RisuInceptionTunnel'
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $projectRoot 'scripts\start-inception-tunnel.ps1'
$refreshScript = Join-Path $projectRoot 'scripts\refresh-inception-creds.ps1'
$startupDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$startupCmd = Join-Path $startupDir 'RisuInceptionTunnel.cmd'

if (-not (Test-Path -LiteralPath $scriptPath)) {
  throw "Launcher script not found: $scriptPath"
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$refreshScript`" -RestartTunnel -UpdateVercel -Redeploy"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

try {
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
  Write-Output "Registered scheduled task $TaskName"
}
catch {
  New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
@"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$refreshScript" -RestartTunnel -UpdateVercel -Redeploy
"@ | Set-Content -LiteralPath $startupCmd -Encoding ASCII
  Write-Output "Scheduled Task registration was denied; installed Startup launcher instead: $startupCmd"
}
