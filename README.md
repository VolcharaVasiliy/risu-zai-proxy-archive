# risu-zai-proxy

`risu-zai-proxy` is an OpenAI-compatible proxy for `RisuAI` that routes requests to a set of web and API-backed providers.

[![Deploy to Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/VolcharaVasiliy/risu-zai-proxy-archive)

## What It Serves

- `GET /v1/models`
- `POST /v1/chat/completions`
- `GET /health`

## Docs

- [Provider reference](docs/providers.md)
- [Deployment and env guide](docs/deployment.md)
- [Repeat deploy notes](REDEPLOY.md)

## Provider Overview

Stable production provider:

- `Z.ai`
- env: `ZAI_TOKEN`

Browser/session providers:

- `Arcee`
- `Grok`
- `OpenAI Web`
- `Gemini Web`
- `Qwen International`
- `Inception`
- `LongCat`
- `Mistral`
- `Perplexity`
- `Phind`
- `Mimo`
- `Kimi`
- `DeepSeek`

API providers:

- `Inflection` / `Pi API`
- `Pi Web Local`
- `UncloseAI`

The full model list, required env vars, manual acquisition paths, and automatic extraction scripts are documented in [docs/providers.md](docs/providers.md).

## How It Works

1. `api/index.py` exposes an OpenAI-compatible API surface.
2. `py/provider_registry.py` resolves a model id to the correct provider.
3. Each provider adapter handles its own auth shape, upstream request format, and streaming behavior.
4. `scripts/get-provider-creds.py` can auto-collect credentials from the local Chat2API desktop storage at `%APPDATA%\chat2api\Partitions\oauth-*`.
5. `scripts/get-arcee-creds.py` extracts the Arcee bearer token from a Chromium/Yandex profile into `auth\arcee-creds.json`.
6. `scripts/get-qwen-creds.py` extracts the Qwen cookie/header bundle into `auth\qwen-creds.json`.
7. `scripts/launch-inception-auth.ps1` and `scripts/get-inception-creds.py` capture the Inception browser session into `auth\inception-creds.json`.
8. `scripts/launch-longcat-auth.ps1` and `scripts/get-longcat-creds.py` capture the LongCat browser session into `auth\longcat-creds.json`.
9. `scripts/launch-mistral-auth.ps1` and `scripts/get-mistral-creds.py` capture the Mistral browser session into `auth\mistral-creds.json`.
10. `scripts/redeploy-vercel.ps1 -SyncEnv` pushes the available credentials into Vercel and deploys the project.

## Local Run

```powershell
F:\DevTools\Portable\NodeJS\node.exe F:\Projects\risu-zai-proxy\local-server.js
```

Python server path:

```powershell
F:\DevTools\Python311\python.exe F:\Projects\risu-zai-proxy\py\server.py
```

## Vercel

The one-click deploy button above creates a Vercel project from this repository.

The environment map and manual/automatic credential sources are documented in [docs/deployment.md](docs/deployment.md).

## Cloudflare Edge

If `chat.inceptionlabs.ai` rejects plain server-side requests, the Python adapter now prefers the direct `curl_cffi` browser-impersonation path when it is available. The edge worker in `cloudflare/worker.mjs` stays as a fallback path for Inception only.

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/VolcharaVasiliy/risu-zai-proxy-archive)

This worker:

- answers `/health` on Cloudflare
- handles only `Inception` models from Cloudflare egress so the upstream sees Cloudflare IPs instead of Vercel
- always receives Inception chat requests with `stream` disabled
- accepts the `INCEPTION_SESSION_TOKEN` / `INCEPTION_COOKIE` values forwarded by Vercel
- can also run as a standalone Inception endpoint when `INCEPTION_SESSION_TOKEN` and `INCEPTION_COOKIE` are configured as Cloudflare Worker secrets
- does not host the rest of the model set

For Python/Vercel runs:

- `py/inception_proxy.py` refreshes the Inception session token through `/api/session`
- when `curl_cffi` is available, the adapter prefers the direct browser-impersonation transport over `INCEPTION_EDGE_URL`
- when running on Vercel and `INCEPTION_EDGE_URL` is set, the adapter prefers the Cloudflare edge path for Inception
- `INCEPTION_FORCE_EDGE=1` can force the Cloudflare edge path back on if you need to debug the worker specifically

Local commands:

```powershell
npm run cloudflare:login
npm run cloudflare:dev
npm run cloudflare:deploy
```

Cloudflare env vars for the worker:

- none required if Vercel forwards the Inception credentials in headers
- `INCEPTION_BASE_URL` optional
- `INCEPTION_REASONING_EFFORT` optional
- `INCEPTION_WEB_SEARCH` optional
- `INCEPTION_USER_AGENT` optional

Vercel env var for routing:

- `INCEPTION_EDGE_URL` - Cloudflare worker URL used only for Inception requests

## Cloudflare Tunnel For Inception

When the hosted Cloudflare worker also gets blocked by the upstream checkpoint, the repo includes a local-only fallback for `Inception`:

- `py/inception_tunnel_server.py` runs an `Inception`-only OpenAI-compatible endpoint on `127.0.0.1:3001`
- `scripts/refresh-inception-creds.ps1` refreshes `auth\inception-creds.json` from either the dedicated browser profile or the local cookie export
- `scripts/start-inception-tunnel.ps1` starts that local endpoint, opens a Cloudflare quick tunnel, updates `INCEPTION_EDGE_URL` in Vercel, and redeploys production
- `scripts/stop-inception-tunnel.ps1` stops the local endpoint and the tunnel
- `scripts/install-inception-tunnel-task.ps1` registers a logon task so the tunnel can come back automatically after sign-in
- `scripts/setup-inception-named-tunnel.ps1` prepares the named-tunnel path; if Cloudflare `cert.pem` is missing it falls back to the quick tunnel and tells you what is still missing

Local command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy-archive\scripts\start-inception-tunnel.ps1 -UpdateVercel -Redeploy
```

Credential refresh + restart command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy-archive\scripts\refresh-inception-creds.ps1 -RestartTunnel -UpdateVercel -Redeploy
```

This path is for `Inception` only. The rest of the providers still stay on Vercel directly.

## Notes

- The project is wired to the companion Chat2API desktop storage layout, so `scripts/get-provider-creds.py` can automatically reuse already logged-in sessions when they exist.
- Arcee uses a bearer token stored in the Chromium/Yandex cookie jar for `api.arcee.ai`; `scripts/get-arcee-creds.py` extracts it into `auth\arcee-creds.json` for local runs and Vercel sync.
- Qwen uses the browser cookie jar plus live `bx-*` request headers from `chat.qwen.ai`; `scripts/get-qwen-creds.py` extracts them into `auth\qwen-creds.json` for local runs and Vercel sync.
- Mistral uses a dedicated browser-profile extractor for `console.mistral.ai`, which feeds the Vercel env sync through `auth\mistral-creds.json`.
- Inception uses a dedicated browser-profile extractor for `chat.inceptionlabs.ai`; each request gets a fresh backend chat id, so chats are not forced into one shared session.
- LongCat uses a dedicated browser-profile extractor for `longcat.chat`; each request gets a fresh `session-create` conversation, so chats are not forced into one shared thread.
- LongCat exposes separate slugs for convenience: `LongCat-Flash-Chat` for regular answers and `LongCat-Flash-Thinking` / `LongCat-Flash-Thinking-2601` for reasoning.
- `Pi Web Local` is intentionally local-only and does not need Vercel env vars.
- `UncloseAI` does not require credentials.
