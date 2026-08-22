# Project Status

This file is a short, repository-safe status snapshot. It intentionally omits
local paths, process IDs, captured credentials, deployment aliases, and other
machine-specific details. Use git history and the issue tracker for long-lived
investigation notes.

## Current Architecture

- Python local server and Vercel entrypoint expose the OpenAI-compatible API.
- `py/provider_registry.py` is the source of truth for provider metadata,
  models, runtime support, and readiness diagnostics.
- `py/observability.py` provides structured JSON lifecycle logs, request IDs,
  redaction, body limits, and streaming error diagnostics.
- `cloudflare/worker.mjs` is the edge fallback for the providers documented as
  Cloudflare-compatible (currently Inception-focused).

## Supported Diagnostics

- `GET /health` is a lightweight liveness check.
- `GET /doctor` returns a compact readiness summary.
- `GET /v1/providers` returns provider/model/runtime metadata and missing
  credential names, never credential values.
- `PROXY_LOG_LEVEL=debug` enables detailed structured logs. Correlate requests
  with `X-Request-ID`.

## Verification

Run `npm run check` before publishing changes. It covers Python compilation,
Node and Cloudflare syntax, provider and observability tests, Codex catalog
generation, and Markdown consistency checks. Keep provider-specific live smoke
tests separate because browser sessions, region routing, and upstream limits
are external state.

## Known Constraints

- Browser-session providers can be local-only when cookies, CAPTCHA, or
  clearance tokens are bound to the solving browser or egress IP.
- Serverless response/session state is in-memory and may not survive a restart.
- Provider upstream protocols change independently; keep adapters isolated and
  add focused contract tests when changing one.
