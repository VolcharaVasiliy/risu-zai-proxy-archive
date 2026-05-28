param(
  [string]$CodexHome = "$env:USERPROFILE\.codex",
  [string]$BaseUrl = "https://risu-zai-proxy-virid.vercel.app/v1",
  [string]$LocalBaseUrl = "http://127.0.0.1:3001/v1",
  [string]$Model = "Qwen3.7-Max",
  [string]$ApiKey = "local",
  [switch]$NoPath,
  [switch]$NoCatalog
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptRoot
$codexHomePath = [System.IO.Path]::GetFullPath($CodexHome)
$binDir = Join-Path $codexHomePath "bin"
$catalogPath = Join-Path $codexHomePath "risu-zai-model-catalog.json"
$configPath = Join-Path $codexHomePath "risu-zai.config.toml"
$launcherSource = Join-Path $scriptRoot "rzai-launcher.ps1"
$launcherTarget = Join-Path $binDir "risu-zai.ps1"
$risuCmd = Join-Path $binDir "risu-zai.cmd"
$rzaiCmd = Join-Path $binDir "rzai.cmd"

function ConvertTo-TomlString {
  param([string]$Value)
  $escaped = $Value.Replace("\", "\\").Replace('"', '\"')
  return '"' + $escaped + '"'
}

function ConvertTo-PowerShellString {
  param([string]$Value)
  $escaped = $Value.Replace("'", "''")
  return "'" + $escaped + "'"
}

function ConvertTo-TomlPath {
  param([string]$Path)
  return ($Path.Replace("\", "/"))
}

function Resolve-Python {
  $candidates = @(
    $env:PYTHON,
    "F:\DevTools\Python311\python.exe",
    "python.exe",
    "python3",
    "python"
  ) | Where-Object { $_ -and [string]::IsNullOrWhiteSpace($_) -eq $false }

  foreach ($candidate in $candidates) {
    if ([System.IO.Path]::IsPathRooted($candidate) -and -not (Test-Path -LiteralPath $candidate)) {
      continue
    }
    try {
      & $candidate --version *> $null
      if ($LASTEXITCODE -eq 0) {
        return $candidate
      }
    } catch {
      continue
    }
  }
  return ""
}

if (-not (Test-Path -LiteralPath $launcherSource)) {
  throw "Launcher template not found: $launcherSource"
}

New-Item -ItemType Directory -Force -Path $codexHomePath | Out-Null
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

$launcherText = Get-Content -LiteralPath $launcherSource -Raw
$launcherText = $launcherText -replace '(?m)^\$defaultRemoteBaseUrl = .+$', ('$defaultRemoteBaseUrl = ' + (ConvertTo-PowerShellString $BaseUrl))
$launcherText = $launcherText -replace '(?m)^\$defaultLocalBaseUrl = .+$', ('$defaultLocalBaseUrl = ' + (ConvertTo-PowerShellString $LocalBaseUrl))
$launcherText = $launcherText -replace '(?m)^\$defaultModel = .+$', ('$defaultModel = ' + (ConvertTo-PowerShellString $Model))
$launcherText | Set-Content -LiteralPath $launcherTarget -Encoding UTF8

@"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0risu-zai.ps1" %*
"@ | Set-Content -LiteralPath $risuCmd -Encoding ASCII

@"
@echo off
call "%~dp0risu-zai.cmd" %*
"@ | Set-Content -LiteralPath $rzaiCmd -Encoding ASCII

if (-not $NoCatalog) {
  $python = Resolve-Python
  if (-not $python) {
    throw "Python was not found. Install Python 3.11 or pass -NoCatalog and generate the catalog later."
  }
  & $python (Join-Path $scriptRoot "generate-codex-catalog.py") --output $catalogPath
  if ($LASTEXITCODE -ne 0) {
    throw "Codex catalog generation failed."
  }
}

$catalogTomlPath = ConvertTo-TomlPath $catalogPath
$config = @"
model_provider = "risu-zai"
model = $(ConvertTo-TomlString $Model)
model_reasoning_effort = "xhigh"
preferred_auth_method = "apikey"
model_catalog_json = $(ConvertTo-TomlString $catalogTomlPath)
approvals_reviewer = "user"

[model_providers.risu-zai]
name = "Risu ZAI Proxy"
base_url = $(ConvertTo-TomlString $BaseUrl)
wire_api = "responses"
env_key = "CODEX_API_KEY"
"@
$config | Set-Content -LiteralPath $configPath -Encoding UTF8

if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
  [System.Environment]::SetEnvironmentVariable("CODEX_API_KEY", $ApiKey, "User")
}

if (-not $NoPath) {
  $currentPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
  $parts = @($currentPath -split ";" | Where-Object { $_ })
  $alreadyPresent = $false
  foreach ($part in $parts) {
    if ([string]::Equals($part.TrimEnd("\"), $binDir.TrimEnd("\"), [System.StringComparison]::OrdinalIgnoreCase)) {
      $alreadyPresent = $true
      break
    }
  }
  if (-not $alreadyPresent) {
    $newPath = if ($currentPath) { "$currentPath;$binDir" } else { $binDir }
    [System.Environment]::SetEnvironmentVariable("Path", $newPath, "User")
  }
}

[pscustomobject]@{
  Ok = $true
  CodexHome = $codexHomePath
  Bin = $binDir
  Launcher = $launcherTarget
  Rzai = $rzaiCmd
  Config = $configPath
  Catalog = if (Test-Path -LiteralPath $catalogPath) { $catalogPath } else { "" }
  BaseUrl = $BaseUrl
  LocalBaseUrl = $LocalBaseUrl
  Model = $Model
  PathUpdated = -not $NoPath
} | Format-List

Write-Host "Open a new terminal, then run: rzai -Print"
