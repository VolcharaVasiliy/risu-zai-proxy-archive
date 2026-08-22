# Credentials Exporter (extension for risu-zai-proxy)

Collects cookies and tokens from all providers and exports a ready-to-use
`credentials.json` for `risu-zai-proxy` — replacing the manual fiddling with
`scripts/get-*-creds.py` and browser SQLite databases.

## Installation

1. Open `chrome://extensions` and enable Developer mode. The extension targets Chromium MV3; Firefox support is experimental because `chrome.debugger` and MV3 service-worker behavior differ.
2. "Load unpacked" → select this folder.

## Usage

1. Sign in to the provider accounts on their websites (important: the same
   profiles/browsers the cookies come from — the extension reads cookies from the
   browser it is installed in).
2. Click "Scan" in the extension popup.
3. Open the preview, click "Download credentials.json" and place the file in the
   repository root.

### Interface

- **Language switcher** (EN / РУ / 中文) sits in the top-right of the popup and
  switches every label instantly — no need to change the browser locale. The
  choice is remembered per installation.
- **Provider table** lists each provider as a row with a status dot
  (grey = idle, orange pulse = scanning, green = captured, red = failed) and a
  short detail line. Click a row to open that provider's site.
- **Panels** (Manual API keys, credentials.json preview) expand and collapse with
  a smooth animation.

### localStorage providers

Z.ai, DeepSeek, Qwen, ChatGLM and Kimi store tokens not in cookies but in
localStorage. For these, open the site in a tab and click "Scan" again — the
extension reads the active tab's localStorage (requires the `scripting`
permission).

### API keys

AI Studio (GOOGLE_AI_STUDIO_API_KEY) is entered manually in the popup (AIza...).

### AI Studio Web (private RPC)

The `google-ai-studio-web` provider works through the browser's private RPCs.
Cookies (`GOOGLE_AI_STUDIO_WEB_COOKIE`) are collected automatically from
`aistudio.google.com`. To generate content you additionally need a captured
request-body template `GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE` — open any
`GenerateContent` request in DevTools, choose "Copy as fetch" and paste **only the
body** (JSON) into the "AI Studio Web — GenerateContent template" field in the
popup. For `CountTokens`, cookies alone are sufficient.

## What maps to what

| Provider | Domain | credentials.json keys |
| --- | --- | --- |
| Z.ai (GLM) | chat.z.ai | ZAI_TOKEN (localStorage `token` / cookie `access_token`) |
| DeepSeek | chat.deepseek.com | DEEPSEEK_TOKEN (localStorage `userToken`) |
| Arcee | api.arcee.ai | ARCEE_ACCESS_TOKEN (cookie `access_token`), ARCEE_REFRESH_TOKEN |
| Gemini Web | gemini.google.com | GEMINI_WEB_COOKIE, GEMINI_WEB_SECURE_1PSID, GEMINI_WEB_SECURE_1PSIDTS |
| Google AI Studio | — | GOOGLE_AI_STUDIO_API_KEY (manual) |
| AI Studio Web | aistudio.google.com | GOOGLE_AI_STUDIO_WEB_COOKIE (cookies), GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE (RPC template, manual) |
| Grok | grok.com | GROK_COOKIE |
| Kimi | www.kimi.com | KIMI_TOKEN, KIMI_REFRESH_TOKEN |
| Inception | chat.inceptionlabs.ai | INCEPTION_COOKIE, INCEPTION_SESSION_TOKEN (cookie `session`) |
| LongCat | longcat.chat | LONGCAT_COOKIE |
| Mistral | console.mistral.ai | MISTRAL_COOKIE, MISTRAL_CSRF_TOKEN (cookie `csrf_token_*`) |
| MiMo | aistudio.xiaomimimo.com / xiaomimimo.com | MIMO_SERVICE_TOKEN, MIMO_USER_ID, MIMO_PH_TOKEN, MIMO_COOKIE |
| ChatGPT | chatgpt.com | OPENAI_WEB_COOKIE, OPENAI_WEB_ACCESS_TOKEN (from `/api/auth/session`), OPENAI_WEB_SENTINEL_TURNSTILE (captured `openai-sentinel-turnstile-token` header) |
| Perplexity | www.perplexity.ai | PERPLEXITY_COOKIE, PERPLEXITY_SESSION_TOKEN (`__Secure-next-auth.session-token`) |
| Phind | phindai.org (primary), www.phind.com | PHIND_COOKIE, PHIND_NONCE (from `phindai.org/phind-chat/` HTML) |
| Qwen | chat.qwen.ai / qwen.ai | QWEN_AI_COOKIE, QWEN_AI_TOKEN, QWEN_AI_BX_* (header capture) |

### Qwen bx-* are session/IP-bound

The `QWEN_AI_BX_*` headers are captured passively by the extension from your
browser. Qwen rejects them with `RGV587_ERROR` when the proxy runs on a different
network than the one that captured them (e.g. Vercel's fixed server IP). The
popup shows how long ago the bx-* were captured; if they are older than ~30
minutes a warning explains how to re-capture them from `chat.qwen.ai` while
connected through the same egress the proxy uses.
| ChatGLM | chatglm.cn | GLM_REFRESH_TOKEN (cookie/localStorage `chatglm_refresh_token`) |
| Inflection | developers.inflection.ai | INFLECTION_API_KEY (manual) |

Only filled keys end up in `credentials.json` — empty values are not exported, so
the file stays clean. The Diagnostics action deliberately reports header names,
ages, domains and counts, never captured header values.

## Contents

- `manifest.json` — Manifest V3, permissions: cookies, scripting, storage, clipboardWrite, activeTab.
- `popup.html` / `popup.css` / `popup.js` — UI and collection logic.
