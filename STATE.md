## Objective
- P1: make Grok work behind Cloudflare. Root cause: generation only happens over xAI Realtime WebSocket (`wss://grok.com/ws/mgw`), which Cloudflare blocks for any server-side client (REST `POST /rest/app-chat/conversations/new` + `/responses` → 403; Python `websockets` WS upgrade → 403; only the in-page browser WebSocket passes). Decision path: tried to replicate WebSocket (blocked by Cloudflare TLS) → fell back to browser transport via an in-page WS bridge. DONE & verified. Part of P1–P5.

## Important Details
- User rule: always ask on choice; picks most reliable.
- Repo `C:\Users\gamer\Documents\Default Project\risu-zai-proxy-repo`; GitHub `VolcharaVasiliy/risu-zai-proxy-archive`; OpenAI Web work pushed `faab25f` earlier (that task complete).
- Vercel team `xlebs-projects`, project `risu-zai-proxy-archive`, alias `https://risu-zai-proxy-archive-eight.vercel.app`; open auth; `DEBUG_LOGGING=1`. Grok is **local-only** (Cloudflare `cf_clearance` IP-bound) → does NOT work on Vercel (proxy returns clear "bridge unreachable" error).
- Edge at `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`. `playwright-core` + `curl_cffi`(0.13) + `websockets`(17) in `pydeps`.
- Proxy `http://127.0.0.1:7897` (Clash). `curl_cffi` REST reaches grok.com fine (cookies valid); Python `websockets` WS upgrade is blocked by Cloudflare (403).
- `credentials.json` `GROK_COOKIE` (no cf_clearance). `grok_cf_clearance.json` holds `{cf_clearance, cookie, captured_at}` — full grok.com cookie set captured by grabber.
- xAI Realtime WS protocol (verified): `wss://grok.com/ws/mgw/?uid=<x-userid>` → `session.create` (model) → `conversation.attached` → `conversation.item.create` (input_chunks) → `response.create` (NO `castle_request_token` needed for in-page WS) → streamed `response.chunk` with `chunk.text.text`. `uid` = `x-userid` cookie.

## Work State
### Completed
- OpenAI Web stable (faab25f).
- Grok via **browser bridge** (user-approved fallback):
  - `scripts/grok-ws-bridge.mjs`: launches logged-in Edge (headless default), opens in-page WS to `wss://grok.com/ws/mgw`, relays streamed tokens as SSE at `POST http://127.0.0.1:8771/chat`; `GET /health`. Auto re-logs-in + re-runs `fetch-grok-cf-clearance.mjs` when `cf_clearance` missing/expired. Env: `GROK_BRIDGE_PORT`(8771), `GROK_BRIDGE_HEADLESS`(true), `GROK_CF_CLEARANCE_PROXY`.
  - `py/grok_proxy.py`: `_grok_bridge_enabled()` (auto/on/off; default auto+localhost:8771), `_bridge_post`, `_bridge_parse`, `_bridge_stream_chunks`, `_bridge_complete_non_stream`. `stream_chunks`/`complete_non_stream` route to bridge when enabled. Old REST `chat_completion` kept as dead fallback.
  - `docs/providers.md`: Grok row + new "Grok browser bridge" section updated.
- Live verified: `complete_non_stream` + `stream_chunks` + `provider_registry.complete_non_stream('grok',...)` all return correct OpenAI SSE (tested `fast`, `grok-3-mini` → "Hi"). Bridge process running (pid ~33088).

### Active
- `scripts/grok-ws-bridge.mjs` must be running for Grok to work locally. It is currently running as a detached background process.

### Blocked / deferred
- Grok on Vercel: impossible (Cloudflare IP-binding). Documented.

### Blocked / deferred
- P4 Mimo: mechanism implemented, cannot verify from this machine.

## Mimo (P4) — mechanism done, needs China egress to verify
- Symptom on Vercel: response comes back as `?????` / `服务器繁忙` (server busy) — a **region guard at the CDN/edge level**, not a decode bug. `aistudio.xiaomimimo.com` is China-only and serves `?????` from non-China edges.
- Fix (primary, infra-free): pin Mimo to a **China edge IP** via `MIMO_RESOLVE_IPS` (curl_cffi `CurlOpt.RESOLVE`) — this is exactly what Smart DNS does (resolve the domain to the China IP so the request lands on the China edge and the guard passes). `MIMO_PROXY` (China egress, fallback to global `HTTPS_PROXY`/`HTTP_PROXY`) is the alternative if the guard is also source-IP based. Both wired into curl_cffi + requests in `py/mimo_proxy.py`. Decode already tries utf-8 → gbk/gb18030 → big5.
- Cannot test locally: direct egress from RU is geo-blocked (connect fails), and curl_cffi over Clash hits a TLS error (curl:35, Clash MITM quirk) — both are environment limits, not code bugs. To verify: set `MIMO_RESOLVE_IPS` to the China IP that Smart DNS returns for `aistudio.xiaomimimo.com` (or `MIMO_PROXY` to a China egress).
- Updated `docs/providers.md` (Mimo row) + `docs/deployment.md` (Mimo env) to document `MIMO_PROXY` and the China-only nature.

## Next Move
1. (Optional) Add `npm`/`package.json` script or a launcher for the Grok bridge; consider auto-starting it with the proxy.
2. P4 Mimo: set `MIMO_PROXY` (China egress) on Vercel + locally, then verify `complete_non_stream`/`stream_chunks` return real Chinese text (not `?????`).

## Arcee (P2) — DONE
- Root cause: `ARCEE_ACCESS_TOKEN` JWT expired (~2.4 d). The token is NOT in cookies/localStorage — it lives in the SPA memory and is minted by `POST /app/v1/oauth/google` on login (auth is Google OAuth). The old `ARCEE_COOKIE` (AWSALB/__cf_bm/ph_/g_state) is only LB/cloudflare stickiness, not auth.
- Fix: `scripts/fetch-arcee-token.mjs` drives a **persistent Edge profile** (`.arcee-edge-profile/`, gitignored), intercepts the `oauth/google` response (body JWT or `Set-Cookie access_token`), and writes the token to `ARCEE_ACCESS_TOKEN` + `arcee_access_token.json` (gitignored). User logs in once via Google; profile persists so re-runs usually auto-login.
- Verified: `complete_non_stream` + `stream_chunks` return correct answers (e.g. "Hello", "1, 2, 3"). `POST /app/v1/refresh` works with a valid token (1h token) → `py/arcee_proxy._ensure_fresh_token` auto-refreshes during active use. After long idle the token expires; re-run the capture script (persistent Google session → usually no code re-entry).
- Updated `docs/providers.md` Arcee row. `credentials.json` holds the fresh token locally (NOT committed — secrets). For Vercel set `ARCEE_ACCESS_TOKEN` env.
- `.gitignore` extended with `.arcee-edge-profile/` and `arcee_access_token.json`.

## Relevant Files
- `scripts/grok-ws-bridge.mjs` — NEW browser WS relay (the working Grok transport).
- `scripts/fetch-grok-cf-clearance.mjs` — grabber (auto-invoked by bridge).
- `scripts/probe-grok-ws.mjs`, `probe-grok-inpage-ws.mjs`, `test_grok_ws.py` — PoC probes (test_grok_ws.py confirms Python WS is Cloudflare-blocked).
- `py/grok_proxy.py` — bridge routing added (lines ~46-48, ~395-605).
- `py/grok_cf_clearance.py` — clearance manager (unchanged, used by bridge for refreshes).
- `docs/providers.md` — Grok row + "Grok browser bridge" section.
- `grok_cf_clearance.json`, `grok-ws-frames.json` — captured data.
- `api/index.py` / `py/provider_registry.py` — call `grok_proxy.complete_non_stream`/`stream_chunks` (unchanged signatures).
- `F:\downloads\сессия-2026-08-11-вечер.md` — P1–P5 tasks.
