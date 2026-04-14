# Provider Reference

This project exposes a uniform OpenAI-compatible API, but each upstream provider has its own auth source, model set, and operational constraints.

## Summary Table

| Provider | Model ids | Required env | Optional env | Manual source | Automatic source | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Z.ai | `GLM-5-Turbo`, `glm-5`, `glm-5.1`, `glm-4.7`, `glm-4.6v`, `glm-4.6`, `glm-4.5v`, `glm-4.5-air` | `ZAI_TOKEN` | `x-zai-token` header | Logged-in `chat.z.ai` session | `scripts/get-zai-token.ps1`, `scripts/get-provider-creds.py` | Stable production provider. |
| DeepSeek | `deepseek-chat`, `deepseek-reasoner`, `deepseek-search` | `DEEPSEEK_TOKEN` | `x-deepseek-token` header | Logged-in `chat.deepseek.com` session | `scripts/get-provider-creds.py` | Browser-session style token provider. |
| Gemini Web | `gemini-3-flash`, `gemini-3-pro`, `gemini-3-flash-thinking`, plus `gemini-web*` aliases | `GEMINI_WEB_SECURE_1PSID` | `GEMINI_WEB_SECURE_1PSIDTS`, `GEMINI_WEB_COOKIE` | Logged-in `gemini.google.com` / Google cookie session | `scripts/launch-gemini-auth.ps1`, `scripts/get-gemini-web-creds.py`, `scripts/get-provider-creds.py` | Account/region gated. Can auto-use WinINET proxy locally. |
| Grok | `grok-3`, `grok-4`, `grok-4-thinking`, `grok-4.1-fast` | `GROK_COOKIE` | `GROK_SSO`, `GROK_CF_CLEARANCE` | Logged-in `grok.com` browser session | `scripts/launch-grok-auth.ps1`, `scripts/get-grok-creds.py` | Cookie-based browser provider. |
| OpenAI Web | `chatgpt-auto` and discovered ChatGPT web slugs | `OPENAI_WEB_ACCESS_TOKEN` | `OPENAI_WEB_COOKIE`, `OPENAI_WEB_DEVICE_ID`, `OPENAI_WEB_ACCOUNT_ID`, `OPENAI_WEB_MODELS` | Logged-in `chatgpt.com` session | `scripts/launch-openai-auth.ps1`, `scripts/get-openai-web-creds.py` | Uses the web auth/session flow, not the public API. |
| Qwen International | `Qwen3-Max`, `Qwen3.5-Plus`, `Qwen3-Coder`, `Qwen3-VL-235B-A22B` | `QWEN_AI_COOKIE` | `QWEN_AI_TOKEN` | Logged-in `chat.qwen.ai` session | `scripts/get-provider-creds.py` | Cookie + token based. |
| Mistral | `mistral-medium-latest` | `MISTRAL_COOKIE` | `MISTRAL_CSRF_TOKEN` | Logged-in `console.mistral.ai` session | Manual only | Uses the console playground conversation endpoint. |
| Perplexity | `Turbo`, `PPLX-Pro`, `GPT-5`, `Claude-Sonnet-4` | `PERPLEXITY_COOKIE` | `PERPLEXITY_SESSION_TOKEN` | Logged-in `perplexity.ai` session | `scripts/get-provider-creds.py` | Session cookie based. |
| Phind | `phind-search`, `phind-chat` | `PHIND_COOKIE` | `PHIND_NONCE` | Logged-in `phindai.org` session | `scripts/launch-phind-auth.ps1`, `scripts/get-phind-creds.ps1`, `scripts/get-provider-creds.py` | WordPress nonce is auto-fetched when missing. |
| Mimo | `mimo-v2-pro`, `mimo-v2-flash-studio`, `mimo-v2-omni` | `MIMO_SERVICE_TOKEN`, `MIMO_USER_ID`, `MIMO_PH_TOKEN` | `MIMO_COOKIE`, `MIMO_RESOLVE_IPS`, `MIMO_SKIP_TLS_VERIFY` | Logged-in `xiaomimimo.com` / `aistudio.xiaomimimo.com` session | `scripts/get-provider-creds.py`, `scripts/redeploy-vercel.ps1 -SyncEnv` | Auto-resolves public IPs if local DNS points to loopback. |
| Kimi | `kimi`, `kimi-thinking`, `kimi-search` | `KIMI_TOKEN` | none | Logged-in `www.kimi.com` session | `scripts/get-provider-creds.py` | Desktop storage token provider. |
| Inflection / Pi API | `pi-api`, `pi-3.1`, aliases `inflection-pi`, `inflection_3_pi`, `pi-3-1` | `INFLECTION_API_KEY` or `PI_INFLECTION_API_KEY` | `INFLECTION_API_BASE` | `https://developers.inflection.ai/keys` | Manual only | Official API path, works on Vercel. |
| Pi Web Local | `pi-web-local` | none | `PI_LOCAL_*` | Local `pi.ai` browser profile | `scripts/launch-pi-auth.ps1`, `scripts/pi-browser-bridge.mjs` | Local-only browser automation path. |
| UncloseAI | `uncloseai-hermes`, `uncloseai-qwen-vl`, `uncloseai-gpt-oss`, `uncloseai-r1-distill` | none | none | Public endpoint | none | Intentionally credential-free. |

## Stable Provider

`Z.ai` is the stable provider and the one that should be used as the default production path.

## Browser-Session Providers

These providers depend on logged-in browser sessions or cookies:

- `Grok`
- `OpenAI Web`
- `Gemini Web`
- `Qwen International`
- `Mistral`
- `Perplexity`
- `Phind`
- `Mimo`
- `Kimi`
- `DeepSeek`

For these providers, the manual source is usually the logged-in website session, cookie export, or local browser profile storage. The exact extraction path depends on the provider.

## API Providers

These providers use official or public API keys rather than browser cookies:

- `Inflection / Pi API`
- `Pi Web Local`
- `UncloseAI`

`Pi Web Local` is local-only and should not be pushed to Vercel.

## Chat2API Integration

The project is already wired to the local Chat2API desktop storage layout:

- `%APPDATA%\chat2api\Partitions\oauth-*`

`scripts/get-provider-creds.py` reads those partitions automatically and can recover:

- `ZAI_TOKEN`
- `DEEPSEEK_TOKEN`
- `KIMI_TOKEN` / `refresh_token`
- `GEMINI_WEB_COOKIE` / `GEMINI_WEB_SECURE_1PSID` / `GEMINI_WEB_SECURE_1PSIDTS`
- `MIMO_COOKIE` / `MIMO_SERVICE_TOKEN` / `MIMO_USER_ID` / `MIMO_PH_TOKEN`
- `QWEN_AI_COOKIE` / `QWEN_AI_TOKEN`
- `PERPLEXITY_COOKIE` / `PERPLEXITY_SESSION_TOKEN`

That is the preferred automatic path when the local Chat2API session already contains a logged-in provider.

## Manual Sources

Manual sources by provider:

- `Z.ai` - logged-in `chat.z.ai` session or JWT export
- `DeepSeek` - logged-in `chat.deepseek.com` session
- `Gemini Web` - `gemini.google.com` login cookies
- `Grok` - `grok.com` cookies
- `OpenAI Web` - `chatgpt.com` session token and cookies
- `Qwen International` - `chat.qwen.ai` cookies
- `Mistral` - `console.mistral.ai` cookies and optional CSRF token
- `Perplexity` - `perplexity.ai` cookies
- `Phind` - `phindai.org` cookies plus nonce
- `Mimo` - `xiaomimimo.com` / `aistudio.xiaomimimo.com` cookies and tokens
- `Kimi` - `www.kimi.com` access token
- `Inflection / Pi API` - developer key from Inflection
- `Pi Web Local` - local browser profile only
- `UncloseAI` - no credentials
