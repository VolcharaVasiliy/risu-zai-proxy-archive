# Repeat Deploy

This file is a short entry point for deployment operations.

For the full environment map, manual credential sources, and automatic extractors, read [docs/deployment.md](docs/deployment.md).

For provider-by-provider details, read [docs/providers.md](docs/providers.md).

## Main Commands

Auto-extract credentials from local storage and Chat2API partitions:

```powershell
F:\DevTools\Python311\python.exe F:\Projects\risu-zai-proxy\scripts\get-provider-creds.py
```

Extract the Mistral browser session into `auth\mistral-creds.json`:

```powershell
F:\DevTools\Python311\python.exe F:\Projects\risu-zai-proxy\scripts\get-mistral-creds.py --profile-root F:\Projects\risu-zai-proxy\auth\mistral-edge-profile --output F:\Projects\risu-zai-proxy\auth\mistral-creds.json
```

Deploy to Vercel with env sync:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\Projects\risu-zai-proxy\scripts\redeploy-vercel.ps1 -SyncEnv
```

## Automatic Sources

The project is already connected to the local Chat2API desktop storage layout at:

- `%APPDATA%\chat2api\Partitions\oauth-*`

That layout is read by `scripts/get-provider-creds.py`, which can populate many provider env vars automatically without manual copying.

Other provider-specific automation lives in:

- `scripts/launch-grok-auth.ps1`
- `scripts/get-grok-creds.py`
- `scripts/launch-openai-auth.ps1`
- `scripts/get-openai-web-creds.py`
- `scripts/launch-gemini-auth.ps1`
- `scripts/get-gemini-web-creds.py`
- `scripts/launch-inception-auth.ps1`
- `scripts/get-inception-creds.py`
- `scripts/launch-mistral-auth.ps1`
- `scripts/get-mistral-creds.py`
- `scripts/launch-phind-auth.ps1`
- `scripts/get-phind-creds.ps1`
- `scripts/launch-pi-auth.ps1`
- `scripts/pi-browser-bridge.mjs`
