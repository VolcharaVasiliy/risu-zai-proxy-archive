# Deployment Guide

## One-Click Deploy

[![Deploy to Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/VolcharaVasiliy/risu-zai-proxy-archive)

Use this button to create a Vercel project from the repository.

## Environment Naming

Use the exact env names expected by the adapters:

| Provider | Vercel env names |
| --- | --- |
| Z.ai | `ZAI_TOKEN` |
| DeepSeek | `DEEPSEEK_TOKEN` |
| Gemini Web | `GEMINI_WEB_SECURE_1PSID`, `GEMINI_WEB_SECURE_1PSIDTS`, `GEMINI_WEB_COOKIE`, `GEMINI_WEB_MODELS` |
| Grok | `GROK_COOKIE`, `GROK_SSO`, `GROK_CF_CLEARANCE` |
| OpenAI Web | `OPENAI_WEB_ACCESS_TOKEN`, `OPENAI_WEB_COOKIE`, `OPENAI_WEB_DEVICE_ID`, `OPENAI_WEB_ACCOUNT_ID`, `OPENAI_WEB_MODELS` |
| Qwen International | `QWEN_AI_COOKIE`, `QWEN_AI_TOKEN` |
| Mistral | `MISTRAL_COOKIE`, optional `MISTRAL_CSRF_TOKEN` |
| Perplexity | `PERPLEXITY_COOKIE`, `PERPLEXITY_SESSION_TOKEN` |
| Phind | `PHIND_COOKIE`, `PHIND_NONCE` |
| Mimo | `MIMO_SERVICE_TOKEN`, `MIMO_USER_ID`, `MIMO_PH_TOKEN`, `MIMO_COOKIE` |
| Kimi | `KIMI_TOKEN` |
| Inflection / Pi API | `INFLECTION_API_KEY`, `PI_INFLECTION_API_KEY`, optional `INFLECTION_API_BASE` |

Local-only variables that should stay off Vercel:

- `GEMINI_WEB_PROXY`
- `HTTPS_PROXY`
- `HTTP_PROXY`
- `MIMO_RESOLVE_IPS`
- `MIMO_SKIP_TLS_VERIFY`
- `PI_LOCAL_*`

## Manual Credential Sources

| Provider | Where to get it manually |
| --- | --- |
| Z.ai | Logged-in `chat.z.ai` session, then export the JWT or copy it from local auth storage. |
| DeepSeek | Logged-in `chat.deepseek.com` session and the stored `userToken`. |
| Gemini Web | Google login cookies from `gemini.google.com`, usually `__Secure-1PSID` and optional `__Secure-1PSIDTS`. |
| Grok | Logged-in `grok.com` cookies. |
| OpenAI Web | `chatgpt.com` session `accessToken`, plus optional cookie header/device id/account id. |
| Qwen International | `chat.qwen.ai` cookies and token. |
| Mistral | `console.mistral.ai` cookies and optional CSRF token. |
| Perplexity | `perplexity.ai` cookies and session token. |
| Phind | `phindai.org` cookies and nonce. |
| Mimo | `xiaomimimo.com` or `aistudio.xiaomimimo.com` cookies and tokens. |
| Kimi | `www.kimi.com` access token. |
| Inflection / Pi API | Create a key at `https://developers.inflection.ai/keys`. |
| Pi Web Local | Local browser profile only, no Vercel env. |
| UncloseAI | No credentials needed. |

## Automatic Credential Sources

Preferred automatic path:

- `scripts/get-provider-creds.py`

This script reads the local Chat2API desktop storage at `%APPDATA%\chat2api\Partitions\oauth-*` and can automatically extract many provider tokens and cookies when the desktop sessions already exist.

`Mistral` currently uses the manually exported `console.mistral.ai` cookie header plus the CSRF token from the same session; there is no bundled auto-extractor yet.

Provider-specific helpers:

- `scripts/get-zai-token.ps1`
- `scripts/launch-grok-auth.ps1`
- `scripts/get-grok-creds.py`
- `scripts/launch-openai-auth.ps1`
- `scripts/get-openai-web-creds.py`
- `scripts/launch-gemini-auth.ps1`
- `scripts/get-gemini-web-creds.py`
- `scripts/launch-phind-auth.ps1`
- `scripts/get-phind-creds.ps1`
- `scripts/launch-pi-auth.ps1`
- `scripts/pi-browser-bridge.mjs`

`scripts/get-provider-creds.py` is the main aggregation point. The repo is already connected to the Chat2API storage layout, so the script can pull data automatically without manual copying when those sessions are present.

## Vercel Sync

Deploy and sync env from local credentials:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy\scripts\redeploy-vercel.ps1 -SyncEnv
```

The script:

- reads `scripts/get-provider-creds.py`
- imports optional JSON files from `auth/`
- writes Vercel env vars with the exact provider names above
- performs the production deploy

## Repository Files Used By Deployment

- `vercel.json` - route rewrites for `/health`, `/v1/models`, and `/v1/chat/completions`
- `api/index.py` - Vercel function entrypoint
- `scripts/redeploy-vercel.ps1` - env sync and deployment automation
- `scripts/get-provider-creds.py` - Chat2API-based auto extraction

## Notes

- `GEMINI_WEB_MODELS` and `OPENAI_WEB_MODELS` should be JSON arrays when set manually.
- Optional env vars should be left blank when you do not have the corresponding credential.
- `Pi Web Local` should stay local; it is not a Vercel provider.
