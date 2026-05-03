# Deployment Guide

## One-Click Deploy

[![Deploy to Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/VolcharaVasiliy/risu-zai-proxy-archive)

Use this button to create a Vercel project from the repository.

## API Surface

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `GET /v1/responses/{response_id}`
- `DELETE /v1/responses/{response_id}`
- `POST /v1/responses/chat/completions`
- `GET /health`

`/v1/chat/completions` is the regular OpenAI-compatible chat path.
`/v1/responses` returns an OpenAI Responses-style object with `output`, `function_call`, and `function_call_output` support.
`GET /v1/responses/{response_id}` and `DELETE /v1/responses/{response_id}` work for responses still present in the proxy's in-memory short-lived response state.
`/v1/responses/chat/completions` is a compatibility route for clients that want response/session state but still expect a chat-completion-shaped response.

Native function-tool passthrough is used for `Inflection / Pi API` and `UncloseAI`.
For the chat-only providers, `AGENT_TOOL_MODE=auto` enables the prompt tool shim: the proxy prompts the model to request client-side tools as strict JSON, removes unsupported upstream `tools` fields, and converts successful JSON tool requests back into OpenAI `tool_calls`.

## Environment Naming

Use the exact env names expected by the adapters:

| Provider / feature | Vercel env names |
| --- | --- |
| Client proxy auth | optional `PROXY_API_KEY` or `RISU_PROXY_API_KEY` |
| Agent prompt tool shim | optional `AGENT_TOOL_MODE`, `AGENT_TOOL_SCHEMA_MAX_CHARS` |
| Z.ai | `ZAI_TOKEN` |
| DeepSeek | `DEEPSEEK_TOKEN` |
| Arcee | `ARCEE_ACCESS_TOKEN` |
| Gemini Web | `GEMINI_WEB_SECURE_1PSID`, `GEMINI_WEB_SECURE_1PSIDTS`, `GEMINI_WEB_COOKIE`, `GEMINI_WEB_MODELS` |
| Grok | `GROK_COOKIE`, `GROK_SSO`, `GROK_CF_CLEARANCE` |
| OpenAI Web | `OPENAI_WEB_ACCESS_TOKEN`, `OPENAI_WEB_COOKIE`, `OPENAI_WEB_DEVICE_ID`, `OPENAI_WEB_ACCOUNT_ID`, `OPENAI_WEB_MODELS` |
| Qwen International | `QWEN_AI_COOKIE`, `QWEN_AI_BX_UMIDTOKEN`, optional `QWEN_AI_TOKEN`, `QWEN_AI_BX_UA`, `QWEN_AI_BX_UA_CREATE`, `QWEN_AI_BX_UA_CHAT`, `QWEN_AI_BX_V`, `QWEN_AI_TIMEZONE` |
| Inception | `INCEPTION_SESSION_TOKEN`, `INCEPTION_COOKIE` |
| LongCat | `LONGCAT_COOKIE` |
| Mistral | `MISTRAL_COOKIE`, optional `MISTRAL_CSRF_TOKEN` |
| Perplexity | `PERPLEXITY_COOKIE`, `PERPLEXITY_SESSION_TOKEN` |
| Phind | `PHIND_COOKIE`, `PHIND_NONCE` |
| Mimo | `MIMO_SERVICE_TOKEN`, `MIMO_USER_ID`, `MIMO_PH_TOKEN`, `MIMO_COOKIE` |
| Kimi | `KIMI_TOKEN` |
| Inflection / Pi API | `INFLECTION_API_KEY`, `PI_INFLECTION_API_KEY`, optional `INFLECTION_API_BASE` |
| Inception Cloudflare edge | `INCEPTION_EDGE_URL` |

Agent/tool compatibility variables:

- `AGENT_TOOL_MODE=auto` is the default. Native-tool providers receive tool schemas directly; chat-only providers use the prompt shim.
- `AGENT_TOOL_MODE=off` disables the prompt shim and makes chat-only providers fail fast when `tools` are supplied.
- `AGENT_TOOL_MODE=force` uses the prompt shim for every provider, including native-tool providers.
- `AGENT_TOOL_SCHEMA_MAX_CHARS` caps the injected tool-schema prompt, defaulting to a safe large value.
- `PROXY_API_KEY` / `RISU_PROXY_API_KEY` is optional client authentication for apps like Zed. When it is set, send it as the normal OpenAI-compatible bearer API key; provider credentials should still live in the proxy env or provider-specific headers.

Local-only variables that should stay off Vercel:

- `GEMINI_WEB_PROXY`
- `HTTPS_PROXY`
- `HTTP_PROXY`
- `MIMO_RESOLVE_IPS`
- `MIMO_SKIP_TLS_VERIFY`
- `PI_LOCAL_*`

When `INCEPTION_EDGE_URL` is set, Vercel can forward only Inception chat requests to the Cloudflare worker. For Python-based runs, `py/inception_proxy.py` now prefers the direct `curl_cffi` browser-impersonation path when that transport is available, and falls back to `INCEPTION_EDGE_URL` only when needed or when `INCEPTION_FORCE_EDGE=1` is set.
For Inception, the proxy refreshes the session token through `/api/session` and strips `stream` before forwarding the request so the upstream always sees a non-streaming payload.

If the hosted Cloudflare worker is also blocked by the upstream checkpoint, use the local tunnel fallback for this one provider:

- `py/inception_tunnel_server.py`
- `scripts/refresh-inception-creds.ps1`
- `scripts/start-inception-tunnel.ps1 -UpdateVercel -Redeploy`
- `scripts/stop-inception-tunnel.ps1`
- `scripts/install-inception-tunnel-task.ps1`
- `scripts/setup-inception-named-tunnel.ps1`

That flow keeps Vercel as the single public API URL, but routes only `Inception` traffic through a Cloudflare quick tunnel into the local direct Python transport.

Named tunnel notes:

- `scripts/setup-inception-named-tunnel.ps1` can prepare the named-tunnel path locally.
- To fully finish a named tunnel, this machine still needs Cloudflare Tunnel auth (`cloudflared tunnel login`, which creates `cert.pem`) and a concrete hostname on a zone you control.
- Until those exist, the script intentionally falls back to the quick tunnel so the provider keeps working.

## Manual Credential Sources

| Provider | Where to get it manually |
| --- | --- |
| Z.ai | Logged-in `chat.z.ai` session, then export the JWT or copy it from local auth storage. |
| DeepSeek | Logged-in `chat.deepseek.com` session and the stored `userToken`. |
| Gemini Web | Google login cookies from `gemini.google.com`, usually `__Secure-1PSID` and optional `__Secure-1PSIDTS`. |
| Grok | Logged-in `grok.com` cookies. |
| OpenAI Web | `chatgpt.com` session `accessToken`, plus optional cookie header/device id/account id. |
| Qwen International | `chat.qwen.ai` cookies plus `bx-ua` / `bx-umidtoken` from the live web requests, and optional token cookie. |
| Inception | `chat.inceptionlabs.ai` cookies and session token. |
| LongCat | `longcat.chat` cookie export. |
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

`Inception` uses its own browser-profile extractor because it is not part of the Chat2API desktop layout:

- `scripts/launch-inception-auth.ps1`
- `scripts/get-inception-creds.py`

Those scripts store `auth\inception-creds.json`, which `scripts/redeploy-vercel.ps1 -SyncEnv` reads and pushes into `INCEPTION_COOKIE` and `INCEPTION_SESSION_TOKEN`.

`LongCat` uses its own browser-profile extractor because it is not part of the Chat2API desktop layout:

- `scripts/launch-longcat-auth.ps1`
- `scripts/get-longcat-creds.py`

Those scripts store `auth\longcat-creds.json`, which `scripts/redeploy-vercel.ps1 -SyncEnv` reads and pushes into `LONGCAT_COOKIE`.

`Arcee` uses a bearer token stored in the Chromium/Yandex cookie jar on `api.arcee.ai`:

- `scripts/get-arcee-creds.py`

That script stores `auth\arcee-creds.json`, which `scripts/redeploy-vercel.ps1 -SyncEnv` now reads and pushes into `ARCEE_ACCESS_TOKEN`.

`Qwen International` can use a dedicated extractor when the generic Chat2API partition path does not expose the live browser headers:

- `scripts/get-qwen-creds.py`

That script stores `auth\qwen-creds.json`, which `scripts/redeploy-vercel.ps1 -SyncEnv` now reads and pushes into `QWEN_AI_COOKIE`, `QWEN_AI_BX_*`, optional `QWEN_AI_TOKEN`, and `QWEN_AI_TIMEZONE`.

`Mistral` uses its own browser-profile extractor because it is not part of the Chat2API desktop layout:

- `scripts/launch-mistral-auth.ps1`
- `scripts/get-mistral-creds.py`

Those scripts store `auth\mistral-creds.json`, which `scripts/redeploy-vercel.ps1 -SyncEnv` reads and pushes into `MISTRAL_COOKIE` and `MISTRAL_CSRF_TOKEN`.

Provider-specific helpers:

- `scripts/get-zai-token.ps1`
- `scripts/launch-grok-auth.ps1`
- `scripts/get-grok-creds.py`
- `scripts/launch-openai-auth.ps1`
- `scripts/get-openai-web-creds.py`
- `scripts/launch-gemini-auth.ps1`
- `scripts/get-gemini-web-creds.py`
- `scripts/launch-longcat-auth.ps1`
- `scripts/get-longcat-creds.py`
- `scripts/launch-mistral-auth.ps1`
- `scripts/get-mistral-creds.py`
- `scripts/launch-phind-auth.ps1`
- `scripts/get-phind-creds.ps1`
- `scripts/launch-pi-auth.ps1`
- `scripts/pi-browser-bridge.mjs`

`scripts/get-provider-creds.py` is the main aggregation point. The repo is already connected to the Chat2API storage layout, so the script can pull data automatically without manual copying when those sessions are present.

## Local Python Dependencies

For local Python runs, install the pinned dependencies into the ignored `pydeps` directory:

```powershell
npm run deps:py
```

Vercel installs from `requirements.txt`; `pydeps` is only for local portable runs.

## Vercel Sync

Deploy and sync env from local credentials:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\downloads\risu-zai-proxy-archive\scripts\redeploy-vercel.ps1 -SyncEnv
```

Optional agent/client-auth envs can be pushed during deploy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\downloads\risu-zai-proxy-archive\scripts\redeploy-vercel.ps1 -SyncEnv -ProxyApiKey "your-client-key" -AgentToolMode auto
```

The script:

- reads `scripts/get-provider-creds.py`
- imports optional JSON files from `auth/`
- loads `credentials.json` when present so the exact file can seed Vercel auth
- writes Vercel env vars with the exact provider names above
- optionally writes `PROXY_API_KEY`, `AGENT_TOOL_MODE`, and `AGENT_TOOL_SCHEMA_MAX_CHARS` when those parameters are supplied
- performs the production deploy

## Repository Files Used By Deployment

- `vercel.json` - route rewrites for `/health`, `/v1/models`, `/v1/chat/completions`, `/v1/responses`, `/v1/responses/{response_id}`, and `/v1/responses/chat/completions`
- `api/index.py` - Vercel function entrypoint
- `py/credentials_bootstrap.py` - loads `credentials.json` into process env before provider imports
- `py/agent_tools.py` - OpenAI-compatible prompt tool shim, tool-call extraction, and tool-call normalization
- `py/responses_api.py` - responses-route translation, session state, Responses-format objects, and agent compatibility rules
- `scripts/redeploy-vercel.ps1` - env sync and deployment automation
- `scripts/refresh-inception-creds.ps1` - refresh the local ignored Inception credentials file and optionally restart/redeploy the tunnel path
- `scripts/setup-inception-named-tunnel.ps1` - prepare the named-tunnel path and fall back to quick tunnel when Cloudflare tunnel auth is still missing
- `scripts/start-inception-tunnel.ps1` - start the local Inception-only endpoint, quick tunnel, and Vercel sync/redeploy
- `scripts/get-provider-creds.py` - Chat2API-based auto extraction

## Notes

- `GEMINI_WEB_MODELS` and `OPENAI_WEB_MODELS` should be JSON arrays when set manually.
- Optional env vars should be left blank when you do not have the corresponding credential.
- `Pi Web Local` should stay local; it is not a Vercel provider.
