import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import crypto from "node:crypto";
import { randomUUID } from "node:crypto";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CREDENTIALS_FILE = path.join(PROJECT_ROOT, "credentials.json");

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
  console.log("opening grok.com (solve challenge if shown)...");
  await page.goto("https://grok.com", { waitUntil: "domcontentloaded", timeout: 60000 });
  const tok = await waitForClearance(context, 180000);
  if (!tok) {
    console.error("NO cf_clearance captured");
    process.exitCode = 2;
    return;
  }
  console.log("cf_clearance captured. Issuing in-page fetch to /new ...");

  const result = await page.evaluate(async (body) => {
    const randB64 = () => {
      const a = new Uint8Array(64);
      crypto.getRandomValues(a);
      let s = "";
      for (const x of a) s += String.fromCharCode(x);
      return btoa(s).replace(/=+$/, "");
    };
    const uuid = () => crypto.randomUUID();
    const headers = {
      Accept: "*/*",
      "Accept-Language": "ru,en;q=0.9",
      "Content-Type": "application/json",
      Origin: "https://grok.com",
      Referer: "https://grok.com/",
      "Sec-Ch-Ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
      "Sec-Ch-Ua-Arch": '"x86"',
      "Sec-Ch-Ua-Bitness": '"64"',
      "Sec-Ch-Ua-Full-Version": '"146.0.3856.62"',
      "Sec-Ch-Ua-Full-Version-List":
        '"Chromium";v="146.0.3856.62", "Not-A.Brand";v="24.0.0.0", "Microsoft Edge";v="146.0.3856.62"',
      "Sec-Ch-Ua-Mobile": "?0",
      "Sec-Ch-Ua-Platform": '"Windows"',
      "Sec-Ch-Ua-Platform-Version": '"10.0.0"',
      "Sec-Fetch-Dest": "empty",
      "Sec-Fetch-Mode": "cors",
      "Sec-Fetch-Site": "same-origin",
      "X-Statsig-Id": randB64(),
      "X-Xai-Request-Id": uuid(),
      Baggage:
        "sentry-environment=production,sentry-release=grok-web,sentry-public_key=b311e0f2690c81f25e2c4cf6d4f7ce1c,sentry-trace_id=" +
        uuid().replace(/-/g, "") +
        ",sentry-org_id=4508179396558848,sentry-sampled=false",
      "Sentry-Trace": uuid().replace(/-/g, "") + "-" + uuid().replace(/-/g, "").slice(0, 16) + "-0",
      Traceparent: "00-" + uuid().replace(/-/g, "") + "-" + uuid().replace(/-/g, "").slice(0, 16) + "-00",
    };
    const resp = await fetch("https://grok.com/rest/app-chat/conversations/new", {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      credentials: "include",
    });
    const text = await resp.text();
    return { status: resp.status, head: text.slice(0, 400) };
  }, { modelName: "grok-3", modelMode: "MODEL_MODE_GROK_3", message: "ping", temporary: true });

  console.log("IN-PAGE FETCH STATUS:", result.status);
  console.log("IN-PAGE FETCH HEAD:", result.head);
  await browser.close().catch(() => {});
}

main().catch((e) => {
  console.error(e.stack || e);
  process.exitCode = 1;
});
