import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function extractModels(html) {
  const re = new RegExp('self\\.__next_f\\.push\\(\\[1,("(?:[^"\\\\]|\\\\.)*")\\]\\)', "g");
  let m, rsc = null;
  while ((m = re.exec(html))) {
    try { const s = JSON.parse(m[1]); if (s.includes("initialModels")) { rsc = s; break; } } catch (e) {}
  }
  if (!rsc) return [];
  const i = rsc.indexOf("initialModels");
  const j = rsc.indexOf("[", i);
  let arrDepth = 0, braceDepth = 0, k = j, inStr = false, esc = false;
  for (; k < rsc.length; k++) {
    const ch = rsc[k];
    if (inStr) { if (esc) esc = false; else if (ch === "\\") esc = true; else if (ch === '"') inStr = false; continue; }
    if (ch === '"') inStr = true;
    else if (ch === "[") arrDepth++;
    else if (ch === "]") { arrDepth--; if (arrDepth === 0 && braceDepth === 0) { k++; break; } }
    else if (ch === "{") braceDepth++;
    else if (ch === "}") braceDepth--;
  }
  let raw = rsc.slice(j, k);
  raw = raw.replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  return JSON.parse(raw);
}

function argValue(n, f = "") { const i = process.argv.indexOf(n); return i >= 0 && i + 1 < process.argv.length ? String(process.argv[i + 1] || "") : f; }
function main() {
  const file = argValue("--html");
  const out = argValue("--out", path.join(os.tmpdir(), "arena-models.json"));
  let html;
  if (file) html = fs.readFileSync(file, "utf8");
  else { html = fs.readFileSync(path.join(os.tmpdir(), "arena-direct.html"), "utf8"); }
  const models = extractModels(html);
  const map = {};
  // Pass 1: canonical `name` wins (overwrite allowed) so exact model names
  // always point at their own id rather than a sibling variant.
  for (const m of models) {
    const id = m.id; if (!id) continue;
    if (m.name) map[m.name.toLowerCase()] = id;
  }
  // Pass 2: displayName / publicName only fill gaps (first occurrence wins) so a
  // variant's shared display name does not clobber the canonical mapping.
  for (const m of models) {
    const id = m.id; if (!id) continue;
    for (const nm of [m.displayName, m.publicName]) {
      if (!nm) continue;
      const k = nm.toLowerCase();
      if (!(k in map)) map[k] = id;
    }
  }
  const result = { count: models.length, byName: map, models: models.map((m) => ({ id: m.id, displayName: m.displayName, publicName: m.publicName, name: m.name, organization: m.organization, provider: m.provider, userSelectable: m.userSelectable })) };
  fs.writeFileSync(out, JSON.stringify(result, null, 2), "utf8");
  console.log("models:", models.length, "unique names:", Object.keys(map).length);
  console.log("sample:", JSON.stringify(models.slice(0, 5)));
}
main();
