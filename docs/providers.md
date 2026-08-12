# Provider Reference

This project exposes a uniform OpenAI-compatible API, but each upstream provider has its own auth source, model set, and operational constraints.

## Summary Table

| Provider | Model ids | Required env | Optional env | Manual source | Automatic source | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Z.ai | `glm-5-agent`, `glm-5-search`, `glm-5`, `glm-5.1-agent`, `glm-5.1-search`, `glm-5.1`, `GLM-5-Turbo`, `glm-4.7`, `glm-4.6v`, `glm-4.6`, `glm-4.5v`, `glm-4.5-air` | `ZAI_TOKEN` | `x-zai-token` header | Logged-in `chat.z.ai` session | `scripts/get-zai-token.ps1`, `scripts/get-provider-creds.py` | Stable production provider. The `*-agent` aliases enable Z.ai thinking/search flags and are the recommended Z.ai picks for agent clients using the prompt shim. Some accounts now gate `GLM-5.1` behind a higher plan level. **LOCAL-ONLY**: every completion needs an Aliyun `captcha_verify_param`, and that token is bound to the resolving IP of the machine that solved the captcha — so the Z.ai provider does not work when deployed to Vercel or any other host with a different public IP (see [Z.ai Captcha (Local-Only)](#zai-captcha-local-only)). |
| GLM Web | `chatglm-web`, `chatglm-web-thinking`, `chatglm-web-deepresearch` | `GLM_REFRESH_TOKEN` | `GLM_TOKEN`, `x-glm-refresh-token`, `x-glm-token` | Logged-in `chatglm.cn` session | `scripts/get-provider-creds.py` | Separate ChatGLM web path. In practice this is the more reliable GLM browser-session route when `chat.z.ai` account-level gating blocks `GLM-5.1`. |
| DeepSeek | `deepseek-chat`, `deepseek-reasoner`, `deepseek-search` | `DEEPSEEK_TOKEN` | `x-deepseek-token` header | Logged-in `chat.deepseek.com` session | `scripts/get-provider-creds.py` | Browser-session style token provider. |
| Arcee | `trinity-mini`, `trinity-large-preview`, `trinity-large-thinking` | `ARCEE_ACCESS_TOKEN` | `ARCEE_SESSION_ID`, `x-arcee-access-token`, `x-arcee-session-id` | Logged-in `chat.arcee.ai` / `api.arcee.ai` bearer cookie | `scripts/get-arcee-creds.py` | Uses the `api.arcee.ai` `access_token` bearer token; request session id can be any UUID. |
| Gemini Web | `gemini-3-flash`, `gemini-3-pro`, `gemini-3-flash-thinking`; `gemini-web*` aliases still resolve but are hidden from `/v1/models` | `GEMINI_WEB_SECURE_1PSID` | `GEMINI_WEB_SECURE_1PSIDTS`, `GEMINI_WEB_COOKIE`, `GEMINI_WEB_MODELS` | Logged-in `gemini.google.com` / Google cookie session | `scripts/launch-gemini-auth.ps1`, `scripts/get-gemini-web-creds.py`, `scripts/get-provider-creds.py` | Account/region gated. Only models with captured internal model headers are listed by default; use `GEMINI_WEB_MODELS` for newly discovered web-only variants. Can auto-use WinINET proxy locally. |
| Google AI Studio Web | `google-ai-studio-web`, `ai-studio-web`, `ai-studio-web-pro`, `ai-studio-web-3-pro`, `ai-studio-web-3-flash`, `ai-studio-web-flash`, `ai-studio-web-lite` | `GOOGLE_AI_STUDIO_WEB_COOKIE` | `GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE`, `GOOGLE_AI_STUDIO_WEB_HEADERS`, `GOOGLE_AI_STUDIO_WEB_API_KEY`, `GOOGLE_AI_STUDIO_WEB_VISIT_ID`, `GOOGLE_AI_STUDIO_WEB_EXT_519733851_BIN` | Logged-in `aistudio.google.com` Google cookies plus captured web request template for generation | Manual network capture only | Experimental private AI Studio web RPC path. `CountTokens` can work with cookies/SAPISID auth alone; `GenerateContent` needs a browser-captured body/template because slot `4` is a content/session-bound capability blob. |
| Google AI Studio / Gemini API | configured `gemini-*` ids, including `gemini-3.5-flash`, `gemini-3.1-pro-preview`, `gemini-3.1-pro-preview-customtools`, `gemini-3.1-flash-lite`, `gemini-3-pro-preview`, `gemini-3-pro-image-preview`, `gemini-3-flash-preview`; `ai-studio*` aliases still resolve but are hidden from `/v1/models` | `GOOGLE_AI_STUDIO_API_KEY` or `GEMINI_API_KEY` | `GOOGLE_AI_STUDIO_MODELS`, `GOOGLE_AI_STUDIO_API_BASE`, `GOOGLE_AI_STUDIO_*`, `MULTIMODAL_*` | `https://aistudio.google.com/app/apikey` | Manual only | Official API path with native images and native Gemini function calling. Also powers optional image descriptions for text-only providers. |
| Grok | `grok-3`, `grok-4`, `grok-4-thinking`, `grok-4.1-fast` | `GROK_COOKIE` | `GROK_SSO`, `GROK_CF_CLEARANCE` | Logged-in `grok.com` browser session | `scripts/launch-grok-auth.ps1`, `scripts/get-grok-creds.py` | Cookie-based browser provider. |
| OpenAI Web | `chatgpt-auto` and discovered ChatGPT web slugs | `OPENAI_WEB_ACCESS_TOKEN` | `OPENAI_WEB_COOKIE`, `OPENAI_WEB_DEVICE_ID`, `OPENAI_WEB_ACCOUNT_ID`, `OPENAI_WEB_MODELS`, `OPENAI_WEB_SENTINEL_TURNSTILE`, `OPENAI_WEB_SENTINEL_CHAT` | Logged-in `chatgpt.com` session | `scripts/launch-openai-auth.ps1`, `scripts/get-openai-web-creds.py`, `scripts/fetch-openai-turnstile.mjs` | Uses the web auth/session flow, not the public API. Local `credentials.json` loads are mirrored to uppercase env names, so `openai_web_*` exports work without renaming. The new `f/conversation` protocol requires a sentinel `turnstile` token on free accounts; without it OpenAI rate-limits (~1 in 4 answers empty / 403 on prepare). The token is read from `openai_turnstile.json` (see [OpenAI Web Sentinel Turnstile](#openai-web-sentinel-turnstile)) with TTL, then falls back to `OPENAI_WEB_SENTINEL_TURNSTILE`. |
| Qwen International | `Qwen3.8-Max`, `Qwen3.7-Max`, `Qwen3.7-Plus`, `Qwen3.6-Max`, `Qwen3.6-Plus`, `Qwen3.6-Flash`, `Qwen3.5-Omni`, `Qwen3.5-Max-Preview`, `Qwen3.5`, `Qwen3-Max`, `Qwen2.5-Max` | `QWEN_AI_COOKIE`, `QWEN_AI_BX_UMIDTOKEN` | `QWEN_AI_TOKEN`, `QWEN_AI_BX_UA`, `QWEN_AI_BX_UA_CREATE`, `QWEN_AI_BX_UA_CHAT`, `QWEN_AI_BX_V`, `QWEN_AI_TIMEZONE` | Logged-in `chat.qwen.ai` session | `scripts/get-provider-creds.py`, `scripts/get-qwen-creds.py` | Cookie + `bx-*` headers based. Most legacy model ids (`qwen3-max`, `qwen2.5-max`, `qwen3.6-max`, `qwen3.6-flash`, `qwen3.5-*`) are dead upstream and get remapped to the nearest live id (`qwen3.8-max` / `qwen3.6-plus`), so old names keep working. Short aliases such as `qwen` route to `qwen3.8-max`; `Qwen3.7-Max-Preview` spelling is still accepted as an alias. Upstream bx anti-bot may answer with a transient captcha punish (see [Qwen bx Anti-Bot (Transient)](#qwen-bx-anti-bot-transient)). |
| Inception | `mercury-2`, `mercury-coder` | `INCEPTION_SESSION_TOKEN` | `INCEPTION_COOKIE` | Logged-in `chat.inceptionlabs.ai` session | `scripts/launch-inception-auth.ps1`, `scripts/get-inception-creds.py`, `scripts/redeploy-vercel.ps1 -SyncEnv` | Each request gets a fresh backend chat id, so sessions do not collapse into one shared conversation. When `INCEPTION_EDGE_URL` is set, Vercel forwards only this provider to the Cloudflare worker. |
| LongCat | `LongCat-Flash-Chat`, `LongCat-Flash-Thinking`, `LongCat-Flash-Thinking-2601` | `LONGCAT_COOKIE` | none | Logged-in `longcat.chat` session | `scripts/launch-longcat-auth.ps1`, `scripts/get-longcat-creds.py`, `scripts/redeploy-vercel.ps1 -SyncEnv` | `LongCat-Flash-Chat` is the regular mode; `LongCat-Flash-Thinking` and `LongCat-Flash-Thinking-2601` are separate reasoning-mode slugs. Each request gets a fresh `session-create` conversation. |
| Mistral | `mistral-small-2603`, `mistral-small-2506`, `mistral-medium-2508`, `mistral-large-2512`, `ministral-14b-2512`, `ministral-8b-2512`, `ministral-3b-2512`, `magistral-medium-2509`, `magistral-small-2509`, `devstral-2512`, `codestral-2508`, `labs-devstral-small-2512`, `labs-leanstral-2603`, `voxtral-mini-2507`, `voxtral-small-2507` | `MISTRAL_COOKIE` | `MISTRAL_CSRF_TOKEN` | Logged-in `console.mistral.ai` session | `scripts/launch-mistral-auth.ps1`, `scripts/get-mistral-creds.py`, `scripts/redeploy-vercel.ps1 -SyncEnv` | Current chat-capable models only; models with 2026 retirement notes are intentionally omitted. |
| Perplexity | `auto`, `Turbo`, `PPLX-Pro`, `GPT-5`, `GPT-5.1`, `Gemini-2.5-Pro`, `Claude-Sonnet-4`, `Claude-Opus-4`, `O3` | `PERPLEXITY_COOKIE` | `PERPLEXITY_SESSION_TOKEN` | Logged-in `perplexity.ai` session | `scripts/get-provider-creds.py` | Session cookie based. `auto`/`Turbo` map to the `pplx_pro` upstream slug; recognized live slugs are `pplx_pro`, `gpt5`, `gpt51`, `gemini25pro`, `claude45sonnet`, `claude45opus`, `o3`. Upstream `INVALID_MODEL_SELECTION` / `failed` events surface as explicit errors instead of empty completions. |
| Phind | `phind-search`, `phind-chat` | `PHIND_COOKIE` | `PHIND_NONCE` | Logged-in `phindai.org` session | `scripts/launch-phind-auth.ps1`, `scripts/get-phind-creds.ps1`, `scripts/get-provider-creds.py` | WordPress nonce is auto-fetched when missing. |
| Mimo | `mimo-v2-pro`, `mimo-v2-flash-studio`, `mimo-v2-omni` | `MIMO_SERVICE_TOKEN`, `MIMO_USER_ID`, `MIMO_PH_TOKEN` | `MIMO_COOKIE`, `MIMO_RESOLVE_IPS`, `MIMO_SKIP_TLS_VERIFY` | Logged-in `xiaomimimo.com` / `aistudio.xiaomimimo.com` session | `scripts/get-provider-creds.py`, `scripts/redeploy-vercel.ps1 -SyncEnv` | Auto-resolves public IPs if local DNS points to loopback. Upstream `error` SSE events (e.g. expired session `登录已过期`) are surfaced as explicit errors instead of empty completions. |
| Kimi | `kimi`, `kimi-thinking`, `kimi-search` | `KIMI_TOKEN` | none | Logged-in `www.kimi.com` session | `scripts/get-provider-creds.py` | Desktop storage token provider. |
| Inflection / Pi API | `pi-api`, `pi-3.1`, aliases `inflection-pi`, `inflection_3_pi`, `pi-3-1` | `INFLECTION_API_KEY` or `PI_INFLECTION_API_KEY` | `INFLECTION_API_BASE` | `https://developers.inflection.ai/keys` | Manual only | Official API path, works on Vercel. |
| Pi Web Local | `pi-web-local` | none | `PI_LOCAL_*` | Local `pi.ai` browser profile | `scripts/launch-pi-auth.ps1`, `scripts/pi-browser-bridge.mjs` | Local-only browser automation path. |
| UncloseAI | `uncloseai-hermes`, `uncloseai-qwen-vl`, `uncloseai-gpt-oss`, `uncloseai-r1-distill` | none | none | Public endpoint | none | Intentionally credential-free. |

## Z.ai Captcha (Local-Only)

`chat.z.ai` requires an Aliyun "human verification" token (`captcha_verify_param`) on every `/api/v2/chat/completions` call. The proxy solves this automatically as follows:

1. `scripts/fetch-zai-captcha.mjs` launches headless Edge (or `--headed`), opens `chat.z.ai`, sends a probe chat, and intercepts the `captcha_verify_param` from the app's retried completion request. Result is saved to `captcha_param.json`.
2. `py/zai_captcha.py` caches the token with a TTL (`ZAI_CAPTCHA_TTL_SECONDS`, default 60) and spawns the grabber on demand (single in-flight run), or never spawns it in `ZAI_CAPTCHA_MODE=file` / `off` mode.
3. `py/zai_proxy.py` includes the token in the completion body and refreshes + retries automatically when the upstream answers `FRONTEND_CAPTCHA_REQUIRED` (both as an HTTP error and inside the SSE stream).

**IP binding (why Vercel does not work).** The token is bound to the public IP that solved the captcha: requests from the same IP succeed, requests from another IP (e.g. a Vercel function) are rejected with `人机验证失败，请重新验证后再试` / `FRONTEND_CAPTCHA_REQUIRED`. It is not bound to the browser fingerprint — the same token works fine from a plain `requests` client on the same machine. Consequences:

- The Z.ai provider is **local-only**: run `py/server.py`, or any host that keeps a stable public IP and can run the grabber (e.g. a VPS with Chromium). Vercel / GitHub Actions runners have different egress IPs and cannot substitute.
- Keep `ZAI_CAPTCHA_MODE=file` on hosts without the grabber, and a generous `ZAI_CAPTCHA_TTL_SECONDS`.
- `captcha_param.json` and `captcha-grabber.log` are runtime artifacts; `captcha-grabber-debug.png` is written on grabber failures.

## OpenAI Web Sentinel Turnstile

`chatgpt.com` (new `f/conversation` protocol) gates free-account traffic behind a sentinel `turnstile` challenge. When the `prepare` response reports `turnstile.required`, the proxy must present a fresh `openai-sentinel-turnstile-token` on the `finalize` call and on the `f/conversation` stream request, otherwise OpenAI silently returns an empty answer or replies `403` on `prepare` (observed ~1 in 4 requests without it).

The proof-of-work (`openai-sentinel-proof-token`) is still solved locally in `py/openai_web_proxy.py` (`generate_answer`); only the turnstile token needs an external source.

**Token source (priority order), in `py/openai_turnstile.py`:**

1. `openai_turnstile.json` — a JSON file written by either the bundled grabber or your own browser extension:
   ```json
   { "turnstile_token": "<openai-sentinel-turnstile-token value>", "captured_at": 1786392894667 }
   ```
   This is the **primary** source. The file path is configurable via `OPENAI_TURNSTILE_FILE` (default `<project root>/openai_turnstile.json`); on read-only hosts (Vercel) point it at a writable path such as `/tmp/openai_turnstile.json`. The token is **session-long**: by default (`OPENAI_TURNSTILE_TTL_SECONDS=0`) it never expires on a timer — it is reused for the whole session and only re-fetched when a real request actually fails (`403` on `prepare` / empty stream), via the retry path. Set a positive TTL only if you want a forced periodic re-validation.
2. `OPENAI_WEB_SENTINEL_TURNSTILE` env (static fallback, for manual paste from DevTools). Only used when the file is missing/empty.

**Extension integration contract.** Your browser extension only needs to write `openai_turnstile.json` (or the path in `OPENAI_TURNSTILE_FILE`) with the captured `turnstile_token` and a fresh `captured_at` (epoch ms). The server reads it automatically; no code change is needed on the extension side beyond producing that file. The token is the exact value of the `openai-sentinel-turnstile-token` request header (seen on `backend-api/sentinel/prepare`, `/finalize`, `/ping` and `f/conversation`). It is reused unchanged across the whole session (verified against the captured chatgpt.com network trace — the same token value appears on every request), so the extension does not need to refresh it more than once per login.

**Bundled grabber (for local testing).** `scripts/fetch-openai-turnstile.mjs` launches headless Edge, authenticates with `OPENAI_WEB_COOKIE` from `credentials.json`, opens `chatgpt.com`, and intercepts the `openai-sentinel-turnstile-token` from the sentinel heartbeat, writing `openai_turnstile.json`. Run it with `node scripts/fetch-openai-turnstile.mjs` (or `--headed` to watch). Environment knobs mirror the Z.ai captcha grabber: `OPENAI_TURNSTILE_MODE`, `OPENAI_TURNSTILE_TTL_SECONDS`, `OPENAI_TURNSTILE_TIMEOUT_SECONDS`, `OPENAI_TURNSTILE_HEADLESS`, `OPENAI_TURNSTILE_CHANNEL`, `OPENAI_TURNSTILE_NODE`. With `OPENAI_TURNSTILE_MODE=file`/`off` the grabber never spawns and the file is the only source.

**Set the token via API (no env paste, works on Vercel).** `POST /api/?route=openai-turnstile` with body `{"turnstile_token": "...", "proof_token": "..."}` writes the file at `OPENAI_TURNSTILE_FILE`. This lets your extension (or a script) push the token to a deployed server without touching environment variables:
```bash
curl -X POST "https://<your-deploy>/api/?route=openai-turnstile" \
  -H "Authorization: Bearer $PROXY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"turnstile_token":"<openai-sentinel-turnstile-token value>"}'
```
On Vercel set `OPENAI_TURNSTILE_FILE=/tmp/openai_turnstile.json` and `OPENAI_TURNSTILE_MODE=file`, then POST the token from the extension each session.

**Retry resilience.** `py/openai_web_proxy.py` retries an empty stream or a `403` prepare up to `OPENAI_WEB_MAX_RETRIES` times (default 3), refreshing the turnstile token and backing off `OPENAI_WEB_RETRY_DELAY` seconds (default 3) between attempts. This raises real-answer rate from ~75% (no token) toward ~100% once a valid turnstile token is supplied, and self-heals if the token expires mid-session.

Check status at `GET /api/?route=openai-turnstile` (returns `openai_turnstile_file` freshness); push/update it at `POST /api/?route=openai-turnstile`. Note: like Z.ai, the turnstile token is IP/session-bound, so the grabber and the proxy must share the same egress IP (run locally; Vercel deploy still works but supply the token via the file/POST rather than the local grabber).

## Qwen bx Anti-Bot (Transient)

`chat.qwen.ai` frontend is protected by Alibaba's bx security module. If the session or IP gets flagged (bursts of requests, unusual headers), the `/api/v2/chat/completions` call is answered with a non-SSE JSON body instead of a stream:

```json
{"ret":["FAIL_SYS_USER_VALIDATE","RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试"],"data":{"url":"https://chat.qwen.ai/api/v2/chat/completions/_____tmd_____/punish?x5secdata=...&x5step=2&action=captcha&pureCaptcha="}}
```

The proxy treats this JSON as an empty stream, so clients see `HTTP 200` with an empty `content` (and `completion_tokens: 0`) rather than an explicit error. Observations:

- **It is transient.** The punish clears on its own after a cooldown (minutes). The same session/credentials start answering normally again without any code change.
- **It is per-IP/per-session.** Using different public IPs (or several sessions) spreads the load and avoids tripping it; hammering a single egress IP with rapid consecutive requests is the usual trigger. If a Vercel deployment is punished while a local run of the same credentials works (or vice versa), that is this mechanism, not a credential or model-mapping bug.
- **It is not a model-mapping bug.** Verify the request reaches upstream with a live model id (e.g. `qwen3.8-max`) first; if it does and the reply is a JSON `FAIL_SYS_USER_VALIDATE` punish, the model map is fine and the fix is cooling down or switching egress IPs.
- The proxy surfaces the situation in debug logs (with `DEBUG_LOGGING=1`) as `qwen_ai_upstream_json` / `qwen_ai_chat_started` entries.

## Responses Route Support

`/v1/chat/completions` is the regular OpenAI-compatible chat path.
`/v1/responses` returns an OpenAI Responses-style object with `output`, `function_call`, and `function_call_output` support.
`GET /v1/responses/{response_id}` and `DELETE /v1/responses/{response_id}` work for responses still present in the proxy's in-memory short-lived response state.
`/v1/responses/chat/completions` is a compatibility route for clients that want response/session state but still expect a chat-completion-shaped response.

Native OpenAI-style tool passthrough is available for:

- `Google AI Studio / Gemini API`
- `Inflection / Pi API`
- `UncloseAI`

All other providers in this repository are chat-only upstreams, but `AGENT_TOOL_MODE=auto` enables the prompt tool shim for them. The shim asks the model to emit strict JSON tool requests, removes unsupported upstream `tools` fields, and converts successful JSON back into OpenAI-compatible `tool_calls` for clients such as Zed. Set `AGENT_TOOL_MODE=off` if you prefer explicit errors for non-native tool providers.

## Lightweight Picks

Use these single-model picks for routine traffic when you want the lighter option for each provider:

| Provider | Recommended model |
| --- | --- |
| Z.ai | `glm-5` |
| DeepSeek | `deepseek-chat` |
| Arcee | `trinity-mini` |
| Gemini Web | `gemini-3-flash` |
| Google AI Studio Web | `google-ai-studio-web` for experimental cookie/RPC tests only |
| Google AI Studio / Gemini API | `google-ai-studio` |
| Grok | `grok-3-mini` |
| Qwen International | `Qwen3.7-Max` |
| Inception | `mercury-2` |
| LongCat | `LongCat-Flash-Chat` |
| Mistral | `mistral-small-2603` |
| Perplexity | `auto` |
| Phind | `phind-chat` |
| Mimo | `mimo-v2-flash-studio` |
| Kimi | `kimi` |
| Pi Web Local | `pi-web-local` |
| UncloseAI | `uncloseai-hermes` |

`OpenAI Web`, `Google AI Studio Web`, and `Inflection / Pi API` are currently not included in the routine recommended picks because the live deployment is known to be unreliable or experimental for those paths.

## Stable Provider

`Z.ai` is the stable provider and the one that should be used as the default production path.

## Browser-Session Providers

These providers depend on logged-in browser sessions or cookies:

- `Grok`
- `OpenAI Web`
- `Gemini Web`
- `Google AI Studio Web` (experimental)
- `Arcee`
- `Qwen International`
- `Inception`
- `LongCat`
- `Mistral`
- `Perplexity`
- `Phind`
- `Mimo`
- `Kimi`
- `DeepSeek`

For these providers, the manual source is usually the logged-in website session, cookie export, or local browser profile storage. The exact extraction path depends on the provider.

## API Providers

These providers use official or public API keys rather than browser cookies:

- `Google AI Studio / Gemini API`
- `Inflection / Pi API`
- `Pi Web Local`
- `UncloseAI`

`Pi Web Local` is local-only and should not be pushed to Vercel.

`Google AI Studio Web` is intentionally separate from the official `Google AI Studio / Gemini API` provider. It uses private `MakerSuiteService` RPCs from the browser UI. `CountTokens` can be replayed with Google cookies and a fresh `SAPISIDHASH`; `GenerateContent` additionally requires `GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE`, because the private request slot `4` is a browser-captured capability/attestation blob that may be bound to the exact request content and session.

## Chat2API Integration

The project is already wired to the local Chat2API desktop storage layout:

- `%APPDATA%\chat2api\Partitions\oauth-*`

`scripts/get-provider-creds.py` reads those partitions automatically and can recover:

- `ZAI_TOKEN`
- `DEEPSEEK_TOKEN`
- `KIMI_TOKEN` / `refresh_token`
- `GEMINI_WEB_COOKIE` / `GEMINI_WEB_SECURE_1PSID` / `GEMINI_WEB_SECURE_1PSIDTS`
- `MIMO_COOKIE` / `MIMO_SERVICE_TOKEN` / `MIMO_USER_ID` / `MIMO_PH_TOKEN`
- `QWEN_AI_COOKIE` / `QWEN_AI_TOKEN`
- `INCEPTION_COOKIE` / `INCEPTION_SESSION_TOKEN`
- `PERPLEXITY_COOKIE` / `PERPLEXITY_SESSION_TOKEN`

Inception uses a separate browser-profile extractor:

- `scripts/launch-inception-auth.ps1`
- `scripts/get-inception-creds.py`

The extractor stores `INCEPTION_COOKIE` and `INCEPTION_SESSION_TOKEN` in `auth\inception-creds.json`, which `scripts/redeploy-vercel.ps1 -SyncEnv` can push into Vercel.
When Inception is routed through Cloudflare, `stream` is stripped before the request leaves Vercel so the upstream always receives a non-streaming request.

LongCat uses a separate browser-profile extractor:

- `scripts/launch-longcat-auth.ps1`
- `scripts/get-longcat-creds.py`

The extractor stores `LONGCAT_COOKIE` in `auth\longcat-creds.json`, which `scripts/redeploy-vercel.ps1 -SyncEnv` can push into Vercel.

Mistral uses a separate browser-profile extractor:

- `scripts/launch-mistral-auth.ps1`
- `scripts/get-mistral-creds.py`

The extractor stores `MISTRAL_COOKIE` and `MISTRAL_CSRF_TOKEN` in `auth\mistral-creds.json`, which `scripts/redeploy-vercel.ps1 -SyncEnv` can push into Vercel.

Google AI Studio Web uses a network-dump extractor:

- `scripts/get-google-ai-studio-web-creds.py`

The extractor reads a browser cookie export plus a "Copy as fetch" dump, then stores `GOOGLE_AI_STUDIO_WEB_*` values in `auth\google-ai-studio-web-creds.json`, which `scripts/redeploy-vercel.ps1 -SyncEnv` can push into Vercel.

That is the preferred automatic path when the local Chat2API session already contains a logged-in provider.

## Manual Sources

Manual sources by provider:

- `Z.ai` - logged-in `chat.z.ai` session or JWT export
- `DeepSeek` - logged-in `chat.deepseek.com` session
- `Arcee` - bearer token from the `api.arcee.ai` `access_token` cookie
- `Gemini Web` - `gemini.google.com` login cookies
- `Google AI Studio Web` - `aistudio.google.com` Google cookies plus a captured `GenerateContent` request body/template when generation is needed
- `Google AI Studio / Gemini API` - official API key from `https://aistudio.google.com/app/apikey`
- `Grok` - `grok.com` cookies
- `OpenAI Web` - `chatgpt.com` session token and cookies
- `Qwen International` - `chat.qwen.ai` cookies
- `Inception` - `chat.inceptionlabs.ai` cookies and session token
- `LongCat` - `longcat.chat` cookies
- `Mistral` - `console.mistral.ai` cookies and optional CSRF token
- `Perplexity` - `perplexity.ai` cookies
- `Phind` - `phindai.org` cookies plus nonce
- `Mimo` - `xiaomimimo.com` / `aistudio.xiaomimimo.com` cookies and tokens
- `Kimi` - `www.kimi.com` access token
- `Inflection / Pi API` - developer key from Inflection
- `Pi Web Local` - local browser profile only
- `UncloseAI` - no credentials

## Agent Picks

Best native-tool picks:

- `google-ai-studio`
- `ai-studio-pro`
- `pi-api`
- `uncloseai-hermes`
- `uncloseai-gpt-oss`
- `uncloseai-r1-distill`

Best prompt-shim picks when you want to reuse existing browser/session providers:

- `glm-5-agent` or `glm-5.1-agent` for Z.ai
- `Qwen3-Coder` for coding-oriented Qwen sessions
- `devstral-2512` or `codestral-2508` for Mistral sessions
- `gemini-3-flash-thinking` or `gemini-3-pro` for Gemini Web sessions

The prompt shim makes these providers usable in OpenAI-compatible agent clients, but it is still prompt-based. Native-tool providers remain more reliable for long tool-heavy loops.

## Image Inputs

- `Google AI Studio / Gemini API` receives OpenAI-style `image_url` / Responses `input_image` content natively. Data URLs and ordinary HTTPS image URLs are converted to Gemini inline image parts.
- `uncloseai-qwen-vl` is advertised as a native vision model and receives the original OpenAI-style image payload.
- Other providers are text-only at the upstream layer. When `GOOGLE_AI_STUDIO_API_KEY` / `GEMINI_API_KEY` is configured, `py/multimodal.py` asks Gemini to describe each image and injects those descriptions into the text prompt before forwarding the request.
- Set `MULTIMODAL_IMAGE_MODE=placeholder` to inject image references without calling Gemini for captions, or `MULTIMODAL_IMAGE_MODE=off` to disable proxy-side image rewriting.
- Useful optional controls: `MULTIMODAL_MAX_IMAGES`, `MULTIMODAL_CAPTION_MODEL`, `MULTIMODAL_CAPTION_PROMPT`, `MULTIMODAL_CAPTION_MAX_OUTPUT_TOKENS`, and `GOOGLE_AI_STUDIO_FETCH_IMAGE_URLS`.
