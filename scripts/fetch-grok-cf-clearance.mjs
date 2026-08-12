import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CREDENTIALS_FILE = path.join(PROJECT_ROOT, "credentials.json");
const DEFAULT_OUTPUT = path.join(PROJECT_ROOT, "grok_cf_clearance.json");

function argValue(name, fallback = "") {
  const index = process.argv.indexOf(name);
  if (index >= 0 && index + 1 < process.argv.length) {
    return String(process.argv[index + 1] || "");
  }
  return fallback;
}

function hasArg(name) {
  return process.argv.includes(name);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readCookieHeader() {
  let raw;
  try {
    raw = fs.readFileSync(CREDENTIALS_FILE, "utf8");
  } catch (error) {
    throw new Error(`cannot read ${CREDENTIALS_FILE}: ${error.message}`);
  }
  const credentials = JSON.parse(raw);
  const header =
    String(credentials.GROK_COOKIE || credentials.grok_cookie || "").trim();
  if (!header) {
    throw new Error("GROK_COOKIE is empty in credentials.json");
  }
  return header;
}

function cookieHeaderToObjects(header) {
  const out = [];
  for (const part of header.split(";")) {
    const idx = part.indexOf("=");
    if (idx < 0) continue;
    const name = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (!name) continue;
    out.push({ name, value, domain: "grok.com", path: "/" });
  }
  return out;
}

async function waitForClearance(context, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const cookies = await context.cookies("https://grok.com");
      const found = cookies.find((c) => c.name === "cf_clearance");
      if (found && found.value && found.value.length > 8) {
        return found.value;
      }
    } catch (err) {
      // ignore transient cookie read errors and keep polling
    }
    await sleep(500);
  }
  return null;
}

async function main() {
  const outputFile = path.resolve(argValue("--out", DEFAULT_OUTPUT));
  const timeoutMs = Number(argValue("--timeout", "180000")) || 180000;
  const headless = hasArg("--headless");
  const browserChannel = argValue("--channel", process.env.GROK_CF_CLEARANCE_CHANNEL || "msedge");
  const cookieHeader = readCookieHeader();

  const proxyServer =
    process.env.GROK_CF_CLEARANCE_PROXY ||
    process.env.HTTPS_PROXY ||
    process.env.https_proxy ||
    "http://127.0.0.1:7897";

  let browser = null;
  const startedAt = Date.now();
  try {
    browser = await chromium.launch({
      channel: browserChannel,
      headless,
      proxy: { server: proxyServer },
      args: [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
      ],
    });
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      locale: "ru-RU",
      timezoneId: "Europe/Moscow",
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    });
    const page = await context.newPage();
    // Inject the session cookies as real browser cookies (not just request headers)
    // so the browser persists them and they are returned by context.cookies() after
    // the Cloudflare challenge. Without this the captured set would miss `sso`/`sso-rw`.
    try {
      const cookieObjects = cookieHeaderToObjects(cookieHeader);
      if (cookieObjects.length) {
        await context.addCookies(cookieObjects);
        console.log(`injected ${cookieObjects.length} session cookies`);
      }
    } catch (cookieErr) {
      console.log("cookie inject failed:", cookieErr.message);
    }

    console.log(
      `opening https://grok.com (channel=${browserChannel}, headless=${headless})`
    );
    if (!headless) {
      console.log(
        "If Cloudflare shows a challenge, solve it in the browser window. " +
          "It closes automatically once cf_clearance is captured."
      );
    }

    await page.goto("https://grok.com", {
      waitUntil: "domcontentloaded",
      timeout: 60000,
    });

    let token = await waitForClearance(context, timeoutMs - (Date.now() - startedAt));

    if (!token) {
      // Cloudflare may not have challenged on first load. Trigger a reload / in-page
      // request to force the managed challenge, then poll again.
      console.log("warn: cf_clearance not present yet; forcing a reload to trigger challenge...");
      try {
        await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
      } catch (reloadErr) {
        console.log("reload failed:", reloadErr.message);
      }
      token = await waitForClearance(context, 60000);
    }

    if (!token) {
      console.error(
        JSON.stringify(
          {
            ok: false,
            error: "cf_clearance not captured (no Cloudflare challenge resolved)",
          },
          null,
          2,
        )
      );
      process.exitCode = 2;
      return;
    }

    const payload = {
      captured_at: Date.now(),
      cf_clearance: token,
      cookie: (await context.cookies("https://grok.com"))
        .map((c) => `${c.name}=${c.value}`)
        .join("; "),
    };
    fs.writeFileSync(outputFile, JSON.stringify(payload, null, 2), "utf8");
    console.log(`saved cf_clearance + grok.com cookie set -> ${outputFile}`);
  } catch (error) {
    console.error(`grok cf_clearance grabber failed: ${error.stack || error}`);
    process.exitCode = 1;
  } finally {
    if (browser) {
      await browser.close().catch(() => {});
    }
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
