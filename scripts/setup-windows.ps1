param(
  [string]$BaseUrl = "https://risu-zai-proxy-virid.vercel.app/v1",
  [string]$LocalBaseUrl = "http://127.0.0.1:3001/v1",
  [string]$Model = "Qwen3.7-Max",
  [string]$ApiKey = "local",
  [string]$CodexHome = "$env:USERPROFILE\.codex",
  [switch]$SkipPythonDeps,
  [switch]$SkipCodexLauncher,
  [switch]$NoPath
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptRoot

function Resolve-CommandPath {
  param(
    [string[]]$Names,
    [string]$FriendlyName
  )

  foreach ($name in $Names) {
    if ([string]::IsNullOrWhiteSpace($name)) {
      continue
    }
    try {
      $cmd = Get-Command $name -ErrorAction Stop
      if ($cmd.Source) {
        return $cmd.Source
      }
    } catch {
      continue
    }
  }

  throw "$FriendlyName was not found. Install it first, then re-run this script."
}

function Invoke-Step {
  param(
    [string]$Name,
    [scriptblock]$Body
  )

  Write-Host ""
  Write-Host "==> $Name"
  & $Body
}

$python = Resolve-CommandPath @($env:PYTHON, $env:PYTHON_EXE, "python", "python3") "Python 3"
$node = Resolve-CommandPath @("node") "Node.js 20+"
$npm = Resolve-CommandPath @("npm") "npm"

Invoke-Step "Tool versions" {
  & $python --version
  & $node --version
  & $npm --version
}

Invoke-Step "Install Node packages" {
  Push-Location $projectRoot
  try {
    if (Test-Path -LiteralPath (Join-Path $projectRoot "package-lock.json")) {
      & $npm ci
    } else {
      & $npm install
    }
    if ($LASTEXITCODE -ne 0) {
      throw "npm install failed."
    }
  } finally {
    Pop-Location
  }
}

if (-not $SkipPythonDeps) {
  Invoke-Step "Install Python dependencies into pydeps" {
    Push-Location $projectRoot
    try {
      & $python -m pip install --target pydeps -r requirements.txt
      if ($LASTEXITCODE -ne 0) {
        throw "Python dependency install failed."
      }
    } finally {
      Pop-Location
    }
  }
}

if (-not $SkipCodexLauncher) {
  Invoke-Step "Install rzai Codex launcher" {
    $installer = Join-Path $scriptRoot "install-rzai.ps1"
    $installerArgs = @(
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      $installer,
      "-CodexHome",
      $CodexHome,
      "-BaseUrl",
      $BaseUrl,
      "-LocalBaseUrl",
      $LocalBaseUrl,
      "-Model",
      $Model,
      "-ApiKey",
      $ApiKey,
      "-NoCatalog"
    )
    if ($NoPath) {
      $installerArgs += "-NoPath"
    }
    & powershell @installerArgs
    if ($LASTEXITCODE -ne 0) {
      throw "rzai launcher install failed."
    }
  }
}

Invoke-Step "Generate local Codex catalog" {
  Push-Location $projectRoot
  try {
    $catalog = Join-Path $CodexHome "risu-zai-model-catalog.json"
    & $python .\scripts\generate-codex-catalog.py --output $catalog
    if ($LASTEXITCODE -ne 0) {
      throw "Catalog generation failed."
    }
    Write-Host "Catalog: $catalog"
  } finally {
    Pop-Location
  }
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "Open a new terminal if PATH was updated, then try:"
Write-Host "  rzai -Print"
Write-Host "  npm run dev"
Write-Host "  rzai -Local exec --ephemeral -s read-only -a never `"reply ok`""
