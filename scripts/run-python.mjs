import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const candidates = [
  process.env.PYTHON,
  process.env.PYTHON_EXE,
  process.platform === "win32" ? "python.exe" : "python3",
  "python3",
  "python",
].filter(Boolean);

function pickPython() {
  for (const candidate of candidates) {
    if (path.isAbsolute(candidate) && !fs.existsSync(candidate)) {
      continue;
    }
    const probe = spawnSync(candidate, ["--version"], {
      encoding: "utf8",
      stdio: "pipe",
    });
    if (probe.status === 0) {
      return candidate;
    }
  }
  throw new Error(
    "Python 3 was not found. Install Python 3.11+ or set PYTHON to python.exe.",
  );
}

const python = pickPython();
const result = spawnSync(python, process.argv.slice(2), {
  cwd: process.cwd(),
  env: process.env,
  stdio: "inherit",
});

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
