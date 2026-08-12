import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CREDENTIALS_FILE = path.join(PROJECT_ROOT, "credentials.json");
const OUT = path.join(PROJECT_ROOT, "grok-ws-frames.json");

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
  const grokCookie = String(creds.GROK_COOKIE || "").trim();

  const proxyServer =
    process.env.GROK_CF_CLEARANCE_PROXY ||
    process.env.HTTPS_PROXY ||
    process.env.https_proxy ||
    "http://127.0.0.1:7897";

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
  await context.addCookies(cookieHeaderToObjects(grokCookie));

  const wsLog = [];
  page.on("websocket", (ws) => {
    const entry = { url: ws.url(), sent: [], received: [] };
    wsLog.push(entry);
    console.log("WEBSOCKET OPENED:", ws.url());
    ws.on("framesent", (frame) => {
      const p = typeof frame.payload === "string" ? frame.payload : `<binary ${frame.payload.length}>`;
      entry.sent.push(p);
      console.log("  SENT:", p.slice(0, 300));
    });
    ws.on("framereceived", (frame) => {
      const p = typeof frame.payload === "string" ? frame.payload : `<binary ${frame.payload.length}>`;
      entry.received.push(p);
      console.log("  RECV:", p.slice(0, 300));
    });
    ws.on("close", () => console.log("  WS CLOSED"));
  });

  console.log("opening grok.com (solve challenge if shown)...");
  await page.goto("https://grok.com", { waitUntil: "domcontentloaded", timeout: 60000 });
  const tok = await waitForClearance(context, 180000);
  if (!tok) {
    console.error("NO cf_clearance captured");
    process.exitCode = 2;
    return;
  }

  const input = page.locator("textarea, [contenteditable='true'], [role='textbox']").first();
  await input.click();
  await page.keyboard.type("ping websocket test");
  await page.keyboard.press("Enter");

  await new Promise((r) => setTimeout(r, 15000));

  const cap = (s) => (typeof s === "string" && s.length > 8000 ? s.slice(0, 8000) : s);
  fs.writeFileSync(
    OUT,
    JSON.stringify(
      wsLog.map((e) => ({
        url: e.url,
        sent_count: e.sent.length,
        received_count: e.received.length,
        sent_full: e.sent.map(cap),
        received_full: e.received.map(cap),
      })),
      null,
      2
    ),
    "utf8"
  );
  console.log("WS frames ->", OUT);
  await browser.close().catch(() => {});
}

main().catch((e) => {
  console.error(e.stack || e);
  process.exitCode = 1;
});
