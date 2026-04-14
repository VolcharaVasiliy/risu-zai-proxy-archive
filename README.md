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
5. `scripts/launch-mistral-auth.ps1` and `scripts/get-mistral-creds.py` capture the Mistral browser session into `auth\mistral-creds.json`.
6. `scripts/redeploy-vercel.ps1 -SyncEnv` pushes the available credentials into Vercel and deploys the project.

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

## Notes

- The project is wired to the companion Chat2API desktop storage layout, so `scripts/get-provider-creds.py` can automatically reuse already logged-in sessions when they exist.
- Mistral uses a dedicated browser-profile extractor for `console.mistral.ai`, which feeds the Vercel env sync through `auth\mistral-creds.json`.
- `Pi Web Local` is intentionally local-only and does not need Vercel env vars.
- `UncloseAI` does not require credentials.
