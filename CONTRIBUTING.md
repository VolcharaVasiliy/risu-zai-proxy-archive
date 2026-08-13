# Contributing

Thanks for helping with risu-zai-proxy. This is a small, pragmatic project — keep changes focused and minimal.

## Setup

Follow the [Quick Start (Windows)](../README.md#quick-start-on-windows) in the README, or the equivalent manual steps for your OS:

```powershell
npm run deps:py   # install Python deps into local pydeps
npm run dev       # local proxy on http://127.0.0.1:3001/v1
npm run check     # run checks
```

## Before you open a PR

- Run `npm run check`.
- Keep `credentials.json` and other secrets **out** of commits (they are git-ignored).
- Repo docs are English; localized READMEs (`README.ru.md`, `README.zh.md`) mirror `README.md` — update all three when you change user-facing docs.
- Prefer small, descriptive commits (imperative summary, e.g. `qwen: clarify RGV587_ERROR`).

## Structure

- `py/` — provider modules and the registry.
- `api/`, `src/` — the OpenAI-compatible server.
- `scripts/` — credential helpers and launchers.
- `extensions/credentials-exporter/` — the browser extension.
- `docs/` — provider and deployment reference.
