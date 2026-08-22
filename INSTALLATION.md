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

## 3. Configure credentials and environment variables

The proxy accepts configuration from (in this order) `credentials.json`, process
environment variables, and provider-specific request headers. `credentials.json`
is git-ignored and is the easiest local setup; environment variables are the
usual choice for Vercel. Do not commit either file.

Minimum to start — the key clients use to talk to the proxy:

```powershell
$env:PROXY_API_KEY = "pick-your-own-secret-key"
```

For a local-only setup you can also create `credentials.json` in the repository
root:

```json
{
  "PROXY_API_KEY": "pick-your-own-secret-key",
  "ZAI_TOKEN": "<token>"
}
```

Locally on `127.0.0.1` the server also starts without a key (for testing), but a
key is required for real use.

Per-provider credentials use the exact names in [the provider reference](docs/providers.md),
for example `ZAI_TOKEN`, `MISTRAL_COOKIE`, or `GOOGLE_AI_STUDIO_API_KEY`. For
one-off requests, supported provider headers such as `x-lmarena-cookie` can be
used instead; `/v1/providers` shows the required credential *names* without
revealing their values.

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

Inspect readiness and provider configuration:

```powershell
curl http://127.0.0.1:3001/doctor `
  -H "Authorization: Bearer $env:PROXY_API_KEY"
curl http://127.0.0.1:3001/v1/providers `
  -H "Authorization: Bearer $env:PROXY_API_KEY"
```

## 7. Make your first request

Via `curl` (Z.ai model):

```powershell
curl http://127.0.0.1:3001/v1/chat/completions `
  -H "Authorization: Bearer $env:PROXY_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"glm-4.7","messages":[{"role":"user","content":"Hello, who are you?"}]}'
```

Same request from Python (openai SDK):

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:3001/v1",
    api_key="pick-your-own-secret-key",
)

resp = client.chat.completions.create(
    model="glm-4.7",
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

3. The normal provider value is the complete `arena.ai` cookie header. Put it in
   `credentials.json` as `LM_ARENA_COOKIE` or set it as an environment variable:

```powershell
$env:LM_ARENA_COOKIE = "arena-auth-prod-v1.1=<value>; other_cookie=<value>"
```

If you use the local browser bridge, the extension's JSON cookie export can be
saved separately and selected with `LM_ARENA_COOKIE_FILE` (the bridge-only file
input). `LM_ARENA_COOKIE` itself is not a filesystem path.

4. Point the bridge at the cookie file when needed (bridge mode defaults to `auto`):

```powershell
$env:LM_ARENA_COOKIE_FILE = "C:\Users\you\Desktop\lmarena-cookie.json"
```

5. Send a request using any model id listed by `/v1/models` (the optional
`lmarena:`/`arena:` aliases are accepted, but are not required):

```powershell
curl http://127.0.0.1:3001/v1/chat/completions `
  -H "Authorization: Bearer $env:PROXY_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"gpt-5.2","messages":[{"role":"user","content":"Tell me a joke"}]}'
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
- Unexpected or empty output → set `PROXY_LOG_LEVEL=debug`, repeat the request,
  and correlate the JSON events with the returned `X-Request-ID`. Secrets and
  cookies are redacted automatically; see [observability.md](docs/observability.md).

## Links

- [Provider reference](docs/providers.md)
- [Deployment and environment guide](docs/deployment.md)
- [README](README.md)
- [Contributing](CONTRIBUTING.md)
