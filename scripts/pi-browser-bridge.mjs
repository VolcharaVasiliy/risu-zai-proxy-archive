const DEFAULT_PORT = 9232;
const DEFAULT_BASE_URL = "https://pi.ai";
const DEFAULT_TIMEOUT_MS = 90000;

function argValue(name, fallback = "") {
  const index = process.argv.indexOf(name);
  if (index >= 0 && index + 1 < process.argv.length) {
    return String(process.argv[index + 1] || "");
  }
  return fallback;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
  const preferred = targets.find((item) => String(item.url || "").includes("/talk/"));
  return preferred || targets.reverse()[0];
}

async function readPrompt(target, prompt, timeoutMs) {
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
  await sleep(4000);

  const expression = `
    (async () => {
      const prompt = ${JSON.stringify(prompt)};
      const timeoutMs = ${JSON.stringify(timeoutMs)};
      const pollDelayMs = 1200;
      const stablePollsRequired = 2;

      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

      const conversationId = () => {
        const parts = location.pathname.split('/').filter(Boolean);
        return parts[parts.length - 1] || '';
      };

      const history = async () => {
        const currentConversationId = conversationId();
        const response = await fetch('/api/chat/history?conversation=' + encodeURIComponent(currentConversationId) + '&limit=100', {
          credentials: 'include',
          headers: {
            Accept: 'application/json',
            'X-Api-Version': '2',
          },
        });
        if (!response.ok) {
          throw new Error('Pi history failed: HTTP ' + response.status);
        }
        return await response.json();
      };

      const before = await history();
      const knownIds = new Set((before.messages || []).map((message) => message.sid));
      const startedAt = Date.now();

      const findComposer = () => {
        const byPlaceholder = document.querySelector('textarea[placeholder*="mind" i]');
        if (byPlaceholder) return byPlaceholder;
        const main = document.querySelector('main textarea, [data-testid="chat-composer"] textarea, form textarea');
        if (main) return main;
        const texts = Array.from(document.querySelectorAll('textarea')).filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 80 && r.height > 20 && window.getComputedStyle(el).visibility !== 'hidden';
        });
        return texts.sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0] || null;
      };

      const textarea = findComposer();
      if (!textarea) {
        throw new Error('Pi composer textarea not found');
      }

      const findSubmit = () => {
        const byLabel = Array.from(document.querySelectorAll('button')).find((button) => {
          const label = (button.getAttribute('aria-label') || '').toLowerCase();
          return label.includes('submit') || label === 'send' || label.includes('send message');
        });
        if (byLabel) return byLabel;
        return textarea.closest('form')?.querySelector('button[type="submit"]') || null;
      };

      const submitButton = findSubmit();

      const valueSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      valueSetter.call(textarea, prompt);
      textarea.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: prompt }));
      textarea.dispatchEvent(new Event('change', { bubbles: true }));
      textarea.focus();
      await sleep(200);
      if (submitButton && !submitButton.disabled) {
        submitButton.click();
      } else {
        textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }));
        textarea.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }));
      }

      let lastOutboundText = '';
      let stablePolls = 0;
      while (Date.now() - startedAt < timeoutMs) {
        const current = await history();
        const messages = current.messages || [];
        const newMessages = messages.filter((message) => !knownIds.has(message.sid));
        const outboundMessages = newMessages.filter((message) => message.direction === 'outbound' && message.text);
        if (outboundMessages.length) {
          const latest = outboundMessages[outboundMessages.length - 1];
          const latestText = String(latest.text || '').trim();
          if (latestText) {
            if (latestText === lastOutboundText) {
              stablePolls += 1;
            } else {
              lastOutboundText = latestText;
              stablePolls = 0;
            }
            if (stablePolls >= stablePollsRequired) {
              return {
                ok: true,
                conversationId: conversationId(),
                content: latestText,
                sentAt: latest.sentAt || '',
                messageId: latest.sid || '',
              };
            }
          }
        }
        await sleep(pollDelayMs);
      }

      throw new Error('Timed out waiting for Pi response');
    })()
  `;

  try {
    const evaluation = await send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (evaluation.exceptionDetails) {
      const details = evaluation.exceptionDetails;
      const description =
        details.exception?.description ||
        details.text ||
        "Pi browser bridge evaluation failed";
      throw new Error(description);
    }
    return evaluation.result.value || {};
  } finally {
    ws.close();
  }
}

async function bridgePrompt(port, baseUrl, prompt, timeoutMs) {
  const origin = new URL(baseUrl).origin;
  const target = await connectTarget(port, origin);
  return await readPrompt(target, prompt, timeoutMs);
}

const port = Number(argValue("--port", String(DEFAULT_PORT))) || DEFAULT_PORT;
const baseUrl = argValue("--base-url", DEFAULT_BASE_URL) || DEFAULT_BASE_URL;
const prompt = argValue("--prompt", "").trim();
const timeoutMs = Number(argValue("--timeout-ms", String(DEFAULT_TIMEOUT_MS))) || DEFAULT_TIMEOUT_MS;

if (!prompt) {
  throw new Error("--prompt is required");
}

const result = await bridgePrompt(port, baseUrl, prompt, timeoutMs);
console.log(JSON.stringify(result));
