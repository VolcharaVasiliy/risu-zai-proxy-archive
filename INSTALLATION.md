# Установка и запуск risu-zai-proxy (пошагово)

> Что это: OpenAI-совместимый прокси-агрегатор. Один локальный сервер отдаёт
> `/v1/chat/completions` и `/v1/models`, а внутри умеет ходить в десяток
> «закрытых» провайдеров (Z.ai, Grok, LM Arena, Gemini Web, GLM Web,
> Inflection/Pi, Arcee, Google AI Studio и др.).
>
> Ниже — установка «от и до» с готовыми командами. Каждый шаг можно выполнять
> по порядку; если шаг помечен «только Windows» — для macOS/Linux дан аналог.

---

## 0. Что нужно поставить (prerequisites)

- **Git** — любой свежий.
- **Node.js 20+** — проверить: `node -v`.
- **Python 3.11+** в `PATH` — проверить: `python --version`.
- (Опц.) **Cloudflare Wrangler** — только если будете поднимать Cloudflare-fallback: `npm i -g wrangler`.
- Доступ в интернет; для части провайдеров нужен системный HTTP(S)-прокси
  (задаётся переменной `HTTPS_PROXY`).

---

## 1. Клонировать репозиторий

```powershell
git clone https://github.com/VolcharaVasiliy/risu-zai-proxy-archive.git
cd risu-zai-proxy-archive
```

---

## 2. Установить зависимости

### Вариант А — установщик (Windows, рекомендуется)

```powershell
npm run setup:windows
```

Он ставит Python-зависимости из `requirements.txt`, делает `npm install` и
готовит шаблон конфигурации.

### Вариант Б — вручную (Windows / macOS / Linux)

```powershell
# Python-зависимости
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate         # macOS / Linux

pip install -r requirements.txt

# Node-зависимости
npm install
```

---

## 3. Настроить переменные окружения

Конфигурация — только через переменные окружения. Файл `.env` не обязателен,
но вы можете экспортировать переменные в shell или задать их системно.

Минимум для запуска — ключ, под которым клиенты обращаются к прокси:

```powershell
$env:PROXY_API_KEY = "придумайте-свой-секретный-ключ"
```

Локально на `127.0.0.1` сервер поднимется и без ключа (для тестов), но для
реального использования ключ обязателен.

Ключи отдельных провайдеров задаются либо переменными вида
`<PROVIDER>_API_KEY` / `<PROVIDER>_TOKEN`, либо передаются в заголовке запроса
`x-<provider>-api-key: ...`. Полный список — в `docs/providers.md`.

---

## 4. Запустить сервер

Локально (Python-сервер через Node-раннер):

```powershell
npm run dev
# альтернатива напрямую:
# node ./scripts/run-python.mjs ./py/server.py
```

Чисто Node-сервер (альтернатива):

```powershell
npm run dev:node
```

Сервер поднимается на `http://127.0.0.1:3001` (поменять через `HOST` / `PORT`).

---

## 5. Проверить, что сервер живой

```powershell
curl http://127.0.0.1:3001/health
```

Ожидаемый ответ: `200 OK` (тело вида `{"status":"ok", ...}`).

---

## 6. Посмотреть список моделей

```powershell
curl http://127.0.0.1:3001/v1/models `
  -H "Authorization: Bearer $env:PROXY_API_KEY"
```

---

## 7. Сделать первый запрос

Через `curl` (модель Z.ai):

```powershell
curl http://127.0.0.1:3001/v1/chat/completions `
  -H "Authorization: Bearer $env:PROXY_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"zai:glm-4.5v","messages":[{"role":"user","content":"Привет, кто ты?"}]}'
```

Тот же запрос из Python (openai SDK):

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:3001/v1",
    api_key="придумайте-свой-секретный-ключ",
)

resp = client.chat.completions.create(
    model="zai:glm-4.5v",
    messages=[{"role": "user", "content": "Привет, кто ты?"}],
)
print(resp.choices[0].message.content)
```

---

## 8. Быстрый старт LM Arena (локальный провайдер)

LM Arena требует cookie с `arena.ai` и решает reCAPTCHA Enterprise v3.
Настроено так, чтобы вы делали минимум действий — прокси сам откроет одно
окно браузера (bridge), сходит за токеном и закроет его при выходе.

1. Залогиньтесь на https://arena.ai в браузере.
2. Экспортируйте cookie (например, через расширение «credentials-exporter»,
   см. `extensions/credentials-exporter/`) в файл, скажем
   `C:\Users\gamer\Desktop\lmarena-cookie.txt`.
3. Укажите путь к cookie (bridge-режим по умолчанию уже `auto`):

```powershell
$env:LM_ARENA_COOKIE = "C:\Users\gamer\Desktop\lmarena-cookie.txt"
# LM_ARENA_BRIDGE_MODE=auto  (значение по умолчанию, можно не задавать)
```

4. Просто сделайте запрос к модели с префиксом `arena:`:

```powershell
curl http://127.0.0.1:3001/v1/chat/completions `
  -H "Authorization: Bearer $env:PROXY_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"arena:gpt-5.2","messages":[{"role":"user","content":"Расскажи анекдот"}]}'
```

Подробности и env-крутилки (`LM_ARENA_BRIDGE_MODE`, `LM_ARENA_BRIDGE_URL`,
`LM_ARENA_BRIDGE_PORT`) — в разделе «LM Arena reCAPTCHA (Local-Only)» файла
`docs/providers.md`.

---

## 9. Деплой на Vercel (опционально)

- Нажмите Deploy-to-Vercel (кнопка в `docs/deployment.md`), ИЛИ вручную:

```powershell
npm i -g vercel
vercel login
vercel link
vercel env pull .env        # либо задайте переменные в дашборде
vercel deploy --prod
```

- Важно: провайдеры «local-only» (Grok, Z.ai, LM Arena) на Vercel **не
  работают** — их reCAPTCHA/кука привязаны к вашему IP и браузеру. Их
  используют только локально.

---

## 10. Разбор неполадок

- `401` / `403` от провайдера → кука/токен протухли: перелогиньтесь и
  обновите cookie (LM Arena) или обновите API-ключ.
- `recaptcha validation failed` → прокси сам перезапросит токен через bridge,
  но если окно браузера закрыто — запросите заново (bridge поднимется сам при
  следующем запросе, если `LM_ARENA_BRIDGE_MODE != off`).
- `429` → rate-limit у провайдера; подождите немного и повторите.
- Сервер не стартует → проверьте, что `python --version` ≥ 3.11 и
  `node -v` ≥ 20, и что `npm install` завершился без ошибок.

---

## Полезные ссылки

- `docs/providers.md` — матрица провайдеров: какие ключи нужны, флаги local-only.
- `docs/deployment.md` — Vercel env-map, Cloudflare fallback, per-provider deploy notes.
- `README.md` / `README.ru.md` — общее описание и примеры интеграции.
