import puppeteer from "@cloudflare/puppeteer";

const INCEPTION_BASE_URL = "https://chat.inceptionlabs.ai";
const SUPPORTED_MODELS = ["mercury-2", "mercury-coder"];
const MODEL_ALIASES = new Map([
  ["mercury", "mercury-2"],
  ["mercury-2", "mercury-2"],
  ["mercury-coder", "mercury-coder"],
  ["inception", "mercury-2"],
  ["inception-chat", "mercury-2"],
]);

const LOG_LEVELS = { debug: 10, info: 20, warning: 30, error: 40 };

function requestId(request) {
  const candidate = String(request.headers.get("x-request-id") || "").trim();
  if (/^[A-Za-z0-9._:-]{1,128}$/.test(candidate)) {
    return candidate;
  }
  return `req_${crypto.randomUUID().replaceAll("-", "")}`;
}

function logEnabled(env, level) {
  let configured = String(env.PROXY_LOG_LEVEL || "").trim().toLowerCase();
  if (!configured) {
    configured = /^(1|true|yes|on)$/i.test(String(env.DEBUG_LOGGING || "")) ? "debug" : "off";
  }
  if (["", "off", "none", "0"].includes(configured)) {
    return false;
  }
  return (LOG_LEVELS[level] || 20) >= (LOG_LEVELS[configured] || 10);
}

function logEvent(env, event, requestIdValue, fields = {}, level = "info") {
  if (!logEnabled(env, level)) {
    return;
  }
  console.log(JSON.stringify({
    ts: new Date().toISOString(),
    level,
    event,
    request_id: requestIdValue,
    ...fields,
  }));
}

function headerSummary(headers) {
  const names = [];
  const sensitivePresent = {};
  for (const [name, value] of headers.entries()) {
    const lowered = name.toLowerCase();
    names.push(lowered);
    if (["authorization", "cookie", "x-api-key", "x-proxy-api-key"].includes(lowered)) {
      sensitivePresent[lowered] = Boolean(String(value || "").trim());
    }
  }
  return { names: [...new Set(names)].sort(), sensitive_present: sensitivePresent };
}

function upstreamPreview(env, value) {
  if (!/^(1|true|yes|on)$/i.test(String(env.PROXY_LOG_UPSTREAM_PREVIEW || ""))) {
    return undefined;
  }
  return String(value || "")
    .slice(0, 500)
    .replace(/(bearer\s+|(?:api[_-]?key|token|cookie|authorization|secret)\s*[=:]\s*)([^\s,;"']{8,})/gi, "$1<redacted>");
}

function withRequestId(response, requestIdValue) {
  const headers = new Headers(response.headers);
  headers.set("X-Request-ID", requestIdValue);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function envToken(value) {
  return String(value || "").trim();
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

function cookieValue(cookieHeader, cookieName) {
  const raw = envToken(cookieHeader);
  if (!raw) {
    return "";
  }

  for (const part of raw.split(";")) {
    const [name, ...rest] = part.split("=");
    if (name && name.trim() === cookieName) {
      return rest.join("=").trim();
    }
  }
  return "";
}

function splitCookieHeader(cookieHeader) {
  const raw = envToken(cookieHeader);
  if (!raw) {
    return [];
  }

  const entries = [];
  for (const part of raw.split(";")) {
    const [name, ...rest] = part.split("=");
    const trimmedName = envToken(name);
    const value = envToken(rest.join("="));
    if (!trimmedName || !value) {
      continue;
    }
    entries.push({ name: trimmedName, value });
  }
  return entries;
}

function mapModel(model) {
  const lowered = envToken(model).toLowerCase();
  return MODEL_ALIASES.get(lowered) || "mercury-2";
}

function supportsModel(model) {
  return MODEL_ALIASES.has(envToken(model).toLowerCase());
}

function contentText(content) {
  if (typeof content === "string") {
    return content;
  }

  if (Array.isArray(content)) {
    return content
      .map((item) => {
        if (!item || typeof item !== "object") {
          return "";
        }
        if (item.type === "text" && item.text) {
          return String(item.text);
        }
        if (item.content) {
          return String(item.content);
        }
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }

  if (content == null) {
    return "";
  }

  return String(content);
}

function messageEntries(payload) {
  const entries = [];
  for (const message of payload.messages || []) {
    const role = envToken(message?.role).toLowerCase();
    if (!role) {
      continue;
    }

    const text = contentText(message?.content).trim();
    if (!text) {
      continue;
    }

    entries.push({
      id: String(message?.id || crypto.randomUUID()).replaceAll("-", "").slice(0, 16),
      role,
      parts: [{ type: "text", text }],
    });
  }
  return entries;
}

function requestBody(payload, env) {
  const model = mapModel(payload?.model || "");
  const messages = messageEntries(payload || {});
  if (!messages.length) {
    throw new Error("Inception request requires at least one message");
  }

  const reasoningEffort = envToken(
    payload?.reasoning_effort ?? payload?.reasoningEffort ?? env.INCEPTION_REASONING_EFFORT ?? "medium",
  ).toLowerCase();

  let webSearchEnabled = payload?.web_search;
  if (webSearchEnabled == null) {
    webSearchEnabled = payload?.webSearchEnabled;
  }
  if (webSearchEnabled == null) {
    webSearchEnabled = /^(1|true|yes|on)$/i.test(envToken(env.INCEPTION_WEB_SEARCH));
  }

  return {
    model,
    body: {
      reasoningEffort: ["low", "medium", "high"].includes(reasoningEffort) ? reasoningEffort : "medium",
      webSearchEnabled: Boolean(webSearchEnabled),
      voiceMode: Boolean(payload?.voiceMode || false),
      id: `inc-${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`,
      messages,
      trigger: "submit-message",
    },
  };
}

function parseSseBlocks(text) {
  const blocks = [];
  for (const rawBlock of String(text || "").split("\n\n")) {
    const block = rawBlock.trim();
    if (!block) {
      continue;
    }

    let eventName = "";
    const dataLines = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
        continue;
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
        continue;
      }
      dataLines.push(line);
    }

    const data = dataLines.join("\n").trim();
    if (!data) {
      continue;
    }
    if (data === "[DONE]") {
      blocks.push([eventName, "[DONE]"]);
      continue;
    }

    try {
      blocks.push([eventName, JSON.parse(data)]);
    } catch {
      blocks.push([eventName, data]);
    }
  }
  return blocks;
}

function openaiChunk(responseId, model, created, delta, finishReason = null) {
  return {
    id: responseId,
    object: "chat.completion.chunk",
    created,
    model,
    choices: [{ index: 0, delta, finish_reason: finishReason }],
  };
}

class OpenAIStreamBuilder {
  constructor(responseId, model) {
    this.responseId = responseId;
    this.model = model;
    this.created = Math.floor(Date.now() / 1000);
    this.roleSent = false;
  }

  ensureRole(mode = "content") {
    if (this.roleSent) {
      return null;
    }
    this.roleSent = true;
    if (mode === "reasoning") {
      return openaiChunk(this.responseId, this.model, this.created, { role: "assistant", reasoning_content: "" });
    }
    return openaiChunk(this.responseId, this.model, this.created, { role: "assistant", content: "" });
  }

  content(text) {
    const value = String(text || "");
    if (!value) {
      return [];
    }

    const chunks = [];
    const roleChunk = this.ensureRole("content");
    if (roleChunk) {
      chunks.push(roleChunk);
    }
    chunks.push(openaiChunk(this.responseId, this.model, this.created, { content: value }));
    return chunks;
  }

  reasoning(text) {
    const value = String(text || "");
    if (!value) {
      return [];
    }

    const chunks = [];
    const roleChunk = this.ensureRole("reasoning");
    if (roleChunk) {
      chunks.push(roleChunk);
    }
    chunks.push(openaiChunk(this.responseId, this.model, this.created, { reasoning_content: value }));
    return chunks;
  }

  finish(finishReason = "stop") {
    return openaiChunk(this.responseId, this.model, this.created, {}, finishReason);
  }
}

function streamResponse(chunks) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(chunk)}\n\n`));
        }
        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
      },
    }),
    {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "close",
      },
    },
  );
}

function aggregateStream(rawText, model, responseId) {
  const builder = new OpenAIStreamBuilder(responseId, model);
  const chunks = [];
  const contentParts = [];
  const reasoningParts = [];

  for (const [eventName, item] of parseSseBlocks(rawText)) {
    if (item === "[DONE]") {
      continue;
    }
    if (!item || typeof item !== "object") {
      continue;
    }

    const eventType = envToken(item.type || eventName || "").toLowerCase();
    if (["reasoning-start", "reasoning-end", "text-start", "text-end"].includes(eventType)) {
      continue;
    }

    if (eventType === "text-delta") {
      const delta = envToken(item.delta);
      if (delta) {
        contentParts.push(delta);
        chunks.push(...builder.content(delta));
      }
      continue;
    }

    if (eventType === "reasoning-delta") {
      const delta = envToken(item.delta);
      if (delta) {
        reasoningParts.push(delta);
        chunks.push(...builder.reasoning(delta));
      }
    }
  }

  chunks.push(builder.finish());
  return {
    chunks,
    content: contentParts.join(""),
    reasoning: reasoningParts.join(""),
  };
}

function aggregatePlainText(text, model, responseId) {
  const builder = new OpenAIStreamBuilder(responseId, model);
  const chunks = [];
  const value = String(text || "");
  if (value) {
    chunks.push(...builder.content(value));
  }
  chunks.push(builder.finish());
  return {
    chunks,
    content: value,
    reasoning: "",
  };
}

function resolveCredentials(headers) {
  let cookie = envToken(headers.get("x-inception-cookie"));
  let sessionToken = envToken(headers.get("x-inception-session-token"));

  if (!sessionToken && cookie) {
    sessionToken = cookieValue(cookie, "session");
  }
  if (!cookie && sessionToken) {
    cookie = `session=${sessionToken}`;
  }

  return { cookie, sessionToken };
}

function resolveCredentialsWithEnv(headers, env) {
  const headerCreds = resolveCredentials(headers);
  let cookie = headerCreds.cookie || envToken(env.INCEPTION_COOKIE);
  let sessionToken = headerCreds.sessionToken || envToken(env.INCEPTION_SESSION_TOKEN);

  if (!sessionToken && cookie) {
    sessionToken = cookieValue(cookie, "session");
  }
  if (!cookie && sessionToken) {
    cookie = `session=${sessionToken}`;
  }

  return { cookie, sessionToken };
}

function buildHeaders(env, baseUrl, cookie, sessionToken) {
  const headers = new Headers({
    Accept: "*/*",
    "Accept-Language": envToken(env.INCEPTION_ACCEPT_LANGUAGE) || "ru,en;q=0.9",
    "Content-Type": "application/json",
    Origin: baseUrl,
    Referer: `${baseUrl}/`,
    Priority: envToken(env.INCEPTION_PRIORITY) || "u=1, i",
    "sec-ch-ua":
      envToken(env.INCEPTION_SEC_CH_UA) ||
      '"Not(A:Brand";v="8", "Chromium";v="144", "YaBrowser";v="26.3", "Yowser";v="2.5"',
    "sec-ch-ua-mobile": envToken(env.INCEPTION_SEC_CH_UA_MOBILE) || "?0",
    "sec-ch-ua-platform": envToken(env.INCEPTION_SEC_CH_UA_PLATFORM) || '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent":
      envToken(env.INCEPTION_USER_AGENT) ||
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
  });
  if (sessionToken) {
    headers.set("x-session-token", sessionToken);
  }

  if (cookie) {
    headers.set("Cookie", cookie);
  }

  return headers;
}

async function refreshSessionToken(env, baseUrl, cookie, sessionToken) {
  const response = await fetch(`${baseUrl}/api/session`, {
    method: "GET",
    headers: buildHeaders(env, baseUrl, cookie, ""),
    redirect: "manual",
  });

  if (!response.ok) {
    const bodyText = await response.text().catch(() => "");
    throw new Error(`Inception session refresh failed: HTTP ${response.status} ${bodyText.slice(0, 300)}`.trim());
  }

  const payload = await response.json().catch(() => null);
  const refreshedToken = envToken(payload?.token);
  if (!refreshedToken) {
    throw new Error("Inception session refresh failed: token missing in response");
  }
  return refreshedToken;
}

async function browserBackedRequest(env, baseUrl, cookie, sessionToken, body) {
  if (!env.MYBROWSER) {
    throw new Error("Cloudflare Browser Rendering binding MYBROWSER is not configured");
  }

  const browser = await puppeteer.launch(env.MYBROWSER);
  const page = await browser.newPage();

  try {
    const hostname = new URL(baseUrl).hostname;
    const userAgent =
      envToken(env.INCEPTION_USER_AGENT) ||
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36";

    await page.setUserAgent(userAgent);
    await page.setExtraHTTPHeaders({
      "Accept-Language": envToken(env.INCEPTION_ACCEPT_LANGUAGE) || "ru,en;q=0.9",
    });

    await page.goto(`${baseUrl}/`, {
      waitUntil: "networkidle2",
      timeout: 45000,
    });

    const cookies = splitCookieHeader(cookie).map(({ name, value }) => ({
      name,
      value,
      url: baseUrl,
      secure: true,
      httpOnly: name === "session" || name === "_vcrcs",
    }));
    if (cookies.length) {
      await page.setCookie(...cookies);
    }

    await page.reload({
      waitUntil: "networkidle2",
      timeout: 45000,
    });

    await page
      .waitForFunction(
        () => {
          const title = String(document.title || "");
          return !title.toLowerCase().includes("security checkpoint");
        },
        { timeout: 10000 },
      )
      .catch(() => {});

    await new Promise((resolve) => setTimeout(resolve, 2000));

    const appliedCookies = await page.cookies(baseUrl);
    const pageInfo = await page.evaluate(() => ({
      href: location.href,
      title: document.title || "",
      text: (document.body?.innerText || "").slice(0, 200),
    }));

    return await page.evaluate(
      async ({ body: activeBody, sessionToken: initialToken, appliedCookieNames, pageInfo: initialPageInfo }) => {
        const sessionResponse = await fetch("/api/session", {
          method: "GET",
          credentials: "include",
          headers: { accept: "*/*" },
        });
        const sessionText = await sessionResponse.text();
        let activeToken = initialToken;
        try {
          const parsed = JSON.parse(sessionText);
          if (parsed && typeof parsed.token === "string" && parsed.token.trim()) {
            activeToken = parsed.token.trim();
          }
        } catch {}

        const chatResponse = await fetch("/api/chat", {
          method: "POST",
          credentials: "include",
          headers: {
            accept: "*/*",
            "content-type": "application/json",
            "x-session-token": activeToken,
          },
          body: JSON.stringify(activeBody),
        });

        return {
          debug: {
            appliedCookieNames,
            hasInitialToken: Boolean(initialToken),
            pageInfo: initialPageInfo,
          },
          session: {
            status: sessionResponse.status,
            text: sessionText,
          },
          chat: {
            status: chatResponse.status,
            text: await chatResponse.text(),
            contentType: chatResponse.headers.get("content-type") || "",
          },
        };
      },
      {
        body,
        sessionToken,
        appliedCookieNames: appliedCookies.map((item) => item.name),
        pageInfo,
      },
    );
  } finally {
    await page.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

async function inceptionResponse(request, env, payload, requestIdValue) {
  const { cookie, sessionToken } = resolveCredentialsWithEnv(request.headers, env);
  if (!sessionToken) {
    return jsonResponse(
      {
        error: {
          message: "INCEPTION_SESSION_TOKEN or x-inception-session-token is required",
          type: "invalid_request_error",
        },
      },
      401,
    );
  }

  const baseUrl = envToken(env.INCEPTION_BASE_URL) || INCEPTION_BASE_URL;
  const { model, body } = requestBody(payload, env);
  let upstreamStatus = 0;
  let rawText = "";
  let contentType = "";
  let browserDebug = null;
  let browserErrorMessage = "";

  try {
    const browserResult = await browserBackedRequest(env, baseUrl, cookie, sessionToken, body);
    browserDebug = browserResult.debug || null;
    if (browserResult.session.status !== 200) {
      logEvent(env, "upstream_response", requestIdValue, {
        provider: "inception",
        operation: "session_refresh",
        status: browserResult.session.status,
        body_bytes: new TextEncoder().encode(String(browserResult.session.text || "")).byteLength,
        body_preview: upstreamPreview(env, browserResult.session.text),
      }, "warning");
      return jsonResponse(
        {
          error: {
            message: `Inception session refresh failed: HTTP ${browserResult.session.status} ${String(browserResult.session.text || "").slice(0, 300)}`.trim(),
            type: "invalid_request_error",
            ...(browserDebug ? { debug: browserDebug } : {}),
          },
        },
        502,
      );
    }
    upstreamStatus = Number(browserResult.chat.status || 0);
    rawText = String(browserResult.chat.text || "");
    contentType = String(browserResult.chat.contentType || "");
  } catch (browserError) {
    browserErrorMessage = browserError instanceof Error ? browserError.message : String(browserError);
    let activeSessionToken = sessionToken;
    try {
      activeSessionToken = await refreshSessionToken(env, baseUrl, cookie, sessionToken);
    } catch (error) {
      return jsonResponse(
        {
          error: {
            message: error instanceof Error ? error.message : String(error),
            type: "invalid_request_error",
            ...(browserErrorMessage ? { browser_error: browserErrorMessage } : {}),
          },
        },
        502,
      );
    }

    const upstream = await fetch(`${baseUrl}/api/chat`, {
      method: "POST",
      headers: buildHeaders(env, baseUrl, cookie, activeSessionToken),
      body: JSON.stringify(body),
      redirect: "manual",
    });
    upstreamStatus = upstream.status;
    rawText = await upstream.text().catch(() => "");
    contentType = String(upstream.headers.get("content-type") || "");

    if (!upstream.ok && upstream.status !== 200) {
      logEvent(env, "upstream_response", requestIdValue, {
        provider: "inception",
        operation: "chat_completion",
        status: upstream.status,
        content_type: contentType,
        body_bytes: new TextEncoder().encode(rawText).byteLength,
        body_preview: upstreamPreview(env, rawText),
        browser_fallback: true,
      }, "warning");
      return jsonResponse(
        {
          error: {
            message: `Inception completion failed: HTTP ${upstream.status} ${rawText.slice(0, 300)}`.trim(),
            type: "invalid_request_error",
            ...(browserErrorMessage ? { browser_error: browserErrorMessage } : {}),
          },
        },
        502,
      );
    }
  }

  logEvent(env, "upstream_response", requestIdValue, {
    provider: "inception",
    operation: "chat_completion",
    status: upstreamStatus,
    content_type: contentType,
    body_bytes: new TextEncoder().encode(rawText).byteLength,
    body_preview: upstreamPreview(env, rawText),
    browser_fallback: Boolean(browserErrorMessage),
  }, upstreamStatus === 200 ? "debug" : "warning");

  if (upstreamStatus !== 200) {
    return jsonResponse(
      {
        error: {
          message: `Inception completion failed: HTTP ${upstreamStatus} ${rawText.slice(0, 300)}`.trim(),
          type: "invalid_request_error",
          ...(browserDebug ? { debug: browserDebug } : {}),
          ...(browserErrorMessage ? { browser_error: browserErrorMessage } : {}),
        },
      },
      502,
    );
  }

  contentType = contentType.toLowerCase();
  const responseId = body.id;

  if (contentType.includes("text/event-stream")) {
    const aggregated = aggregateStream(rawText, model, responseId);
    return jsonResponse({
      id: `inc-${Math.floor(Date.now() / 1000)}`,
      object: "chat.completion",
      created: Math.floor(Date.now() / 1000),
      model,
      choices: [
        {
          index: 0,
          message: {
            role: "assistant",
            content: aggregated.content,
            ...(aggregated.reasoning ? { reasoning_content: aggregated.reasoning } : {}),
          },
          finish_reason: "stop",
        },
      ],
    });
  }

  let parsed = null;
  try {
    parsed = JSON.parse(rawText);
  } catch {
    parsed = null;
  }

  const text = parsed && typeof parsed === "object" ? String(parsed.text || parsed.content || "") : String(rawText || "");
  const aggregated = aggregatePlainText(text, model, responseId);

  return jsonResponse({
    id: `inc-${Math.floor(Date.now() / 1000)}`,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [
      {
        index: 0,
        message: {
          role: "assistant",
          content: aggregated.content,
          ...(aggregated.reasoning ? { reasoning_content: aggregated.reasoning } : {}),
        },
        finish_reason: "stop",
      },
    ],
  });
}

function modelList() {
  return {
    object: "list",
    data: SUPPORTED_MODELS.map((model) => ({
      id: model,
      object: "model",
      created: 0,
      owned_by: "chat.inceptionlabs.ai",
      provider: "inception",
      requires_env: ["INCEPTION_SESSION_TOKEN", "INCEPTION_COOKIE (optional)"],
    })),
  };
}

async function handleRequest(request, env, requestIdValue) {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/internal/state/")) {
      return stateResponse(request, env, url);
    }

    if (url.pathname === "/health") {
      return jsonResponse({ ok: true, edge: "cloudflare", provider: "inception" });
    }

    if (url.pathname === "/doctor") {
      const ready = Boolean(env.INCEPTION_SESSION_TOKEN || env.INCEPTION_COOKIE);
      const edge = edgeProviderList(env);
      return jsonResponse({
        ok: ready && edge.every((item) => item.ready),
        runtime: "cloudflare",
        providers_total: 1 + edge.length,
        providers_ready: (ready ? 1 : 0) + edge.filter((item) => item.ready).length,
        providers_missing_credentials: (ready ? 0 : 1) + edge.filter((item) => !item.ready).length,
        missing_credentials: [...(ready ? [] : ["inception"]), ...edge.filter((item) => !item.ready).map((item) => item.id)],
        runtimes: ["cloudflare"],
      });
    }

    if (url.pathname === "/v1/models") {
      const result = modelList();
      for (const item of edgeProviders(env)) for (const model of item.models) result.data.push({ id: model, object: "model", created: 0, owned_by: item.owned_by, provider: item.id, requires_env: item.token_env ? [item.token_env] : [] });
      return jsonResponse(result);
    }

    if (url.pathname === "/v1/providers") {
      const result = providerList(env);
      result.data.push(...edgeProviderList(env));
      result.providers_total = result.data.length;
      result.providers_ready = result.data.filter((item) => item.ready).length;
      return jsonResponse(result);
    }

    if (url.pathname === "/v1/chat/completions" && request.method === "POST") {
      let payload;
      try {
        payload = await request.json();
      } catch {
        return jsonResponse(
          {
            error: {
              message: "Invalid JSON body",
              type: "invalid_request_error",
            },
          },
          400,
        );
      }

      if (!payload.model) {
        return jsonResponse(
          {
            error: {
              message: "model is required",
              type: "invalid_request_error",
            },
          },
          400,
        );
      }

      if (!Array.isArray(payload.messages) || payload.messages.length === 0) {
        return jsonResponse(
          {
            error: {
              message: "messages must be a non-empty array",
              type: "invalid_request_error",
            },
          },
          400,
        );
      }

      if (!supportsModel(payload.model)) {
        const edge = edgeProviderForModel(env, payload.model);
        if (edge) return edgeResponse(request, env, payload, edge, requestIdValue);
        return jsonResponse(
          {
            error: {
              message: `Unsupported model: ${payload.model}`,
              type: "invalid_request_error",
            },
          },
          400,
        );
      }

      return inceptionResponse(request, env, payload, requestIdValue);
    }

    return jsonResponse({ error: { message: "Not found" } }, 404);
}

function stateAuthorized(request, env) {
  const expected = envToken(env.STATE_API_TOKEN);
  if (!expected) return false;
  return envToken(request.headers.get("Authorization")) === `Bearer ${expected}`;
}

async function stateResponse(request, env, url) {
  if (!env.STATE_KV) return jsonResponse({ error: { message: "STATE_KV binding is not configured" } }, 503);
  if (!stateAuthorized(request, env)) return jsonResponse({ error: { message: "Unauthorized" } }, 401);
  let key = "";
  try {
    key = decodeURIComponent(url.pathname.slice("/internal/state/".length));
  } catch {
    return jsonResponse({ error: { message: "Invalid state key" } }, 400);
  }
  if (!key || key.length > 256) return jsonResponse({ error: { message: "Invalid state key" } }, 400);
  if (request.method === "GET") {
    const value = await env.STATE_KV.get(key, { type: "json" });
    return value == null ? jsonResponse({ error: { message: "Not found" } }, 404) : jsonResponse(value);
  }
  if (request.method === "PUT") {
    const payload = await request.json();
    const configuredTtl = Number(env.STATE_TTL_SECONDS || 21600);
    const expirationTtl = Number.isFinite(configuredTtl) ? Math.max(60, Math.floor(configuredTtl)) : 21600;
    await env.STATE_KV.put(key, JSON.stringify(payload), { expirationTtl });
    return jsonResponse({ ok: true });
  }
  if (request.method === "DELETE") {
    const existed = await env.STATE_KV.get(key) !== null;
    await env.STATE_KV.delete(key);
    return jsonResponse({ deleted: existed });
  }
  return jsonResponse({ error: { message: "Method not allowed" } }, 405);
}

function edgeProviders(env) {
  try {
    const parsed = JSON.parse(String(env.EDGE_PROVIDERS_JSON || "[]"));
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item) => item && item.id && item.base_url && Array.isArray(item.models)).slice(0, 32).map((item) => ({ id: String(item.id), base_url: String(item.base_url).replace(/\/$/, ""), models: item.models.map(String).slice(0, 128), token_env: String(item.token_env || ""), owned_by: String(item.owned_by || item.id) }));
  } catch { return []; }
}
function edgeProviderForModel(env, model) { return edgeProviders(env).find((item) => item.models.includes(String(model))) || null; }
function edgeProviderList(env) { return edgeProviders(env).map((item) => { const ready = !item.token_env || Boolean(env[item.token_env]); return { id: item.id, owned_by: item.owned_by, models: item.models, runtimes: ["cloudflare"], auth_mode: item.token_env ? "api_key" : "public", requires_env: item.token_env ? [item.token_env] : [], credential_sets: item.token_env ? [[item.token_env]] : [], configured_env: ready && item.token_env ? [item.token_env] : [], missing_env: ready ? [] : [item.token_env], ready }; }); }
async function edgeResponse(request, env, payload, provider, rid) {
  const token = provider.token_env ? envToken(env[provider.token_env]) : "";
  if (provider.token_env && !token) return jsonResponse({ error: { message: `${provider.token_env} is required`, type: "authentication_error", request_id: rid } }, 401);
  const headers = new Headers({ "Content-Type": "application/json", "Accept": "application/json, text/event-stream" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const upstream = await fetch(`${provider.base_url}/chat/completions`, { method: "POST", headers, body: JSON.stringify(payload) });
  return new Response(upstream.body, { status: upstream.status, headers: { "Content-Type": upstream.headers.get("Content-Type") || "application/json", "Cache-Control": "no-cache, no-transform" } });
}

function providerList(env) {
  const ready = Boolean(env.INCEPTION_SESSION_TOKEN || env.INCEPTION_COOKIE);
  return {
    object: "list",
    runtime: "cloudflare",
    data: [{
      id: "inception",
      owned_by: "chat.inceptionlabs.ai",
      models: [...SUPPORTED_MODELS],
      runtimes: ["cloudflare"],
      auth_mode: "browser_session",
      requires_env: ["INCEPTION_SESSION_TOKEN", "INCEPTION_COOKIE (optional)"],
      credential_sets: [["INCEPTION_SESSION_TOKEN"], ["INCEPTION_COOKIE"]],
      configured_env: [
        ...(env.INCEPTION_SESSION_TOKEN ? ["INCEPTION_SESSION_TOKEN"] : []),
        ...(env.INCEPTION_COOKIE ? ["INCEPTION_COOKIE"] : []),
      ],
      missing_env: ready ? [] : ["INCEPTION_SESSION_TOKEN", "INCEPTION_COOKIE"],
      ready,
    }],
  };
}

export default {
  async fetch(request, env) {
    const started = Date.now();
    const rid = requestId(request);
    const url = new URL(request.url);
    let provider = "";
    let model = "";
    let stream = false;

    if (url.pathname === "/v1/chat/completions" && request.method === "POST") {
      provider = "inception";
      try {
        const payload = await request.clone().json();
        model = String(payload?.model || "");
        stream = payload?.stream !== false;
      } catch {
        // The route handler returns the canonical invalid JSON response.
      }
    }

    logEvent(env, "http_request_started", rid, {
      runtime: "cloudflare",
      method: request.method,
      path: url.pathname,
      headers: headerSummary(request.headers),
      provider,
      model,
      stream,
    });

    try {
      const response = await handleRequest(request, env, rid);
      logEvent(env, "http_request_finished", rid, {
        runtime: "cloudflare",
        method: request.method,
        path: url.pathname,
        provider,
        model,
        stream,
        status: response.status,
        duration_ms: Date.now() - started,
      });
      return withRequestId(response, rid);
    } catch (error) {
      const errorText = error instanceof Error ? error.message : String(error);
      logEvent(env, "http_request_error", rid, {
        runtime: "cloudflare",
        method: request.method,
        path: url.pathname,
        provider,
        model,
        error_type: error?.name || "Error",
        error_length: errorText.length,
        error_preview: upstreamPreview(env, errorText),
        duration_ms: Date.now() - started,
      }, "error");
      return withRequestId(jsonResponse({
        error: {
          message: "Provider request failed; inspect Cloudflare logs with the X-Request-ID",
          type: "server_error",
          request_id: rid,
        },
      }, 500), rid);
    }
  },
};
