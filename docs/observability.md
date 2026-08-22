# Observability and Troubleshooting

The local server, Vercel entrypoint, and Cloudflare Worker emit one JSON object per log event. Every request gets a `request_id`; a valid incoming `X-Request-ID` is preserved, otherwise an ID such as `req_<uuid>` is generated. JSON responses and streaming error events return the same ID in `X-Request-ID` or `error.request_id`.

## Log levels

Set `PROXY_LOG_LEVEL` to one of:

- `debug`: request lifecycle plus provider/upstream diagnostics from existing adapters.
- `info`: request start/finish and stream lifecycle events.
- `warning`: warnings only.
- `error`: errors with exception type and traceback.
- `off`: disable proxy logs (the default when no flag is configured).

`DEBUG_LOGGING=1` remains supported for compatibility and is equivalent to `PROXY_LOG_LEVEL=debug` when `PROXY_LOG_LEVEL` is unset. `PROXY_LOG_LEVEL` takes precedence.

PowerShell example:

```powershell
$env:PROXY_LOG_LEVEL = "debug"
npm run dev
```

## Correlating a failing request

Send a stable ID from the client:

```powershell
curl.exe -H "X-Request-ID: risu-test-42" http://127.0.0.1:3001/v1/health
```

Look for the same `request_id` in `http_request_started`, provider debug events, `http_stream_aborted` or error events, and `http_request_finished`. Lifecycle entries include method, path/route, provider, model, streaming mode, chunk count, status, and duration.

Unexpected non-stream errors return a generic message and the request ID rather than an upstream exception. For streams that have already started, the proxy emits one final SSE `error` object containing a safe message, error type, and `request_id` before closing when the client connection is still writable.

For deployment-specific checks, filter the provider report by runtime:

```text
GET /v1/providers?runtime=local
GET /v1/providers?runtime=vercel
GET /doctor?runtime=cloudflare
```

The filter only changes which manifest entries are reported; it never changes
credential resolution or exposes secret values.

## Redaction

Headers are logged as names plus a boolean indicating whether common sensitive headers were present. Recursive redaction covers authorization, cookies, API keys, tokens, sessions, captcha/Turnstile values, credentials, and similar fields. Secret values are replaced by a length and a short SHA-256 fingerprint, which is useful for detecting accidental credential rotation without exposing the credential itself. Prompt and response bodies are never logged by the lifecycle logger.

For rare malformed upstream responses, set `PROXY_LOG_UPSTREAM_PREVIEW=1`. The Cloudflare adapter then includes at most 500 redacted characters in `upstream_response.body_preview`, together with status, content type, and byte length. Keep this flag temporary: upstream text can still contain user-provided content even after credential redaction.

## Request size guard

`PROXY_MAX_BODY_BYTES` limits JSON request bodies. The default is 8 MiB; set it to `0` to disable the limit. Oversized bodies are rejected before provider code runs.

## Metrics and bridge health

Authenticated `GET /metrics` returns a bounded JSON snapshot. Send `Accept: text/plain`
for Prometheus text. Labels are limited to provider, status and streaming mode; prompt
content, credentials and arbitrary model strings are never emitted. `GET /v1/bridges`
reports local Grok and LM Arena bridge health and ownership without exposing process
arguments or cookies.

```powershell
$env:PROXY_MAX_BODY_BYTES = "16777216"
```
