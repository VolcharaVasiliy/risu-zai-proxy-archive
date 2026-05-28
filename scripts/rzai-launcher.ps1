#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

$profileName = "risu-zai"
$defaultRemoteBaseUrl = "https://risu-zai-proxy-virid.vercel.app/v1"
$defaultLocalBaseUrl = "http://127.0.0.1:3001/v1"
$defaultModel = "Qwen3.7-Max"

function Show-RisuZaiHelp {
    @"
Usage:
  rzai     [launcher options] [codex options] [prompt]
  risu-zai [launcher options] [codex options] [prompt]

Launcher options:
  -Local                 Use http://127.0.0.1:3001/v1 instead of Vercel.
  -Remote                Use the Vercel endpoint. This is the default.
  -BaseUrl <url>         Use a custom OpenAI-compatible /v1 base URL.
  -Model <id>            Override Codex model. Default profile model is $defaultModel.
  -ApiKey <value>        Set CODEX_API_KEY for this run. Defaults to 'local' if empty.
  -Print                 Print the resolved codex command without running it.
  -Help                  Show this help.

Everything else is passed to codex.

Examples:
  rzai
  rzai "fix tests"
  rzai -Model mistral-small-2603 "explain this repo"
  rzai -Local exec --ephemeral -s read-only -a never "reply ok"
  rzai -BaseUrl https://example.vercel.app/v1 --search
"@
}

function Get-RequiredValue {
    param(
        [string[]] $AllArgs,
        [int] $Index,
        [string] $OptionName
    )

    if ($Index + 1 -ge $AllArgs.Count) {
        throw "$OptionName requires a value."
    }

    return $AllArgs[$Index + 1]
}

function ConvertTo-TomlString {
    param([string] $Value)

    $escaped = $Value.Replace("\", "\\").Replace('"', '\"')
    return '"' + $escaped + '"'
}

function Normalize-CodexArgs {
    param([System.Collections.Generic.List[string]] $InputArgs)

    $items = @($InputArgs)
    if ($items.Count -eq 0) {
        return @()
    }

    $execIndex = -1
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ($items[$i] -eq "--") {
            break
        }
        if ($items[$i] -eq "exec" -or $items[$i] -eq "e") {
            $execIndex = $i
            break
        }
    }

    if ($execIndex -lt 0) {
        return $items
    }

    $globalArgs = New-Object System.Collections.Generic.List[string]
    $execArgs = New-Object System.Collections.Generic.List[string]

    for ($i = 0; $i -lt $execIndex; $i++) {
        [void] $globalArgs.Add([string] $items[$i])
    }

    [void] $execArgs.Add([string] $items[$execIndex])

    for ($i = $execIndex + 1; $i -lt $items.Count; $i++) {
        $item = [string] $items[$i]

        if ($item -eq "--") {
            for ($j = $i; $j -lt $items.Count; $j++) {
                [void] $execArgs.Add([string] $items[$j])
            }
            break
        }

        if ($item -eq "-a" -or $item -eq "--ask-for-approval") {
            if ($i + 1 -ge $items.Count) {
                throw "$item requires a value."
            }
            [void] $globalArgs.Add($item)
            [void] $globalArgs.Add([string] $items[$i + 1])
            $i++
            continue
        }

        if ($item -like "--ask-for-approval=*" -or $item -like "-a=*") {
            [void] $globalArgs.Add($item)
            continue
        }

        if ($item -eq "--search" -or $item -eq "--no-alt-screen") {
            [void] $globalArgs.Add($item)
            continue
        }

        [void] $execArgs.Add($item)
    }

    return @($globalArgs) + @($execArgs)
}

function Add-SkipGitRepoCheckForExec {
    param([object[]] $InputArgs)

    $items = @($InputArgs)
    if ($items.Count -eq 0) {
        return $items
    }

    $execIndex = -1
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ($items[$i] -eq "--") {
            break
        }
        if ($items[$i] -eq "exec" -or $items[$i] -eq "e") {
            $execIndex = $i
            break
        }
    }

    if ($execIndex -lt 0) {
        return $items
    }

    foreach ($item in $items) {
        if ($item -eq "--skip-git-repo-check") {
            return $items
        }
    }

    $before = @()
    if ($execIndex -gt 0) {
        $before = $items[0..($execIndex - 1)]
    }
    $after = @()
    if ($execIndex + 1 -lt $items.Count) {
        $after = $items[($execIndex + 1)..($items.Count - 1)]
    }

    return @($before) + @($items[$execIndex]) + @("--skip-git-repo-check") + @($after)
}

$useLocal = $false
$baseUrl = $null
$model = $null
$apiKey = $null
$printOnly = $false
$codexArgs = New-Object System.Collections.Generic.List[string]

:argLoop for ($i = 0; $i -lt $args.Count; $i++) {
    $arg = [string] $args[$i]

    switch -Regex ($arg) {
        "^(--local|-local|-Local)$" {
            $useLocal = $true
            continue
        }
        "^(--remote|-remote|-Remote|-Vercel|--vercel)$" {
            $useLocal = $false
            continue
        }
        "^(--base-url|-base-url|-BaseUrl)$" {
            $baseUrl = Get-RequiredValue $args $i $arg
            $i++
            continue
        }
        "^(--model|-model|-Model)$" {
            $model = Get-RequiredValue $args $i $arg
            $i++
            continue
        }
        "^(--api-key|-api-key|-ApiKey)$" {
            $apiKey = Get-RequiredValue $args $i $arg
            $i++
            continue
        }
        "^(--print|-print|-Print)$" {
            $printOnly = $true
            continue
        }
        "^(--help|-help|-Help|-h|/\?)$" {
            Show-RisuZaiHelp
            exit 0
        }
        "^--$" {
            for ($j = $i + 1; $j -lt $args.Count; $j++) {
                [void] $codexArgs.Add([string] $args[$j])
            }
            break argLoop
        }
        default {
            [void] $codexArgs.Add($arg)
            continue
        }
    }
}

if (-not $baseUrl) {
    if ($useLocal) {
        $baseUrl = $defaultLocalBaseUrl
    } else {
        $baseUrl = $defaultRemoteBaseUrl
    }
}

if ($apiKey) {
    $env:CODEX_API_KEY = $apiKey
} elseif (-not $env:CODEX_API_KEY) {
    $env:CODEX_API_KEY = "local"
}

$codex = Get-Command codex -ErrorAction Stop

$resolvedArgs = New-Object System.Collections.Generic.List[string]
[void] $resolvedArgs.Add("-p")
[void] $resolvedArgs.Add($profileName)
[void] $resolvedArgs.Add("-c")
[void] $resolvedArgs.Add("model_providers.$profileName.base_url=$(ConvertTo-TomlString $baseUrl)")

if ($model) {
    [void] $resolvedArgs.Add("-m")
    [void] $resolvedArgs.Add($model)
}

$normalizedCodexArgs = Add-SkipGitRepoCheckForExec (Normalize-CodexArgs $codexArgs)
foreach ($item in $normalizedCodexArgs) {
    [void] $resolvedArgs.Add($item)
}

if ($printOnly) {
    Write-Host "CODEX_API_KEY=$env:CODEX_API_KEY"
    Write-Host ("codex " + (($resolvedArgs | ForEach-Object {
        if ($_ -match '\s') { '"' + $_.Replace('"', '\"') + '"' } else { $_ }
    }) -join " "))
    exit 0
}

& $codex.Source @resolvedArgs
exit $LASTEXITCODE
