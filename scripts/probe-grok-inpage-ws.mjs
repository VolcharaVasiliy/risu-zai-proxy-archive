import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CREDENTIALS_FILE = path.join(PROJECT_ROOT, "credentials.json");
const CLEAR_FILE = path.join(PROJECT_ROOT, "grok_cf_clearance.json");

function cookieHeaderToObjects(header) {
  const out = [];
  for (const part of header.split(";")) {
    const idx = part.indexOf("=");
    if (idx < 0) continue;
    const name = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (name) out.push({ name, value, domain: "grok.com", path: "/" });
  }
  return out;
}

async function waitForClearance(context, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const c = await context.cookies("https://grok.com");
      const f = c.find((x) => x.name === "cf_clearance");
      if (f && f.value && f.value.length > 8) return f.value;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  return null;
}

async function main() {
  const creds = JSON.parse(fs.readFileSync(CREDENTIALS_FILE, "utf8"));
  const cookieSet = JSON.parse(fs.readFileSync(CLEAR_FILE, "utf8")).cookie;
  const proxyServer = process.env.HTTPS_PROXY || "http://127.0.0.1:7897";

  const browser = await chromium.launch({
    channel: "msedge",
    headless: false,
    proxy: { server: proxyServer },
    args: ["--disable-blink-features=AutomationControlled", "--no-first-run"],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
  });
  const page = await context.newPage();
  await context.addCookies(cookieHeaderToObjects(creds.GROK_COOKIE));
  await context.addCookies(cookieHeaderToObjects(cookieSet));

  await page.goto("https://grok.com", { waitUntil: "domcontentloaded", timeout: 60000 });
  const tok = await waitForClearance(context, 180000);
  console.log("clearance:", tok ? "OK" : "MISSING");

  const prompt = process.argv[2] || "Say hi in one word.";
  const result = await page.evaluate(async (prompt) => {
    function getCookie(name) {
      const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
      return m ? decodeURIComponent(m[2]) : null;
    }
    const uid = getCookie("x-userid") || crypto.randomUUID();
    const ws = new WebSocket("wss://grok.com/ws/mgw/?uid=" + uid);
    const log = [];
    let sessionId = null;
    let text = "";
    let resolveDone;
    const done = new Promise((r) => (resolveDone = r));

    function send(obj) {
      ws.send(JSON.stringify(obj));
    }
    ws.addEventListener("open", () => {
      send({
        event: {
          type: "session.create",
          event_id: "evt_init_" + crypto.randomUUID(),
          session: {
            model: "fast",
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
      const msg = JSON.parse(e.data);
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
        send({
          session_id: sessionId,
          event: { type: "response.create", event_id: "evt_resp_" + Date.now() },
        });
      } else if (t === "response.chunk") {
        const txt = ev.chunk && ev.chunk.text && ev.chunk.text.text;
        if (txt) text += txt;
      } else if (t === "response.done") {
        resolveDone({ ok: true, text });
      } else if (t === "error") {
        resolveDone({ ok: false, error: JSON.stringify(ev).slice(0, 400) });
      }
    });
    ws.addEventListener("error", () => resolveDone({ ok: false, error: "ws error" }));
    const to = setTimeout(() => resolveDone({ ok: false, error: "timeout", text }), 60000);
    const res = await done;
    clearTimeout(to);
    ws.close();
    return res;
  }, prompt);

  console.log("RESULT:", JSON.stringify(result, null, 2).slice(0, 2000));
  await browser.close().catch(() => {});
}

main().catch((e) => {
  console.error(e.stack || e);
  process.exitCode = 1;
});
