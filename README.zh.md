# risu-zai-proxy

[English](README.md) · [Русский](README.ru.md) · [中文](README.zh.md)

面向 RisuAI、Codex、Zed 及其他 OpenAI 风格客户端的 OpenAI 兼容代理。它将众多基于浏览器会话和 API 的提供商统一暴露在单一的 `/v1` 端点之后，包括 `/v1/chat/completions` 和 `/v1/responses`。

单一的 `/v1` 端点通过提供商注册表把每个模型路由到正确的后端——抓取的浏览器会话、API 密钥，或备用方案。

[![部署到 Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/VolcharaVasiliy/risu-zai-proxy-archive) ![许可证](https://img.shields.io/github/license/VolcharaVasiliy/risu-zai-proxy-archive)

## 目录

- [功能概览](#功能概览)
- [便携版](#便携版免安装windows-x64)
- [Windows 快速开始](#windows-快速开始)
- [诊断与日志](#诊断与日志)

## 功能概览

- OpenAI 兼容路由：`/v1/models`、`/v1/providers`、`/v1/chat/completions`、`/v1/responses`、`/health`、`/doctor`
- 为 Codex 准备的 Responses API 支持，因此本代理无需 `api2codex`
- `rzai` 启动器，用一条简短命令即可通过代理运行 Codex
- 提供商注册表，带别名、模型目录生成，以及为 Codex 清理重复模型
- 面向纯聊天提供商的提示词工具垫片，使 Qwen/Mistral/Gemini Web 等模型仍能驱动 Codex 工具
- 常见浏览器/会话提供商的凭据辅助工具
- Vercel 部署路径、本地 Python 服务，以及 Inception 的 Cloudflare 备用方案

> **Z.ai 仅限本地。** Z.ai 提供商需要 Aliyun 的 `captcha_verify_param`，它绑定到解出验证码的公网 IP，因此只能在能运行 `scripts/fetch-zai-captcha.mjs` 的主机上工作（本地机器或带 Chromium 的 VPS）——无法在 Vercel 或 CI 上运行。详情与环境变量开关见 `docs/providers.md` → «Z.ai Captcha (Local-Only)»。

## Windows 快速开始

前置要求：

- Node.js 20+
- Python 3.11+
- Git
- 已安装 OpenAI Codex CLI，并可作为 `codex` 使用

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

安装脚本会：

- 安装 Node 包
- 将 Python 依赖安装到本地 `pydeps`
- 在 `%USERPROFILE%\.codex\risu-zai-model-catalog.json` 生成 Codex 模型目录
- 将 `rzai` 与 `risu-zai` 启动器安装到 `%USERPROFILE%\.codex\bin`
- 除非使用了 `-NoPath`，否则将该 bin 目录加入用户 PATH
- 写入 `%USERPROFILE%\.codex\risu-zai.config.toml`

修改 PATH 后请打开一个新终端，然后测试：

```powershell
rzai -Print
rzai -Local exec --ephemeral -s read-only -a never "reply ok"
```

使用不同的公网代理 URL 或默认模型：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 `
  -BaseUrl "https://your-project.vercel.app/v1" `
  -Model "Qwen3.7-Max"
```


## 便携版（免安装，Windows x64）

想要下载即用、零配置？请到 [Releases 页面](https://github.com/VolcharaVasiliy/risu-zai-proxy-archive/releases) 下载独立压缩包（文件名 `risu-zai-proxy-portable-*.zip`）。它内置便携版 Python 3.11（预装全部依赖）和便携版 Node.js——无需安装、无需 `pip`、无需修改 PATH，可在干净 Windows 上任意盘符运行。

1. 下载并解压到任意位置（例如 `D:\risu-zai-proxy`）。
2. 双击 `start.bat`（或在 PowerShell 运行 `start.ps1`）。
3. 代理随即运行在 `http://127.0.0.1:3001/v1`。

就这么简单。更多说明（如何启用代理 API Key、修改 host/port）见压缩包内的 `README.portable.md`。

## 日常命令

安装/更新 Python 依赖：

```powershell
npm run deps:py
```

在 `http://127.0.0.1:3001/v1` 运行本地代理：

```powershell
npm run dev
```

生成新的 Codex 目录：

```powershell
npm run codex:catalog -- --output "$env:USERPROFILE\.codex\risu-zai-model-catalog.json"
```

运行检查：

```powershell
npm run check
```

## 诊断与日志

遇到异常上游响应时，可启用结构化 JSON 日志：

```powershell
$env:PROXY_LOG_LEVEL = "debug"
npm run dev
```

每个请求都有 `request_id`。传入自己的 `X-Request-ID`，即可将客户端响应、请求生命周期、提供商日志和流式错误关联起来。凭据、Cookie 和令牌会自动脱敏；生命周期日志不会记录完整请求或响应正文。

可用级别为 `debug`、`info`、`warning`、`error`、`off`。未设置 `PROXY_LOG_LEVEL` 时，旧的 `DEBUG_LOGGING=1` 仍等价于 `debug`。`PROXY_MAX_BODY_BYTES` 用于设置 JSON 请求体上限，默认 8 MiB。

使用需要鉴权的 `GET /v1/providers` 查看提供商模型、runtime、鉴权方式和缺失的凭据名称；追加 `?runtime=local` 或 `?runtime=vercel` 可只检查一个部署目标。使用 `GET /doctor` 获取简要就绪状态。两个接口均不会返回凭据值。完整说明见 [docs/observability.md](docs/observability.md)。

## 本地配置

项目不依赖特定盘符。脚本会相对于仓库根目录解析项目文件，并从环境变量或 PATH 中解析外部工具。

如果你的 Python、Node、cloudflared、浏览器、Chat2API 存储或鉴权配置文件位于自定义位置，请将 `path-config.example.json` 复制为 `path-config.json`，并只填写你需要的路径。`path-config.json` 会被 git 忽略。

通过已安装的启动器运行 Codex：

```powershell
rzai -Model Qwen3.7-Max "explain this repo"
rzai -Local -Model mistral-small-2603 exec --ephemeral -s workspace-write -a never "fix the failing test"
```

启动器选项：

- `-Local` 使用 `http://127.0.0.1:3001/v1`
- `-Remote` 使用配置好的 Vercel URL
- `-BaseUrl <url>` 使用任意 OpenAI 兼容的 `/v1` URL
- `-Model <id>` 覆盖默认模型
- `-ApiKey <value>` 为该次运行设置 `CODEX_API_KEY`
- `-Print` 仅打印解析后的 Codex 命令而不执行

## 凭据

代理会在导入提供商模块之前，从仓库根目录加载 `credentials.json`。你也可以直接使用环境变量。

最小本地用法：

```powershell
$env:CODEX_API_KEY = "local"
$env:MISTRAL_COOKIE = "<console.mistral.ai cookie header>"
npm run dev
```

然后在另一个终端：

```powershell
rzai -Local -Model mistral-small-2603 exec --ephemeral -s read-only -a never "reply ok"
```

提供商的凭据保留在代理一侧。Codex/Zed 等客户端只需要面向代理的密钥（`CODEX_API_KEY`），前提是启用了 `PROXY_API_KEY` 或 `RISU_PROXY_API_KEY`。

## 部署到 Vercel

1. 点击上方的部署按钮，或将本仓库导入 Vercel。
2. 将提供商凭据添加为 Vercel 环境变量。
3. 部署。
4. 将客户端指向：

```text
https://your-project.vercel.app/v1
```

实用的重新部署辅助脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\redeploy-vercel.ps1 -SyncEnv
```

完整的环境变量映射与 Vercel 说明见 [docs/deployment.md](docs/deployment.md)。

## 提供商

完整的提供商矩阵见 [docs/providers.md](docs/providers.md)。常见选择：

| 使用场景 | 模型 |
| --- | --- |
| Qwen 网页端编程/智能体测试 | `Qwen3.7-Max` |
| 稳定的 Mistral 冒烟测试 | `mistral-small-2603` |
| Mistral 编程 | `codestral-2508` |
| Gemini Web | `gemini-3-pro` 或 `gemini-3-flash-thinking` |
| GLM Web | `chatglm-web` 或 `chatglm-web-thinking` |
| 原生工具的 Gemini API | `google-ai-studio` |
| 原生工具的公用备用 | `uncloseai-hermes` |

浏览器/会话类提供商通常需要来自已登录浏览器会话的 Cookie 或令牌。API 类提供商需要普通的 API 密钥。

凭据辅助工具入口：

```powershell
python .\scripts\get-provider-creds.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\launch-mistral-auth.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\launch-gemini-auth.ps1
python .\scripts\get-qwen-creds.py
```

### Credentials Exporter 扩展（简易方式）

不必使用手动脚本——浏览器扩展会从所有提供商收集 Cookie/令牌，并下载就绪的 `credentials.json`：

1. 安装：打开 `chrome://extensions`（Firefox：`about:debugging#/runtime/this-firefox`），启用「开发者模式」，点击 **Load unpacked** 并选择 `extensions/credentials-exporter`。
2. 在你使用的提供商网站上登录（在安装了扩展的浏览器中）。
3. 打开扩展弹窗并点击 **扫描**。
4. 对于基于 localStorage 的提供商（Z.ai、DeepSeek、Qwen、ChatGLM、Kimi）：在内标签页中打开网站再次扫描——令牌会从当前标签页获取。
5. 若使用 AI Studio，可手动填入 API 密钥，然后点击 **下载 credentials.json** 并将文件放到仓库根目录。

进度会在弹窗多次打开之间保存，因此你可以逐个网站扫描——已收集的值绝不会被覆盖。详情见 [extensions/credentials-exporter/README.md](extensions/credentials-exporter/README.md)。

## Codex 与 Zed

Codex 可以直接与本代理通信：

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

`scripts/install-rzai.ps1` 会自动为 `rzai` 启动器写入该配置。仅当你面向的是另一个只有 chat completions 但没有 Responses API 的上游时，才使用 `api2codex`。

## Zed 及其他 OpenAI 兼容客户端

将代理当作普通的 OpenAI 兼容提供商使用：

- API URL：`https://your-project.vercel.app/v1` 或 `http://127.0.0.1:3001/v1`
- API key：你的 `PROXY_API_KEY` / `RISU_PROXY_API_KEY`，若代理鉴权关闭则可为任意占位符
- Model：来自 `/v1/models` 的任意 id

对于 MCP/工具调用，请在客户端中配置 MCP。代理接收 OpenAI 兼容的工具 schema，要么透传给原生工具提供商，要么对纯聊天提供商使用提示词垫片。

## API 接口

- `GET /health`
- `GET /doctor`
- `GET /v1/models`
- `GET /v1/providers`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `GET /v1/responses/{response_id}`
- `DELETE /v1/responses/{response_id}`
- `POST /v1/responses/chat/completions`

`/v1/responses/chat/completions` 是一个兼容路由，面向那些需要 response/session 语义、但仍期望 chat-completion 形态输出的客户端。

## 更多文档

- [分步安装指南](INSTALLATION.md)
- [提供商参考](docs/providers.md)
- [部署与环境指南](docs/deployment.md)
- [重复部署说明](REDEPLOY.md)

## 说明

- `credentials.json`、`.env*`、`auth/`、`pydeps/` 以及本地运行文件均被 git 忽略。
- 在可用处设置 `AGENT_TOOL_MODE=auto`（默认）以使用原生工具，其余情况使用提示词工具垫片。
- 若你更希望纯聊天提供商在涉及工具时报出明确错误，可设置 `AGENT_TOOL_MODE=off`。
- Inception 有 Cloudflare/本地隧道的备用方案，详见 [docs/deployment.md](docs/deployment.md)。
