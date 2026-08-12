import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CREDENTIALS_FILE = path.join(PROJECT_ROOT, "credentials.json");
const OUT = path.join(PROJECT_ROOT, "grok-real-headers.json");

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
  if (!grokCookie) throw new Error("GROK_COOKIE empty");

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

  let capturedHeaders = null;
  let capturedBody = null;
  const seenUrls = [];
  const posts = [];
  page.on("request", (req) => {
    const u = req.url();
    if (u.includes("grok.com/rest") || u.includes("conversations")) {
      seenUrls.push(u);
    }
    if (u.includes("grok.com") && req.method().toUpperCase() === "POST") {
      posts.push({ url: u, headers: req.headers(), body: req.postData() });
      if (
        (u.includes("/rest/app-chat/conversations/new") ||
          u.includes("/load-responses")) &&
        !capturedHeaders
      ) {
        capturedHeaders = req.headers();
        capturedBody = req.postData();
      }
    }
  });

  console.log("opening grok.com (solve challenge if shown)...");
  await page.goto("https://grok.com", { waitUntil: "domcontentloaded", timeout: 60000 });
  const tok = await waitForClearance(context, 180000);
  if (!tok) {
    console.error("NO cf_clearance captured");
    process.exitCode = 2;
    return;
  }
  console.log("cf_clearance captured. Waiting for composer to appear...");

  // Find the composer: a textarea or contenteditable element.
  let selector = null;
  try {
    await page.waitForSelector("textarea, [contenteditable='true'], [role='textbox']", {
      timeout: 60000,
      state: "visible",
    });
    selector = "textarea, [contenteditable='true'], [role='textbox']";
  } catch (e) {
    console.log("composer not found via waitForSelector; dumping candidates");
  }

  if (!selector) {
    const candidates = await page.evaluate(() => {
      const els = Array.from(
        document.querySelectorAll("textarea, input, [contenteditable], [role='textbox']")
      ).slice(0, 20);
      return els.map((el) => ({
        tag: el.tagName,
        id: el.id,
        cls: String(el.className).slice(0, 80),
        role: el.getAttribute("role"),
        placeholder: el.getAttribute("placeholder"),
      }));
    });
    console.log("CANDIDATES:", JSON.stringify(candidates, null, 2));
    process.exitCode = 4;
    await browser.close().catch(() => {});
    return;
  }

  const input = page.locator(selector).first();
  await input.click();
  await page.keyboard.type("ping");
  await new Promise((r) => setTimeout(r, 500));
  const typed = await input.innerText().catch(() => "");
  console.log("composer text after typing:", JSON.stringify(typed));
  await page.keyboard.press("Enter");
  await new Promise((r) => setTimeout(r, 3000));

  // enumerate send-like buttons and click the first plausible one
  const buttons = await page.evaluate(() =>
    Array.from(document.querySelectorAll("button")).map((b) => ({
      aria: b.getAttribute("aria-label"),
      text: (b.innerText || "").slice(0, 30),
      cls: String(b.className).slice(0, 60),
    }))
  );
  const sendBtn = buttons.find(
    (b) =>
      (b.aria && /send|отправ/i.test(b.aria)) ||
      (b.text && /send|отправ|➤|↑|➜/i.test(b.text))
  );
  console.log("send button candidate:", JSON.stringify(sendBtn));
  if (sendBtn) {
    try {
      await page.evaluate(() => {
        const b = document.querySelector('button[aria-label="Отправить"]');
        if (b) b.click();
      });
    } catch {}
  }

  // wait for the chat request to be intercepted
  const deadline = Date.now() + 40000;
  while (!capturedHeaders && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 300));
  }

  if (capturedHeaders) {
    const safe = {};
    for (const [k, v] of Object.entries(capturedHeaders)) {
      safe[k] = k.toLowerCase() === "cookie" ? "<REDACTED len=" + String(v).length + ">" : v;
    }
    const bodyObj = (() => {
      try {
        return JSON.parse(capturedBody || "{}");
      } catch {
        return capturedBody;
      }
    })();
    fs.writeFileSync(
      OUT,
      JSON.stringify({ headers: safe, body_keys: bodyObj && typeof bodyObj === "object" ? Object.keys(bodyObj) : null, body_sample: bodyObj }, null, 2),
      "utf8"
    );
    console.log("captured REAL chat request headers ->", OUT);
    console.log(JSON.stringify(safe, null, 2));
    console.log("BODY KEYS:", JSON.stringify(bodyObj && typeof bodyObj === "object" ? Object.keys(bodyObj) : null));
  } else {
    console.error("no chat request intercepted.");
    console.log("POST requests seen:", JSON.stringify(posts.map((p) => p.url), null, 2));
    console.error("GET seen URLs:", JSON.stringify(seenUrls.slice(0, 20), null, 2));
    process.exitCode = 3;
  }
  await browser.close().catch(() => {});
}

main().catch((e) => {
  console.error(e.stack || e);
  process.exitCode = 1;
});
