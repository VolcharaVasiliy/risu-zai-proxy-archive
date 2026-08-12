import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CREDENTIALS_FILE = path.join(PROJECT_ROOT, "credentials.json");
const CLEAR_FILE = path.join(PROJECT_ROOT, "grok_cf_clearance.json");

const PORT = Number(process.env.GROK_BRIDGE_PORT || "8771");
const PROXY_SERVER = process.env.HTTPS_PROXY || process.env.https_proxy || "http://127.0.0.1:7897";
const HEADLESS = (process.env.GROK_BRIDGE_HEADLESS || "true") !== "false";
const GRAB_TIMEOUT = Number(process.env.GROK_CF_CLEARANCE_TIMEOUT_SECONDS || "180");

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
}

function cookieHeaderToObjects(header) {
  const out = [];
  for (const part of String(header).split(";")) {
    const idx = part.indexOf("=");
    if (idx < 0) continue;
    const name = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (name) out.push({ name, value, domain: "grok.com", path: "/" });
  }
  return out;
}

function sseChunk(res, obj) {
  res.write("data: " + JSON.stringify(obj) + "\n\n");
}

class GrokBridge {
  constructor() {
    this.browser = null;
    this.page = null;
    this.currentRes = null;
    this.queue = Promise.resolve();
  }

  async launch() {
    this.browser = await chromium.launch({
      channel: "msedge",
      headless: HEADLESS,
      proxy: { server: PROXY_SERVER },
      args: ["--disable-blink-features=AutomationControlled", "--no-first-run"],
    });
    this.context = await this.browser.newContext({
      viewport: { width: 1440, height: 900 },
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    });
    this.page = await this.context.newPage();
    await this.context.addCookies(cookieHeaderToObjects(readJson(CREDENTIALS_FILE, {}).GROK_COOKIE || ""));
    await this.context.addCookies(cookieHeaderToObjects(readJson(CLEAR_FILE, {}).cookie || ""));
    await this.page.exposeBinding("__grokChunk", (_b, text) => {
      if (this.currentRes) sseChunk(this.currentRes, { choices: [{ delta: { content: text } }] });
    });
    await this.page.goto("https://grok.com", { waitUntil: "domcontentloaded", timeout: 60000 });
    await this.ensureClearance();
  }

  async ensureClearance() {
    try {
      const c = await this.context.cookies("https://grok.com");
      const f = c.find((x) => x.name === "cf_clearance");
      if (f && f.value && f.value.length > 8) return true;
    } catch {}
    return this.runGrabber();
  }

  async runGrabber() {
    return new Promise((resolve) => {
      const child = spawn(
        "node",
        [path.join(__dirname, "fetch-grok-cf-clearance.mjs"), "--timeout", String(GRAB_TIMEOUT * 1000)],
        { cwd: PROJECT_ROOT, env: { ...process.env, HTTPS_PROXY: PROXY_SERVER, HTTP_PROXY: PROXY_SERVER } }
      );
      child.on("exit", async (code) => {
        if (code === 0) {
          try {
            const cookie = readJson(CLEAR_FILE, {}).cookie || "";
            await this.context.addCookies(cookieHeaderToObjects(cookie));
          } catch {}
        }
        resolve(code === 0);
      });
    });
  }

  async oneShot(prompt, model) {
    return this.page.evaluate(
      async ({ prompt, model }) => {
        function getCookie(name) {
          const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
          return m ? decodeURIComponent(m[2]) : null;
        }
        const uid = getCookie("x-userid") || crypto.randomUUID();
        const ws = new WebSocket("wss://grok.com/ws/mgw/?uid=" + uid);
        let sessionId = null;
        let text = "";
        let resolveDone;
        const done = new Promise((r) => (resolveDone = r));
        const send = (o) => ws.send(JSON.stringify(o));
        ws.addEventListener("open", () => {
          send({
            event: {
              type: "session.create",
              event_id: "evt_init_" + crypto.randomUUID(),
              session: {
                model: model || "fast",
                x_grok: {
                  protocol_capabilities: ["conversation_attached", "custom_methods_v1"],
                  use_chunk: true,
                  enable_side_by_side: true,
                  force_side_by_side: false,
                  enable_image_generation: true,
                  image_generation_count: 2,
                  disable_text_follow_ups: false,
                  disable_artifact: true,
                  force_concise: false,
                },
              },
            },
          });
        });
        ws.addEventListener("message", (e) => {
          let msg;
          try {
            msg = JSON.parse(e.data);
          } catch {
            return;
          }
          const ev = msg.event || {};
          const t = ev.type;
          if (t === "session.created") {
            sessionId = msg.session_id;
          } else if (t === "conversation.attached") {
            send({
              session_id: sessionId,
              event: {
                type: "conversation.item.create",
                event_id: "evt_msg_" + Date.now(),
                item: {
                  type: "message",
                  role: "user",
                  x_grok: {
                    client_message_id: crypto.randomUUID(),
                    input_chunks: [{ text: { text: prompt } }],
                  },
                },
              },
            });
            send({ session_id: sessionId, event: { type: "response.create", event_id: "evt_resp_" + Date.now() } });
          } else if (t === "response.chunk") {
            const txt = ev.chunk && ev.chunk.text && ev.chunk.text.text;
            if (txt) {
              text += txt;
              try {
                window.__grokChunk(txt);
              } catch {}
            }
          } else if (t === "response.done") {
            resolveDone({ ok: true, text });
          } else if (t === "error") {
            resolveDone({ ok: false, error: JSON.stringify(ev).slice(0, 400) });
          }
        });
        ws.addEventListener("error", () => resolveDone({ ok: false, error: "ws error", text }));
        const to = setTimeout(() => resolveDone({ ok: false, error: "timeout", text }), 120000);
        const res = await done;
        clearTimeout(to);
        try {
          ws.close();
        } catch {}
        return res;
      },
      { prompt, model }
    );
  }

  async handleChat(req, res, body) {
    const prompt = body.prompt || "";
    const model = body.model || "fast";
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "Access-Control-Allow-Origin": "*",
    });
    this.currentRes = res;
    let result;
    try {
      result = await this.oneShot(prompt, model);
    } catch (e) {
      result = { ok: false, error: String(e && e.message ? e.message : e) };
    }
    if (!result || !result.ok) {
      const err = (result && result.error) || "unknown";
      if (result && result.text) sseChunk(res, { choices: [{ delta: { content: result.text } }] });
      sseChunk(res, { error: err });
    }
    res.write("data: [DONE]\n\n");
    res.end();
    this.currentRes = null;
  }

  async handleHealth(res) {
    let clearance = false;
    try {
      const c = await this.context.cookies("https://grok.com");
      clearance = !!c.find((x) => x.name === "cf_clearance" && x.value && x.value.length > 8);
    } catch {}
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, logged_in: true, clearance }));
  }

  listen() {
    const server = http.createServer(async (req, res) => {
      if (req.method === "GET" && req.url === "/health") return this.handleHealth(res);
      if (req.method === "POST" && req.url === "/chat") {
        let raw = "";
        req.on("data", (c) => (raw += c));
        req.on("end", async () => {
          let body = {};
          try {
            body = JSON.parse(raw || "{}");
          } catch {}
          // serialize requests
          this.queue = this.queue
            .catch(() => {})
            .then(() => this.handleChat(req, res, body));
          return this.queue;
        });
        return;
      }
      res.writeHead(404);
      res.end("not found");
    });
    server.listen(PORT, () => console.log("grok bridge listening on " + PORT));
  }
}

(async () => {
  const bridge = new GrokBridge();
  await bridge.launch();
  bridge.listen();
})().catch((e) => {
  console.error(e.stack || e);
  process.exit(1);
});
