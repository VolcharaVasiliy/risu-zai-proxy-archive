import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(fileURLToPath(import.meta.url));
const host = process.env.HOST || "127.0.0.1";
const port = process.env.PORT || "3001";

const pythonCandidates = [
  process.env.PYTHON,
  "F:\\DevTools\\Python311\\python.exe",
  process.platform === "win32" ? "python.exe" : "python3",
  "python",
].filter(Boolean);

function pickPython() {
  for (const candidate of pythonCandidates) {
    if (path.isAbsolute(candidate) && !existsSync(candidate)) {
      continue;
    }
    return candidate;
  }
  return "python";
}

const python = pickPython();
const child = spawn(python, ["py/server.py"], {
  cwd: rootDir,
  stdio: "inherit",
  env: {
    ...process.env,
    HOST: host,
    PORT: port,
    PYTHONUNBUFFERED: "1",
  },
});

child.on("error", (error) => {
  console.error(
    `Failed to start Python API server with ${python}: ${error.message}`,
  );
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    console.error(`Python API server stopped after signal ${signal}`);
    process.exit(1);
  }
  process.exit(code ?? 0);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    if (!child.killed) {
      child.kill(signal);
    }
  });
}
