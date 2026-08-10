# Credentials Exporter (расширение для risu-zai-proxy)

Собирает куки и токены со всех провайдеров и выгружает готовый `credentials.json`
для `risu-zai-proxy` — заменяет ручные манипуляции с `scripts/get-*-creds.py`
и SQLite-базами браузеров.

## Установка

1. Откройте `chrome://extensions` (в Firefox — `about:debugging#/runtime/this-firefox`).
2. Включите «Режим разработчика».
3. «Загрузить распакованное» → выберите эту папку.

## Использование

1. Зайдите и войдите в аккаунты на сайтах провайдеров (важно: те же профили/браузеры,
   из которых берутся куки — расширение читает куки браузера, в котором установлено).
2. Нажмите «Сканировать» в попапе расширения.
3. Откройте предпросмотр, нажмите «Скачать credentials.json» и положите файл
   в корень репозитория.

### localStorage-провайдеры

Z.ai, DeepSeek, Qwen, ChatGLM и Kimi хранят токены не в куках, а в localStorage.
Для них откройте сайт во вкладке и нажмите «Сканировать» повторно — расширение
прочитает localStorage активной вкладки (нужно разрешение `scripting`).

### API-ключи

AI Studio (GOOGLE_AI_STUDIO_API_KEY) вводится вручную в попапе (AIza...).

## Что во что маппится

| Провайдер | Домен | Ключи credentials.json |
|---|---|---|
| Z.ai (GLM) | chat.z.ai | ZAI_TOKEN (localStorage `token` / кука `access_token`) |
| DeepSeek | chat.deepseek.com | DEEPSEEK_TOKEN (localStorage `userToken`) |
| Arcee | api.arcee.ai | ARCEE_ACCESS_TOKEN (кука `access_token`) |
| Gemini Web | gemini.google.com | GEMINI_WEB_COOKIE (все куки; 1PSID/1PSIDTS прокси вытаскивает сам) |
| AI Studio | — | GOOGLE_AI_STUDIO_API_KEY (вручную) |
| Grok | grok.com | GROK_COOKIE |
| Kimi | www.kimi.com | KIMI_TOKEN (localStorage `access_token` / кука `access_token`) |
| Inception | chat.inceptionlabs.ai | INCEPTION_COOKIE, INCEPTION_SESSION_TOKEN (кука `session`) |
| LongCat | longcat.chat | LONGCAT_COOKIE |
| Mistral | console.mistral.ai | MISTRAL_COOKIE, MISTRAL_CSRF_TOKEN (кука `csrf_token_*`) |
| MiMo | aistudio.xiaomimimo.com / xiaomimimo.com | MIMO_SERVICE_TOKEN, MIMO_USER_ID, MIMO_PH_TOKEN, MIMO_COOKIE |
| ChatGPT | chatgpt.com | OPENAI_WEB_COOKIE, OPENAI_WEB_ACCESS_TOKEN (из `/api/auth/session`) |
| Perplexity | www.perplexity.ai | PERPLEXITY_COOKIE, PERPLEXITY_SESSION_TOKEN (`__Secure-next-auth.session-token`) |
| Phind | phindai.org (основной), www.phind.com | PHIND_COOKIE, PHIND_NONCE (из HTML `phindai.org/phind-chat/`) |
| Qwen | chat.qwen.ai / qwen.ai | QWEN_AI_COOKIE, QWEN_AI_TOKEN (кука `token` / localStorage `Qwen-Max-User-Info`) |
| ChatGLM | chatglm.cn | GLM_REFRESH_TOKEN (кука/localStorage `chatglm_refresh_token`) |

Пустые ключи (INFLECTION_*, PI_LOCAL_TOKEN, QWEN_AI_BX_*, UNCLOSEAI_*) остаются
в файле пустыми — так файл совместим со структурой репозитория.

## Состав

- `manifest.json` — Manifest V3, permissions: cookies, scripting, storage, clipboardWrite, activeTab.
- `popup.html` / `popup.css` / `popup.js` — интерфейс и логика сбора.
