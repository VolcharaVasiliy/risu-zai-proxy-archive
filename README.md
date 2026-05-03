# risu-zai-proxy

`risu-zai-proxy` is an OpenAI-compatible proxy for `RisuAI` that routes requests to a set of web and API-backed providers.

[![Deploy to Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/VolcharaVasiliy/risu-zai-proxy-archive)

## What It Serves

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `GET /v1/responses/{response_id}`
- `DELETE /v1/responses/{response_id}`
- `POST /v1/responses/chat/completions`
- `GET /health`

## Docs

- [Provider reference](docs/providers.md)
- [Deployment and env guide](docs/deployment.md)
- [Repeat deploy notes](REDEPLOY.md)

## Agent and Tool Routes

- `/v1/chat/completions` remains the regular OpenAI-compatible chat path.
- `/v1/responses` returns an OpenAI Responses-style object with `output`, `function_call`, and `function_call_output` support.
- `GET /v1/responses/{response_id}` and `DELETE /v1/responses/{response_id}` work for responses still present in the proxy's in-memory short-lived response state.
- `/v1/responses/chat/completions` is a compatibility route for clients that want response/session semantics but still expect a chat-completion-shaped response.
- Native OpenAI-style tool passthrough is used for `Inflection / Pi API` and `UncloseAI`.
- Other chat-only providers can still be used by agent clients through the prompt tool shim. The shim injects a strict client-side tool protocol into the prompt, removes unsupported upstream tool fields, and converts the model's JSON tool request back into OpenAI `tool_calls`.
- The prompt shim is enabled by default with `AGENT_TOOL_MODE=auto`. Set `AGENT_TOOL_MODE=off` to fail fast for providers without native tools, or `AGENT_TOOL_MODE=force` to use the shim even for native-tool providers.
- `PROXY_API_KEY` / `RISU_PROXY_API_KEY` is optional client authentication for OpenAI-compatible apps. When it is set, clients send it as their normal bearer API key while provider credentials stay in server env vars or provider-specific headers.

## Provider Overview

Stable production provider:

- `Z.ai`
- env: `ZAI_TOKEN`

Browser/session providers:

- `Arcee`
- `Grok`
- `OpenAI Web` (alpha)
- `Gemini Web`
- `Google AI Studio Web` (experimental private RPC)
- `Qwen International`
- `Inception`
- `LongCat`
- `Mistral` (Playground)
- `Perplexity`
- `Phind` (beta)
- `Mimo`
- `Kimi`
- `DeepSeek`

API providers:

- `Google AI Studio` / `Gemini API`
- `Inflection` / `Pi API`
- `Pi Web Local`
- `UncloseAI`

The full model list, required env vars, manual acquisition paths, and automatic extraction scripts are documented in [docs/providers.md](docs/providers.md).

## How It Works

1. `api/index.py` exposes an OpenAI-compatible API surface.
2. `py/credentials_bootstrap.py` loads `credentials.json` into the runtime environment before provider modules import.
3. `py/provider_registry.py` resolves a model id to the correct provider.
4. `py/agent_tools.py` handles OpenAI-compatible prompt-shim tool instructions, `tool_calls` extraction, and normalization for chat-only upstreams.
5. `py/multimodal.py` keeps native image payloads for vision providers and can turn images into Gemini-generated descriptions for text-only providers.
6. `py/responses_api.py` translates OpenAI Responses-style input/output and keeps short-lived response/session state for multi-turn tool loops.
7. Each provider adapter handles its own auth shape, upstream request format, and streaming behavior.
8. `scripts/get-provider-creds.py` can auto-collect credentials from the local Chat2API desktop storage at `%APPDATA%\chat2api\Partitions\oauth-*`.
9. `scripts/get-arcee-creds.py` extracts the Arcee bearer token from a Chromium/Yandex profile into `auth\arcee-creds.json`.
10. `scripts/get-qwen-creds.py` extracts the Qwen cookie/header bundle into `auth\qwen-creds.json`.
11. `scripts/get-google-ai-studio-web-creds.py` extracts AI Studio Web cookie/header/template values from a cookie export plus browser "Copy as fetch" dump into `auth\google-ai-studio-web-creds.json`.
12. `scripts/launch-inception-auth.ps1` and `scripts/get-inception-creds.py` capture the Inception browser session into `auth\inception-creds.json`.
13. `scripts/launch-longcat-auth.ps1` and `scripts/get-longcat-creds.py` capture the LongCat browser session into `auth\longcat-creds.json`.
14. `scripts/launch-mistral-auth.ps1` and `scripts/get-mistral-creds.py` capture the Mistral browser session into `auth\mistral-creds.json`.
15. `scripts/redeploy-vercel.ps1 -SyncEnv` pushes the available credentials into Vercel and deploys the project.

## Zed / OpenAI-Compatible Agent Setup

Configure Zed as an OpenAI API Compatible provider with your proxy URL as `api_url`. Keep upstream provider credentials on the proxy itself; use `PROXY_API_KEY` as the client-facing key if you want Zed to authenticate to the proxy. In Zed's provider API-key field, paste the same `PROXY_API_KEY` value; if you configure Zed via env vars, use the API-key env var name Zed derives from your provider display name.

Example Zed settings shape:

```json
{
  "language_models": {
    "openai_compatible": {
      "Risu ZAI Proxy": {
        "api_url": "http://127.0.0.1:3001/v1",
        "available_models": [
          {
            "name": "glm-5-agent",
            "display_name": "GLM-5 Agent via Proxy",
            "max_tokens": 128000,
            "capabilities": {
              "tools": true,
              "images": true,
              "parallel_tool_calls": false,
              "chat_completions": true
            }
          },
          {
            "name": "google-ai-studio",
            "display_name": "Gemini via Google AI Studio",
            "max_tokens": 1048576,
            "capabilities": {
              "tools": true,
              "images": true,
              "parallel_tool_calls": true,
              "chat_completions": true
            }
          },
          {
            "name": "uncloseai-hermes",
            "display_name": "UncloseAI Hermes Tools",
            "max_tokens": 128000,
            "capabilities": {
              "tools": true,
              "images": true,
              "parallel_tool_calls": true,
              "chat_completions": true
            }
          }
        ]
      }
    }
  }
}
```

For Zed MCP servers, configure MCP in Zed itself. Zed executes MCP tools locally and sends them to this proxy as OpenAI-compatible `tools`; the proxy's job is to make the selected upstream model request structured `tool_calls` instead of writing commands as plain text.

## Local Run

Install Python dependencies into the ignored local `pydeps` directory once:

```powershell
npm run deps:py
```

Start through the Node wrapper:

```powershell
F:\DevTools\Portable\NodeJS\node.exe F:\downloads\risu-zai-proxy-archive\local-server.js
```

Python server path:

```powershell
F:\DevTools\Python311\python.exe F:\downloads\risu-zai-proxy-archive\py\server.py
```

Or from the repo root:

```powershell
npm run dev
```

## Vercel

The one-click deploy button above creates a Vercel project from this repository.

The environment map and manual/automatic credential sources are documented in [docs/deployment.md](docs/deployment.md).
When `credentials.json` is present, the Python entrypoints load it before importing providers so Vercel can use the file as the auth source of truth.

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
- `py/credentials_bootstrap.py` mirrors lowercase keys from extracted creds files to uppercase env names, so local `openai_web_*` / `gemini_web_*` exports work without manual renaming.
- Arcee uses a bearer token stored in the Chromium/Yandex cookie jar for `api.arcee.ai`; `scripts/get-arcee-creds.py` extracts it into `auth\arcee-creds.json` for local runs and Vercel sync.
- Qwen uses the browser cookie jar plus live `bx-*` request headers from `chat.qwen.ai`; `scripts/get-qwen-creds.py` extracts them into `auth\qwen-creds.json` for local runs and Vercel sync.
- Mistral uses a dedicated browser-profile extractor for `console.mistral.ai`, which feeds the Vercel env sync through `auth\mistral-creds.json`.
- Inception uses a dedicated browser-profile extractor for `chat.inceptionlabs.ai`; each request gets a fresh backend chat id, so chats are not forced into one shared session.
- LongCat uses a dedicated browser-profile extractor for `longcat.chat`; each request gets a fresh `session-create` conversation, so chats are not forced into one shared thread.
- LongCat exposes separate slugs for convenience: `LongCat-Flash-Chat` for regular answers and `LongCat-Flash-Thinking` / `LongCat-Flash-Thinking-2601` for reasoning.
- `Pi Web Local` is intentionally local-only and does not need Vercel env vars.
- `UncloseAI` does not require credentials.
- `Google AI Studio` uses `GOOGLE_AI_STUDIO_API_KEY` / `GEMINI_API_KEY` and supports native images plus native Gemini function calling.
- `Google AI Studio Web` is a separate experimental cookie-backed provider. `CountTokens` uses the private AI Studio RPC with `GOOGLE_AI_STUDIO_WEB_COOKIE`; `GenerateContent` also requires a captured `GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE` because the browser request includes a protected capability blob.
- `Gemini Web` assembles chat history into one prompt and trims older text at `GEMINI_WEB_MAX_PROMPT_CHARS` (default `90000`) to reduce `Gemini Web returned no reply candidates` failures on long chats.
- When `GOOGLE_AI_STUDIO_API_KEY` is configured, text-only providers can receive image descriptions generated by Gemini. Set `MULTIMODAL_IMAGE_MODE=placeholder` to avoid external image-caption calls, or `MULTIMODAL_IMAGE_MODE=off` to pass requests unchanged.
- For the most reliable OpenAI Agents / long-running tool loops, use `google-ai-studio`, `pi-api`, or an `uncloseai-*` model because those providers receive native tool schemas.
- `Z.ai` remains the stable general chat path. For agent clients that must use Z.ai, prefer `glm-5-agent` or `glm-5.1-agent`; those aliases use the prompt tool shim plus Z.ai thinking/search flags.
