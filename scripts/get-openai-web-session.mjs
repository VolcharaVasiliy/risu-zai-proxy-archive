const DEFAULT_PORT = 9222;
const DEFAULT_BASE_URL = "https://chatgpt.com";

function argValue(name, fallback = "") {
  const index = process.argv.indexOf(name);
  if (index >= 0 && index + 1 < process.argv.length) {
    return String(process.argv[index + 1] || "");
  }
  return fallback;
}

function makeDeferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function connectTarget(port, origin) {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`);
  if (!response.ok) {
    throw new Error(`CDP target list failed: HTTP ${response.status}`);
  }
  const list = await response.json();
  const targets = list.filter(
    (item) => item.type === "page" && String(item.url || "").startsWith(origin),
  );
  if (!targets.length) {
    throw new Error(`No page target for ${origin}`);
  }
  return targets.reverse();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readTargetSession(target) {
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  const pending = new Map();
  let messageId = 0;

  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) {
      return;
    }
    const deferred = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) {
      deferred.reject(new Error(JSON.stringify(message.error)));
      return;
    }
    deferred.resolve(message.result);
  };

  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = (event) => reject(event.error || new Error("CDP websocket open failed"));
  });

  const send = (method, params = {}) => {
    const deferred = makeDeferred();
    const id = ++messageId;
    pending.set(id, deferred);
    ws.send(JSON.stringify({ id, method, params }));
    return deferred.promise;
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Page.bringToFront");

  const expression = `
    (async () => {
      const result = {
        href: location.href,
        title: document.title,
        readyState: document.readyState,
        accessToken: "",
        sessionToken: "",
        authProvider: "",
        expires: "",
        deviceId: "",
        user: {},
        account: {},
        modelSlugs: [],
        accountOrdering: [],
        modelsStatus: 0,
        accountsStatus: 0,
      };

      const didMatch = document.cookie.match(/(?:^|;\\\\s*)oai-did=([^;]+)/);
      result.deviceId = didMatch ? decodeURIComponent(didMatch[1]) : "";

      const sessionResp = await fetch("/api/auth/session", { credentials: "include" });
      result.sessionStatus = sessionResp.status;
      const sessionText = await sessionResp.text();
      try {
        const session = JSON.parse(sessionText);
        result.accessToken = String(session.accessToken || "");
        result.sessionToken = String(session.sessionToken || "");
        result.authProvider = String(session.authProvider || "");
        result.expires = String(session.expires || "");
        result.user = session.user || {};
        result.account = session.account || {};
      } catch (error) {
        result.sessionError = String(error);
        result.sessionPreview = sessionText.slice(0, 800);
        return result;
      }

      if (!result.accessToken) {
        return result;
      }

      const headers = { Authorization: "Bearer " + result.accessToken };
      if (result.deviceId) {
        headers["Oai-Device-Id"] = result.deviceId;
      }

      const modelsResp = await fetch("/backend-api/models?history_and_training_disabled=false", {
        credentials: "include",
        headers,
      });
      result.modelsStatus = modelsResp.status;
      const modelsText = await modelsResp.text();
      try {
        const modelsJson = JSON.parse(modelsText);
        result.modelSlugs = (modelsJson.models || [])
          .map((item) => item.slug || item.id)
          .filter(Boolean);
      } catch (error) {
        result.modelsError = String(error);
        result.modelsPreview = modelsText.slice(0, 800);
      }

      const accountsResp = await fetch("/backend-api/accounts/check/v4-2023-04-27", {
        credentials: "include",
        headers,
      });
      result.accountsStatus = accountsResp.status;
      const accountsText = await accountsResp.text();
      try {
        const accountsJson = JSON.parse(accountsText);
        result.accountOrdering = accountsJson.account_ordering || [];
      } catch (error) {
        result.accountsError = String(error);
        result.accountsPreview = accountsText.slice(0, 800);
      }

      return result;
    })()
  `;

  try {
    let lastResult = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const evaluation = await send("Runtime.evaluate", {
        expression,
        awaitPromise: true,
        returnByValue: true,
      });
      lastResult = evaluation.result.value || {};
      if (lastResult.accessToken) {
        return lastResult;
      }
      await sleep(1000);
    }
    return lastResult || {};
  } finally {
    ws.close();
  }
}

async function cdpSession(port, baseUrl) {
  const origin = new URL(baseUrl).origin;
  const targets = await connectTarget(port, origin);
  let lastResult = null;
  for (const target of targets) {
    if (!target.webSocketDebuggerUrl) {
      continue;
    }
    const result = await readTargetSession(target);
    lastResult = result;
    if (result && result.accessToken) {
      return result;
    }
  }
  return lastResult || {};
}

const port = Number(argValue("--port", String(DEFAULT_PORT))) || DEFAULT_PORT;
const baseUrl = argValue("--base-url", DEFAULT_BASE_URL) || DEFAULT_BASE_URL;

const result = await cdpSession(port, baseUrl);
console.log(JSON.stringify(result));
