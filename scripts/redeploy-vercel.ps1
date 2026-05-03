param(
  [ValidateSet('preview', 'production')]
  [string]$Target = 'production',
  [string]$Scope = 'spichekkorobok500-1532s-projects',
  [string]$CredsFile = '',
  [string]$ArceeCredsFile = '',
  [string]$QwenCredsFile = '',
  [string]$GeminiWebCredsFile = '',
  [string]$GrokCredsFile = '',
  [string]$MistralCredsFile = '',
  [string]$InceptionCredsFile = '',
  [string]$LongCatCredsFile = '',
  [string]$OpenAIWebCredsFile = '',
  [string]$PhindCredsFile = '',
  [string]$InceptionEdgeUrl = '',
  [string]$ProxyApiKey = '',
  [string]$AgentToolMode = '',
  [string]$AgentToolSchemaMaxChars = '',
  [switch]$SyncEnv
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$nodeRoot = 'F:\DevTools\Portable\NodeJS'
$nodeExe = Join-Path $nodeRoot 'node.exe'
$pythonExe = 'F:\DevTools\Python311\python.exe'
$vercelBin = Join-Path $projectRoot 'node_modules\.bin\vercel.cmd'
$vercelCliScript = Join-Path $projectRoot 'node_modules\vercel\dist\index.js'
$credsScript = Join-Path $projectRoot 'scripts\get-provider-creds.py'
$defaultArceeCredsFile = Join-Path $projectRoot 'auth\arcee-creds.json'
$defaultQwenCredsFile = Join-Path $projectRoot 'auth\qwen-creds.json'
$defaultGeminiWebCredsFile = Join-Path $projectRoot 'auth\gemini-web-creds.json'
$defaultGrokCredsFile = Join-Path $projectRoot 'auth\grok-creds.json'
$defaultMistralCredsFile = Join-Path $projectRoot 'auth\mistral-creds.json'
$defaultInceptionCredsFile = Join-Path $projectRoot 'auth\inception-creds.json'
$defaultLongCatCredsFile = Join-Path $projectRoot 'auth\longcat-creds.json'
$defaultOpenAIWebCredsFile = Join-Path $projectRoot 'auth\openai-web-creds.json'
$defaultPhindCredsFile = Join-Path $projectRoot 'auth\phind-creds.json'
$defaultCredentialsJson = Join-Path $projectRoot 'credentials.json'

if (-not (Test-Path -LiteralPath $vercelBin)) {
  throw "Vercel CLI not found at $vercelBin. Run npm install in $projectRoot first."
}

if (-not (Test-Path -LiteralPath $nodeExe)) {
  throw "Node not found at $nodeExe."
}

if (-not (Test-Path -LiteralPath $vercelCliScript)) {
  throw "Vercel CLI entrypoint not found at $vercelCliScript."
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

  Invoke-Vercel env add $Name $Target --value $Value --yes --force --non-interactive --scope $Scope
}

function Set-VercelEnvFromJson {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }

  $json = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
  foreach ($property in $json.PSObject.Properties) {
    $name = [string]$property.Name
    $value = [string]$property.Value
    if ([string]::IsNullOrWhiteSpace($value)) {
      continue
    }

    switch ($name) {
      'INFLECTION_TOKEN' {
        Set-VercelEnv -Name 'INFLECTION_API_KEY' -Value $value
        Set-VercelEnv -Name 'PI_INFLECTION_API_KEY' -Value $value
      }
      default {
        Set-VercelEnv -Name $name -Value $value
      }
    }
  }
}

if ($InceptionEdgeUrl) {
  Set-VercelEnv -Name 'INCEPTION_EDGE_URL' -Value $InceptionEdgeUrl
  Set-VercelEnv -Name 'INCEPTION_FORCE_EDGE' -Value 'true'
}

if ($ProxyApiKey) {
  Set-VercelEnv -Name 'PROXY_API_KEY' -Value $ProxyApiKey
}

if ($AgentToolMode) {
  Set-VercelEnv -Name 'AGENT_TOOL_MODE' -Value $AgentToolMode
}

if ($AgentToolSchemaMaxChars) {
  Set-VercelEnv -Name 'AGENT_TOOL_SCHEMA_MAX_CHARS' -Value $AgentToolSchemaMaxChars
}

if ($SyncEnv) {
  if ($Target -eq 'preview') {
    throw 'Preview env sync is not enabled in this script. Use project-level preview envs in Vercel or deploy preview without env sync.'
  }

  Set-VercelEnvFromJson -Path $defaultCredentialsJson

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
  Set-VercelEnv -Name 'INCEPTION_COOKIE' -Value $creds.inception_cookie
  Set-VercelEnv -Name 'INCEPTION_SESSION_TOKEN' -Value $creds.inception_session_token
  Set-VercelEnv -Name 'LONGCAT_COOKIE' -Value $creds.longcat_cookie
  Set-VercelEnv -Name 'MISTRAL_COOKIE' -Value $creds.mistral_cookie
  Set-VercelEnv -Name 'MISTRAL_CSRF_TOKEN' -Value $creds.mistral_csrf_token
  Set-VercelEnv -Name 'MIMO_SERVICE_TOKEN' -Value $creds.mimo_service_token
  Set-VercelEnv -Name 'MIMO_USER_ID' -Value $creds.mimo_user_id
  Set-VercelEnv -Name 'MIMO_PH_TOKEN' -Value $creds.mimo_ph_token
  Set-VercelEnv -Name 'QWEN_AI_COOKIE' -Value $creds.qwen_cookie
  Set-VercelEnv -Name 'QWEN_AI_TOKEN' -Value $creds.qwen_token
  Set-VercelEnv -Name 'PERPLEXITY_COOKIE' -Value $creds.perplexity_cookie
  Set-VercelEnv -Name 'PERPLEXITY_SESSION_TOKEN' -Value $creds.perplexity_session_token

  if (-not $ArceeCredsFile -and (Test-Path -LiteralPath $defaultArceeCredsFile)) {
    $ArceeCredsFile = $defaultArceeCredsFile
  }
  if (-not $QwenCredsFile -and (Test-Path -LiteralPath $defaultQwenCredsFile)) {
    $QwenCredsFile = $defaultQwenCredsFile
  }
  if (-not $GeminiWebCredsFile -and (Test-Path -LiteralPath $defaultGeminiWebCredsFile)) {
    $GeminiWebCredsFile = $defaultGeminiWebCredsFile
  }
  if (-not $GrokCredsFile -and (Test-Path -LiteralPath $defaultGrokCredsFile)) {
    $GrokCredsFile = $defaultGrokCredsFile
  }
  if (-not $MistralCredsFile -and (Test-Path -LiteralPath $defaultMistralCredsFile)) {
    $MistralCredsFile = $defaultMistralCredsFile
  }
  if (-not $InceptionCredsFile -and (Test-Path -LiteralPath $defaultInceptionCredsFile)) {
    $InceptionCredsFile = $defaultInceptionCredsFile
  }
  if (-not $LongCatCredsFile -and (Test-Path -LiteralPath $defaultLongCatCredsFile)) {
    $LongCatCredsFile = $defaultLongCatCredsFile
  }
  if (-not $OpenAIWebCredsFile -and (Test-Path -LiteralPath $defaultOpenAIWebCredsFile)) {
    $OpenAIWebCredsFile = $defaultOpenAIWebCredsFile
  }
  if (-not $PhindCredsFile -and (Test-Path -LiteralPath $defaultPhindCredsFile)) {
    $PhindCredsFile = $defaultPhindCredsFile
  }

  if ($ArceeCredsFile) {
    if (-not (Test-Path -LiteralPath $ArceeCredsFile)) {
      throw "Arcee credentials file not found: $ArceeCredsFile"
    }

    $arceeCreds = Get-Content -LiteralPath $ArceeCredsFile -Raw | ConvertFrom-Json
    Set-VercelEnv -Name 'ARCEE_ACCESS_TOKEN' -Value $arceeCreds.access_token
  }

  if ($QwenCredsFile) {
    if (-not (Test-Path -LiteralPath $QwenCredsFile)) {
      throw "Qwen credentials file not found: $QwenCredsFile"
    }

    $qwenCreds = Get-Content -LiteralPath $QwenCredsFile -Raw | ConvertFrom-Json
    Set-VercelEnv -Name 'QWEN_AI_COOKIE' -Value $qwenCreds.qwen_ai_cookie
    Set-VercelEnv -Name 'QWEN_AI_TOKEN' -Value $qwenCreds.qwen_ai_token
    Set-VercelEnv -Name 'QWEN_AI_BX_UA' -Value $qwenCreds.qwen_ai_bx_ua
    Set-VercelEnv -Name 'QWEN_AI_BX_UA_CREATE' -Value $qwenCreds.qwen_ai_bx_ua_create
    Set-VercelEnv -Name 'QWEN_AI_BX_UA_CHAT' -Value $qwenCreds.qwen_ai_bx_ua_chat
    Set-VercelEnv -Name 'QWEN_AI_BX_UMIDTOKEN' -Value $qwenCreds.qwen_ai_bx_umidtoken
    Set-VercelEnv -Name 'QWEN_AI_BX_V' -Value $qwenCreds.qwen_ai_bx_v
    Set-VercelEnv -Name 'QWEN_AI_TIMEZONE' -Value $qwenCreds.qwen_ai_timezone
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

  if ($InceptionCredsFile) {
    if (-not (Test-Path -LiteralPath $InceptionCredsFile)) {
      throw "Inception credentials file not found: $InceptionCredsFile"
    }

    $inceptionCreds = Get-Content -LiteralPath $InceptionCredsFile -Raw | ConvertFrom-Json
    Set-VercelEnv -Name 'INCEPTION_COOKIE' -Value $inceptionCreds.inception_cookie
    Set-VercelEnv -Name 'INCEPTION_SESSION_TOKEN' -Value $inceptionCreds.inception_session_token
  }

  if ($LongCatCredsFile) {
    if (-not (Test-Path -LiteralPath $LongCatCredsFile)) {
      throw "LongCat credentials file not found: $LongCatCredsFile"
    }

    $longcatCreds = Get-Content -LiteralPath $LongCatCredsFile -Raw | ConvertFrom-Json
    Set-VercelEnv -Name 'LONGCAT_COOKIE' -Value $longcatCreds.longcat_cookie
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
  'deploy',
  $projectRoot,
  '-y',
  '--force',
  '--non-interactive',
  '--scope', $Scope,
  '--format', 'json'
)

if ($Target -eq 'production') {
  $deployArgs += '--prod'
}

Invoke-Vercel @deployArgs
