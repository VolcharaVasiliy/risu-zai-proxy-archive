# Installation

> What this is: an OpenAI-compatible proxy aggregator. One local server exposes
> `/v1/chat/completions` and `/v1/models`, and routes each model through a
> provider backend (Z.ai, Grok, LM Arena, Gemini Web, GLM Web, Inflection/Pi,
> Arcee, Google AI Studio, and more).
>
> Below is a step-by-step setup with copy-paste commands.

## 0. Prerequisites

- Git (any recent version)
- Node.js 20+
- Python 3.11+ on `PATH`
- (Optional) Cloudflare Wrangler — only for the Cloudflare fallback: `npm i -g wrangler`
- Internet access; some providers need a system HTTP(S) proxy (`HTTPS_PROXY`).

## 1. Clone

```powershell
git clone https://github.com/VolcharaVasiliy/risu-zai-proxy-archive.git
cd risu-zai-proxy-archive
```

## 2. Install dependencies

### Option A — installer (Windows, recommended)

```powershell
npm run setup:windows
```

It installs the Python deps from `requirements.txt`, runs `npm install`, and
prepares a config template.

### Option B — manual (Windows / macOS / Linux)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate         # macOS / Linux

pip install -r requirements.txt
npm install
```

## 3. Configure environment variables

Configuration is via environment variables only. A `.env` file is optional; you
can export variables in your shell or set them system-wide.

Minimum to start — the key clients use to talk to the proxy:

```powershell
$env:PROXY_API_KEY = "pick-your-own-secret-key"
```

Locally on `127.0.0.1` the server also starts without a key (for testing), but a
key is required for real use.

Per-provider keys are set either via `<PROVIDER>_API_KEY` / `<PROVIDER>_TOKEN`
variables, or passed in the request header `x-<provider>-api-key: ...`. See the
provider reference (link below) for the full list.

## 4. Start the server

Local (Python server via the Node runner):

```powershell
npm run dev
# or directly:
# node ./scripts/run-python.mjs ./py/server.py
```

Pure-Node server (alternative):

```powershell
npm run dev:node
```

The server listens on `http://127.0.0.1:3001` (override with `HOST` / `PORT`).

## 5. Check the server is alive

```powershell
curl http://127.0.0.1:3001/health
```

Expected: `200 OK`.

## 6. List models

```powershell
curl http://127.0.0.1:3001/v1/models `
  -H "Authorization: Bearer $env:PROXY_API_KEY"
```

## 7. Make your first request

Via `curl` (Z.ai model):

```powershell
curl http://127.0.0.1:3001/v1/chat/completions `
  -H "Authorization: Bearer $env:PROXY_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"zai:glm-4.5v","messages":[{"role":"user","content":"Hello, who are you?"}]}'
```

Same request from Python (openai SDK):

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:3001/v1",
    api_key="pick-your-own-secret-key",
)

resp = client.chat.completions.create(
    model="zai:glm-4.5v",
    messages=[{"role": "user", "content": "Hello, who are you?"}],
)
print(resp.choices[0].message.content)
```

## 8. LM Arena quick start (local-only provider)

LM Arena needs a cookie from `arena.ai` and solves a reCAPTCHA Enterprise v3
token. It is set up so you do the minimum: the proxy opens a single browser
window (bridge), fetches the token, and closes it on exit.

1. Log in to https://arena.ai in your browser.
2. Export the cookie (e.g. via the [credentials-exporter extension](extensions/credentials-exporter/)) to a file,
   e.g. `C:\Users\gamer\Desktop\lmarena-cookie.txt`.

<details>
<summary>How to install the credentials-exporter extension</summary>

1. Open `chrome://extensions` (Firefox: `about:debugging#/runtime/this-firefox`).
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select the `extensions/credentials-exporter` folder from this repo.
4. Log in to https://arena.ai in that browser.
5. Open the extension popup and click **Сканировать** (Scan), then save the LM Arena cookie to `lmarena-cookie.txt`.

</details>

3. Point the proxy at the cookie (bridge mode defaults to `auto`):

```powershell
$env:LM_ARENA_COOKIE = "C:\Users\gamer\Desktop\lmarena-cookie.txt"
```

4. Just send a request to a model with the `arena:` prefix:

```powershell
curl http://127.0.0.1:3001/v1/chat/completions `
  -H "Authorization: Bearer $env:PROXY_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"arena:gpt-5.2","messages":[{"role":"user","content":"Tell me a joke"}]}'
```

Env switches and details are in the provider reference (link below).

## 9. Deploy to Vercel (optional)

- Use the Deploy-to-Vercel button, or manually:

```powershell
npm i -g vercel
vercel login
vercel link
vercel env pull .env
vercel deploy --prod
```

- Note: local-only providers (Grok, Z.ai, LM Arena) do **not** work on Vercel —
  their reCAPTCHA/cookie are bound to your IP and browser. Use them locally only.

## 10. Troubleshooting

- `401` / `403` from a provider → cookie/token expired: re-login and refresh the
  cookie (LM Arena) or update the API key.
- `recaptcha validation failed` → the proxy re-requests a token via the bridge
  automatically; if the browser window is closed, it is re-opened on the next
  request (unless `LM_ARENA_BRIDGE_MODE=off`).
- `429` → provider rate limit; wait a moment and retry.
- Server won't start → check `python --version` ≥ 3.11 and `node -v` ≥ 20, and
  that `npm install` finished cleanly.

## Links

- [Provider reference](docs/providers.md)
- [Deployment and environment guide](docs/deployment.md)
- [README](README.md)
- [Contributing](CONTRIBUTING.md)
