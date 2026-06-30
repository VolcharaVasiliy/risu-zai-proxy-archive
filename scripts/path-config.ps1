$script:RzaiProjectRoot = Split-Path -Parent $PSScriptRoot
$script:RzaiPathConfig = $null

$configCandidates = @($env:RZAI_PATH_CONFIG, $env:PATH_CONFIG, (Join-Path $script:RzaiProjectRoot 'path-config.json')) |
  Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }

foreach ($candidate in $configCandidates) {
  $expanded = [Environment]::ExpandEnvironmentVariables([string]$candidate)
  if (Test-Path -LiteralPath $expanded) {
    $script:RzaiPathConfig = Get-Content -LiteralPath $expanded -Raw | ConvertFrom-Json
    break
  }
}

function Get-RzaiProjectRoot {
  return $script:RzaiProjectRoot
}

function Get-RzaiConfigValue {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Path,
    [object]$Default = ''
  )

  $node = $script:RzaiPathConfig
  foreach ($segment in $Path) {
    if ($null -eq $node) {
      return $Default
    }
    $property = $node.PSObject.Properties[$segment]
    if ($null -eq $property) {
      return $Default
    }
    $node = $property.Value
  }
  if ($null -eq $node) {
    return $Default
  }
  return $node
}

function Resolve-RzaiProjectPath {
  param(
    [AllowEmptyString()]
    [string]$Value,
    [Parameter(Mandatory = $true)]
    [string]$Default
  )

  $text = if ([string]::IsNullOrWhiteSpace($Value)) { $Default } else { $Value }
  $expanded = [Environment]::ExpandEnvironmentVariables($text)
  if ([System.IO.Path]::IsPathRooted($expanded)) {
    return [System.IO.Path]::GetFullPath($expanded)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $script:RzaiProjectRoot $expanded))
}

function Resolve-RzaiExecutable {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Candidates,
    [string]$Label = 'Executable'
  )

  foreach ($candidate in $Candidates) {
    if ([string]::IsNullOrWhiteSpace($candidate)) {
      continue
    }
    $expanded = [Environment]::ExpandEnvironmentVariables($candidate)
    if ([System.IO.Path]::IsPathRooted($expanded)) {
      if (Test-Path -LiteralPath $expanded) {
        return [System.IO.Path]::GetFullPath($expanded)
      }
      continue
    }
    if ($expanded.Contains('\') -or $expanded.Contains('/')) {
      $projectPath = Resolve-RzaiProjectPath -Value $expanded -Default $expanded
      if (Test-Path -LiteralPath $projectPath) {
        return $projectPath
      }
      continue
    }
    $command = Get-Command $expanded -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
      return $command.Source
    }
    if (Test-Path -LiteralPath $expanded) {
      return [System.IO.Path]::GetFullPath($expanded)
    }
  }
  throw "$Label was not found. Set it in path-config.json, an environment variable, or PATH."
}

function Resolve-RzaiPython {
  $candidates = @(
    $env:PYTHON,
    $env:PYTHON_EXE,
    (Get-RzaiConfigValue -Path @('python', 'executable')),
    'python.exe',
    'python3',
    'python'
  )
  return Resolve-RzaiExecutable -Candidates $candidates -Label 'Python'
}

function Resolve-RzaiNode {
  $candidates = @(
    $env:NODE,
    $env:NODE_EXE,
    (Get-RzaiConfigValue -Path @('node', 'executable')),
    'node.exe',
    'node'
  )
  return Resolve-RzaiExecutable -Candidates $candidates -Label 'Node.js'
}

function Resolve-RzaiCloudflared {
  $candidates = @(
    $env:CLOUDFLARED,
    $env:CLOUDFLARED_EXE,
    (Get-RzaiConfigValue -Path @('cloudflared', 'executable')),
    'cloudflared.exe',
    'cloudflared'
  )
  return Resolve-RzaiExecutable -Candidates $candidates -Label 'cloudflared'
}

function Join-RzaiEnvPath {
  param(
    [string]$EnvName,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Parts
  )

  $root = [Environment]::GetEnvironmentVariable($EnvName)
  if ([string]::IsNullOrWhiteSpace($root)) {
    return ''
  }
  $path = $root
  foreach ($part in $Parts) {
    $path = Join-Path $path $part
  }
  return $path
}

function Get-RzaiBrowserCandidates {
  param([switch]$IncludeYandex)

  $candidates = @(
    $env:BROWSER_PATH,
    $env:EDGE_PATH,
    $env:CHROME_PATH,
    (Get-RzaiConfigValue -Path @('browser', 'executable'))
  )
  if ($IncludeYandex) {
    $candidates += @(
      (Get-RzaiConfigValue -Path @('browser', 'yandexExecutable')),
      (Join-RzaiEnvPath 'LOCALAPPDATA' 'Yandex' 'YandexBrowser' 'Application' 'browser.exe')
    )
  }
  $candidates += @(
    (Join-RzaiEnvPath 'ProgramFiles(x86)' 'Microsoft' 'Edge' 'Application' 'msedge.exe'),
    (Join-RzaiEnvPath 'ProgramFiles' 'Microsoft' 'Edge' 'Application' 'msedge.exe'),
    (Join-RzaiEnvPath 'LOCALAPPDATA' 'Microsoft' 'Edge' 'Application' 'msedge.exe'),
    (Join-RzaiEnvPath 'ProgramFiles' 'Google' 'Chrome' 'Application' 'chrome.exe'),
    (Join-RzaiEnvPath 'ProgramFiles(x86)' 'Google' 'Chrome' 'Application' 'chrome.exe'),
    (Join-RzaiEnvPath 'LOCALAPPDATA' 'Google' 'Chrome' 'Application' 'chrome.exe')
  )
  return $candidates | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -Unique
}

function Resolve-RzaiBrowser {
  param([switch]$IncludeYandex)
  foreach ($candidate in (Get-RzaiBrowserCandidates -IncludeYandex:$IncludeYandex)) {
    if (Test-Path -LiteralPath $candidate) {
      return [System.IO.Path]::GetFullPath($candidate)
    }
  }
  throw 'No supported Chromium browser found. Install Edge/Chrome/Yandex or set browser.executable in path-config.json.'
}

function Get-RzaiAuthProfile {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [string]$DefaultFolder
  )

  $envName = ('RZAI_{0}_PROFILE_ROOT' -f $Name.ToUpperInvariant())
  $value = [Environment]::GetEnvironmentVariable($envName)
  if ([string]::IsNullOrWhiteSpace($value)) {
    $value = [string](Get-RzaiConfigValue -Path @('profiles', $Name))
  }
  return Resolve-RzaiProjectPath -Value $value -Default (Join-Path 'auth' $DefaultFolder)
}

function Get-RzaiAuthOutput {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [string]$DefaultFile
  )

  $envName = ('RZAI_{0}_CREDS_FILE' -f $Name.ToUpperInvariant())
  $value = [Environment]::GetEnvironmentVariable($envName)
  if ([string]::IsNullOrWhiteSpace($value)) {
    $value = [string](Get-RzaiConfigValue -Path @('authOutputs', $Name))
  }
  return Resolve-RzaiProjectPath -Value $value -Default (Join-Path 'auth' $DefaultFile)
}
