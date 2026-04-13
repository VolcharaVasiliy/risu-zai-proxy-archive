# risu-zai-proxy

Minimal OpenAI-compatible proxy for `RisuAI -> web providers`.

## Endpoints

- `GET /v1/models`
- `POST /v1/chat/completions`
- `GET /health`

## Stable Provider

Stable and live-verified provider:

- `Z.ai`
- model examples: `GLM-5-Turbo`, `glm-5`, `glm-5.1`, `glm-4.7`, `glm-4.6v`, `glm-4.6`, `glm-4.5v`, `glm-4.5-air`
- env: `ZAI_TOKEN=<ZAI_JWT>`

## Lab Providers

Requested provider set for lab:

- `Grok`
- model examples: `grok-3`, `grok-4`, `grok-4-thinking`, `grok-4.1-fast`
- env: `GROK_COOKIE=<full grok.com cookie header>`
- optional extra envs: `GROK_SSO=<sso cookie value>`, `GROK_CF_CLEARANCE=<cf_clearance cookie value>`

- `OpenAI Web`
- model examples:
  `chatgpt-auto` by default
  plus discovered ChatGPT web slugs synced into `OPENAI_WEB_MODELS`
- preferred env: `OPENAI_WEB_ACCESS_TOKEN=<accessToken from chatgpt.com/api/auth/session>`
- optional fallback env: `OPENAI_WEB_COOKIE=<full chatgpt.com cookie header>`
- optional extra envs:
  `OPENAI_WEB_DEVICE_ID=<oai-did cookie value>`
  `OPENAI_WEB_ACCOUNT_ID=<workspace/account id>`
  `OPENAI_WEB_MODELS=<json array of discovered slugs>`

- `Gemini Web`
- model examples:
  `gemini-3-flash`, `gemini-3-pro`, `gemini-3-flash-thinking`
  plus aliases `gemini-web`, `gemini-web-pro`, `gemini-web-thinking`
  plus discovered Gemini model entries synced into `GEMINI_WEB_MODELS`
- preferred env: `GEMINI_WEB_SECURE_1PSID=<__Secure-1PSID cookie value>`
- optional extra envs:
  `GEMINI_WEB_SECURE_1PSIDTS=<__Secure-1PSIDTS cookie value>`
  `GEMINI_WEB_COOKIE=<full google.com cookie header>`
  `GEMINI_WEB_MODELS=<json array of discovered Gemini model objects>`
- note: Gemini Web access is account/region gated; some accounts still return Gemini status `1060` on generation even though model discovery succeeds
- local Windows note: when `GEMINI_WEB_PROXY` / `HTTPS_PROXY` are not set explicitly, the adapter now auto-uses the current WinINET system proxy from Internet Settings if one is enabled

- `Pi` (official Inflection API — same family as pi.ai, no browser)
- model examples: `pi-api` (Pi / `inflection_3_pi`), `pi-3.1` (`Pi-3.1`), aliases `inflection-pi`, `inflection_3_pi`, `pi-3-1`
- env: `INFLECTION_API_KEY=<key from https://developers.inflection.ai/keys>` (or `PI_INFLECTION_API_KEY`)
- works on Vercel and locally; optional header `x-inflection-api-key` or `Authorization: Bearer` when env is empty
- optional env: `INFLECTION_API_BASE` if your org uses a non-default gateway (must include `/v1` suffix the same way as the public docs)

- `Pi Web Local`
- model examples: `pi-web-local`
- env: none required for the default profile path
- local-only: drives the consumer `pi.ai` website through a local Edge/Chrome profile and Node CDP bridge; Cloudflare blocks non-browser calls, so this path never replaces the official API on serverless

- `Qwen International`
- model examples: `Qwen3-Max`, `Qwen3.5-Plus`, `Qwen3-Coder`, `Qwen3-VL-235B-A22B`
- env: `QWEN_AI_COOKIE=<full cookie header string>`
- optional extra env: `QWEN_AI_TOKEN=<token cookie value>`

- `Mimo`
- model examples: `mimo-v2-pro`, `mimo-v2-flash-studio`, `mimo-v2-omni`
- envs:
  `MIMO_SERVICE_TOKEN=<serviceToken cookie>`
  `MIMO_USER_ID=<userId cookie>`
  `MIMO_PH_TOKEN=<xiaomichatbot_ph cookie>`
- optional fallback env: `MIMO_COOKIE=<full xiaomimimo.com cookie header>`
- optional local-only debug env: `MIMO_SKIP_TLS_VERIFY=1` if the desktop network path is intercepted and Python sees a hostname mismatch on `aistudio.xiaomimimo.com`
- optional local DNS override: `MIMO_RESOLVE_IPS=<comma-separated A records>` if `aistudio.xiaomimimo.com` resolves to `127.0.0.1`; the proxy now auto-queries public DNS when it detects loopback resolution, but the env is still available for manual pinning

- `Perplexity`
- model examples: `Turbo`, `PPLX-Pro`, `GPT-5`, `Claude-Sonnet-4`
- env: `PERPLEXITY_COOKIE=<full cookie header string>`
- optional extra env: `PERPLEXITY_SESSION_TOKEN=<__Secure-next-auth.session-token>`

- `Phind`
- model examples: `phind-search` (search-augmented AI), `phind-chat` (conversational chat)
- env: `PHIND_COOKIE=<full phindai.org cookie header>`
- optional extra env: `PHIND_NONCE=<WordPress nonce token>` (auto-fetched if not provided)
- note: uses WordPress AJAX API at phindai.org; nonce is automatically extracted from the page if not provided

- `Kimi`
- model examples: `kimi`, `kimi-thinking`, `kimi-search`
- env: `KIMI_TOKEN=<access token>`

- `DeepSeek`
- model examples: `deepseek-chat`, `deepseek-reasoner`, `deepseek-search`
- env: `DEEPSEEK_TOKEN=<userToken from local desktop storage>`

- `UncloseAI`
- model examples: `uncloseai-hermes`, `uncloseai-qwen-vl`, `uncloseai-gpt-oss`, `uncloseai-r1-distill`
- env: none
- note: these aliases are intentionally namespaced so they do not collide with existing provider model ids

`Z.ai` stays unchanged and remains the stable provider.

## Auth

For Z.ai you can still pass the token manually if needed:

- `Authorization: Bearer <ZAI_JWT>`
- or `x-zai-token: <ZAI_JWT>`

The proxy does not persist provider state and creates a fresh upstream chat for each request.

## Streaming

`stream=true` is supported on `/v1/chat/completions` for all configured providers.

- `Z.ai` streams native upstream SSE.
- `DeepSeek`, `Kimi`, `Perplexity`, `Phind`, and `Qwen International` now emit native incremental OpenAI-style chunks too.
- `UncloseAI` forwards native OpenAI-compatible responses from public endpoints and rewrites the upstream model id back to the requested `uncloseai-*` alias.
- `Grok` now follows the same stateless server pattern and translates native `token` / `isThinking` events into OpenAI-style streaming chunks.
- `OpenAI Web` uses the real ChatGPT web `sentinel + proof-of-work + backend-api/conversation` flow and emits OpenAI-style SSE chunks.
- `Pi` (Inflection API) streams OpenAI-style SSE from `https://api.inflection.ai/v1/chat/completions`.
- `Pi Web Local` is buffered through a local browser automation step against the saved `pi.ai` profile.
- The response ends with `data: [DONE]`.

## Local run

```powershell
F:\DevTools\Portable\NodeJS\node.exe F:\Projects\risu-zai-proxy\local-server.js
```

Working path for Z.ai at the moment is Python:

```powershell
F:\DevTools\Python311\python.exe F:\Projects\risu-zai-proxy\py\server.py
```

Server-side token mode:

```powershell
$env:ZAI_TOKEN = '<ZAI_JWT>'
F:\DevTools\Python311\python.exe F:\Projects\risu-zai-proxy\py\server.py
```

If provider env vars are set, clients do not need to send any API key.

## Quick test

```powershell
$headers = @{
  "Content-Type" = "application/json"
}

$body = @{
  model = "glm-5"
  stream = $false
  messages = @(
    @{
      role = "user"
      content = "Say hello in one short sentence."
    }
  )
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:3001/v1/chat/completions" -Headers $headers -Body $body
```

Provider routing examples:

```powershell
$body = @{
  model = "kimi"
  stream = $false
  messages = @(
    @{
      role = "user"
      content = "Say hello in one short sentence."
    }
  )
} | ConvertTo-Json -Depth 10
```

## RisuAI setup

- API type: `OpenAI`
- Base URL: `http://127.0.0.1:3001/v1`
- API key: leave empty if the selected provider env is configured on the server
- Model:
  `GLM-5-Turbo` or `glm-5` for stable Z.ai
  `Qwen3-Max`, `mimo-v2-pro`, `Turbo`, `phind-search`, `phind-chat`, `kimi`, `deepseek-chat`, `grok-4`, `uncloseai-hermes`, `uncloseai-qwen-vl`, `uncloseai-gpt-oss`, `uncloseai-r1-distill`, `pi-api`, `pi-3.1`, `pi-web-local`, `gemini-3-flash`, `gemini-3-pro`, `gemini-3-flash-thinking`, or `chatgpt-auto` / discovered OpenAI Web and Gemini Web models for the added lab providers once their envs are set

Later on Vercel, only the base URL changes.

## Vercel env

Set this in the Vercel project:

- `ZAI_TOKEN=<your Z.ai JWT>`
- `GROK_COOKIE=<your full grok.com cookie header>`
- `GROK_SSO=<optional sso cookie value>`
- `GROK_CF_CLEARANCE=<optional cf_clearance cookie value>`
- `OPENAI_WEB_ACCESS_TOKEN=<your ChatGPT web accessToken>`
- `OPENAI_WEB_COOKIE=<optional full chatgpt.com cookie header>`
- `OPENAI_WEB_DEVICE_ID=<optional oai-did value>`
- `OPENAI_WEB_ACCOUNT_ID=<optional account/workspace id>`
- `OPENAI_WEB_MODELS=<optional json array of discovered ChatGPT model slugs>`
- `GEMINI_WEB_SECURE_1PSID=<your __Secure-1PSID cookie value>`
- `GEMINI_WEB_SECURE_1PSIDTS=<optional __Secure-1PSIDTS cookie value>`
- `GEMINI_WEB_COOKIE=<optional full google.com cookie header>`
- `GEMINI_WEB_MODELS=<optional json array of discovered Gemini model objects>`
- `QWEN_AI_COOKIE=<your full chat.qwen.ai cookie header>`
- `QWEN_AI_TOKEN=<optional token cookie value>`
- `PERPLEXITY_COOKIE=<your full perplexity cookie header>`
- `PERPLEXITY_SESSION_TOKEN=<optional session token>`
- `PHIND_COOKIE=<your full phindai.org cookie header>`
- `PHIND_NONCE=<optional WordPress nonce token>`
- `KIMI_TOKEN=<your Kimi access token>`
- `MIMO_SERVICE_TOKEN=<your Xiaomi Mimo serviceToken cookie>`
- `MIMO_USER_ID=<your Xiaomi Mimo userId cookie>`
- `MIMO_PH_TOKEN=<your Xiaomi Mimo xiaomichatbot_ph cookie>`
- `MIMO_COOKIE=<optional full xiaomimimo.com cookie header>`
- `DEEPSEEK_TOKEN=<your DeepSeek userToken>`
- `INFLECTION_API_KEY=<Inflection developer API key>` (optional `PI_INFLECTION_API_KEY` as an alias)

`UncloseAI` does not need any server env to work.
`Pi Web Local` is meant for the local Python server and uses `F:\Projects\risu-zai-proxy\auth\pi-edge-profile` by default. Optional overrides: `PI_LOCAL_PROFILE_ROOT`, `PI_LOCAL_BROWSER_PATH`, `PI_LOCAL_NODE_PATH`, `PI_LOCAL_CDP_PORT`, `PI_LOCAL_TIMEOUT_MS`.

Then RisuAI only needs:

- base URL
- model

## Vercel routes

- `/health`
- `/v1/models`
- `/v1/chat/completions`

These are rewritten internally to a single Python entrypoint in `api/index.py`.

## Repeat Deploy

- Token extractor: `F:\Projects\risu-zai-proxy\scripts\get-zai-token.ps1`
- Full provider extractor: `F:\Projects\risu-zai-proxy\scripts\get-provider-creds.py`
- Grok auth launcher: `F:\Projects\risu-zai-proxy\scripts\launch-grok-auth.ps1`
- Grok cookie extractor: `F:\Projects\risu-zai-proxy\scripts\get-grok-creds.py`
- OpenAI Web auth launcher: `F:\Projects\risu-zai-proxy\scripts\launch-openai-auth.ps1`
- OpenAI Web creds extractor: `F:\Projects\risu-zai-proxy\scripts\get-openai-web-creds.py`
  it reopens the dedicated profile briefly with local CDP and extracts the real `accessToken` from the logged-in `chatgpt.com` page
- Gemini Web auth launcher: `F:\Projects\risu-zai-proxy\scripts\launch-gemini-auth.ps1`
- Gemini Web creds extractor: `F:\Projects\risu-zai-proxy\scripts\get-gemini-web-creds.py`
  it reads `__Secure-1PSID` / optional `__Secure-1PSIDTS` from the dedicated Gemini profile, then tries Yandex Browser user data, then falls back to Chat2API storage; discovered models are synced into `GEMINI_WEB_MODELS`
- Phind auth launcher: `F:\Projects\risu-zai-proxy\scripts\launch-phind-auth.ps1`
- Phind cookie extractor: `F:\Projects\risu-zai-proxy\scripts\get-phind-creds.ps1`
- Pi local auth launcher: `F:\Projects\risu-zai-proxy\scripts\launch-pi-auth.ps1`
- Pi local browser bridge: `F:\Projects\risu-zai-proxy\scripts\pi-browser-bridge.mjs`
- Repeat deploy script: `F:\Projects\risu-zai-proxy\scripts\redeploy-vercel.ps1`
- Short guide: `F:\Projects\risu-zai-proxy\REDEPLOY.md`
