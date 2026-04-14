param(
  [ValidateSet('preview', 'production')]
  [string]$Target = 'production',
  [string]$CredsFile = '',
  [string]$GeminiWebCredsFile = '',
  [string]$GrokCredsFile = '',
  [string]$MistralCredsFile = '',
  [string]$OpenAIWebCredsFile = '',
  [string]$PhindCredsFile = '',
  [switch]$SyncEnv
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$nodeRoot = 'F:\DevTools\Portable\NodeJS'
$nodeExe = Join-Path $nodeRoot 'node.exe'
$pythonExe = 'F:\DevTools\Python311\python.exe'
$globalConfigDir = Join-Path $projectRoot '.vercel-global'
$vercelBin = Join-Path $projectRoot 'node_modules\.bin\vercel.cmd'
$vercelCliScript = Join-Path $projectRoot 'node_modules\vercel\dist\vc.js'
$credsScript = Join-Path $projectRoot 'scripts\get-provider-creds.py'
$defaultGeminiWebCredsFile = Join-Path $projectRoot 'auth\gemini-web-creds.json'
$defaultGrokCredsFile = Join-Path $projectRoot 'auth\grok-creds.json'
$defaultMistralCredsFile = Join-Path $projectRoot 'auth\mistral-creds.json'
$defaultOpenAIWebCredsFile = Join-Path $projectRoot 'auth\openai-web-creds.json'
$defaultPhindCredsFile = Join-Path $projectRoot 'auth\phind-creds.json'

if (-not (Test-Path -LiteralPath $vercelBin)) {
  throw "Vercel CLI not found at $vercelBin. Run npm install in $projectRoot first."
}

if (-not (Test-Path -LiteralPath $nodeExe)) {
  throw "Node not found at $nodeExe."
}

if (-not (Test-Path -LiteralPath $vercelCliScript)) {
  throw "Vercel CLI entrypoint not found at $vercelCliScript."
}

if (-not (Test-Path -LiteralPath $globalConfigDir)) {
  throw "Vercel global config directory not found at $globalConfigDir."
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
  throw "Python not found at $pythonExe."
}

$env:PATH = "$nodeRoot;$projectRoot\node_modules\.bin;$env:PATH"

function Invoke-Vercel {
  param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
  )

  & $nodeExe $vercelCliScript @Args
}

function Set-VercelEnv {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [AllowEmptyString()]
    [string]$Value
  )

  if ([string]::IsNullOrWhiteSpace($Value)) {
    return
  }

  Invoke-Vercel --global-config $globalConfigDir env add $Name $Target --value $Value --yes --force --non-interactive
}

if ($SyncEnv) {
  if ($Target -eq 'preview') {
    throw 'Preview env sync is not enabled in this script. Use project-level preview envs in Vercel or deploy preview without env sync.'
  }

  if ($CredsFile) {
    if (-not (Test-Path -LiteralPath $CredsFile)) {
      throw "Credentials file not found: $CredsFile"
    }
    $creds = Get-Content -LiteralPath $CredsFile -Raw | ConvertFrom-Json
  }
  else {
    $credsJson = & $pythonExe $credsScript
    $creds = $credsJson | ConvertFrom-Json
  }

  Set-VercelEnv -Name 'ZAI_TOKEN' -Value $creds.zai_token
  Set-VercelEnv -Name 'DEEPSEEK_TOKEN' -Value $creds.deepseek_token
  Set-VercelEnv -Name 'KIMI_TOKEN' -Value $creds.kimi_access_token
  Set-VercelEnv -Name 'GEMINI_WEB_COOKIE' -Value $creds.gemini_web_cookie
  Set-VercelEnv -Name 'GEMINI_WEB_SECURE_1PSID' -Value $creds.gemini_web_secure_1psid
  Set-VercelEnv -Name 'GEMINI_WEB_SECURE_1PSIDTS' -Value $creds.gemini_web_secure_1psidts
  Set-VercelEnv -Name 'MISTRAL_COOKIE' -Value $creds.mistral_cookie
  Set-VercelEnv -Name 'MISTRAL_CSRF_TOKEN' -Value $creds.mistral_csrf_token
  Set-VercelEnv -Name 'MIMO_SERVICE_TOKEN' -Value $creds.mimo_service_token
  Set-VercelEnv -Name 'MIMO_USER_ID' -Value $creds.mimo_user_id
  Set-VercelEnv -Name 'MIMO_PH_TOKEN' -Value $creds.mimo_ph_token
  Set-VercelEnv -Name 'QWEN_AI_COOKIE' -Value $creds.qwen_cookie
  Set-VercelEnv -Name 'QWEN_AI_TOKEN' -Value $creds.qwen_token
  Set-VercelEnv -Name 'PERPLEXITY_COOKIE' -Value $creds.perplexity_cookie
  Set-VercelEnv -Name 'PERPLEXITY_SESSION_TOKEN' -Value $creds.perplexity_session_token

  if (-not $GeminiWebCredsFile -and (Test-Path -LiteralPath $defaultGeminiWebCredsFile)) {
    $GeminiWebCredsFile = $defaultGeminiWebCredsFile
  }
  if (-not $GrokCredsFile -and (Test-Path -LiteralPath $defaultGrokCredsFile)) {
    $GrokCredsFile = $defaultGrokCredsFile
  }
  if (-not $MistralCredsFile -and (Test-Path -LiteralPath $defaultMistralCredsFile)) {
    $MistralCredsFile = $defaultMistralCredsFile
  }
  if (-not $OpenAIWebCredsFile -and (Test-Path -LiteralPath $defaultOpenAIWebCredsFile)) {
    $OpenAIWebCredsFile = $defaultOpenAIWebCredsFile
  }
  if (-not $PhindCredsFile -and (Test-Path -LiteralPath $defaultPhindCredsFile)) {
    $PhindCredsFile = $defaultPhindCredsFile
  }

  if ($GeminiWebCredsFile) {
    if (-not (Test-Path -LiteralPath $GeminiWebCredsFile)) {
      throw "Gemini Web credentials file not found: $GeminiWebCredsFile"
    }

    $geminiWebCreds = Get-Content -LiteralPath $GeminiWebCredsFile -Raw | ConvertFrom-Json
    Set-VercelEnv -Name 'GEMINI_WEB_COOKIE' -Value $geminiWebCreds.gemini_web_cookie
    Set-VercelEnv -Name 'GEMINI_WEB_SECURE_1PSID' -Value $geminiWebCreds.gemini_web_secure_1psid
    Set-VercelEnv -Name 'GEMINI_WEB_SECURE_1PSIDTS' -Value $geminiWebCreds.gemini_web_secure_1psidts
    if ($geminiWebCreds.gemini_web_models) {
      Set-VercelEnv -Name 'GEMINI_WEB_MODELS' -Value (($geminiWebCreds.gemini_web_models | ConvertTo-Json -Depth 10 -Compress))
    }
  }

  if ($GrokCredsFile) {
    if (-not (Test-Path -LiteralPath $GrokCredsFile)) {
      throw "Grok credentials file not found: $GrokCredsFile"
    }

    $grokCreds = Get-Content -LiteralPath $GrokCredsFile -Raw | ConvertFrom-Json
    Set-VercelEnv -Name 'GROK_COOKIE' -Value $grokCreds.grok_cookie
    Set-VercelEnv -Name 'GROK_SSO' -Value $grokCreds.grok_sso
    Set-VercelEnv -Name 'GROK_CF_CLEARANCE' -Value $grokCreds.grok_cf_clearance
  }

  if ($MistralCredsFile) {
    if (-not (Test-Path -LiteralPath $MistralCredsFile)) {
      throw "Mistral credentials file not found: $MistralCredsFile"
    }

    $mistralCreds = Get-Content -LiteralPath $MistralCredsFile -Raw | ConvertFrom-Json
    Set-VercelEnv -Name 'MISTRAL_COOKIE' -Value $mistralCreds.mistral_cookie
    Set-VercelEnv -Name 'MISTRAL_CSRF_TOKEN' -Value $mistralCreds.mistral_csrf_token
  }

  if ($OpenAIWebCredsFile) {
    if (-not (Test-Path -LiteralPath $OpenAIWebCredsFile)) {
      throw "OpenAI Web credentials file not found: $OpenAIWebCredsFile"
    }

    $openaiWebCreds = Get-Content -LiteralPath $OpenAIWebCredsFile -Raw | ConvertFrom-Json
    Set-VercelEnv -Name 'OPENAI_WEB_ACCESS_TOKEN' -Value $openaiWebCreds.openai_web_access_token
    Set-VercelEnv -Name 'OPENAI_WEB_COOKIE' -Value $openaiWebCreds.openai_web_cookie
    Set-VercelEnv -Name 'OPENAI_WEB_DEVICE_ID' -Value $openaiWebCreds.openai_web_device_id
    Set-VercelEnv -Name 'OPENAI_WEB_ACCOUNT_ID' -Value $openaiWebCreds.openai_web_account_id
    if ($openaiWebCreds.openai_web_models) {
      Set-VercelEnv -Name 'OPENAI_WEB_MODELS' -Value (($openaiWebCreds.openai_web_models | ConvertTo-Json -Compress))
    }
  }

  if ($PhindCredsFile) {
    if (-not (Test-Path -LiteralPath $PhindCredsFile)) {
      throw "Phind credentials file not found: $PhindCredsFile"
    }

    $phindCreds = Get-Content -LiteralPath $PhindCredsFile -Raw | ConvertFrom-Json
    Set-VercelEnv -Name 'PHIND_COOKIE' -Value $phindCreds.cookie
    # PHIND_NONCE is optional and auto-fetched, so we don't set it
  }
}

$deployArgs = @(
  '--global-config', $globalConfigDir,
  'deploy',
  $projectRoot,
  '-y',
  '--force',
  '--non-interactive',
  '--format', 'json'
)

if ($Target -eq 'production') {
  $deployArgs += '--prod'
}

Invoke-Vercel @deployArgs
