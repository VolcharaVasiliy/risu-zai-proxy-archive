import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const requiredFiles = [
  "package.json",
  "vercel.json",
  "local-server.js",
  "api/index.py",
  "py/arcee_proxy.py",
  "py/grok_proxy.py",
  "py/gemini_web_proxy.py",
  "py/google_ai_studio_proxy.py",
  "py/google_ai_studio_web_proxy.py",
  "py/http_helpers.py",
  "py/credentials_bootstrap.py",
  "py/agent_tools.py",
  "py/inflection_proxy.py",
  "py/mimo_proxy.py",
  "py/multimodal.py",
  "py/openai_web_proxy.py",
  "py/phind_proxy.py",
  "py/pi_local_proxy.py",
  "py/responses_api.py",
  "py/provider_registry.py",
  "py/server.py",
  "py/uncloseai_proxy.py",
  "py/zai_proxy.py",
  "README.md",
  "REDEPLOY.md",
  "requirements.txt",
  "scripts/test_agent_tools.py",
  "scripts/get-arcee-creds.py",
  "scripts/get-qwen-creds.py",
  "scripts/get-grok-creds.py",
  "scripts/get-gemini-web-creds.py",
  "scripts/get-google-ai-studio-web-creds.py",
  "scripts/get-openai-web-creds.py",
  "scripts/get-openai-web-session.mjs",
  "scripts/launch-gemini-auth.ps1",
  "scripts/launch-openai-auth.ps1",
  "scripts/launch-grok-auth.ps1",
  "scripts/launch-pi-auth.ps1",
  "scripts/pi-browser-bridge.mjs",
  "scripts/redeploy-vercel.ps1",
];

for (const file of requiredFiles) {
  const fullPath = path.join(process.cwd(), file);
  if (!fs.existsSync(fullPath)) {
    throw new Error(`Missing required file: ${file}`);
  }
}

const pythonCandidates = [
  process.env.PYTHON,
  "F:\\DevTools\\Python311\\python.exe",
  process.platform === "win32" ? "python.exe" : "python3",
  "python",
].filter(Boolean);

let python = "";
for (const candidate of pythonCandidates) {
  if (path.isAbsolute(candidate) && !fs.existsSync(candidate)) {
    continue;
  }
  const probe = spawnSync(candidate, ["--version"], { encoding: "utf8" });
  if (probe.status === 0) {
    python = candidate;
    break;
  }
}

if (!python) {
  throw new Error("Python is required for this proxy but was not found");
}

const compile = spawnSync(python, ["-m", "compileall", "-q", "py", "api"], {
  cwd: process.cwd(),
  encoding: "utf8",
});
if (compile.status !== 0) {
  throw new Error(
    `Python compile failed:\n${compile.stdout || ""}${compile.stderr || ""}`,
  );
}

const nodeSyntax = spawnSync(process.execPath, ["--check", "local-server.js"], {
  cwd: process.cwd(),
  encoding: "utf8",
});
if (nodeSyntax.status !== 0) {
  throw new Error(
    `Node syntax check failed:\n${nodeSyntax.stdout || ""}${nodeSyntax.stderr || ""}`,
  );
}

const agentToolsTest = spawnSync(python, ["scripts/test_agent_tools.py"], {
  cwd: process.cwd(),
  encoding: "utf8",
});
if (agentToolsTest.status !== 0) {
  throw new Error(
    `Agent tool tests failed:\n${agentToolsTest.stdout || ""}${agentToolsTest.stderr || ""}`,
  );
}

console.log("check: ok");
