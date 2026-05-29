# risu-zai-proxy

OpenAI-compatible proxy for RisuAI, Codex, Zed, and other OpenAI-style clients. It exposes many browser-session and API-backed providers behind one `/v1` endpoint, including `/v1/chat/completions` and `/v1/responses`.

[![Deploy to Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/VolcharaVasiliy/risu-zai-proxy-archive)

## What You Get

- OpenAI-compatible routes: `/v1/models`, `/v1/chat/completions`, `/v1/responses`, `/health`
- Codex-ready Responses API support, so `api2codex` is not needed for this proxy
- `rzai` launcher for running Codex against the proxy with one short command
- Provider registry with aliases, model catalog generation, and duplicate-model cleanup for Codex
- Prompt-tool shim for chat-only providers, so models such as Qwen/Mistral/Gemini Web can still drive Codex tools
- Credential helpers for common browser/session providers
- Vercel deploy path, local Python server, and Cloudflare fallback for Inception

## Quick Start On Windows

Prerequisites:

- Node.js 20+
- Python 3.11+
- Git
- OpenAI Codex CLI installed and available as `codex`

From the repo root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

The setup script:

- installs Node packages
- installs Python dependencies into local `pydeps`
- generates the Codex model catalog at `%USERPROFILE%\.codex\risu-zai-model-catalog.json`
- installs `rzai` and `risu-zai` launchers into `%USERPROFILE%\.codex\bin`
- adds that bin directory to the user PATH unless `-NoPath` is used
- writes `%USERPROFILE%\.codex\risu-zai.config.toml`

Open a new terminal after PATH changes, then test:

```powershell
rzai -Print
rzai -Local exec --ephemeral -s read-only -a never "reply ok"
```

Use a different public proxy URL or default model:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 `
  -BaseUrl "https://your-project.vercel.app/v1" `
  -Model "Qwen3.7-Max"
```

## Daily Commands

Install/update Python dependencies:

```powershell
npm run deps:py
```

Run the local proxy on `http://127.0.0.1:3001/v1`:

```powershell
npm run dev
```

Generate a fresh Codex catalog:

```powershell
npm run codex:catalog -- --output "$env:USERPROFILE\.codex\risu-zai-model-catalog.json"
```

Run checks:

```powershell
npm run check
```

Run Codex through the installed launcher:

```powershell
rzai -Model Qwen3.7-Max "explain this repo"
rzai -Local -Model mistral-small-2603 exec --ephemeral -s workspace-write -a never "fix the failing test"
```

Launcher options:

- `-Local` uses `http://127.0.0.1:3001/v1`
- `-Remote` uses the configured Vercel URL
- `-BaseUrl <url>` uses any OpenAI-compatible `/v1` URL
- `-Model <id>` overrides the default model
- `-ApiKey <value>` sets `CODEX_API_KEY` for that run
- `-Print` prints the resolved Codex command without running it

## Local Credentials

The proxy loads `credentials.json` from the repo root before provider modules import. You can also use environment variables directly.

Minimal local pattern:

```powershell
$env:CODEX_API_KEY = "local"
$env:MISTRAL_COOKIE = "<console.mistral.ai cookie header>"
npm run dev
```

Then in another terminal:

```powershell
rzai -Local -Model mistral-small-2603 exec --ephemeral -s read-only -a never "reply ok"
```

Provider credentials stay on the proxy. Clients such as Codex/Zed only need the proxy-facing key (`CODEX_API_KEY`) when `PROXY_API_KEY` or `RISU_PROXY_API_KEY` is enabled.

## Deploy To Vercel

1. Click the deploy button above or import this repository into Vercel.
2. Add provider credentials as Vercel environment variables.
3. Deploy.
4. Point clients to:

```text
https://your-project.vercel.app/v1
```

Useful redeploy helper:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\redeploy-vercel.ps1 -SyncEnv
```

See [docs/deployment.md](docs/deployment.md) for the full env map and Vercel notes.

## Providers

The full provider matrix lives in [docs/providers.md](docs/providers.md). Common picks:

| Use case | Model |
| --- | --- |
| Qwen web coding/agent tests | `Qwen3.7-Max` |
| Stable Mistral smoke test | `mistral-small-2603` |
| Mistral coding | `devstral-2512` or `codestral-2508` |
| Gemini Web | `gemini-3-pro` or `gemini-3-flash-thinking` |
| Native-tool Gemini API | `google-ai-studio` |
| Native-tool public fallback | `uncloseai-hermes` |

Browser/session providers usually need cookies or tokens from a logged-in browser session. API providers need ordinary API keys.

Credential helper entry points:

```powershell
python .\scripts\get-provider-creds.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\launch-mistral-auth.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\launch-gemini-auth.ps1
python .\scripts\get-qwen-creds.py
```

## Codex Notes

Codex can talk to this proxy directly:

```toml
model_provider = "risu-zai"
model = "Qwen3.7-Max"
model_reasoning_effort = "xhigh"
preferred_auth_method = "apikey"
model_catalog_json = "C:/Users/<you>/.codex/risu-zai-model-catalog.json"

[model_providers.risu-zai]
name = "Risu ZAI Proxy"
base_url = "https://your-project.vercel.app/v1"
wire_api = "responses"
env_key = "CODEX_API_KEY"
```

`scripts/install-rzai.ps1` writes this profile automatically for the `rzai` launcher. Use `api2codex` only when you are targeting a different upstream that has chat completions but no Responses API.

## Zed / OpenAI-Compatible Clients

Use the proxy as a normal OpenAI-compatible provider:

- API URL: `https://your-project.vercel.app/v1` or `http://127.0.0.1:3001/v1`
- API key: your `PROXY_API_KEY` / `RISU_PROXY_API_KEY`, or any placeholder if proxy auth is disabled
- Model: any id from `/v1/models`

For MCP/tool use, configure MCP in the client. The proxy receives OpenAI-compatible tool schemas and either passes them through to native-tool providers or uses the prompt shim for chat-only providers.

## API Surface

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `GET /v1/responses/{response_id}`
- `DELETE /v1/responses/{response_id}`
- `POST /v1/responses/chat/completions`

`/v1/responses/chat/completions` is a compatibility route for clients that want response/session semantics but still expect chat-completion-shaped output.

## More Docs

- [Provider reference](docs/providers.md)
- [Deployment and environment guide](docs/deployment.md)
- [Repeat deploy notes](REDEPLOY.md)

## Notes

- `credentials.json`, `.env*`, `auth/`, `pydeps/`, and local run files are ignored by git.
- Set `AGENT_TOOL_MODE=auto` (default) for native tools where available and prompt-shim tools elsewhere.
- Set `AGENT_TOOL_MODE=off` if you prefer explicit errors for chat-only providers with tools.
- Inception has a Cloudflare/local tunnel fallback documented in [docs/deployment.md](docs/deployment.md).
