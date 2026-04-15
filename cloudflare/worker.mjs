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

async function inceptionResponse(request, env, payload) {
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return jsonResponse({ ok: true, edge: "cloudflare", provider: "inception" });
    }

    if (url.pathname === "/v1/models") {
      return jsonResponse(modelList());
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

      return inceptionResponse(request, env, payload);
    }

    return jsonResponse({ error: { message: "Not found" } }, 404);
  },
};
