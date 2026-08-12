import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CREDENTIALS_FILE = path.join(PROJECT_ROOT, "credentials.json");
const OUT_FILE = path.join(PROJECT_ROOT, "arcee_access_token.json");
const PROFILE_DIR = path.join(PROJECT_ROOT, ".arcee-edge-profile");

const JWT_RE = /eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g;

function cookieHeaderToObjects(header) {
  const out = [];
  for (const part of String(header).split(";")) {
    const idx = part.indexOf("=");
    if (idx < 0) continue;
    const name = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (name) out.push({ name, value, domain: ".arcee.ai", path: "/" });
  }
  return out;
}

function tryJwt(obj) {
  if (!obj || typeof obj !== "object") return null;
  for (const k of ["access_token", "accessToken", "token", "id_token", "refresh_token", "refreshToken"]) {
    const v = obj[k];
    if (typeof v === "string" && v.startsWith("eyJ") && v.split(".").length === 3) return { key: k, value: v };
  }
  for (const v of Object.values(obj)) {
    if (v && typeof v === "object") {
      const r = tryJwt(v);
      if (r) return r;
    }
  }
  return null;
}

async function main() {
  const creds = JSON.parse(fs.readFileSync(CREDENTIALS_FILE, "utf8"));
  const proxyServer = process.env.ARCEE_PROXY || process.env.HTTPS_PROXY || "http://127.0.0.1:7897";

  const context = await chromium.launchPersistentContext(PROFILE_DIR, {
    channel: "msedge",
    headless: false,
    proxy: { server: proxyServer },
    args: ["--disable-blink-features=AutomationControlled", "--no-first-run"],
    viewport: { width: 1440, height: 900 },
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
  });
  // Seed cookies so the LB/Cloudflare session is warm (login persists in profile).
  await context.addCookies(cookieHeaderToObjects(String(creds.ARCEE_COOKIE || "").trim()));
  console.log("profile persisted at", PROFILE_DIR);

  let found = null;
  const seenUrls = new Set();

  async function scan(res) {
    const u = res.url();
    if (!u.includes("arcee.ai")) return;
    try {
      const text = (await res.body()).toString("utf8");
      if (text.includes("eyJ")) {
        let jwt = null;
        try {
          jwt = tryJwt(JSON.parse(text));
        } catch {}
        if (!jwt) {
          const m = text.match(JWT_RE);
          if (m) jwt = { key: "jwt", value: m[0] };
        }
        if (jwt && !found) {
          found = jwt;
          console.log(">>> FOUND (body)", jwt.key, "len", jwt.value.length, "from", u);
          return;
        }
      }
    } catch {}
    // Also inspect Set-Cookie headers (Arcee may issue the token as a cookie).
    try {
      const sc = res.headers()["set-cookie"];
      if (sc) {
        for (const part of String(sc).split(",")) {
          const m = part.match(/access_token=(eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)/);
          if (m && !found) {
            found = { key: "access_token(cookie)", value: m[1] };
            console.log(">>> FOUND (set-cookie) len", m[1].length, "from", u);
            return;
          }
        }
      }
    } catch {}
  }

  // context-level: covers popups (Google OAuth consent window) too
  context.on("request", (req) => {
    const u = req.url();
    if (u.includes("arcee.ai") && (u.includes("token") || u.includes("auth") || u.includes("refresh") || u.includes("session") || u.includes("callback") || u.includes("oauth"))) {
      if (!seenUrls.has(u)) {
        seenUrls.add(u);
        console.log("REQ", req.method(), u);
      }
    }
  });
  context.on("response", scan);

  console.log("opening chat.arcee.ai — LOG IN via Google when prompted...");
  const page = await context.newPage();
  await page.goto("https://chat.arcee.ai", { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {});

  const deadline = Date.now() + 600000;
  while (!found && Date.now() < deadline) {
    await page.waitForTimeout(3000);
    const left = Math.round((deadline - Date.now()) / 1000);
    if (!found && left % 15 === 0) console.log("waiting for login + token mint,", left, "s left");
  }

  if (!found) {
    console.error("NO token captured from network (login not completed?).");
    await context.close().catch(() => {});
    process.exitCode = 2;
    return;
  }

  const token = found.value;
  const allCookies = await context.cookies();
  const cookieHeader = allCookies.map((c) => `${c.name}=${c.value}`).join("; ");

  const data = { access_token: token, token_key: found.key, captured_at: Date.now(), cookie: cookieHeader };
  fs.writeFileSync(OUT_FILE, JSON.stringify(data, null, 2), "utf8");

  try {
    const full = JSON.parse(fs.readFileSync(CREDENTIALS_FILE, "utf8"));
    full.ARCEE_ACCESS_TOKEN = token;
    full.ARCEE_COOKIE = cookieHeader;
    fs.writeFileSync(CREDENTIALS_FILE, JSON.stringify(full, null, 2), "utf8");
    console.log("updated credentials.json ARCEE_ACCESS_TOKEN + ARCEE_COOKIE");
  } catch (e) {
    console.log("credentials write warn:", e.message);
  }

  console.log("ACCESS TOKEN (", found.key, ") LEN:", token.length, "->", OUT_FILE);
  await context.close().catch(() => {});
}

main().catch((e) => {
  console.error(e.stack || e);
  process.exitCode = 1;
});
