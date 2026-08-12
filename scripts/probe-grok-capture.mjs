import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CREDENTIALS_FILE = path.join(PROJECT_ROOT, "credentials.json");
const OUT = path.join(PROJECT_ROOT, "grok-newchat-request.json");

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
  console.log("opening grok.com (solve challenge if shown)...");
  await page.goto("https://grok.com", { waitUntil: "domcontentloaded", timeout: 60000 });
  const tok = await waitForClearance(context, 180000);
  if (!tok) {
    console.error("NO cf_clearance captured");
    process.exitCode = 2;
    return;
  }

  // click "New chat"
  const newChat = page.getByRole("button", { name: /новый чат|new chat/i }).first();
  if (await newChat.count()) {
    await newChat.click().catch(() => {});
    console.log("clicked New chat");
  } else {
    console.log("New chat button not found; continuing");
  }
  await new Promise((r) => setTimeout(r, 1500));

  const captured = [];
  page.on("request", (req) => {
    const u = req.url();
    if (u.includes("/rest/app-chat/") && req.method().toUpperCase() === "POST") {
      captured.push({ url: u, headers: req.headers(), body: req.postData() || "" });
    }
  });

  const input = page.locator("textarea, [contenteditable='true'], [role='textbox']").first();
  await input.click();
  await page.keyboard.type("hello world unique 12345");
  await page.keyboard.press("Enter");

  const deadline = Date.now() + 40000;
  while (captured.length === 0 && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 300));
  }

  if (captured.length) {
    const safeAll = captured.map((c) => {
      const safe = {};
      for (const [k, v] of Object.entries(c.headers)) {
        safe[k] = k.toLowerCase() === "cookie" ? "<REDACTED len=" + String(v).length + ">" : v;
      }
      return { url: c.url, headers: safe, body: c.body };
    });
    fs.writeFileSync(OUT, JSON.stringify(safeAll, null, 2), "utf8");
    console.log("CAPTURED", captured.length, "app-chat POSTs ->", OUT);
    for (const c of safeAll) {
      console.log("URL:", c.url);
      console.log("  BODY:", c.body.slice(0, 500).replace(/\n/g, " "));
    }
  } else {
    console.error("no app-chat POST captured after New chat + send");
    process.exitCode = 3;
  }
  await browser.close().catch(() => {});
}

main().catch((e) => {
  console.error(e.stack || e);
  process.exitCode = 1;
});
