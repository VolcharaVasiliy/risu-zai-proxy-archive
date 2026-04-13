# Redeploy

## Where The Credentials Live

Current Chat2API desktop install stores provider sessions under:

- `C:\Users\gamer\AppData\Roaming\chat2api\Partitions\`

This project now extracts:

- `Z.ai` JWT from the newest partition that actually contains `chat.z.ai`
- `DeepSeek` `userToken`
- `Grok` cookies from a dedicated local Chromium profile created for `grok.com`
- `OpenAI Web` cookie header and `accessToken` from a dedicated local Chromium profile created for `chatgpt.com`
- `Gemini Web` `__Secure-1PSID` / optional `__Secure-1PSIDTS` from a dedicated local Chromium profile created for `gemini.google.com` or from Chat2API desktop storage when Gemini cookies are present there
- `Kimi` `access_token` and `refresh_token`
- `Mimo` cookie values `serviceToken`, `userId`, and `xiaomichatbot_ph`
- `Qwen International` cookie header and `token` cookie
- `Perplexity` cookie header and `__Secure-next-auth.session-token`
- `Phind` cookie header from dedicated browser profile for `phindai.org`
- `UncloseAI` does not need extracted credentials or env sync
- `Pi Web Local` does not deploy to Vercel; it uses the dedicated local browser profile `auth\pi-edge-profile`

## Quick Extract

Z.ai only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy\scripts\get-zai-token.ps1
```

All supported providers:

```powershell
F:\DevTools\Python311\python.exe F:\Projects\risu-zai-proxy\scripts\get-provider-creds.py
```

Grok login browser and cookie extract:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy\scripts\launch-grok-auth.ps1
F:\DevTools\Python311\python.exe F:\Projects\risu-zai-proxy\scripts\get-grok-creds.py --profile-root F:\Projects\risu-zai-proxy\auth\grok-edge-profile --output F:\Projects\risu-zai-proxy\auth\grok-creds.json
```

OpenAI Web login browser and credential extract:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy\scripts\launch-openai-auth.ps1
F:\DevTools\Python311\python.exe F:\Projects\risu-zai-proxy\scripts\get-openai-web-creds.py --profile-root F:\Projects\risu-zai-proxy\auth\openai-web-edge-profile --output F:\Projects\risu-zai-proxy\auth\openai-web-creds.json
```

`get-openai-web-creds.py` now reopens that dedicated profile briefly with local CDP, asks the real `chatgpt.com` page for `/api/auth/session`, then closes the browser again. This avoids the direct server-side `403` path on `chatgpt.com/api/auth/session`.

Gemini Web login browser and credential extract:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy\scripts\launch-gemini-auth.ps1
F:\DevTools\Python311\python.exe F:\Projects\risu-zai-proxy\scripts\get-gemini-web-creds.py --profile-root F:\Projects\risu-zai-proxy\auth\gemini-web-edge-profile --output F:\Projects\risu-zai-proxy\auth\gemini-web-creds.json
```

`get-gemini-web-creds.py` reads `__Secure-1PSID` / optional `__Secure-1PSIDTS` from the dedicated profile or Chat2API storage, then syncs discovered Gemini model descriptors into `gemini_web_models`.
If the dedicated profile is empty, it now also tries the main Yandex Browser user-data root. If Yandex is running and the cookie DB is locked, the script records that profile error and falls back cleanly instead of aborting.

Phind login browser and cookie extract:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy\scripts\launch-phind-auth.ps1
node F:\Projects\risu-zai-proxy\scripts\get-phind-session.mjs
```

Or use the combined script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy\scripts\get-phind-creds.ps1
```

This extracts cookies from `phindai.org` using CDP. The nonce is auto-fetched from the page when needed, so only the cookie is required in env vars.

## Redeploy To Vercel

This refreshes all locally available provider env vars, including `MIMO_*` and `GEMINI_WEB_*` from local credentials, optionally adds `GROK_*` from `auth\grok-creds.json`, optionally adds `OPENAI_WEB_*` from `auth\openai-web-creds.json`, optionally adds `GEMINI_WEB_*` plus `GEMINI_WEB_MODELS` from `auth\gemini-web-creds.json`, optionally adds `PHIND_COOKIE` from `auth\phind-creds.json`, then runs a fresh production deploy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy\scripts\redeploy-vercel.ps1 -SyncEnv
```

For local Gemini testing, the Python adapter now auto-detects the current Windows Internet Settings proxy when `GEMINI_WEB_PROXY` / `HTTPS_PROXY` are not set explicitly. On this machine that means local Gemini requests can ride the enabled system proxy at `127.0.0.1:7897`.

If local DNS points `aistudio.xiaomimimo.com` to `127.0.0.1`, set `MIMO_RESOLVE_IPS` before local testing so the proxy can pin the real public A records explicitly. The Python adapter also auto-queries `dns.google` when it detects loopback resolution.

## Current Live URL

- `https://risu-zai-proxy.vercel.app`

## RisuAI

- API type: `OpenAI`
- Base URL: `https://risu-zai-proxy.vercel.app/v1`
- API key: empty
- Models:
  `glm-5`
  `mimo-v2-pro`
  `grok-4`
  `chatgpt-auto`
  `gemini-3-flash`
  `gemini-3-pro`
  `deepseek-chat`
  `kimi`
  `Qwen3-Max`
  `Turbo`
  `phind-search`
  `phind-chat`
  `uncloseai-hermes`
  `uncloseai-qwen-vl`
  `uncloseai-gpt-oss`
  `uncloseai-r1-distill`

## Pi (Inflection API) on Vercel

Pi in production should use the official Inflection API (OpenAI-compatible), not the consumer `pi.ai` website.

- Create a key at https://developers.inflection.ai/keys
- In Vercel project env set `INFLECTION_API_KEY` (or `PI_INFLECTION_API_KEY`)
- Models: `pi-api` / `inflection-pi` → `inflection_3_pi`, or `pi-3.1` → `Pi-3.1`
- Redeploy: `F:\Projects\risu-zai-proxy\scripts\redeploy-vercel.ps1` (add the var in the Dashboard if you do not extend it into `SyncEnv`)

## Pi Local (consumer pi.ai in browser)

Pi **Web** is local-only: in-browser API calls work, but direct server-side replay still hits Cloudflare (see `F:\REPORT.md`).

Prepare the profile if needed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy\scripts\launch-pi-auth.ps1
```

Then run the local Python server with model `pi-web-local`.
