import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import http from "node:http";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.dirname(__dirname);
const EDGE = process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const DEBUG_PORT = parseInt(process.env.LM_ARENA_BRIDGE_DEBUG_PORT || "9234", 10);
const SITE_KEY = "6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0";
const ACTION = "chat_submit";
const PORT = parseInt(process.env.LM_ARENA_BRIDGE_PORT || "8772", 10);
const RECAPTCHA_FILE = process.env.LM_ARENA_CAPTCHA_FILE || path.join(PROJECT_ROOT, "lmarena-recaptcha.json");
const SESSION_FILE = process.env.LM_ARENA_SESSION_FILE || path.join(PROJECT_ROOT, "lmarena-session.json");
const COOKIE_FILE = process.env.LM_ARENA_COOKIE_FILE || "C:\\Users\\gamer\\Desktop\\lmarena-cookie.txt";
const cookieFile = process.argv.includes("--cookie-file")
  ? process.argv[process.argv.indexOf("--cookie-file") + 1]
  : COOKIE_FILE;
const proxy = process.env.ARENA_PROXY || process.env.HTTPS_PROXY || "http://127.0.0.1:7897";

function argValue(n, f = "") { const i = process.argv.indexOf(n); return i >= 0 && i + 1 < process.argv.length ? String(process.argv[i + 1] || "") : f; }
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function storageSnapshot() { try { const value = JSON.parse(process.env.LM_ARENA_STORAGE || "null"); return value && typeof value === "object" ? value : null; } catch { return null; } }
function loadCookies(f) {
  const out = [];
  let source = [];
  const header = String(process.env.LM_ARENA_COOKIE || "").trim();
  if (header) {
    source = header.split(";").map((part) => {
      const i = part.indexOf("=");
      return i > 0 ? { name: part.slice(0, i).trim(), value: part.slice(i + 1).trim(), domain: "arena.ai", path: "/" } : null;
    }).filter(Boolean);
  } else {
    source = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : [];
    if (!Array.isArray(source) && source && typeof source === "object") {
      const raw = String(source.LM_ARENA_COOKIE || source.lm_arena_cookie || "");
      source = raw.split(";").map((part) => {
        const i = part.indexOf("=");
        return i > 0 ? { name: part.slice(0, i).trim(), value: part.slice(i + 1).trim(), domain: "arena.ai", path: "/" } : null;
      }).filter(Boolean);
    }
  }
  for (const c of source) {
    if (!c || !c.name) continue;
    out.push({ name: c.name, value: c.value, domain: c.domain || "arena.ai", path: c.path || "/",
      secure: !!c.secure, httpOnly: !!c.httpOnly,
      sameSite: c.sameSite === "no_restriction" ? "None" : c.sameSite === "strict" ? "Strict" : "Lax",
      ...(typeof c.expirationDate === "number" ? { expirationDate: Math.floor(c.expirationDate) } : {}) });
  }
  return out;
}
class CDP {
  constructor(ws) { this.ws = ws; this.n = 1; this.p = []; ws.onmessage = (e) => this._m(e.data); }
  on(m, cb) { (this._h = this._h || new Map()).set(m, cb); }
  _m(d) { let m; try { m = JSON.parse(d); } catch { return; }
    if (m.id !== undefined && this.p[m.id]) { const { res, rej } = this.p[m.id]; this.p[m.id] = null;
      m.error ? rej(new Error(m.error.message)) : res(m.result); }
    else if (m.method && this._h && this._h.get(m.method)) this._h.get(m.method)(m.params); }
  send(m, a = {}) { const id = this.n++; return new Promise((res, rej) => { this.p[id] = { res, rej };
    this.ws.send(JSON.stringify({ id, method: m, params: a }));
    setTimeout(() => { if (this.p[id]) { this.p[id] = null; rej(new Error("timeout:" + m)); } }, 60000); }); }
  close() { try { this.ws.close(); } catch {} }
}
async function waitDbg(port, t) { const dl = Date.now() + t; while (Date.now() < dl) { try { if ((await fetch(`http://127.0.0.1:${port}/json/version`)).ok) return true; } catch {} await sleep(300); } return false; }

let cdp = null;
let browserProc = null;

async function restoreStorage() {
  const snapshot = storageSnapshot();
  if (!snapshot) return;
  const source = `(() => {
    const snapshot = ${JSON.stringify(snapshot)};
    const put = (storage, values) => { for (const [key, value] of Object.entries(values || {})) storage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value)); };
    try { put(localStorage, snapshot.local); put(sessionStorage, snapshot.session); } catch {}
  })()`;
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source });
  await cdp.send("Page.navigate", { url: "https://arena.ai/" });
  await sleep(3500);
  await cdp.send("Runtime.evaluate", { expression: `(() => new Promise(async (resolve) => {
    const snapshot = ${JSON.stringify(snapshot)};
    try {
      for (const dbInfo of snapshot.indexedDB || []) {
        const db = await new Promise((res) => { const request = indexedDB.open(dbInfo.name); request.onsuccess = () => res(request.result); request.onerror = () => res(null); });
        if (!db) continue;
        for (const storeInfo of dbInfo.stores || []) {
          if (!db.objectStoreNames.contains(storeInfo.name)) continue;
          await new Promise((res) => {
            const tx = db.transaction(storeInfo.name, 'readwrite');
            const store = tx.objectStore(storeInfo.name);
            for (const record of storeInfo.records || []) {
              try {
                /* Inline keyPath stores reject a separate key argument. */
                if (store.keyPath == null) store.put(record.value, record.key);
                else store.put(record.value);
              } catch {}
            }
            tx.oncomplete = res; tx.onerror = res;
          });
        }
        db.close();
      }
    } catch {}
    resolve(true);
  }))()`, awaitPromise: true, returnByValue: true });
}

async function currentCookieHeader() {
  try {
    const result = await cdp.send("Network.getAllCookies");
    const map = new Map();
    for (const cookie of result.cookies || []) {
      if (cookie.value && String(cookie.domain || "").includes("arena.ai")) map.set(cookie.name, cookie.value);
    }
    return [...map.entries()].map(([name, value]) => `${name}=${value}`).join("; ");
  } catch { return ""; }
}

async function mintToken() {
  if (!cdp) throw new Error("browser not ready");
  const r = await cdp.send("Runtime.evaluate", {
    expression: `(() => new Promise((resolve) => {
      function tryExec(n) {
        if (n > 12) return resolve(null);
        const g = window.grecaptcha;
        if (g && g.enterprise) {
          return g.enterprise.ready(() => {
            g.enterprise.execute('${SITE_KEY}', { action: '${ACTION}' })
              .then((t) => resolve(typeof t === 'string' && t.length >= 100 ? t : null))
              .catch(() => setTimeout(() => tryExec(n + 1), 400));
          });
        }
        setTimeout(() => tryExec(n + 1), 600);
      }
      tryExec(0);
    }))()`,
    returnByValue: true, awaitPromise: true,
  });
  const v = r && r.result ? r.result.value : null;
  return v && typeof v === "string" && v.length >= 100 ? v : null;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const json = (code, obj) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(obj)); };
  if (url.pathname === "/health") return json(200, { ok: true, ready: !!cdp });
  if (url.pathname === "/mint") {
    try {
      const token = await mintToken();
      if (!token) return json(503, { error: "no_token" });
      const payload = { token, captured_at: Date.now() };
      try { fs.writeFileSync(RECAPTCHA_FILE, JSON.stringify(payload), "utf8"); } catch {}
      const cookie = await currentCookieHeader();
      if (cookie) try { fs.writeFileSync(SESSION_FILE, JSON.stringify({ cookie, captured_at: Date.now() }), "utf8"); } catch {}
      return json(200, { ...payload, cookie_updated: !!cookie });
    } catch (e) { return json(500, { error: String(e && e.message || e) }); }
  }
  return json(404, { error: "not found" });
});

async function main() {
  const cookies = loadCookies(cookieFile);
  const ud = path.join(os.tmpdir(), `arena-bridge-${Date.now()}`);
  fs.rmSync(ud, { recursive: true, force: true });
  browserProc = spawn(EDGE, [`--remote-debugging-port=${DEBUG_PORT}`, `--proxy-server=${proxy}`, "--no-first-run", "--no-default-browser-check", "--disable-blink-features=AutomationControlled", "--start-maximized", `--user-data-dir=${ud}`, "about:blank"], { stdio: "ignore", detached: true });
  if (!(await waitDbg(DEBUG_PORT, 30000))) { console.error("no debugger"); process.exit(1); }
  const ti = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/new`, { method: "PUT" })).json();
  const ws = new WebSocket(ti.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("ws")); });
  cdp = new CDP(ws);
  await cdp.send("Network.enable"); await cdp.send("Page.enable"); await cdp.send("Runtime.enable");
  for (const ck of cookies) { try { await cdp.send("Network.setCookie", ck); } catch {} }
  await restoreStorage();
  await cdp.send("Page.navigate", { url: "https://arena.ai/text/direct" });
  await sleep(9000);
  server.listen(PORT, "127.0.0.1", () => console.log(`lmarena recaptcha bridge on http://127.0.0.1:${PORT}`));
  const shutdown = () => { try { cdp.close(); } catch {} try { browserProc.kill("SIGKILL"); } catch {} process.exit(0); };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}
main().catch((e) => { console.error(e.stack || e); try { browserProc && browserProc.kill("SIGKILL"); } catch {} process.exit(1); });
