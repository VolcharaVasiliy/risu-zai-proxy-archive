import process from "node:process";

const baseUrl = process.env.PROXY_HEALTH_URL || "";
const strict = process.argv.includes("--strict");
const publicChecks = process.argv.includes("--public");

async function check(label, url) {
  const started = Date.now();
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const text = await response.text();
    let payload = null;
    try { payload = JSON.parse(text); } catch {}
    return { label, ok: response.ok, status: response.status, duration_ms: Date.now() - started, payload };
  } catch (error) {
    return { label, ok: false, status: 0, duration_ms: Date.now() - started, error: error.message };
  }
}

const checks = [];
if (baseUrl) {
  const normalized = baseUrl.replace(/\/$/, "");
  checks.push(await check("proxy health", `${normalized}/health`));
  checks.push(await check("proxy providers", `${normalized}/v1/providers`));
  checks.push(await check("proxy models", `${normalized}/v1/models`));
}
if (publicChecks) {
  checks.push(await check("OpenCode Zen models", "https://opencode.ai/zen/v1/models"));
  checks.push(await check("UncloseAI Hermes models", "https://hermes.ai.unturf.com/v1/models"));
  checks.push(await check("UncloseAI Qwen-VL models", "https://qwen-vl.ai.unturf.com/v1/models"));
}
for (const item of checks) {
  const suffix = item.error || `${item.status} ${item.duration_ms}ms`;
  console.log(`${item.ok ? "OK" : "WARN"} ${item.label}: ${suffix}`);
}
if (strict && checks.some((item) => !item.ok)) process.exitCode = 1;

