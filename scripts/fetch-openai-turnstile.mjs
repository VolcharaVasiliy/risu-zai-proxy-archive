import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CREDENTIALS_FILE = path.join(PROJECT_ROOT, "credentials.json");
const DEFAULT_OUTPUT = path.join(PROJECT_ROOT, "openai_turnstile.json");
const DEFAULT_PORT = process.env.OPENAI_TURNSTILE_CDP_PORT || "9333";

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
    String(credentials.OPENAI_WEB_COOKIE || credentials.openai_web_cookie || "").trim();
  if (!header) {
    throw new Error("OPENAI_WEB_COOKIE is empty in credentials.json");
  }
  return header;
}

function makeTurnstileWrangler(page) {
  const state = { turnstileToken: null, proofToken: null, events: [] };
  page.on("request", (request) => {
    const token = request.headers()["openai-sentinel-turnstile-token"];
    if (token && token.length > 8) {
      state.turnstileToken = token;
      state.events.push(`turnstile captured from ${request.url().slice(0, 80)} at ${Date.now()}`);
    }
    const proof = request.headers()["openai-sentinel-proof-token"];
    if (proof && proof.length > 8 && !state.proofToken) {
      state.proofToken = proof;
    }
  });
  return state;
}

async function waitForTurnstile(state, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (state.turnstileToken) return state.turnstileToken;
    await sleep(250);
  }
  return null;
}

async function main() {
  const outputFile = path.resolve(argValue("--out", DEFAULT_OUTPUT));
  const timeoutMs = Number(argValue("--timeout", "150000")) || 150000;
  const headless = !hasArg("--headed");
  const browserChannel = argValue("--channel", process.env.OPENAI_TURNSTILE_CHANNEL || "msedge");
  const cookieHeader = readCookieHeader();

  const proxyServer =
    process.env.OPENAI_TURNSTILE_PROXY ||
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
    await page.setExtraHTTPHeaders({ Cookie: cookieHeader });
    const state = makeTurnstileWrangler(page);

    console.log(`opening https://chatgpt.com (channel=${browserChannel}, headless=${headless})`);
    await page.goto("https://chatgpt.com", {
      waitUntil: "domcontentloaded",
      timeout: 45000,
    });

    // Wait for the sentinel heartbeat (ping) that carries the solved turnstile token.
    const waitStarted = Date.now();
    let token = await waitForTurnstile(state, timeoutMs - (waitStarted - startedAt) || 60000);

    if (!token) {
      console.log("warn: no turnstile token from sentinel ping yet; probing composer...");
      try {
        const input = page.locator("#prompt-textarea").first();
        if (await input.count()) {
          await input.click().catch(() => {});
          await page.keyboard.type("hi");
          await sleep(200);
          await page.keyboard.press("Enter");
          token = await waitForTurnstile(state, 40000);
        }
      } catch (probeErr) {
        console.log("probe failed:", probeErr.message);
      }
    }

    if (!token) {
      console.error(
        JSON.stringify(
          {
            ok: false,
            error: "openai-sentinel-turnstile-token not captured",
            events: state.events.slice(-10),
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
      turnstile_token: token,
      proof_token: state.proofToken || "",
    };
    fs.writeFileSync(outputFile, JSON.stringify(payload, null, 2), "utf8");
    console.log(`saved openai-sentinel-turnstile-token -> ${outputFile}`);
  } catch (error) {
    console.error(`turnstile grabber failed: ${error.stack || error}`);
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
