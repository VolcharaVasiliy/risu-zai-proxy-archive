import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

export const projectRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

function loadConfig() {
  const candidates = [
    process.env.RZAI_PATH_CONFIG,
    process.env.PATH_CONFIG,
    path.join(projectRoot, "path-config.json"),
  ].filter(Boolean);
  for (const candidate of candidates) {
    const fullPath = path.resolve(candidate);
    if (!fs.existsSync(fullPath)) {
      continue;
    }
    try {
      return JSON.parse(fs.readFileSync(fullPath, "utf8"));
    } catch (error) {
      throw new Error(`Invalid path config JSON at ${fullPath}: ${error.message}`);
    }
  }
  return {};
}

const config = loadConfig();

export function configValue(keys, defaultValue = "") {
  let node = config;
  for (const key of keys) {
    if (!node || typeof node !== "object" || !(key in node)) {
      return defaultValue;
    }
    node = node[key];
  }
  return node ?? defaultValue;
}

function expandEnv(value) {
  return String(value || "").replace(/%([^%]+)%/g, (_match, name) => process.env[name] || "");
}

export function resolveProjectPath(value, fallback) {
  const text = expandEnv(value || fallback);
  if (path.isAbsolute(text)) {
    return path.normalize(text);
  }
  return path.join(projectRoot, text);
}

function fromEnvRoot(envName, ...parts) {
  return process.env[envName] ? path.join(process.env[envName], ...parts) : "";
}

function unique(values) {
  const result = [];
  const seen = new Set();
  for (const value of values) {
    const text = expandEnv(value);
    if (!text) {
      continue;
    }
    const key = text.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(text.includes("/") || text.includes("\\") ? resolveProjectPath(text, text) : text);
  }
  return result;
}

export function pythonCandidates() {
  return unique([
    process.env.PYTHON,
    process.env.PYTHON_EXE,
    configValue(["python", "executable"]),
    process.platform === "win32" ? "python.exe" : "python3",
    "python3",
    "python",
  ]);
}

export function nodeCandidates() {
  return unique([
    process.env.NODE,
    process.env.NODE_EXE,
    configValue(["node", "executable"]),
    process.execPath,
    "node",
  ]);
}

export function browserCandidates({ includeYandex = false } = {}) {
  const candidates = [
    process.env.BROWSER_PATH,
    process.env.EDGE_PATH,
    process.env.CHROME_PATH,
    configValue(["browser", "executable"]),
  ];
  if (includeYandex) {
    candidates.push(
      configValue(["browser", "yandexExecutable"]),
      fromEnvRoot("LOCALAPPDATA", "Yandex", "YandexBrowser", "Application", "browser.exe"),
    );
  }
  candidates.push(
    fromEnvRoot("ProgramFiles(x86)", "Microsoft", "Edge", "Application", "msedge.exe"),
    fromEnvRoot("ProgramFiles", "Microsoft", "Edge", "Application", "msedge.exe"),
    fromEnvRoot("LOCALAPPDATA", "Microsoft", "Edge", "Application", "msedge.exe"),
    fromEnvRoot("ProgramFiles", "Google", "Chrome", "Application", "chrome.exe"),
    fromEnvRoot("ProgramFiles(x86)", "Google", "Chrome", "Application", "chrome.exe"),
    fromEnvRoot("LOCALAPPDATA", "Google", "Chrome", "Application", "chrome.exe"),
  );
  return unique(candidates);
}

export function pickExecutable(candidates, { probeArgs = [] } = {}) {
  for (const candidate of candidates.filter(Boolean)) {
    if (path.isAbsolute(candidate) && !fs.existsSync(candidate)) {
      continue;
    }
    if (!probeArgs.length) {
      return candidate;
    }
    const probe = spawnSync(candidate, probeArgs, { encoding: "utf8", stdio: "pipe" });
    if (probe.status === 0) {
      return candidate;
    }
  }
  throw new Error("Required executable was not found. Set it in path-config.json or an environment variable.");
}

export function pickPython() {
  return pickExecutable(pythonCandidates(), { probeArgs: ["--version"] });
}

export function authProfile(name, defaultFolder) {
  const envName = `RZAI_${name.toUpperCase()}_PROFILE_ROOT`;
  return resolveProjectPath(process.env[envName] || configValue(["profiles", name]), path.join("auth", defaultFolder));
}

export function authOutput(name, defaultFile) {
  const envName = `RZAI_${name.toUpperCase()}_CREDS_FILE`;
  return resolveProjectPath(process.env[envName] || configValue(["authOutputs", name]), path.join("auth", defaultFile));
}
