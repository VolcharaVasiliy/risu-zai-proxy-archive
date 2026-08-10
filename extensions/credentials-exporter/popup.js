/* popup.js — RisuAI Proxy Credentials Exporter
   Собирает куки и localStorage-токены провайдеров и собирает credentials.json. */

const $ = (id) => document.getElementById(id);

/* Порядок ключей — как в credentials.json репозитория.
   OPENAI_WEB_COOKIE добавлен в конец (читается proxy для openai-web). */
const REPO_KEYS = [
  "ZAI_TOKEN",
  "DEEPSEEK_TOKEN",
  "ARCEE_ACCESS_TOKEN",
  "GEMINI_WEB_COOKIE",
  "GOOGLE_AI_STUDIO_API_KEY",
  "GROK_COOKIE",
  "KIMI_TOKEN",
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
  "INFLECTION_TOKEN",
  "INFLECTION_COOKIE",
  "PI_LOCAL_TOKEN",
  "QWEN_AI_COOKIE",
  "QWEN_AI_TOKEN",
  "QWEN_AI_BX_COOKIE",
  "QWEN_AI_BX_TOKEN",
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

/* ---------- провайдеры ---------- */

const PROVIDERS = [
  {
    id: "zai",
    name: "Z.ai (GLM)",
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
    keys: ["ARCEE_ACCESS_TOKEN"],
    async run() {
      const token = await findCookie("https://api.arcee.ai/", "access_token");
      setCred("ARCEE_ACCESS_TOKEN", token);
      return { ok: !!token, detail: token ? "access_token есть" : "нет куки access_token" };
    },
  },
  {
    id: "gemini-web",
    name: "Gemini Web",
    keys: ["GEMINI_WEB_COOKIE"],
    async run() {
      const cookie = await cookieHeader("https://gemini.google.com/");
      setCred("GEMINI_WEB_COOKIE", cookie);
      return { ok: !!cookie, detail: cookie ? `${cookie.split("; ").length} кук` : "нет кук" };
    },
  },
  {
    id: "ai-studio",
    name: "AI Studio",
    keys: ["GOOGLE_AI_STUDIO_API_KEY"],
    async run() {
      const key = $("studioKey").value.trim();
      setCred("GOOGLE_AI_STUDIO_API_KEY", key);
      return { ok: !!key, detail: key ? "ключ задан" : "введите ключ ниже" };
    },
  },
  {
    id: "grok",
    name: "Grok",
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
    keys: ["KIMI_TOKEN"],
    async run() {
      let token = await findCookie("https://www.kimi.com/", "access_token");
      if (!token) token = await findCookie("https://kimi.com/", "access_token");
      if (!token) {
        const ls = await readLsOnActiveTab("kimi.com", [
          { key: "access_token", json: false },
          { key: "anonymous_access_token", json: false },
        ]);
        if (ls) token = String(ls.access_token || ls.anonymous_access_token || "").trim();
      }
      setCred("KIMI_TOKEN", token);
      return {
        ok: !!token,
        detail: token ? "access_token есть" : "нет токена — войдите в kimi и откройте сайт во вкладке",
      };
    },
  },
  {
    id: "inception",
    name: "Inception",
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
    keys: ["MISTRAL_COOKIE", "MISTRAL_CSRF_TOKEN"],
    async run() {
      const cookie = await cookieHeader("https://console.mistral.ai/");
      const list = await cookieList("https://console.mistral.ai/");
      const csrf = list.find((c) => c.name.startsWith("csrf_token_"));
      setCred("MISTRAL_COOKIE", cookie);
      setCred("MISTRAL_CSRF_TOKEN", csrf && csrf.value);
      return { ok: !!csrf, detail: csrf ? "csrf есть" : "нет csrf_token" };
    },
  },
  {
    id: "mimo",
    name: "MiMo",
    keys: ["MIMO_COOKIE", "MIMO_SERVICE_TOKEN", "MIMO_USER_ID", "MIMO_PH_TOKEN"],
    async run() {
      const hosts = ["aistudio.xiaomimimo.com", "xiaomimimo.com"];
      const want = {
        st: ["xiaomichatbot_serviceToken", "serviceToken"],
        uid: ["userId"],
        ph: ["xiaomichatbot_ph"],
      };
      const found = { st: "", uid: "", ph: "" };
      let cookie = "";
      for (const h of hosts) {
        if (!cookie) cookie = await cookieHeader(`https://${h}/`);
        const list = await cookieList(`https://${h}/`);
        for (const key of Object.keys(want)) {
          if (found[key]) continue;
          for (const cname of want[key]) {
            const hit = list.find((c) => c.name === cname);
            if (hit) {
              found[key] = unquote(hit.value);
              break;
            }
          }
        }
      }
      const st = found.st, uid = found.uid, ph = found.ph;
      setCred("MIMO_SERVICE_TOKEN", st);
      setCred("MIMO_USER_ID", uid);
      setCred("MIMO_PH_TOKEN", ph);
      setCred("MIMO_COOKIE", st && uid && ph ? `serviceToken=${st}; userId=${uid}; xiaomichatbot_ph=${ph}` : "");
      return { ok: !!(st && uid && ph), detail: st && uid && ph ? "все три токена есть" : "не хватает токенов" };
    },
  },
  {
    id: "chatgpt",
    name: "ChatGPT",
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
    keys: ["PHIND_COOKIE", "PHIND_NONCE"],
    async run() {
      /* Прокси ходит на phindai.org (WordPress AJAX) — куки нужны именно оттуда,
         nonce вытаскиваем из HTML страницы /phind-chat/ */
      let cookie = await cookieHeader("https://phindai.org/");
      if (!cookie) cookie = await cookieHeader("https://www.phind.com/");
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
      return {
        ok: !!cookie,
        detail: cookie
          ? `${cookie.split("; ").length} кук` + (nonce ? " + nonce" : ", nonce не найден")
          : "нет кук — зайдите на phindai.org",
      };
    },
  },
  {
    id: "qwen",
    name: "Qwen",
    keys: ["QWEN_AI_COOKIE", "QWEN_AI_TOKEN"],
    async run() {
      const url = "https://chat.qwen.ai/";
      let cookie = await cookieHeader(url);
      if (!cookie) cookie = await cookieHeader("https://qwen.ai/");
      let token = await findCookie(url, "token");
      if (!token) token = await findCookie("https://qwen.ai/", "token");
      if (!token) {
        const ls = await readLsOnActiveTab("chat.qwen.ai", [{ key: "Qwen-Max-User-Info", json: true }]);
        if (ls) token = String(ls["Qwen-Max-User-Info"] || "").trim();
      }
      setCred("QWEN_AI_COOKIE", cookie);
      setCred("QWEN_AI_TOKEN", token);
      return { ok: !!cookie, detail: cookie ? (token ? "куки и токен есть" : "куки есть") : "нет кук — зайдите на chat.qwen.ai" };
    },
  },
  {
    id: "chatglm",
    name: "ChatGLM",
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
        result = { ok: false, detail: "ошибка" };
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
  } finally {
    sweep.remove();
    btn.disabled = false;
    btn.classList.remove("scanning");
    btn.querySelector(".scan-btn-label").textContent = "Сканировать";
  }
}

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

chrome.storage.local.get({ [STORE_KEY]: null, studioKey: "" }, (data) => {
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
