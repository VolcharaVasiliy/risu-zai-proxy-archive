# risu-zai-proxy

[English](README.md) · [Русский](README.ru.md) · [中文](README.zh.md)

OpenAI-совместимый прокси для RisuAI, Codex, Zed и других клиентов с OpenAI-подобным API. За одной точкой входа `/v1` (включая `/v1/chat/completions` и `/v1/responses`) скрываются множество провайдеров — как на основе браузерных сессий, так и на обычных API-ключах.

Единая точка `/v1` направляет каждую модель через реестр провайдеров к нужному бэкенду — захваченной браузерной сессии, API-ключу или резервному варианту.

[![Развернуть на Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/VolcharaVasiliy/risu-zai-proxy-archive) ![Лицензия](https://img.shields.io/github/license/VolcharaVasiliy/risu-zai-proxy-archive)

## Содержание

- [Что внутри](#что-внутри)
- [Портативная сборка](#портативная-сборка-без-установки-windows-x64)
- [Быстрый старт в Windows](#быстрый-старт-в-windows)
- [Диагностика и логи](#диагностика-и-логи)

## Что внутри

- OpenAI-совместимые маршруты: `/v1/models`, `/v1/providers`, `/v1/chat/completions`, `/v1/responses`, `/health`, `/doctor`
- Поддержка Responses API, готовая для Codex, — `api2codex` для этого прокси не нужен
- Лаунчер `rzai` для запуска Codex через прокси одной короткой командой
- Реестр провайдеров с алиасами, генерацией каталога моделей и очисткой дубликатов для Codex
- Промпт-шим для чат-провайдеров, чтобы модели вроде Qwen/Mistral/Gemini Web всё равно могли задействовать инструменты Codex
- Помощники для учётных данных распространённых браузерных/сессионных провайдеров
- Развёртывание на Vercel, локальный Python-сервер и Cloudflare-резерв для Inception

> **Z.ai работает только локально.** Провайдеру Z.ai нужен Aliyun `captcha_verify_param`, привязанный к публичному IP, с которого был решён капчный токен, поэтому он работает только с хоста, способного запустить `scripts/fetch-zai-captcha.mjs` (локальная машина или VPS с Chromium) — не с Vercel или CI. Подробности и переключатели окружения: `docs/providers.md` → «Z.ai Captcha (Local-Only)».

## Быстрый старт в Windows

Требования:

- Node.js 20+
- Python 3.11+
- Git
- Установленный OpenAI Codex CLI, доступный как `codex`

Из корня репозитория:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

Скрипт установки:

- устанавливает Node-пакеты
- устанавливает Python-зависимости в локальный `pydeps`
- генерирует каталог моделей Codex по пути `%USERPROFILE%\.codex\risu-zai-model-catalog.json`
- устанавливает лаунчеры `rzai` и `risu-zai` в `%USERPROFILE%\.codex\bin`
- добавляет эту папку bin в PATH пользователя, если не указан `-NoPath`
- записывает `%USERPROFILE%\.codex\risu-zai.config.toml`

Откройте новый терминал после изменения PATH и проверьте:

```powershell
rzai -Print
rzai -Local exec --ephemeral -s read-only -a never "reply ok"
```

Использовать другой публичный URL прокси или модель по умолчанию:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 `
  -BaseUrl "https://your-project.vercel.app/v1" `
  -Model "Qwen3.7-Max"
```


## Портативная сборка (без установки, Windows x64)

Хотите просто скачать и запустить без всякой настройки? Возьмите самодостаточный архив на [странице релизов](https://github.com/VolcharaVasiliy/risu-zai-proxy-archive/releases) (файл `risu-zai-proxy-portable-*.zip`). Внутри — портативный Python 3.11 со всеми зависимостями и портативный Node.js: ничего устанавливать не нужно, без `pip` и без изменения PATH, работает с любого диска на чистой Windows.

1. Скачайте и распакуйте архив в любое место (например `D:\risu-zai-proxy`).
2. Дважды кликните `start.bat` (или запустите `start.ps1` в PowerShell).
3. Прокси поднимется на `http://127.0.0.1:3001/v1`.

Всё. Подробности, включая как включить ключ прокси и поменять хост/порт, — в `README.portable.md` внутри архива.

## Ежедневные команды

Установить/обновить Python-зависимости:

```powershell
npm run deps:py
```

Запустить локальный прокси на `http://127.0.0.1:3001/v1`:

```powershell
npm run dev
```

Сгенерировать свежий каталог Codex:

```powershell
npm run codex:catalog -- --output "$env:USERPROFILE\.codex\risu-zai-model-catalog.json"
```

Прогнать проверки:

```powershell
npm run check
```

## Диагностика и логи

Для поиска странных ответов включите подробные структурированные JSON-логи:

```powershell
$env:PROXY_LOG_LEVEL = "debug"
npm run dev
```

Каждый запрос получает `request_id`. Передайте свой `X-Request-ID`, и тот же идентификатор вернётся в ответе и появится в событиях начала/завершения запроса, провайдера и потоковой ошибки. Секреты, куки и токены автоматически заменяются безопасным отпечатком; полные промпты и ответы lifecycle-логгер не пишет.

Доступны уровни `debug`, `info`, `warning`, `error` и `off`. Старый `DEBUG_LOGGING=1` по-прежнему означает `debug`, если `PROXY_LOG_LEVEL` не задан. Размер входного JSON ограничен 8 MiB и настраивается через `PROXY_MAX_BODY_BYTES`. Полная памятка: [docs/observability.md](docs/observability.md).

Для проверки настройки провайдеров используйте авторизованные `GET /v1/providers` и `GET /doctor`. Добавьте `?runtime=local` или `?runtime=vercel`, чтобы проверить только нужный runtime. Первый показывает режим авторизации, модели и отсутствующие имена переменных, второй даёт короткий итог готовности. Ни один из них не возвращает сами токены или cookies.

## Локальная настройка

Проекту не требуется конкретная буква диска. Скрипты разрешают файлы проекта относительно корня репозитория, а внешние инструменты — из переменных окружения или PATH.

Если ваши Python, Node, cloudflared, браузер, хранилище Chat2API или профили авторизации лежат в нестандартных местах, скопируйте `path-config.example.json` в `path-config.json` и заполните только нужные пути. `path-config.json` игнорируется git.

Запуск Codex через установленный лаунчер:

```powershell
rzai -Model Qwen3.7-Max "explain this repo"
rzai -Local -Model mistral-small-2603 exec --ephemeral -s workspace-write -a never "fix the failing test"
```

Опции лаунчера:

- `-Local` использует `http://127.0.0.1:3001/v1`
- `-Remote` использует настроенный URL Vercel
- `-BaseUrl <url>` использует любой OpenAI-совместимый URL `/v1`
- `-Model <id>` переопределяет модель по умолчанию
- `-ApiKey <value>` задаёт `CODEX_API_KEY` для этого запуска
- `-Print` выводит итоговую команду Codex без запуска

## Учётные данные

Прокси загружает `credentials.json` из корня репозитория до импорта модулей провайдеров. Также можно использовать переменные окружения напрямую.

Минимальный локальный сценарий:

```powershell
$env:CODEX_API_KEY = "local"
$env:MISTRAL_COOKIE = "<console.mistral.ai cookie header>"
npm run dev
```

Затем в другом терминале:

```powershell
rzai -Local -Model mistral-small-2603 exec --ephemeral -s read-only -a never "reply ok"
```

Учётные данные провайдеров остаются на прокси. Клиентам вроде Codex/Zed нужен только ключ со стороны прокси (`CODEX_API_KEY`), когда включён `PROXY_API_KEY` или `RISU_PROXY_API_KEY`.

## Развёртывание на Vercel

1. Нажмите кнопку развёртывания выше или импортируйте этот репозиторий в Vercel.
2. Добавьте учётные данные провайдеров как переменные окружения Vercel.
3. Разверните.
4. Направьте клиентов на:

```text
https://your-project.vercel.app/v1
```

Полезный помощник для повторного развёртывания:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\redeploy-vercel.ps1 -SyncEnv
```

Полная карта переменных окружения и заметки по Vercel — в [docs/deployment.md](docs/deployment.md).

## Провайдеры

Полная матрица провайдеров — в [docs/providers.md](docs/providers.md). Частые варианты:

| Сценарий | Модель |
| --- | --- |
| Qwen web для кодинга/агентных тестов | `Qwen3.7-Max` |
| Стабильный дымовой тест Mistral | `mistral-small-2603` |
| Кодинг на Mistral | `codestral-2508` |
| Gemini Web | `gemini-3-pro` или `gemini-3-flash-thinking` |
| GLM Web | `chatglm-web` или `chatglm-web-thinking` |
| Gemini API с родными инструментами | `google-ai-studio` |
| Публичный фоллбэк с родными инструментами | `uncloseai-hermes` |

Браузерным/сессионным провайдерам обычно нужны куки или токены из залогиненной браузерной сессии. API-провайдерам нужны обычные API-ключи.

Точки входа в помощники учётных данных:

```powershell
python .\scripts\get-provider-creds.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\launch-mistral-auth.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\launch-gemini-auth.ps1
python .\scripts\get-qwen-creds.py
```

### Расширение Credentials Exporter (простой способ)

Вместо ручных скриптов — браузерное расширение собирает куки/токены всех провайдеров и выгружает готовый `credentials.json`:

1. Установите: откройте `chrome://extensions` (Firefox: `about:debugging#/runtime/this-firefox`), включите «Режим разработчика», нажмите **Load unpacked** и выберите `extensions/credentials-exporter`.
2. Войдите на нужные сайты провайдеров (в том браузере, где установлено расширение).
3. Откройте попап расширения и нажмите **Сканировать**.
4. Для провайдеров на основе localStorage (Z.ai, DeepSeek, Qwen, ChatGLM, Kimi): откройте сайт во вкладке и отсканируйте снова — токены подхватятся из активной вкладки.
5. При необходимости введите свой API-ключ AI Studio вручную, затем нажмите **Скачать credentials.json** и положите файл в корень репозитория.

Прогресс сохраняется между открытиями попапа, поэтому можно сканировать сайты по одному — собранные значения никогда не перезаписываются. Подробности: [extensions/credentials-exporter/README.md](extensions/credentials-exporter/README.md).

## Codex и Zed

Codex может общаться с этим прокси напрямую:

```toml
model_provider = "risu-zai"
model = "Qwen3.7-Max"
model_reasoning_effort = "xhigh"
preferred_auth_method = "apikey"
model_catalog_json = "C:/Users/<you>/.codex/risu-zai-model-catalog.json"

[model_providers.risu-zai]
name = "Risu ZAI Proxy"
base_url = "https://your-project.vercel.app/v1"
wire_api = "responses"
env_key = "CODEX_API_KEY"
```

`scripts/install-rzai.ps1` записывает этот профиль автоматически для лаунчера `rzai`. Используйте `api2codex` только когда целитесь в другой апстрим, у которого есть chat completions, но нет Responses API.

## Zed и другие OpenAI-совместимые клиенты

Используйте прокси как обычного OpenAI-совместимого провайдера:

- API URL: `https://your-project.vercel.app/v1` или `http://127.0.0.1:3001/v1`
- API key: ваш `PROXY_API_KEY` / `RISU_PROXY_API_KEY` либо любой плейсхолдер, если авторизация на прокси отключена
- Model: любой id из `/v1/models`

Для MCP/инструментов настройте MCP в клиенте. Прокси получает OpenAI-совместимые схемы инструментов и либо пропускает их к провайдерам с родными инструментами, либо использует промпт-шим для чат-провайдеров.

## API-поверхность

- `GET /health`
- `GET /doctor`
- `GET /v1/models`
- `GET /v1/providers`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `GET /v1/responses/{response_id}`
- `DELETE /v1/responses/{response_id}`
- `POST /v1/responses/chat/completions`

`/v1/responses/chat/completions` — совместимый маршрут для клиентов, которым нужна семантика response/session, но которые всё ещё ожидают вывод в форме chat-completion.

## Документация

- [Пошаговая инструкция по установке](INSTALLATION.md)
- [Справочник провайдеров](docs/providers.md)
- [Руководство по развёртыванию и окружению](docs/deployment.md)
- [Заметки по повторному развёртыванию](REDEPLOY.md)

## Заметки

- `credentials.json`, `.env*`, `auth/`, `pydeps/` и локальные файлы запуска игнорируются git.
- Установите `AGENT_TOOL_MODE=auto` (по умолчанию) для родных инструментов, где доступно, и промпт-шима в остальных случаях.
- Установите `AGENT_TOOL_MODE=off`, если предпочитаете явные ошибки для чат-провайдеров с инструментами.
- У Inception есть Cloudflare/локальный туннель-фоллбэк, описанный в [docs/deployment.md](docs/deployment.md).
