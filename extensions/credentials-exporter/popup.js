/* popup.js — RisuAI Proxy Credentials Exporter
   Collects provider cookies and localStorage tokens and assembles credentials.json. */

const $ = (id) => document.getElementById(id);

/* ---------- i18n (bundled + runtime-switchable) ----------
   Strings live in i18n-bundle.js (generated from _locales). This lets the
   popup switch language live, independent of the browser UI locale. */
const SUPPORTED_LANGS = ["en", "ru", "zh"];
let LANG = "en";

function detectLang() {
  try {
    const ui = (chrome.i18n && chrome.i18n.getUILanguage && chrome.i18n.getUILanguage()) || "en";
    const base = String(ui).split("-")[0];
    if (SUPPORTED_LANGS.includes(base)) return base;
  } catch (e) {}
  return "en";
}
function t(key, fallback) {
  const all = window.I18N || {};
  const dict = all[LANG] || all.en || {};
  const en = all.en || {};
  const v = dict[key] != null ? dict[key] : en[key] != null ? en[key] : fallback != null ? fallback : key;
  return v;
}
function tf(key, vars, fallback) {
  let s = t(key, fallback);
  if (vars) s = s.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : "{" + k + "}"));
  return s;
}

/* Key order matches credentials.json in the repo.
   Grouped by provider; empty keys are not written to the file (see cleanCreds). */
const REPO_KEYS = [
  // Z.ai (GLM, local-only) — localStorage/cookie 'token'
  "ZAI_TOKEN",
  // DeepSeek — localStorage 'userToken'
  "DEEPSEEK_TOKEN",
  // Arcee — cookies from api.arcee.ai
  "ARCEE_ACCESS_TOKEN",
  "ARCEE_REFRESH_TOKEN",
  // Gemini Web — cookies from gemini.google.com
  "GEMINI_WEB_COOKIE",
  "GEMINI_WEB_SECURE_1PSID",
  "GEMINI_WEB_SECURE_1PSIDTS",
  // Google AI Studio (official API key, manual)
  "GOOGLE_AI_STUDIO_API_KEY",
  // Google AI Studio Web (private RPC) — cookies + captured GenerateContent template
  "GOOGLE_AI_STUDIO_WEB_COOKIE",
  "GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE",
  // Grok (local-only) — cookies from grok.com
  "GROK_COOKIE",
  // Kimi — cookie/localStorage 'access_token'
  "KIMI_TOKEN",
  "KIMI_REFRESH_TOKEN",
  // Inception — cookie 'session'
  "INCEPTION_SESSION_TOKEN",
  "INCEPTION_COOKIE",
  // LongCat — cookies from longcat.chat
  "LONGCAT_COOKIE",
  // Mistral — cookies from console.mistral.ai
  "MISTRAL_COOKIE",
  "MISTRAL_CSRF_TOKEN",
  // MiMo — cookies from xiaomimimo.com
  "MIMO_SERVICE_TOKEN",
  "MIMO_USER_ID",
  "MIMO_PH_TOKEN",
  "MIMO_COOKIE",
  // OpenAI Web — cookies + accessToken from /api/auth/session + sentinel turnstile
  "OPENAI_WEB_ACCESS_TOKEN",
  "OPENAI_WEB_COOKIE",
  "OPENAI_WEB_SENTINEL_TURNSTILE",
  // Perplexity — cookies + session-token
  "PERPLEXITY_COOKIE",
  "PERPLEXITY_SESSION_TOKEN",
  // Phind — cookies + nonce
  "PHIND_COOKIE",
  "PHIND_NONCE",
  // Inflection (official API key, manual)
  "INFLECTION_API_KEY",
  // Qwen — cookies from chat.qwen.ai + bx-* headers (session/IP-bound)
  "QWEN_AI_COOKIE",
  "QWEN_AI_TOKEN",
  "QWEN_AI_BX_UA",
  "QWEN_AI_BX_UA_CREATE",
  "QWEN_AI_BX_UA_CHAT",
  "QWEN_AI_BX_UMIDTOKEN",
  "QWEN_AI_BX_V",
  "QWEN_AI_TIMEZONE",
  // ChatGLM — refresh_token
  "GLM_REFRESH_TOKEN",
];

const LS_READER = (wanted) => {
  const out = {};
  for (const w of wanted || []) {
    try {
      const raw = window.localStorage.getItem(w.key);
      if (raw == null || raw === "") continue;
      let value = raw;
      if (w.json) {
        try {
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === "object") {
            if (typeof parsed.value === "string" && parsed.value) value = parsed.value;
            else if (typeof parsed.access_token === "string" && parsed.access_token)
              value = parsed.access_token;
            else if (typeof parsed.refresh_token === "string" && parsed.refresh_token)
              value = parsed.refresh_token;
            else value = JSON.stringify(parsed);
          }
        } catch (e) {
          /* keep raw value */
        }
      }
      out[w.key] = value;
    } catch (e) {
      out[w.key] = "";
    }
  }
  return out;
};

async function readLsOnActiveTab(pageMatch, wanted) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !/^https?:/.test(tab.url)) return null;
  let host = "";
  try {
    host = new URL(tab.url).hostname;
  } catch (e) {
    return null;
  }
  if (!host.includes(pageMatch)) return null;
  try {
    const res = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: LS_READER,
      args: [wanted],
    });
    return (res && res[0] && res[0].result) || {};
  } catch (e) {
    return null;
  }
}

/* Scans the active tab's localStorage for keys that look like tokens and
   returns {name: value}. See readLsProbe. */
const LS_PROBE = () => {
  const out = {};
  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i);
      if (k && /token|user|auth/i.test(k)) out[k] = window.localStorage.getItem(k);
    }
  } catch (e) {
    /* no access */
  }
  return out;
};

async function readLsProbe(pageMatch) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !/^https?:/.test(tab.url)) return null;
  let host = "";
  try {
    host = new URL(tab.url).hostname;
  } catch (e) {
    return null;
  }
  if (!host.includes(pageMatch)) return null;
  try {
    const res = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: LS_PROBE,
    });
    return (res && res[0] && res[0].result) || null;
  } catch (e) {
    return null;
  }
}

async function cookieList(url) {
  try {
    return await chrome.cookies.getAll({ url });
  } catch (e) {
    return [];
  }
}

async function cookieHeader(url) {
  const list = await cookieList(url);
  return list
    .filter((c) => c.value)
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
}

async function findCookie(url, name) {
  const list = await cookieList(url);
  const hit = list.find((c) => c.name === name);
  return (hit && hit.value) || "";
}

/* Strips surrounding quotes from cookie values ("value" -> value) */
function unquote(v) {
  let s = String(v == null ? "" : v).trim();
  if (s.length >= 2 && s[0] === '"' && s[s.length - 1] === '"') s = s.slice(1, -1);
  return s;
}

/* ---------- network interception (background.js) ---------- */

function readHeaderCapture(host) {
  return new Promise((resolve) => {
    chrome.storage.local.get({ rzaiHeaderCapture: {} }, (data) => {
      const map = data.rzaiHeaderCapture || {};
      resolve(map[host] || null);
    });
  });
}

/* ---------- CDP fallback ----------
   The cookies API only sees unpartitioned cookies of the current cookie store.
   Via CDP (chrome.debugger) we read the active tab's cookies directly —
   httpOnly and partitioned cookies become visible. */
function cdpSend(tabId, method, params) {
  return new Promise((resolve) => {
    try {
      chrome.debugger.sendCommand({ tabId }, method, params || {}, (res) => {
        if (chrome.runtime.lastError) return resolve(null);
        resolve(res || {});
      });
    } catch (e) {
      resolve(null);
    }
  });
}

async function readCookiesViaCdp(hostMatch) {
  let tab = null;
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    tab = tabs && tabs[0];
  } catch (e) {
    return null;
  }
  if (!tab || !tab.url || !tab.url.includes(hostMatch)) return null;
  const tabId = tab.id;
  try {
    const result = await Promise.race([
      (async () => {
        try {
          const ok = await new Promise((resolve) => {
            chrome.debugger.attach({ tabId }, "1.3", () => resolve(!chrome.runtime.lastError));
          });
          if (!ok) return null;
          const res = await cdpSend(tabId, "Network.getAllCookies");
          try {
            chrome.debugger.detach({ tabId });
          } catch (e) {
            /* already detached */
          }
          if (!res || !Array.isArray(res.cookies)) return null;
          const out = res.cookies.map((c) => ({
            name: c.name,
            value: c.value,
            domain: c.domain,
            httpOnly: !!c.httpOnly,
            partitioned: !!c.partitionKey,
          }));
          out.tabUrl = tab.url;
          return out;
        } catch (e) {
          return null;
        }
      })(),
      new Promise((resolve) => setTimeout(() => resolve(null), 6000)),
    ]);
    if (!result) {
      try {
        chrome.debugger.detach({ tabId });
      } catch (e) {
        /* was not attached */
      }
    }
    return result;
  } catch (e) {
    return null;
  }
}

/* ---------- providers ---------- */

const PROVIDERS = [
  {
    id: "zai",
    name: "Z.ai (GLM)",
    url: "https://chat.z.ai/",
    keys: ["ZAI_TOKEN"],
    async run() {
      let token = "";
      const ls = await readLsOnActiveTab("chat.z.ai", [{ key: "token", json: false }]);
      if (ls) token = String(ls.token || "").trim();
      if (!token) token = await findCookie("https://chat.z.ai/", "access_token");
      setCred("ZAI_TOKEN", token);
      return { ok: !!token, detail: token ? t("detailTokenOk", "token present") : t("detailNoToken", "no token") };
    },
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    url: "https://chat.deepseek.com/",
    keys: ["DEEPSEEK_TOKEN"],
    async run() {
      let token = "";
      const ls = await readLsOnActiveTab("chat.deepseek.com", [
        { key: "userToken", json: true },
        { key: "token", json: false },
      ]);
      if (ls) {
        token = String(ls.userToken || ls.token || "").trim();
        if (token === "null" || token === "undefined") token = "";
      }
      if (!token) token = await findCookie("https://chat.deepseek.com/", "token");
      setCred("DEEPSEEK_TOKEN", token);
      return { ok: !!token, detail: token ? t("detailTokenOk", "token present") : t("detailNoToken", "no token") };
    },
  },
  {
    id: "arcee",
    name: "Arcee",
    url: "https://api.arcee.ai/",
    keys: ["ARCEE_ACCESS_TOKEN", "ARCEE_REFRESH_TOKEN"],
    async run() {
      const token = await findCookie("https://api.arcee.ai/", "access_token");
      setCred("ARCEE_ACCESS_TOKEN", token);
      /* refresh_token — httpOnly cookie (~30 days); lets the proxy refresh
         access_token forever via POST /app/v1/refresh (like the browser). */
      const refresh = await findCookie("https://api.arcee.ai/", "refresh_token");
      setCred("ARCEE_REFRESH_TOKEN", refresh);
      const ok = !!token;
      const detail = token
        ? t("detailAccessTokenOk", "access_token present") + (refresh ? t("detailRefreshOk", ", refresh_token present") : t("detailRefreshNo", ", refresh_token missing"))
        : t("detailNoAccessTokenCookie", "no access_token cookie");
      return { ok, detail };
    },
  },
  {
    id: "gemini-web",
    name: "Gemini Web",
    url: "https://gemini.google.com/",
    keys: ["GEMINI_WEB_COOKIE", "GEMINI_WEB_SECURE_1PSID", "GEMINI_WEB_SECURE_1PSIDTS"],
    async run() {
      let cookie = await cookieHeader("https://gemini.google.com/");
      let s1psid = "";
      let s1psidts = "";
      const cdp = await readCookiesViaCdp("gemini.google.com");
      if (cdp) {
        const all = [...cdp];
        const pick = (name) => {
          const hit = all.find((c) => c.name === name);
          return hit ? String(hit.value || "") : "";
        };
        s1psid = pick("__Secure-1PSID");
        s1psidts = pick("__Secure-1PSIDTS");
        if (!s1psid || !s1psidts) {
          const google = all.filter((c) => c.domain === ".google.com");
          for (const c of google) {
            if (c.name === "__Secure-1PSID" && !s1psid) s1psid = String(c.value || "");
            if (c.name === "__Secure-1PSIDTS" && !s1psidts) s1psidts = String(c.value || "");
            if (cookie.indexOf(` ${c.name}=`) < 0 && cookie.indexOf(`${c.name}=`) !== 0) {
              cookie += `${cookie ? "; " : ""}${c.name}=${c.value}`;
            }
          }
        }
      }
      setCred("GEMINI_WEB_COOKIE", cookie);
      setCred("GEMINI_WEB_SECURE_1PSID", s1psid);
      setCred("GEMINI_WEB_SECURE_1PSIDTS", s1psidts);
      const detail = s1psid ? t("detailSidOk", "SID present") : cookie ? t("detailSidNo", "SID missing") : t("detailNoCookies", "no cookies");
      return { ok: !!(cookie && s1psid), detail };
    },
  },
  {
    id: "ai-studio",
    name: "AI Studio",
    url: "https://aistudio.google.com/",
    keys: ["GOOGLE_AI_STUDIO_API_KEY"],
    async run() {
      const key = $("studioKey").value.trim();
      setCred("GOOGLE_AI_STUDIO_API_KEY", key);
      return { ok: !!key, detail: key ? t("detailKeySet", "key provided") : t("detailEnterKey", "enter key below") };
    },
  },
  {
    id: "ai-studio-web",
    name: "AI Studio Web",
    url: "https://aistudio.google.com/",
    keys: ["GOOGLE_AI_STUDIO_WEB_COOKIE", "GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE"],
    async run() {
      const cookie = await cookieHeader("https://aistudio.google.com/");
      setCred("GOOGLE_AI_STUDIO_WEB_COOKIE", cookie);
      /* The GenerateContent template — a browser-captured RPC body from DevTools
         ("Copy as fetch" -> request body). Pasted manually in the popup. */
      const tpl = ($("studioWebTemplate") && $("studioWebTemplate").value.trim()) || "";
      setCred("GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE", tpl);
      const detail = cookie
        ? t("detailCookiesOk", "cookies present") + (tpl ? t("detailTemplateOk", ", template present") : t("detailTemplateNo", ", template missing"))
        : t("detailNoCookiesGoToAistudio", "no cookies — open aistudio.google.com");
      return { ok: !!cookie, detail };
    },
  },
  {
    id: "inflection",
    name: "Inflection",
    url: "https://developers.inflection.ai/keys",
    keys: ["INFLECTION_API_KEY"],
    async run() {
      const key = $("inflectionKey").value.trim();
      setCred("INFLECTION_API_KEY", key);
      return { ok: !!key, detail: key ? t("detailKeySet", "key provided") : t("detailEnterKey", "enter key below") };
    },
  },
  {
    id: "grok",
    name: "Grok",
    url: "https://grok.com/",
    keys: ["GROK_COOKIE"],
    async run() {
      const cookie = await cookieHeader("https://grok.com/");
      setCred("GROK_COOKIE", cookie);
      return { ok: cookie.includes("sso"), detail: cookie ? t("detailCookiesCount", "$1 cookies").replace("$1", cookie.split("; ").length) : t("detailNoCookies", "no cookies") };
    },
  },
  {
    id: "kimi",
    name: "Kimi",
    url: "https://www.kimi.com/",
    keys: ["KIMI_TOKEN", "KIMI_REFRESH_TOKEN"],
    async run() {
      let token = await findCookie("https://www.kimi.com/", "access_token");
      if (!token) token = await findCookie("https://kimi.com/", "access_token");
      let refresh = await findCookie("https://www.kimi.com/", "refresh_token");
      if (!refresh) refresh = await findCookie("https://kimi.com/", "refresh_token");
      let found = [];
      if (!token || !refresh) {
        const ls = await readLsOnActiveTab("kimi.com", [
          { key: "access_token", json: false },
          { key: "anonymous_access_token", json: false },
          { key: "refresh_token", json: false },
        ]);
        if (ls) {
          found = Object.keys(ls);
          if (!token) token = String(ls.access_token || ls.anonymous_access_token || "").trim();
          if (!refresh) refresh = String(ls.refresh_token || "").trim();
        }
      }
      if (!token || !refresh) {
        /* look for any token-like keys to discover the refresh mechanism */
        const probe = await readLsProbe("kimi.com");
        if (probe) {
          for (const k of Object.keys(probe)) {
            if (!found.includes(k)) found.push(k);
            if (!token && /access_token|anonymous/i.test(k)) token = String(probe[k] || "").trim();
            if (!refresh && /refresh/i.test(k)) refresh = String(probe[k] || "").trim();
          }
        }
      }
      setCred("KIMI_TOKEN", token);
      setCred("KIMI_REFRESH_TOKEN", refresh);
      const keys = found.length ? `; ls keys: ${found.join(", ")}` : "";
      return {
        ok: !!token,
        detail: "access " + (token ? t("detailYes", "present") : t("detailNo", "missing")) + ", refresh " + (refresh ? t("detailYes", "present") : t("detailNo", "missing")) + keys,
      };
    },
  },
  {
    id: "inception",
    name: "Inception",
    url: "https://chat.inceptionlabs.ai/",
    keys: ["INCEPTION_COOKIE", "INCEPTION_SESSION_TOKEN"],
    async run() {
      const cookie = await cookieHeader("https://chat.inceptionlabs.ai/");
      const session = await findCookie("https://chat.inceptionlabs.ai/", "session");
      setCred("INCEPTION_COOKIE", cookie);
      setCred("INCEPTION_SESSION_TOKEN", session);
      return { ok: !!session, detail: session ? t("detailSessionOk", "session present") : t("detailNoSession", "no session") };
    },
  },
  {
    id: "longcat",
    name: "LongCat",
    url: "https://longcat.chat/",
    keys: ["LONGCAT_COOKIE"],
    async run() {
      const cookie = await cookieHeader("https://longcat.chat/");
      setCred("LONGCAT_COOKIE", cookie);
      return { ok: !!cookie, detail: cookie ? t("detailCookiesCount", "$1 cookies").replace("$1", cookie.split("; ").length) : t("detailNoCookies", "no cookies") };
    },
  },
  {
    id: "mistral",
    name: "Mistral",
    url: "https://console.mistral.ai/",
    keys: ["MISTRAL_COOKIE", "MISTRAL_CSRF_TOKEN"],
    async run() {
      let cookie = await cookieHeader("https://console.mistral.ai/");
      let list = await cookieList("https://console.mistral.ai/");
      let csrf = list.find((c) => c.name === "csrftoken" || c.name.startsWith("csrf_token_"));
      let cdpUsed = false;
      if (!/session/i.test(cookie)) {
        /* the session cookie may be partitioned — the cookies API can't see it (like mimo) */
        const cdp = await readCookiesViaCdp("mistral");
        if (cdp && cdp.length) {
          const hostCookies = cdp.filter((c) => c.domain.includes("mistral.ai"));
          if (hostCookies.length) {
            list = hostCookies;
            cookie = hostCookies
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((c) => `${c.name}=${c.value}`)
              .join("; ");
            const csrfHit = hostCookies.find(
              (c) => c.name === "csrftoken" || c.name.startsWith("csrf_token_")
            );
            if (csrfHit) csrf = csrfHit;
            cdpUsed = true;
          }
        }
      }
      setCred("MISTRAL_COOKIE", cookie);
      setCred("MISTRAL_CSRF_TOKEN", csrf && csrf.value);
      let detail;
      if (csrf) {
        detail = t("detailCsrfOk", "csrf present");
        if (cdpUsed) detail += " (CDP)";
      } else {
        detail = t("detailNoCsrf", "no csrf_token");
        if (cdpUsed) detail = t("detailNoCsrf", "no csrf_token") + " (CDP)";
      }
      return { ok: !!csrf, detail };
    },
  },
  {
    id: "mimo",
    name: "MiMo",
    url: "https://aistudio.xiaomimimo.com/#/c",
    keys: ["MIMO_COOKIE", "MIMO_SERVICE_TOKEN", "MIMO_USER_ID", "MIMO_PH_TOKEN"],
    async run() {
      const found = { st: "", uid: "", ph: "" };
      let all = [];
      try {
        all = await chrome.cookies.getAll({});
      } catch (e) {
        /* no access */
      }
      let list = all.filter(
        (c) => c.domain === "xiaomimimo.com" || c.domain.endsWith(".xiaomimimo.com")
      );
      /* the cookies API can't see them (partitioning/incognito) — try CDP */
      let cdpUsed = false;
      if (!list.length) {
        const cdp = await readCookiesViaCdp("xiaomimimo");
        if (cdp && cdp.length) {
          list = cdp.filter((c) => c.domain.endsWith("xiaomimimo.com"));
          cdpUsed = true;
        }
      }
      for (const c of list) {
        if (c.name === "xiaomichatbot_serviceToken" || c.name === "serviceToken") {
          if (!found.st) found.st = unquote(c.value);
        } else if (c.name === "userId") {
          if (!found.uid) found.uid = unquote(c.value);
        } else if (c.name === "xiaomichatbot_ph") {
          if (!found.ph) found.ph = unquote(c.value);
        }
      }
      const st = found.st, uid = found.uid, ph = found.ph;
      setCred("MIMO_SERVICE_TOKEN", st);
      setCred("MIMO_USER_ID", uid);
      setCred("MIMO_PH_TOKEN", ph);
      setCred("MIMO_COOKIE", st && uid && ph ? `serviceToken=${st}; userId=${uid}; xiaomichatbot_ph=${ph}` : "");
      const missing = [];
      if (!st) missing.push("serviceToken");
      if (!uid) missing.push("userId");
      if (!ph) missing.push("ph");
      let detail;
      if (st && uid && ph) {
        detail = t("detailAllThreeTokens", "all three tokens present");
      } else if (!list.length && !cdpUsed) {
        detail = t("detailMimoNoCookies", "0 cookies on xiaomimimo — open the site in this browser's tab or enable incognito access for the extension");
      } else {
        detail = t("detailMimoMissingPrefix", "missing: ") + missing.join(", ") + " (" + list.length + " " + t("detailMimoCookiesWord", "cookies") + t("detailMimoOnXiaomimimo", " on xiaomimimo") + (cdpUsed ? ", CDP" : "") + ")";
      }
      return { ok: !!(st && uid && ph), detail };
    },
  },
  {
    id: "chatgpt",
    name: "ChatGPT",
    url: "https://chatgpt.com/",
    keys: ["OPENAI_WEB_COOKIE", "OPENAI_WEB_ACCESS_TOKEN", "OPENAI_WEB_SENTINEL_TURNSTILE"],
    async run() {
      const cookie = await cookieHeader("https://chatgpt.com/");
      let accessToken = "";
      try {
        const r = await fetch("https://chatgpt.com/api/auth/session", { credentials: "include" });
        if (r.ok) {
          const data = await r.json();
          if (data && typeof data === "object") {
            accessToken = String(data.accessToken || "");
            if (data.user && data.user.id) accessToken = accessToken || String(data.user.id);
          }
        }
      } catch (e) {
        /* no access */
      }
      /* the sentinel turnstile token is captured by background.js from the
         request headers of chatgpt.com (openai-sentinel-turnstile-token). */
      const cap = await readHeaderCapture("chatgpt.com");
      let turnstile = "";
      if (cap && cap.headers) {
        const rec = (name) => cap.headers[name];
        const val = (name) => (rec(name) && rec(name).value) || "";
        turnstile = val("openai-sentinel-turnstile-token");
      }
      setCred("OPENAI_WEB_ACCESS_TOKEN", accessToken);
      setCred("OPENAI_WEB_COOKIE", cookie);
      setCred("OPENAI_WEB_SENTINEL_TURNSTILE", turnstile);
      let detail = accessToken ? t("detailChatgptAccessTokenOk", "accessToken present") : cookie ? t("detailCookiesCount", "$1 cookies").replace("$1", cookie.split("; ").length) : t("detailNoCookies", "no cookies");
      if (turnstile) detail += " + turnstile";
      return { ok: !!(accessToken || cookie), detail };
    },
  },
  {
    id: "perplexity",
    name: "Perplexity",
    url: "https://www.perplexity.ai/",
    keys: ["PERPLEXITY_COOKIE", "PERPLEXITY_SESSION_TOKEN"],
    async run() {
      const cookie = await cookieHeader("https://www.perplexity.ai/");
      const session = await findCookie("https://www.perplexity.ai/", "__Secure-next-auth.session-token");
      setCred("PERPLEXITY_COOKIE", cookie);
      setCred("PERPLEXITY_SESSION_TOKEN", session);
      return { ok: !!session, detail: session ? t("detailSessionTokenOk", "session-token present") : cookie ? t("detailNoSessionToken", "no session-token") : t("detailNoCookies", "no cookies") };
    },
  },
  {
    id: "phind",
    name: "Phind",
    url: "https://phindai.org/phind-chat/",
    keys: ["PHIND_COOKIE", "PHIND_NONCE"],
    async run() {
      /* The proxy talks to phindai.org (WordPress AJAX) — cookies are needed from
         there specifically; the nonce is extracted from the /phind-chat/ HTML page */
      let cookie = await cookieHeader("https://phindai.org/");
      if (!cookie) cookie = await cookieHeader("https://www.phind.com/");
      let cdpUsed = false;
      if (!cookie) {
        const cdp = await readCookiesViaCdp("phind");
        if (cdp && cdp.length) {
          const hostCookies = cdp.filter(
            (c) => c.domain.includes("phindai.org") || c.domain.includes("phind.com")
          );
          if (hostCookies.length) {
            cookie = hostCookies
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((c) => `${c.name}=${c.value}`)
              .join("; ");
            cdpUsed = true;
          }
        }
      }
      let nonce = "";
      try {
        const r = await fetch("https://phindai.org/phind-chat/", { credentials: "include" });
        if (r.ok) {
          const text = await r.text();
          const patterns = [
            /phindAjax\.nonce\s*=\s*["']([^"']+)["']/,
            /"nonce"\s*:\s*"([^"]+)"/,
            /nonce["']?\s*:\s*["']([^"']+)["']/,
          ];
          for (const re of patterns) {
            const m = text.match(re);
            if (m) {
              nonce = m[1];
              break;
            }
          }
        }
      } catch (e) {
        /* network unavailable from popup */
      }
      if (!nonce) {
        const list = await cookieList("https://www.phind.com/");
        const nonceHit = list.find((c) => /nonce|csrf/i.test(c.name));
        nonce = (nonceHit && nonceHit.value) || "";
      }
      setCred("PHIND_COOKIE", cookie);
      setCred("PHIND_NONCE", nonce);
      let detail;
      if (cookie) {
        detail = t("detailCookiesCount", "$1 cookies").replace("$1", cookie.split("; ").length) + (nonce ? t("detailNonceOk", " + nonce") : t("detailNonceNotFound", ", nonce not found"));
        if (cdpUsed) detail += " (CDP)";
      } else {
        detail = cdpUsed
          ? t("detailPhindNoCookiesCdp", "0 cookies on phind even via CDP — open phindai.org in this browser")
          : t("detailPhindOpenSite", "no cookies — open phindai.org in this browser's tab");
      }
      return { ok: !!cookie, detail };
    },
  },
  {
    id: "qwen",
    name: "Qwen",
    url: "https://chat.qwen.ai/",
    keys: ["QWEN_AI_COOKIE", "QWEN_AI_TOKEN"],
    async run() {
      const url = "https://chat.qwen.ai/";
      /* CDP sees httpOnly and partitioned cookies (ssxmod_*, acw_tc, etc.);
         chrome.cookies API misses them — the tab must be on chat.qwen.ai */
      const cdp = await readCookiesViaCdp("qwen.ai");
      let cookie = await cookieHeader(url);
      if (!cookie) cookie = await cookieHeader("https://qwen.ai/");
      let token = await findCookie(url, "token");
      if (!token) token = await findCookie("https://qwen.ai/", "token");
      if (cdp && Array.isArray(cdp)) {
        const map = new Map();
        for (const c of cdp) {
          if (!c.value) continue;
          if (!String(c.domain || "").includes("qwen.ai")) continue;
          map.set(c.name, c.value);
        }
        const fromCdp = [...map.entries()]
          .map(([name, value]) => `${name}=${value}`)
          .sort()
          .join("; ");
        if (fromCdp) cookie = fromCdp;
        if (!token) {
          const tokenHit = map.get("token");
          if (tokenHit) token = String(tokenHit).trim();
        }
      }
      if (!token) {
        const ls = await readLsOnActiveTab("chat.qwen.ai", [{ key: "Qwen-Max-User-Info", json: true }]);
        if (ls) token = String(ls["Qwen-Max-User-Info"] || "").trim();
      }
      if (!token) {
        /* the key name may have changed — look for similar keys in localStorage */
        const probe = await readLsProbe("chat.qwen.ai");
        if (probe) {
          for (const [k, v] of Object.entries(probe)) {
            if (typeof v !== "string" || !v || v === "null" || v === "undefined") continue;
            let cand = v;
            try {
              const parsed = JSON.parse(v);
              if (parsed && typeof parsed === "object") {
                if (typeof parsed.token === "string" && parsed.token) cand = parsed.token;
                else if (typeof parsed.access_token === "string" && parsed.access_token)
                  cand = parsed.access_token;
              }
            } catch (e) {
              /* raw value */
            }
            if (cand.length > 40) {
              token = cand;
              break;
            }
          }
        }
      }
      /* bx-* headers are captured passively by background.js. They are
         session/IP-bound: Qwen rejects them (RGV587_ERROR) if the proxy runs on a
         different network than the one that captured them (e.g. Vercel's fixed IP). */
      const cap = await readHeaderCapture("chat.qwen.ai");
      let bxInfo = "";
      let qwenBx = null;
      if (cap && cap.headers) {
        const rec = (name) => cap.headers[name];
        const val = (name) => (rec(name) && rec(name).value) || "";
        const bxCreate = val("bx-ua-create") || val("bx-ua");
        const bxChat = val("bx-ua-chat") || val("bx-ua");
        setCred("QWEN_AI_BX_UA", val("bx-ua") || bxCreate || bxChat);
        setCred("QWEN_AI_BX_UA_CREATE", bxCreate);
        setCred("QWEN_AI_BX_UA_CHAT", bxChat);
        setCred("QWEN_AI_BX_UMIDTOKEN", val("bx-umidtoken"));
        setCred("QWEN_AI_BX_V", val("bx-v"));
        setCred("QWEN_AI_TIMEZONE", val("timezone"));
        const hasBx = !!(cap.headers["bx-ua"] || cap.headers["bx-umidtoken"]);
        if (hasBx) {
          const updatedAt = cap.updatedAt || Date.now();
          const ageMin = Math.max(0, Math.round((Date.now() - updatedAt) / 60000));
          bxInfo = "; " + tf("qwenBxFresh", { m: String(ageMin) });
          qwenBx = { updatedAt, hasBx: true };
        }
      }
      lastQwenBx = qwenBx;
      setCred("QWEN_AI_COOKIE", cookie);
      setCred("QWEN_AI_TOKEN", token);
      const nCookies = cookie ? cookie.split("; ").filter(Boolean).length : 0;
      const cdpNote = cdp && Array.isArray(cdp) ? " (CDP)" : "";
      return {
        ok: !!cookie,
        detail: cookie
          ? `${nCookies} ` + t("detailMimoCookiesWord", "cookies") + cdpNote + ", token " + (token ? t("detailYes", "present") : t("detailNo", "missing")) + bxInfo
          : t("detailQwenNoCookies", "no cookies — open chat.qwen.ai") + bxInfo,
      };
    },
  },
  {
    id: "chatglm",
    name: "ChatGLM",
    url: "https://chatglm.cn/",
    keys: ["GLM_REFRESH_TOKEN"],
    async run() {
      let rt = await findCookie("https://chatglm.cn/", "chatglm_refresh_token");
      if (!rt) {
        const ls = await readLsOnActiveTab("chatglm.cn", [{ key: "chatglm_refresh_token", json: false }]);
        if (ls) rt = String(ls.chatglm_refresh_token || "").trim();
      }
      setCred("GLM_REFRESH_TOKEN", rt);
      return { ok: !!rt, detail: rt ? t("detailRefreshTokenOk", "refresh_token present") : t("detailNoRefreshToken", "no refresh_token") };
    },
  },
];

/* ---------- UI ---------- */

const STORE_KEY = "rzaiCreds";

let creds = null;
const chipStates = {};
let lastQwenBx = null;
let lastScanTime = null;

/* Writes the value only if it is non-empty — empty scan results do not
   overwrite previously collected tokens. */
function setCred(key, value) {
  const v = String(value == null ? "" : value).trim();
  if (v) creds[key] = v;
}

function saveState() {
  chrome.storage.local.set({ [STORE_KEY]: { creds, chips: chipStates } });
}

function refreshClearBtn() {
  const hasData = Object.keys(chipStates).some((id) => chipStates[id] && chipStates[id].state === "ok");
  $("clearBtn").classList.toggle("hidden", !hasData);
}

/* Returns only the filled keys — empty "junk" never makes it into credentials.json. */
function cleanCreds() {
  const out = {};
  for (const k of REPO_KEYS) {
    const v = String(creds[k] == null ? "" : creds[k]).trim();
    if (v) out[k] = v;
  }
  return out;
}

function refreshPreview() {
  const data = cleanCreds();
  $("jsonOut").value = JSON.stringify(data, null, 2);
  const hasData = Object.keys(data).length > 0;
  $("dlBtn").disabled = !hasData;
  if (hasData) {
    $("jsonPanel").classList.add("open");
    $("jsonToggle").setAttribute("aria-expanded", "true");
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function makeProviders() {
  const root = $("providers");
  root.innerHTML = "";
  for (const p of PROVIDERS) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "prov";
    row.id = `prov-${p.id}`;
    if (p.url) row.setAttribute("data-url", p.url);
    row.title = p.url || "";
    row.innerHTML =
      '<span class="pdot"></span>' +
      '<span class="pinfo"><span class="pname">' + escapeHtml(p.name) + '</span><span class="pdetail"></span></span>' +
      '<span class="popen">↗</span>';
    if (p.url) row.addEventListener("click", () => chrome.tabs.create({ url: p.url }));
    root.appendChild(row);
  }
}

function setProvider(id, state, detail) {
  const row = $(`prov-${id}`);
  if (!row) return;
  row.classList.remove("pending", "scanning", "ok", "err");
  if (state) row.classList.add(state);
  if (detail != null) row.querySelector(".pdetail").textContent = detail;
}

function showHint(text) {
  const hint = $("hint");
  if (text) {
    hint.textContent = text;
    hint.classList.remove("hidden");
  } else {
    hint.classList.add("hidden");
    hint.textContent = "";
  }
}

function renderQwenWarn(info) {
  const warn = $("warn");
  if (!info || !info.hasBx) {
    warn.classList.add("hidden");
    warn.textContent = "";
    return;
  }
  const ageMin = Math.max(0, Math.round((Date.now() - (info.updatedAt || Date.now())) / 60000));
  if (ageMin <= 30) {
    warn.classList.add("hidden");
    warn.textContent = "";
    return;
  }
  warn.textContent = tf("qwenBxStaleWarn", { m: String(ageMin) });
  warn.classList.remove("hidden");
}

function fmtTime(d) {
  try {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (e) {
    return "";
  }
}

function updateLastScan() {
  const el = $("lastScan");
  if (lastScanTime) el.textContent = tf("lastScan", { t: fmtTime(lastScanTime) });
  else el.textContent = "";
}

async function scan() {
  const btn = $("scanBtn");
  const sweep = document.createElement("div");
  sweep.className = "sweep";
  $("providers").parentElement.appendChild(sweep);
  btn.disabled = true;
  btn.classList.add("scanning");
  btn.querySelector(".scan-btn-label").textContent = t("scanBtnScanning", "Scanning…");
  showHint("");

  try {
    for (const p of PROVIDERS) setProvider(p.id, "pending", "");

    for (const p of PROVIDERS) {
      setProvider(p.id, "scanning", "…");
      let result;
      try {
        result = await p.run();
      } catch (e) {
        result = {
          ok: false,
          detail: e && e.message ? t("errorDetail", "error: ") + e.message : t("errorDetail", "error: ") + String(e),
        };
      }
      const kept = p.keys.some((k) => String(creds[k] || "").trim());
      let state = "err";
      let detail = result.detail || "";
      if (result.ok) {
        state = "ok";
      } else if (kept) {
        state = "ok";
        detail = detail ? `${detail} — ${t("detailKeptPrev", "previous kept")}` : t("detailKeptPrev", "previous kept");
      }
      setProvider(p.id, state, detail);
      chipStates[p.id] = { state, detail };
      saveState();
      await new Promise((r) => setTimeout(r, 120));
    }

    refreshPreview();
    refreshClearBtn();
    lastScanTime = new Date();
    updateLastScan();
    renderQwenWarn(lastQwenBx);

    const activeHost = await activeTabHost();
    const lsProviders = ["chat.z.ai", "chat.deepseek.com", "chat.qwen.ai", "chatglm.cn", "kimi.com"];
    const missing = lsProviders.filter((h) => !(activeHost && activeHost.includes(h)));
    const anyOk = Object.values(chipStates).some((s) => s && s.state === "ok");
    if (missing.length) {
      showHint(t("hintLocalStorage", "Tip: for Z.ai, DeepSeek, Qwen, ChatGLM and Kimi, open the site in a tab and click \"Scan\" again — this picks up localStorage tokens."));
    } else if (anyOk) {
      showHint(t("hintAllOk", "Scanned providers with open tabs. Open a provider site and scan again to collect more."));
    }
  } catch (e) {
    showHint(t("extError", "Extension error: ") + (e && e.message ? e.message : String(e)));
  } finally {
    sweep.remove();
    btn.disabled = false;
    btn.classList.remove("scanning");
    btn.querySelector(".scan-btn-label").textContent = t("scanBtn", "Scan");
  }
}

window.addEventListener("error", (e) => {
  showHint(t("extError", "Extension error: ") + (e.message || "unknown"));
});
window.addEventListener("unhandledrejection", (e) => {
  const reason = e.reason;
  showHint(t("extError", "Extension error: ") + (reason && reason.message ? reason.message : String(reason)));
});

async function activeTabHost() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return tab && tab.url ? new URL(tab.url).hostname : "";
  } catch (e) {
    return "";
  }
}

function togglePanel(panelId, toggleId) {
  const panel = $(panelId);
  const open = panel.classList.toggle("open");
  const tog = $(toggleId);
  if (tog) tog.setAttribute("aria-expanded", open ? "true" : "false");
}

$("scanBtn").addEventListener("click", scan);

$("apiToggle").addEventListener("click", () => togglePanel("apiPanel", "apiToggle"));
$("jsonToggle").addEventListener("click", () => togglePanel("jsonPanel", "jsonToggle"));

$("debugBtn").addEventListener("click", async () => {
  try {
    let all = [];
    try {
      all = await chrome.cookies.getAll({});
    } catch (e) {
      all = [];
    }
    const byDomain = {};
    const tokens = [];
    for (const c of all) {
      byDomain[c.domain] = (byDomain[c.domain] || 0) + 1;
      if (/token|session|service/i.test(c.name)) tokens.push(`${c.domain} :: ${c.name}`);
    }
    const out = {
      total: all.length,
      domains: Object.keys(byDomain)
        .sort((a, b) => a.localeCompare(b))
        .map((d) => `${d} (${byDomain[d]})`),
      tokenLike: tokens.slice(0, 40),
    };
    const cdp = await readCookiesViaCdp("");
    if (cdp) {
      const cdpDomains = {};
      const mimoViaCdp = cdp.filter((c) => c.domain.endsWith("xiaomimimo.com"));
      for (const c of cdp) {
        cdpDomains[c.domain] = (cdpDomains[c.domain] || 0) + 1;
      }
      out.cdp = {
        tabUrl: cdp.tabUrl || undefined,
        total: cdp.length,
        domains: Object.keys(cdpDomains)
          .sort((a, b) => a.localeCompare(b))
          .map((d) => `${d} (${cdpDomains[d]})`),
        xiaomimimoViaCdp: mimoViaCdp.map((c) => c.name),
      };
    } else {
      out.cdp = t("debugCdpUnavailable", "unavailable — activate a tab with the site or CDP did not attach");
    }
    const headerCapture = await new Promise((resolve) => {
      chrome.storage.local.get({ rzaiHeaderCapture: {} }, (data) =>
        resolve(data.rzaiHeaderCapture || {})
      );
    });
    out.headerCapture = headerCapture;
    $("jsonPanel").classList.add("open");
    $("jsonToggle").setAttribute("aria-expanded", "true");
    $("jsonOut").value = JSON.stringify(out, null, 2);
  } catch (e) {
    showHint(t("extError", "Extension error: ") + (e && e.message ? e.message : String(e)));
  }
});

$("copyBtn").addEventListener("click", async () => {
  const text = $("jsonOut").value;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    const btn = $("copyBtn");
    btn.classList.add("copy-flash");
    btn.textContent = t("copyCopied", "Copied");
    setTimeout(() => {
      btn.classList.remove("copy-flash");
      btn.textContent = t("copyBtn", "Copy");
    }, 1200);
  } catch (e) {
    $("jsonOut").select();
    document.execCommand("copy");
  }
});

$("dlBtn").addEventListener("click", () => {
  const text = $("jsonOut").value;
  if (!text) return;
  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "credentials.json";
  a.click();
  URL.revokeObjectURL(url);
});

/* ---------- i18n application + language switch ---------- */

function applyI18n() {
  const setText = (id, key, fb) => {
    const el = $(id);
    if (el) el.textContent = t(key, fb);
  };
  setText("headerSubtitle", "headerSubtitle", "Collecting tokens and cookies for risu-zai-proxy");
  setText("scanBtnLabel", "scanBtn", "Scan");
  setText("clearBtn", "clearBtn", "Clear collected");
  setText("apiToggleLabel", "apiPanelTitle", "Manual API keys");
  setText("studioKeyLabel", "studioKeyLabel", "Google AI Studio (GOOGLE_AI_STUDIO_API_KEY)");
  setText("studioWebTemplateLabel", "studioWebTemplateLabel", "AI Studio Web — GenerateContent template (JSON)");
  setText("inflectionKeyLabel", "inflectionKeyLabel", "Inflection (INFLECTION_API_KEY)");
  setText("jsonToggleLabel", "jsonPanelTitle", "credentials.json preview");
  setText("debugBtn", "debugBtn", "Diagnostics");
  setText("copyBtn", "copyBtn", "Copy");
  setText("dlBtn", "dlBtn", "Download credentials.json");
  setText("footer", "footer", "Install: chrome://extensions → Developer mode → Load unpacked. For Z.ai and DeepSeek, open the site in a tab before scanning.");
  setText("providersTitle", "providersTitle", "Providers");
  const swt = $("studioWebTemplate");
  if (swt) swt.placeholder = t("studioWebTemplatePlaceholder", "from DevTools \"Copy as fetch\" on a GenerateContent request (RPC body). Needed only for generation, not for CountTokens.");
  const ik = $("inflectionKey");
  if (ik) ik.placeholder = t("inflectionKeyPlaceholder", "key from developers.inflection.ai/keys");
  const sk = $("studioKey");
  if (sk) sk.placeholder = t("studioKeyPlaceholder", "AIza...");
  updateLastScan();
  renderQwenWarn(lastQwenBx);
}

function setLang(lang, animate) {
  if (!SUPPORTED_LANGS.includes(lang)) lang = "en";
  LANG = lang;
  try {
    chrome.storage.local.set({ rzaiLang: lang });
  } catch (e) {}
  document.documentElement.lang = lang;
  document.querySelectorAll("#langSwitch button").forEach((b) =>
    b.classList.toggle("active", b.getAttribute("data-lang") === lang)
  );
  applyI18n();
  if (animate) {
    const app = $("app");
    app.classList.remove("lang-fade");
    void app.offsetWidth;
    app.classList.add("lang-fade");
  }
}

/* ---------- init ---------- */

creds = {};
for (const key of REPO_KEYS) creds[key] = "";

makeProviders();
applyI18n();

chrome.storage.local.get(
  { rzaiLang: null, [STORE_KEY]: null, studioKey: "", inflectionKey: "", studioWebTemplate: "" },
  (data) => {
    if (data.rzaiLang && SUPPORTED_LANGS.includes(data.rzaiLang)) {
      LANG = data.rzaiLang;
    } else {
      LANG = detectLang();
    }
    document.documentElement.lang = LANG;
    document.querySelectorAll("#langSwitch button").forEach((b) =>
      b.classList.toggle("active", b.getAttribute("data-lang") === LANG)
    );
    applyI18n();

    const saved = data[STORE_KEY];
    if (saved && saved.creds) {
      for (const key of REPO_KEYS) {
        if (typeof saved.creds[key] === "string") creds[key] = saved.creds[key];
      }
      for (const p of PROVIDERS) {
        const st = saved.chips && saved.chips[p.id];
        if (st && st.state && st.state !== "scanning" && st.state !== "pending") {
          chipStates[p.id] = st;
          setProvider(p.id, st.state, st.detail);
        }
      }
      refreshPreview();
      refreshClearBtn();
    }
    if (data.studioKey) $("studioKey").value = data.studioKey;
    if (data.studioWebTemplate) $("studioWebTemplate").value = data.studioWebTemplate;
    if (data.inflectionKey) $("inflectionKey").value = data.inflectionKey;
  }
);

$("clearBtn").addEventListener("click", () => {
  creds = {};
  for (const key of REPO_KEYS) creds[key] = "";
  for (const id of Object.keys(chipStates)) delete chipStates[id];
  for (const p of PROVIDERS) setProvider(p.id, "pending", "");
  $("jsonOut").value = "";
  $("dlBtn").disabled = true;
  $("jsonPanel").classList.remove("open");
  $("jsonToggle").setAttribute("aria-expanded", "false");
  lastQwenBx = null;
  lastScanTime = null;
  updateLastScan();
  renderQwenWarn(null);
  showHint("");
  chrome.storage.local.remove(STORE_KEY);
  refreshClearBtn();
});

$("studioKey").addEventListener("input", (e) => {
  chrome.storage.local.set({ studioKey: e.target.value.trim() });
});

$("studioWebTemplate").addEventListener("input", (e) => {
  chrome.storage.local.set({ studioWebTemplate: e.target.value.trim() });
});

$("inflectionKey").addEventListener("input", (e) => {
  chrome.storage.local.set({ inflectionKey: e.target.value.trim() });
});

document.querySelectorAll("#langSwitch button").forEach((b) => {
  b.addEventListener("click", () => setLang(b.getAttribute("data-lang"), true));
});
