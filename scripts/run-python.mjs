import { spawnSync } from "node:child_process";
import process from "node:process";
import { pickPython } from "./path-config.mjs";

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
