/* background.js — passive interception of provider request headers.
   The popup already collects cookies and localStorage; network headers (bx-* for
   Qwen, etc.) were invisible to the extension — now we capture them here.
   MV3: webRequest is observer-only (non-blocking). The listener is active only
   for hosts from host_permissions — events from other hosts never arrive. */

const STORAGE_KEY = "rzaiHeaderCapture";

/* Candidate headers that look like tokens/keys, for any provider */
const UNIVERSAL_HEADERS = [
  "authorization",
  "x-api-key",
  "api-key",
  "x-auth-token",
  "x-access-token",
  "x-session-token",
  "x-csrf-token",
  "csrf-token",
  "x-nonce",
  "nonce",
  "x-msh-token",
  "x-msh-session-key",
  "x-msh-ai-token",
  "x-msh-user-id",
  "x-token",
  "x-user-id",
  "openai-sentinel-turnstile-token",
  "openai-sentinel-proof-token",
];

/* Host-specific headers (bx-* for Qwen and others as discovered) */
const HOST_HEADERS = {
  "chat.qwen.ai": ["bx-ua", "bx-umidtoken", "bx-v", "timezone"],
};

/* Hosts where, for diagnostics/completeness, we capture ALL request headers to the API */
const HOST_FULL_HEADERS = {
  "chat.qwen.ai": /(chat\/completions|chats\/new)/,
};

/* bx-ua differs between the create phase (/api/v2/chats/new) and the chat phase (/chat/completions) */
function phaseOf(url) {
  if (/\/api\/v2\/chats\/new/.test(url)) return "create";
  if (/\/chat\/completions/.test(url)) return "chat";
  return null;
}

chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    let host = "";
    try {
      host = new URL(details.url).hostname;
    } catch (e) {
      return;
    }
    const wanted = new Set([...UNIVERSAL_HEADERS, ...(HOST_HEADERS[host] || [])]);
    const fullForHost = HOST_FULL_HEADERS[host];
    const captureFull = fullForHost && fullForHost.test(details.url);
    const picked = {};
    for (const h of details.requestHeaders || []) {
      const name = String(h.name || "").toLowerCase();
      if (!h.value) continue;
      const rec = {
        value: String(h.value),
        at: Date.now(),
        url: details.url,
        phase: name === "bx-ua" ? phaseOf(details.url) : null,
      };
      if (captureFull || wanted.has(name)) {
        picked[name] = rec;
        /* bx-ua differs for create/chat — store both variants separately */
        if (name === "bx-ua" && rec.phase) picked[`bx-ua-${rec.phase}`] = rec;
      }
    }
    if (!Object.keys(picked).length) return;

    chrome.storage.local.get({ [STORAGE_KEY]: {} }, (data) => {
      const store = data[STORAGE_KEY] || {};
      const entry = store[host] || { headers: {}, updatedAt: 0 };
      for (const [name, rec] of Object.entries(picked)) {
        const prev = entry.headers[name];
        if (!prev || rec.at >= prev.at) entry.headers[name] = rec;
      }
      entry.updatedAt = Date.now();
      store[host] = entry;
      chrome.storage.local.set({ [STORAGE_KEY]: store });
    });
  },
  { urls: ["<all_urls>"] },
  ["requestHeaders"]
);