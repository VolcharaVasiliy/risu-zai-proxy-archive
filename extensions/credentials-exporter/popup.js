/* popup.js — RisuAI Proxy Credentials Exporter
   Собирает куки и localStorage-токены провайдеров и собирает credentials.json. */

const $ = (id) => document.getElementById(id);

/* Порядок ключей — как в credentials.json репозитория.
   OPENAI_WEB_COOKIE добавлен в конец (читается proxy для openai-web). */
const REPO_KEYS = [
  "ZAI_TOKEN",
  "DEEPSEEK_TOKEN",
  "ARCEE_ACCESS_TOKEN",
  "ARCEE_REFRESH_TOKEN",
  "GEMINI_WEB_COOKIE",
  "GEMINI_WEB_SECURE_1PSID",
  "GEMINI_WEB_SECURE_1PSIDTS",
  "GOOGLE_AI_STUDIO_API_KEY",
  "GROK_COOKIE",
  "KIMI_TOKEN",
  "KIMI_REFRESH_TOKEN",
  "INCEPTION_SESSION_TOKEN",
  "INCEPTION_COOKIE",
  "LONGCAT_COOKIE",
  "MISTRAL_COOKIE",
  "MISTRAL_CSRF_TOKEN",
  "MIMO_SERVICE_TOKEN",
  "MIMO_USER_ID",
  "MIMO_PH_TOKEN",
  "MIMO_COOKIE",
  "OPENAI_WEB_ACCESS_TOKEN",
  "PERPLEXITY_COOKIE",
  "PHIND_COOKIE",
  "PHIND_NONCE",
  "INFLECTION_API_KEY",
  "PI_LOCAL_TOKEN",
  "QWEN_AI_COOKIE",
  "QWEN_AI_TOKEN",
  "QWEN_AI_BX_UA",
  "QWEN_AI_BX_UA_CREATE",
  "QWEN_AI_BX_UA_CHAT",
  "QWEN_AI_BX_UMIDTOKEN",
  "QWEN_AI_BX_V",
  "QWEN_AI_TIMEZONE",
  "UNCLOSEAI_TOKEN",
  "UNCLOSEAI_COOKIE",
  "PERPLEXITY_SESSION_TOKEN",
  "GLM_REFRESH_TOKEN",
  "OPENAI_WEB_COOKIE",
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
          /* оставить сырое значение */
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

/* Ищет в localStorage активной вкладки ключи, похожие на токены, и
   возвращает {имя: значение}. См. readLsProbe. */
const LS_PROBE = () => {
  const out = {};
  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i);
      if (k && /token|user|auth/i.test(k)) out[k] = window.localStorage.getItem(k);
    }
  } catch (e) {
    /* нет доступа */
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

/* Снимает обёртку из кавычек с значений кук ("value" -> value) */
function unquote(v) {
  let s = String(v == null ? "" : v).trim();
  if (s.length >= 2 && s[0] === '"' && s[s.length - 1] === '"') s = s.slice(1, -1);
  return s;
}

/* ---------- сетевой перехват (background.js) ---------- */

function readHeaderCapture(host) {
  return new Promise((resolve) => {
    chrome.storage.local.get({ rzaiHeaderCapture: {} }, (data) => {
      const map = data.rzaiHeaderCapture || {};
      resolve(map[host] || null);
    });
  });
}

/* ---------- CDP-фолбэк ----------
   cookies API видит только непартиционированные куки текущего cookie store.
   Через CDP (chrome.debugger) читаем куки активной вкладки напрямую —
   видны httpOnly и партиционированные. */
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
            /* уже отцеплен */
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
        /* не прикреплялись */
      }
    }
    return result;
  } catch (e) {
    return null;
  }
}

/* ---------- провайдеры ---------- */

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
      return { ok: !!token, detail: token ? "токен есть" : "нет токена" };
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
      return { ok: !!token, detail: token ? "токен есть" : "нет токена" };
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
      /* refresh_token — httpOnly-кука (~30 дней); даёт прокси вечно
         обновлять access_token через POST /app/v1/refresh (как браузер). */
      const refresh = await findCookie("https://api.arcee.ai/", "refresh_token");
      setCred("ARCEE_REFRESH_TOKEN", refresh);
      const ok = !!token;
      const detail = token
        ? `access_token есть${refresh ? ", refresh_token есть" : ", refresh_token НЕТ"}`
        : "нет куки access_token";
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
      const detail = s1psid ? "SID есть" : cookie ? "SID нет" : "нет кук";
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
      return { ok: !!key, detail: key ? "ключ задан" : "введите ключ ниже" };
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
      return { ok: !!key, detail: key ? "ключ задан" : "введите ключ ниже" };
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
      return { ok: cookie.includes("sso"), detail: cookie ? `${cookie.split("; ").length} кук` : "нет кук" };
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
        /* ищем любые токеноподобные ключи, чтобы обнаружить refresh-механизм */
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
        detail: `access ${token ? "есть" : "НЕТ"}, refresh ${refresh ? "есть" : "НЕТ"}${keys}`,
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
      return { ok: !!session, detail: session ? "сессия есть" : "нет сессии" };
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
      return { ok: !!cookie, detail: cookie ? `${cookie.split("; ").length} кук` : "нет кук" };
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
        /* сессионная кука может быть партиционированной — cookies API её не видит (как у mimo) */
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
        detail = "csrf есть";
        if (cdpUsed) detail += " (CDP)";
      } else {
        detail = "нет csrf_token";
        if (cdpUsed) detail = "нет csrf_token (CDP)";
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
        /* без доступа */
      }
      let list = all.filter(
        (c) => c.domain === "xiaomimimo.com" || c.domain.endsWith(".xiaomimimo.com")
      );
      /* cookies API не видит (партиционирование/инкогнито) — пробуем CDP */
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
        detail = "все три токена есть";
      } else if (!list.length && !cdpUsed) {
        detail = "0 кук на xiaomimimo — откройте сайт во вкладке этого браузера или включите расширению доступ в инкогнито";
      } else {
        detail = `нет: ${missing.join(", ")} (${list.length} кук на xiaomimimo${cdpUsed ? ", CDP" : ""})`;
      }
      return { ok: !!(st && uid && ph), detail };
    },
  },
  {
    id: "chatgpt",
    name: "ChatGPT",
    url: "https://chatgpt.com/",
    keys: ["OPENAI_WEB_COOKIE", "OPENAI_WEB_ACCESS_TOKEN"],
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
        /* без доступа */
      }
      setCred("OPENAI_WEB_ACCESS_TOKEN", accessToken);
      setCred("OPENAI_WEB_COOKIE", cookie);
      return { ok: !!(accessToken || cookie), detail: accessToken ? "accessToken есть" : cookie ? `${cookie.split("; ").length} кук` : "нет кук" };
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
      return { ok: !!session, detail: session ? "session-token есть" : cookie ? "нет session-token" : "нет кук" };
    },
  },
  {
    id: "phind",
    name: "Phind",
    url: "https://phindai.org/phind-chat/",
    keys: ["PHIND_COOKIE", "PHIND_NONCE"],
    async run() {
      /* Прокси ходит на phindai.org (WordPress AJAX) — куки нужны именно оттуда,
         nonce вытаскиваем из HTML страницы /phind-chat/ */
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
        /* сеть недоступна из попапа */
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
        detail = `${cookie.split("; ").length} кук` + (nonce ? " + nonce" : ", nonce не найден");
        if (cdpUsed) detail += " (CDP)";
      } else {
        detail = cdpUsed
          ? "0 кук на phind даже через CDP — зайдите на phindai.org в этом браузере"
          : "нет кук — откройте phindai.org во вкладке этого браузера";
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
      /* CDP видит httpOnly и партиционированные куки (ssxmod_*, acw_tc и др.),
         chrome.cookies API их пропускает — вкладка должна быть на chat.qwen.ai */
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
        /* имя ключа могло поменяться — ищем похожие ключи в localStorage */
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
              /* сырое значение */
            }
            if (cand.length > 40) {
              token = cand;
              break;
            }
          }
        }
      }
      const cap = await readHeaderCapture("chat.qwen.ai");
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
      }
      setCred("QWEN_AI_COOKIE", cookie);
      setCred("QWEN_AI_TOKEN", token);
      const bxInfo = cap && cap.headers && (cap.headers["bx-ua"] || cap.headers["bx-umidtoken"])
        ? "; bx-* перехвачены"
        : "";
      const nCookies = cookie ? cookie.split("; ").filter(Boolean).length : 0;
      const cdpNote = cdp && Array.isArray(cdp) ? " (CDP)" : "";
      return {
        ok: !!cookie,
        detail: cookie
          ? `${nCookies} кук${cdpNote}, токен ${token ? "есть" : "нет"}${bxInfo}`
          : "нет кук — зайдите на chat.qwen.ai" + bxInfo,
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
      return { ok: !!rt, detail: rt ? "refresh_token есть" : "нет refresh_token" };
    },
  },
];

/* ---------- UI ---------- */

const STORE_KEY = "rzaiCreds";

let creds = null;
const chipStates = {};

/* Записывает значение только если оно непустое — пустые результаты
   сканирования не затирают ранее собранные токены. */
function setCred(key, value) {
  const v = String(value == null ? "" : value).trim();
  if (v) creds[key] = v;
}

function saveState() {
  chrome.storage.local.set({ [STORE_KEY]: { creds, chips: chipStates } });
}

function refreshClearBtn() {
  const hasData = Object.keys(chipStates).some((id) => chipStates[id].state === "ok");
  $("clearBtn").classList.toggle("hidden", !hasData);
}

function refreshPreview() {
  const json = JSON.stringify(creds, null, 2);
  $("jsonOut").value = json;
  const hasData = Object.keys(creds).some((k) => String(creds[k] || "").trim());
  $("dlBtn").disabled = !hasData;
  if (hasData) {
    $("jsonToggle").classList.add("open");
    $("jsonBody").classList.remove("hidden");
  }
}

function makeChips() {
  const grid = $("grid");
  grid.innerHTML = "";
  for (const p of PROVIDERS) {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.id = `chip-${p.id}`;
    chip.title = p.name;
    chip.innerHTML = `<span class="dot"></span><span class="name">${p.name}</span><span class="count"></span>`;
    if (p.url) {
      chip.addEventListener("click", () => chrome.tabs.create({ url: p.url }));
    }
    grid.appendChild(chip);
  }
}

function setChip(id, state, detail) {
  const chip = $(`chip-${id}`);
  if (!chip) return;
  chip.classList.remove("scanning", "ok", "err");
  if (state) chip.classList.add(state);
  if (detail) {
    chip.title = detail;
    chip.querySelector(".count").textContent = detail;
  }
}

function showHint(text) {
  const hint = $("hint");
  hint.textContent = text;
  hint.classList.toggle("hidden", !text);
}

async function scan() {
  const btn = $("scanBtn");
  const sweep = document.createElement("div");
  sweep.className = "sweep";
  $("grid").parentElement.appendChild(sweep);
  btn.disabled = true;
  btn.classList.add("scanning");
  btn.querySelector(".scan-btn-label").textContent = "Сканирование…";
  showHint("");

  try {
    for (const p of PROVIDERS) setChip(p.id, "pending", "");

    for (const p of PROVIDERS) {
      setChip(p.id, "scanning", "…");
      let result;
      try {
        result = await p.run();
      } catch (e) {
        result = {
          ok: false,
          detail: e && e.message ? "ошибка: " + e.message : "ошибка: " + String(e),
        };
      }
      const kept = p.keys.some((k) => String(creds[k] || "").trim());
      let state = "err";
      let detail = result.detail || "";
      if (result.ok) {
        state = "ok";
      } else if (kept) {
        state = "ok";
        detail = detail ? `${detail} — оставлен прежний` : "оставлен прежний";
      }
      setChip(p.id, state, detail);
      chipStates[p.id] = { state, detail };
      saveState();
      await new Promise((r) => setTimeout(r, 120));
    }

    refreshPreview();
    refreshClearBtn();

    const activeHost = await activeTabHost();
    const lsProviders = ["chat.z.ai", "chat.deepseek.com", "chat.qwen.ai", "chatglm.cn", "kimi.com"];
    const missing = lsProviders.filter((h) => !(activeHost && activeHost.includes(h)));
    if (missing.length) {
      showHint(
        "Совет: для Z.ai, DeepSeek, Qwen, ChatGLM и Kimi откройте сайт во вкладке и нажмите «Сканировать» ещё раз — так подхватятся localStorage-токены."
      );
    }
  } catch (e) {
    showHint("Ошибка расширения: " + (e && e.message ? e.message : String(e)));
  } finally {
    sweep.remove();
    btn.disabled = false;
    btn.classList.remove("scanning");
    btn.querySelector(".scan-btn-label").textContent = "Сканировать";
  }
}

window.addEventListener("error", (e) => {
  showHint("Ошибка расширения: " + (e.message || "неизвестная"));
});
window.addEventListener("unhandledrejection", (e) => {
  const reason = e.reason;
  showHint("Ошибка расширения: " + (reason && reason.message ? reason.message : String(reason)));
});

async function activeTabHost() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return tab && tab.url ? new URL(tab.url).hostname : "";
  } catch (e) {
    return "";
  }
}

$("scanBtn").addEventListener("click", scan);

$("apiToggle").addEventListener("click", () => {
  $("apiToggle").classList.toggle("open");
  $("apiBody").classList.toggle("hidden");
});

$("jsonToggle").addEventListener("click", () => {
  $("jsonToggle").classList.toggle("open");
  $("jsonBody").classList.toggle("hidden");
});

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
      out.cdp = "недоступно — активируйте вкладку с сайтом или CDP не прикрепился";
    }
    const headerCapture = await new Promise((resolve) => {
      chrome.storage.local.get({ rzaiHeaderCapture: {} }, (data) =>
        resolve(data.rzaiHeaderCapture || {})
      );
    });
    out.headerCapture = headerCapture;
    $("jsonToggle").classList.add("open");
    $("jsonBody").classList.remove("hidden");
    $("jsonOut").value = JSON.stringify(out, null, 2);
  } catch (e) {
    showHint("Ошибка расширения: " + (e && e.message ? e.message : String(e)));
  }
});

$("copyBtn").addEventListener("click", async () => {
  const text = $("jsonOut").value;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    const btn = $("copyBtn");
    btn.classList.add("copy-flash");
    btn.textContent = "Скопировано";
    setTimeout(() => {
      btn.classList.remove("copy-flash");
      btn.textContent = "Копировать";
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

/* ---------- init ---------- */

creds = {};
for (const key of REPO_KEYS) creds[key] = "";

makeChips();

chrome.storage.local.get({ [STORE_KEY]: null, studioKey: "", inflectionKey: "" }, (data) => {
  const saved = data[STORE_KEY];
  if (saved && saved.creds) {
    for (const key of REPO_KEYS) {
      if (typeof saved.creds[key] === "string") creds[key] = saved.creds[key];
    }
    for (const p of PROVIDERS) {
      const st = saved.chips && saved.chips[p.id];
      if (st && st.state && st.state !== "scanning" && st.state !== "pending") {
        chipStates[p.id] = st;
        setChip(p.id, st.state, st.detail);
      }
    }
    refreshPreview();
    refreshClearBtn();
  }
  if (data.studioKey) $("studioKey").value = data.studioKey;
  if (data.inflectionKey) $("inflectionKey").value = data.inflectionKey;
});

$("clearBtn").addEventListener("click", () => {
  creds = {};
  for (const key of REPO_KEYS) creds[key] = "";
  for (const id of Object.keys(chipStates)) delete chipStates[id];
  for (const p of PROVIDERS) setChip(p.id, "pending", "");
  $("jsonOut").value = "";
  $("dlBtn").disabled = true;
  $("jsonToggle").classList.remove("open");
  $("jsonBody").classList.add("hidden");
  showHint("");
  chrome.storage.local.remove(STORE_KEY);
  refreshClearBtn();
});

$("studioKey").addEventListener("input", (e) => {
  chrome.storage.local.set({ studioKey: e.target.value.trim() });
});

$("inflectionKey").addEventListener("input", (e) => {
  chrome.storage.local.set({ inflectionKey: e.target.value.trim() });
});
