/* background.js — пассивный перехват заголовков запросов провайдеров.
   Куки и localStorage попап уже умеет собирать, а сетевые заголовки (bx-* у
   Qwen и т.п.) расширению не были видны — теперь перехватываем их здесь.
   MV3: webRequest наблюдательный (не блокирующий). Подписка активна только
   для хостов из host_permissions — события на чужих хостах не приходят. */

const STORAGE_KEY = "rzaiHeaderCapture";

/* Заголовки-кандидаты, похожие на токены/ключи, для любых провайдеров */
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
];

/* Специфичные заголовки по хостам (bx-* у Qwen и др. по мере обнаружения) */
const HOST_HEADERS = {
  "chat.qwen.ai": ["bx-ua", "bx-umidtoken", "bx-v", "timezone"],
};

/* Хосты, где для диагностики/полноты ловим ВСЕ заголовки запросов к API */
const HOST_FULL_HEADERS = {
  "chat.qwen.ai": /(chat\/completions|chats\/new)/,
};

/* bx-ua различается для фаз create (/api/v2/chats/new) и chat (/chat/completions) */
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
        /* bx-ua разный для create/chat — храним оба варианта отдельно */
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