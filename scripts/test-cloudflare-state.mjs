import assert from "node:assert/strict";
import worker from "../cloudflare/worker.mjs";

const records = new Map();
const writes = [];
const env = {
  STATE_API_TOKEN: "test-token",
  STATE_TTL_SECONDS: "invalid",
  STATE_KV: {
    async get(key, options) {
      const value = records.get(key);
      if (value === undefined) return null;
      return options?.type === "json" ? JSON.parse(value) : value;
    },
    async put(key, value, options) {
      records.set(key, value);
      writes.push({ key, options });
    },
    async delete(key) {
      records.delete(key);
    },
  },
};

function request(path, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("Authorization", "Bearer test-token");
  return worker.fetch(new Request(`https://worker.example${path}`, { ...init, headers }), env);
}

let response = await worker.fetch(new Request("https://worker.example/internal/state/item"), env);
assert.equal(response.status, 401);

response = await request("/internal/state/response%2Fone", {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ value: { ok: true }, updated_at: 123 }),
});
assert.equal(response.status, 200);
assert.equal(writes[0].key, "response/one");
assert.equal(writes[0].options.expirationTtl, 21600);

response = await request("/internal/state/response%2Fone");
assert.equal(response.status, 200);
assert.deepEqual(await response.json(), { value: { ok: true }, updated_at: 123 });

response = await request("/internal/state/response%2Fone", { method: "DELETE" });
assert.equal(response.status, 200);
assert.deepEqual(await response.json(), { deleted: true });

response = await request("/internal/state/%E0%A4%A");
assert.equal(response.status, 400);

console.log("cloudflare state tests: ok");
