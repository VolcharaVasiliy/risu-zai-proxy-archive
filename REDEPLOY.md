# Repeat Deploy

This file is a short entry point for deployment operations.

For the full environment map, manual credential sources, and automatic extractors, read [docs/deployment.md](docs/deployment.md).

For provider-by-provider details, read [docs/providers.md](docs/providers.md).

## Main Commands

Auto-extract credentials from local storage and Chat2API partitions:

```powershell
python .\scripts\get-provider-creds.py
```

Extract the Mistral browser session into `auth\mistral-creds.json`:

```powershell
python .\scripts\get-mistral-creds.py --profile-root .\auth\mistral-edge-profile --output .\auth\mistral-creds.json
```

Extract the LongCat browser session into `auth\longcat-creds.json`:

```powershell
python .\scripts\get-longcat-creds.py --profile-root .\auth\longcat-edge-profile --output .\auth\longcat-creds.json
```

Deploy to Vercel with env sync:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\redeploy-vercel.ps1 -SyncEnv
```

## Agent Route Notes

- `/v1/chat/completions` is the regular chat path.
- `/v1/responses` and `/v1/responses/chat/completions` are the agent-facing paths.
- `/doctor` and `/v1/providers` are read-only diagnostics endpoints; they report
  readiness and missing credential names, never secret values.
- Pass a stable `X-Request-ID` when troubleshooting a client request; it is
  echoed in the response and structured logs.
- Native function-tool loops are supported by `google-ai-studio`, `pi-api`, and `uncloseai-*`.
- Other providers use the prompt tool shim by default with `AGENT_TOOL_MODE=auto`; set `AGENT_TOOL_MODE=off` if you want them to fail fast instead.

## Automatic Sources

The project is already connected to the local Chat2API desktop storage layout at:

- `%APPDATA%\chat2api\Partitions\oauth-*`

That layout is read by `scripts/get-provider-creds.py`, which can populate many provider env vars automatically without manual copying.

Other provider-specific automation lives in:

- `scripts/get-arcee-creds.py`
- `scripts/get-qwen-creds.py`
- `scripts/launch-grok-auth.ps1`
- `scripts/get-grok-creds.py`
- `scripts/launch-openai-auth.ps1`
- `scripts/get-openai-web-creds.py`
- `scripts/launch-gemini-auth.ps1`
- `scripts/get-gemini-web-creds.py`
- `scripts/launch-inception-auth.ps1`
- `scripts/get-inception-creds.py`
- `scripts/launch-longcat-auth.ps1`
- `scripts/get-longcat-creds.py`
- `scripts/launch-mistral-auth.ps1`
- `scripts/get-mistral-creds.py`
- `scripts/launch-phind-auth.ps1`
- `scripts/get-phind-creds.ps1`
- `scripts/launch-pi-auth.ps1`
- `scripts/pi-browser-bridge.mjs`
