import { spawn } from "node:child_process";
import process from "node:process";
import { pickPython, projectRoot } from "./scripts/path-config.mjs";

const host = process.env.HOST || "127.0.0.1";
const port = process.env.PORT || "3001";

const python = pickPython();
const child = spawn(python, ["py/server.py"], {
  cwd: projectRoot,
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
