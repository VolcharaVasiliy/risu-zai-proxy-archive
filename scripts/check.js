import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { pickPython } from "./path-config.mjs";

const requiredFiles = [
  "package.json",
  "vercel.json",
  "cloudflare/worker.mjs",
  "local-server.js",
  "api/index.py",
  "py/arcee_proxy.py",
  "py/grok_proxy.py",
  "py/gemini_web_proxy.py",
  "py/google_ai_studio_proxy.py",
  "py/google_ai_studio_web_proxy.py",
  "py/http_helpers.py",
  "py/observability.py",
  "py/metrics.py",
  "py/state_store.py",
  "py/bridge_manager.py",
  "generated/provider-catalog.json",
  "docs/provider-catalog.md",
  "extensions/credentials-exporter/provider-schema.js",
  ".github/workflows/check.yml",
  "scripts/generate_provider_artifacts.py",
  "scripts/generate_extension_i18n.py",
  "scripts/provider-health.mjs",
  "scripts/provider_health.py",
  "scripts/test_state_http.py",
  "scripts/test_generated_artifacts.py",
  "scripts/test-cloudflare-state.mjs",
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
  "docs/observability.md",
  "REDEPLOY.md",
  "path-config.example.json",
  "requirements.txt",
  "scripts/path_config.py",
  "scripts/path-config.mjs",
  "scripts/path-config.ps1",
  "scripts/run-python.mjs",
  "scripts/setup-windows.ps1",
  "scripts/test_agent_tools.py",
  "scripts/test_observability.py",
  "scripts/test_docs.py",
  "scripts/generate-codex-catalog.py",
  "scripts/install-rzai.ps1",
  "scripts/rzai-launcher.ps1",
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

const python = pickPython();

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

for (const script of ["scripts/run-python.mjs", "scripts/check.js"]) {
  const check = spawnSync(process.execPath, ["--check", script], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
  if (check.status !== 0) {
    throw new Error(
      `Node syntax check failed for ${script}:\n${check.stdout || ""}${check.stderr || ""}`,
    );
  }
}

const readme = fs.readFileSync(path.join(process.cwd(), "README.md"), "utf8");
for (const snippet of [
  "## Quick Start On Windows",
  "scripts\\setup-windows.ps1",
  "rzai -Print",
  "npm run dev",
]) {
  if (!readme.includes(snippet)) {
    throw new Error(`README is missing onboarding snippet: ${snippet}`);
  }
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

const cloudflareSyntax = spawnSync(process.execPath, ["--check", "cloudflare/worker.mjs"], {
  cwd: process.cwd(),
  encoding: "utf8",
});
if (cloudflareSyntax.status !== 0) {
  throw new Error(
    `Cloudflare Worker syntax check failed:\n${cloudflareSyntax.stdout || ""}${cloudflareSyntax.stderr || ""}`,
  );
}

const cloudflareStateTest = spawnSync(process.execPath, ["scripts/test-cloudflare-state.mjs"], {
  cwd: process.cwd(),
  encoding: "utf8",
});
if (cloudflareStateTest.status !== 0) {
  throw new Error(
    `Cloudflare state tests failed:\n${cloudflareStateTest.stdout || ""}${cloudflareStateTest.stderr || ""}`,
  );
}

const observabilityTest = spawnSync(python, ["scripts/test_observability.py"], {
  cwd: process.cwd(),
  encoding: "utf8",
});
if (observabilityTest.status !== 0) {
  throw new Error(
    `Observability tests failed:\n${observabilityTest.stdout || ""}${observabilityTest.stderr || ""}`,
  );
}

for (const script of ["scripts/test_state_metrics.py", "scripts/test_state_http.py", "scripts/test_extension.py", "scripts/test_provider_contracts.py", "scripts/test_generated_artifacts.py"]) {
  const result = spawnSync(python, [script], { cwd: process.cwd(), encoding: "utf8" });
  if (result.status !== 0) throw new Error(`${script} failed:\n${result.stdout || ""}${result.stderr || ""}`);
}

const docsTest = spawnSync(python, ["scripts/test_docs.py"], {
  cwd: process.cwd(),
  encoding: "utf8",
});
if (docsTest.status !== 0) {
  throw new Error(
    `Documentation tests failed:\n${docsTest.stdout || ""}${docsTest.stderr || ""}`,
  );
}

for (const script of ["scripts/generate_provider_artifacts.py", "scripts/generate_extension_i18n.py"]) {
  const generated = spawnSync(python, [script, "--check"].filter(Boolean), { cwd: process.cwd(), encoding: "utf8" });
  if (generated.status !== 0) throw new Error(`${script} is stale:\n${generated.stdout || ""}${generated.stderr || ""}`);
}

const providerHealth = spawnSync(python, ["scripts/provider_health.py"], { cwd: process.cwd(), encoding: "utf8" });
if (providerHealth.status !== 0) throw new Error(`Provider health matrix failed:\n${providerHealth.stdout || ""}${providerHealth.stderr || ""}`);

const codexCatalog = spawnSync(
  python,
  [
    "scripts/generate-codex-catalog.py",
    "--provider",
    "mistral",
    "--model",
    "mistral-small-2603",
    "--indent",
    "0",
  ],
  {
    cwd: process.cwd(),
    encoding: "utf8",
  },
);
if (codexCatalog.status !== 0) {
  throw new Error(
    `Codex catalog generation failed:\n${codexCatalog.stdout || ""}${codexCatalog.stderr || ""}`,
  );
}

try {
  const catalog = JSON.parse(codexCatalog.stdout);
  if (!Array.isArray(catalog.models) || catalog.models.length !== 1) {
    throw new Error("expected one generated Mistral model");
  }
  if (catalog.models[0].slug !== "mistral-small-2603") {
    throw new Error("unexpected generated model slug");
  }
} catch (error) {
  throw new Error(`Codex catalog JSON validation failed: ${error.message}`);
}

console.log("check: ok");
