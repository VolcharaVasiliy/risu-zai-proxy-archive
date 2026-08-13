import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.dirname(__dirname);
const EDGE = process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const DEBUG_PORT = 9231;
const SITE_KEY = "6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0";
const ACTION = "chat_submit";

function argValue(n, f = "") { const i = process.argv.indexOf(n); return i >= 0 && i + 1 < process.argv.length ? String(process.argv[i + 1] || "") : f; }
function hasArg(n) { return process.argv.includes(n); }
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function loadCookies(f) {
  const out = [];
  for (const c of JSON.parse(fs.readFileSync(f, "utf8"))) {
    if (!c || !c.name) continue;
    out.push({ name: c.name, value: c.value, domain: c.domain || "arena.ai", path: c.path || "/",
      secure: !!c.secure, httpOnly: !!c.httpOnly,
      sameSite: c.sameSite === "no_restriction" ? "None" : c.sameSite === "strict" ? "Strict" : "Lax",
      ...(c.session || typeof c.expirationDate !== "number" ? {} : { expirationDate: Math.floor(c.expirationDate) }) });
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
    setTimeout(() => { if (this.p[id]) { this.p[id] = null; rej(new Error("timeout:" + m)); } }, 120000); }); }
  close() { try { this.ws.close(); } catch {} }
}
async function waitDbg(port, t) { const dl = Date.now() + t; while (Date.now() < dl) { try { if ((await fetch(`http://127.0.0.1:${port}/json/version`)).ok) return true; } catch {} await sleep(300); } return false; }

async function main() {
  const cookieFile = argValue("--cookie-file", process.env.LM_ARENA_COOKIE_FILE || "C:\\Users\\gamer\\Desktop\\lmarena-cookie.txt");
  const outFile = argValue("--out", path.join(PROJECT_ROOT, "lmarena-recaptcha.json"));
  const headless = hasArg("--headless");
  const cookies = loadCookies(cookieFile);
  const proxy = process.env.ARENA_PROXY || process.env.HTTPS_PROXY || process.env.https_proxy || "http://127.0.0.1:7897";
  const ud = path.join(os.tmpdir(), `arena-edge-${Date.now()}`);
  fs.rmSync(ud, { recursive: true, force: true });
  const proc = spawn(EDGE, [`--remote-debugging-port=${DEBUG_PORT}`, `--proxy-server=${proxy}`, "--no-first-run", "--no-default-browser-check", "--disable-blink-features=AutomationControlled", headless ? "--headless=new" : "--start-maximized", `--user-data-dir=${ud}`, "about:blank"], { stdio: "ignore", detached: true });
  if (!(await waitDbg(DEBUG_PORT, 30000))) { console.error("no debugger"); process.exitCode = 1; return; }
  const ti = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/new`, { method: "PUT" })).json();
  const ws = new WebSocket(ti.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("ws")); });
  const c = new CDP(ws);
  let token = null;
  try {
    await c.send("Network.enable"); await c.send("Page.enable"); await c.send("Runtime.enable");
    for (const ck of cookies) { try { await c.send("Network.setCookie", ck); } catch {} }
    await c.send("Page.navigate", { url: "https://arena.ai/text/direct" });
    await sleep(9000);
    const r = await c.send("Runtime.evaluate", {
      expression: `(() => new Promise((resolve, reject) => {
        function tryExec(n) {
          if (n > 12) return reject(new Error('grecaptcha not ready'));
          if (window.grecaptcha && window.grecaptcha.enterprise) {
            return window.grecaptcha.enterprise.ready(() => {
              window.grecaptcha.enterprise.execute('${SITE_KEY}', { action: '${ACTION}' })
                .then((t) => { if (typeof t === 'string' && t.length >= 100) resolve(t); else setTimeout(() => tryExec(n + 1), 400); })
                .catch((e) => setTimeout(() => tryExec(n + 1), 400));
            });
          }
          setTimeout(() => tryExec(n + 1), 700);
        }
        tryExec(0);
      }))()`,
      returnByValue: true, awaitPromise: true,
    });
    token = r && r.result ? r.result.value : null;
  } catch (e) { console.error("err", e.stack || e); process.exitCode = 1; }
  finally {
    try { c.close(); } catch {}
    try { proc.kill("SIGKILL"); } catch {}
    setTimeout(() => {
      if (token && typeof token === "string" && token.length >= 100) {
        const payload = { token, captured_at: Date.now() };
        fs.writeFileSync(outFile, JSON.stringify(payload), "utf8");
        console.log(token);
      } else {
        console.error("NO_RECAPTCHA_TOKEN");
        process.exitCode = 1;
      }
      process.exit(process.exitCode || 0);
    }, 400);
  }
}
main().catch((e) => { console.error(e.stack || e); process.exitCode = 1; });
