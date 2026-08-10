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
const DEFAULT_OUTPUT = path.join(PROJECT_ROOT, "captcha_param.json");
const DEFAULT_PORT = process.env.ZAI_CAPTCHA_CDP_PORT || "9222";

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

function zaiToken() {
  let raw;
  try {
    raw = fs.readFileSync(CREDENTIALS_FILE, "utf8");
  } catch (error) {
    throw new Error(`cannot read ${CREDENTIALS_FILE}: ${error.message}`);
  }
  const credentials = JSON.parse(raw);
  const token = String(credentials.ZAI_TOKEN || "").trim();
  if (!token) {
    throw new Error("ZAI_TOKEN is empty in credentials.json");
  }
  return token;
}

function makeCaptchaWrangler(page) {
  const state = {
    verifyParam: null,
    completionRequests: [],
    completionResponses: [],
    verifyResponses: [],
    events: [],
  };
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/v2/chat/completions") || url.includes("/api/agent/v2/chat/completions")) {
      const entry = { url, postData: null };
      try {
        const postData = request.postData();
        if (postData) entry.postData = postData;
      } catch {}
      state.completionRequests.push(entry);
      try {
        const json = JSON.parse(entry.postData || "{}");
        if (json && json.captcha_verify_param) {
          state.verifyParam = json.captcha_verify_param;
          state.events.push(`captured from completion request at ${Date.now()}`);
        }
      } catch {}
    }
    if (url.includes("no8xfe-verify.captcha-open-southeast.aliyuncs.com")) {
      state.events.push(`verify request seen at ${Date.now()}`);
    }
  });
  page.on("response", async (response) => {
    const url = response.url();
    if (url.includes("no8xfe-verify.")) {
      try {
        const text = await response.text();
        state.verifyResponses.push({ url, text });
        const parsed = JSON.parse(text || "{}");
        const result = String(parsed.ResultObject || parsed.Result || "");
        const lookup = [result, text].join(" ");
        const certify = lookup.match(/certifyId["']?\s*[:=]\s*["']?([A-Za-z0-9_-]{3,40})/);
        const security = lookup.match(/securityToken["']?\s*[:=]\s*["']?([A-Za-z0-9+/=_-]{10,})/);
        if (certify && security) {
          state.events.push(`verify response parsed (certifyId=${certify[1]}) at ${Date.now()}`);
          try {
            const object = JSON.parse(result);
            if (typeof object === "object" && object !== null) {
              parsed._parsedResult = object;
            }
          } catch {}
        }
      } catch {}
    }
    if (url.includes("/api/v2/chat/completions") || url.includes("/api/agent/v2/chat/completions")) {
      state.completionResponses.push({ url, status: response.status() });
    }
  });
  return state;
}

const HANDLE_SELECTORS = [
  ".secsdk-captcha-drag-icon",
  "[class*='secsdk-captcha-drag-icon']",
  "button[class*='secsdk'][class*='drag']",
  "[class*='captcha'][class*='drag-icon']",
  "[class*='drag-slider']",
  "[class*='slider-btn']",
  "img[class*='drag']",
  ".secsdk-captcha-drag-btn",
].filter(Boolean);

async function findDragHandle(page) {
  for (const frame of page.frames()) {
    for (const selector of HANDLE_SELECTORS) {
      try {
        const locator = frame.locator(selector).first();
        if (await locator.count()) {
          const box = await locator.boundingBox();
          if (box && box.width > 4 && box.height > 4) {
            return { frame, selector, box };
          }
        }
      } catch {}
    }
  }
  return null;
}

async function dragHandle(page, handle, offsetPx) {
  const { frame, selector, box } = handle;
  const startX = box.x + box.width / 2;
  const startY = box.y + box.height / 2;
  const steps = 34;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await sleep(80);
  let previousX = startX;
  for (let step = 1; step <= steps; step++) {
    const progress = step / steps;
    const eased = 1 - Math.pow(1 - progress, 3);
    const targetX = startX + offsetPx * eased;
    const jitterX = (Math.random() - 0.5) * 1.6;
    const jitterY = (Math.random() - 0.5) * 1.2;
    const moveX = previousX + (targetX - previousX) * 0.55 + jitterX;
    await page.mouse.move(moveX, startY + jitterY, { steps: 1 });
    previousX = moveX;
    await sleep(9 + Math.floor(Math.random() * 14));
  }
  await page.mouse.move(startX + offsetPx + 1, startY + (Math.random() - 0.5));
  await sleep(120);
  await page.mouse.up();
}

async function solveCaptcha(page, attempts = 3) {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const handle = await findDragHandle(page);
    if (!handle) {
      console.log(`attempt ${attempt}: drag handle not found yet; waiting...`);
      await sleep(1500);
      continue;
    }
    console.log(
      `attempt ${attempt}: handle at (${handle.box.x.toFixed(0)},${handle.box.y.toFixed(0)}) size ${handle.box.width.toFixed(0)}x${handle.box.height.toFixed(0)}`
    );
    await dragHandle(page, handle, 320);
    await sleep(1800);
    return true;
  }
  return false;
}

async function waitForVerifyParam(state, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (state.verifyParam) return state.verifyParam;
    await sleep(250);
  }
  return null;
}

async function main() {
  const outputFile = path.resolve(argValue("--out", DEFAULT_OUTPUT));
  const timeoutMs = Number(argValue("--timeout", "150000")) || 150000;
  const headless = !hasArg("--headed");
  const browserChannel = argValue("--channel", process.env.ZAI_CAPTCHA_CHANNEL || "msedge");
  const token = zaiToken();

  let browser = null;
  const startedAt = Date.now();
  try {
    browser = await chromium.launch({
      channel: browserChannel,
      headless,
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
    await context.addInitScript(({ tokenValue }) => {
      try {
        window.localStorage.setItem("token", tokenValue);
      } catch {}
    }, { tokenValue: token });

    const page = await context.newPage();
    const state = makeCaptchaWrangler(page);

    console.log(`opening https://chat.z.ai (channel=${browserChannel}, headless=${headless})`);
    await page.goto("https://chat.z.ai", { waitUntil: "domcontentloaded", timeout: 45000 });

    await page.waitForSelector("#chat-input", { timeout: 45000 }).catch(() => {
      console.log("warn: #chat-input not found within 45s; continuing anyway");
    });

    console.log("typing probe message...");
    const overlayInfo = await page
      .evaluate(() => {
        const overlay = document.querySelector("div.fixed.inset-0");
        return overlay
          ? { present: true, className: String(overlay.className).slice(0, 120) }
          : { present: false };
      })
      .catch(() => ({ present: "eval-failed" }));
    console.log("overlay before dismiss:", JSON.stringify(overlayInfo));

    for (let round = 0; round < 4; round++) {
      await page.keyboard.press("Escape").catch(() => {});
      await sleep(500);
      const stillPresent = await page
        .evaluate(() => !!document.querySelector("div.fixed.inset-0"))
        .catch(() => true);
      if (!stillPresent) break;
    }

    const input = page.locator("#chat-input").first();
    await input.evaluate((element) => {
      element.focus();
    }).catch(() => {});
    await sleep(300);
    const focusInfo = await page
      .evaluate(() => {
        const active = document.activeElement;
        return active ? { tag: active.tagName, id: active.id || "" } : { tag: "none" };
      })
      .catch(() => ({ tag: "eval-failed" }));
    console.log("active element:", JSON.stringify(focusInfo));

    if (String(focusInfo.tag).toLowerCase() !== "textarea") {
      const box = await input.boundingBox().catch(() => null);
      if (box) {
        await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
        await sleep(300);
      }
    }

    await page.keyboard.type("hi");
    await sleep(200);
    const valueInfo = await input.inputValue().catch(() => "ERR");
    console.log("textarea value:", JSON.stringify(String(valueInfo)));
    await page.keyboard.press("Enter");

    const completionDeadline = Date.now() + 30000;
    while (Date.now() < completionDeadline) {
      if (state.completionRequests.length) break;
      await sleep(300);
    }
    console.log(
      `completion requests captured: ${state.completionRequests.length}, events: ${state.events.slice(-6).join(" | ") || "none"}`
    );

    const waitStarted = Date.now();
    const param = await waitForVerifyParam(state, timeoutMs - (waitStarted - startedAt) || 40000);
    if (param) {
      console.log("captcha_verify_param captured from page");
    } else {
      console.log("no captcha_verify_param yet; attempting slider solve...");
      await solveCaptcha(page);
      const afterSolve = await waitForVerifyParam(state, 40000);
      if (!afterSolve) {
        console.log("warn: still no captcha param after slider attempt");
      }
    }

    const finalParam = state.verifyParam;
    if (!finalParam) {
      await page.screenshot({ path: path.join(PROJECT_ROOT, "captcha-grabber-debug.png"), fullPage: true });
      console.error(
        JSON.stringify(
          {
            ok: false,
            error: "captcha_verify_param not captured",
            completionRequests: state.completionRequests.length,
            completionResponses: state.completionResponses.slice(0, 5),
            verifyResponses: state.verifyResponses.slice(0, 3),
            events: state.events.slice(-10),
          },
          null,
          2
        )
      );
      process.exitCode = 2;
      return;
    }

    const payload = {
      captured_at: Date.now(),
      captcha_verify_param: finalParam,
    };
    fs.writeFileSync(outputFile, JSON.stringify(payload, null, 2), "utf8");
    console.log(`saved captcha_verify_param -> ${outputFile}`);
  } catch (error) {
    console.error(`grabber failed: ${error.stack || error}`);
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