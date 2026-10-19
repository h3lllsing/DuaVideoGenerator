/**
 * CI + local smoke suite for the 7871 upload server.
 * Heavy-runner-free: only exercises routes that don't need Python.
 * Run:  node test/smoke.mjs          (expects server on BASE, default 7879)
 * BASE=http://127.0.0.1:7879 node test/smoke.mjs
 */
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..", "..");
const AUTH_FILE = process.env.AUTH_FILE || path.join(REPO_ROOT, "remotion", "dashboard", "auth.json");
const AUTH_TOKEN = require(AUTH_FILE).token;
const AUTH_HDR = { Authorization: `Bearer ${AUTH_TOKEN}` };

const BASE = process.env.BASE || "http://127.0.0.1:7879";

let pass = 0, fail = 0;
const ok = (n) => { pass++; console.log(`  PASS  ${n}`); };
const no = (n, extra = "") => { fail++; console.log(`  FAIL  ${n}  ${extra}`); };

async function get(p, headers = {}) {
  const r = await fetch(`${BASE}${p}`, { headers });
  const body = await r.text();
  return { status: r.status, body, headers: r.headers };
}

// 1. health (no auth)
try {
  const r = await get("/api/v1/upload/health");
  (r.status === 200 ? ok : no)("health 200 without auth", `status=${r.status}`);
} catch (e) { no("health 200 without auth", String(e)); }

// 2. duas: 401 without auth
try {
  const r = await get("/api/v1/duas");
  (r.status === 401 ? ok : no)("duas 401 without token", `status=${r.status}`);
} catch (e) { no("duas 401 without token", String(e)); }

// 3. duas: 200 with Bearer
try {
  const r = await get("/api/v1/duas", AUTH_HDR);
  const j = JSON.parse(r.body);
  (r.status === 200 && j.ok === true ? ok : no)("duas 200 with Bearer", `status=${r.status} ok=${j.ok}`);
} catch (e) { no("duas 200 with Bearer", String(e)); }

// 4. wrong token: 401
try {
  const r = await get("/api/v1/duas", { Authorization: "Bearer 0000000000000000000000000000000000000000000000" });
  (r.status === 401 ? ok : no)("wrong token 401", `status=${r.status}`);
} catch (e) { no("wrong token 401", String(e)); }

// 5. bad token format (not-hex): 401
try {
  const r = await get("/api/v1/duas", { Authorization: "Bearer ../../etc/passwd" });
  (r.status === 401 ? ok : no)("malformed token 401", `status=${r.status}`);
} catch (e) { no("malformed token 401", String(e)); }

// 6. cookie path
try {
  const r = await get("/api/v1/duas", { Cookie: `auth_token=${AUTH_TOKEN}` });
  (r.status === 200 ? ok : no)("cookie auth 200", `status=${r.status}`);
} catch (e) { no("cookie auth 200", String(e)); }

// 7. cookie patch attempted (traversal in cookie value should still 401, not 200)
try {
  const r = await get("/api/v1/duas", { Cookie: "auth_token=../" + AUTH_TOKEN });
  (r.status === 401 ? ok : no)("cookie traversal 401", `status=${r.status}`);
} catch (e) { no("cookie traversal 401", String(e)); }

// 8. 404 unknown route
try {
  const r = await get("/api/v1/unknown", AUTH_HDR);
  (r.status === 404 ? ok : no)("unknown route 404", `status=${r.status}`);
} catch (e) { no("unknown route 404", String(e)); }

// 9. busy route (GET tolerated)
try {
  const r = await get("/api/v1/upload/busy", AUTH_HDR);
  const j = JSON.parse(r.body);
  (r.status === 200 && j.ok === true ? ok : no)("busy route 200", `status=${r.status} ok=${j.ok}`);
} catch (e) { no("busy route 200", String(e)); }

// 10. loopback CORS echo
try {
  const r = await fetch(`${BASE}/api/v1/duas`, {
    headers: { ...AUTH_HDR, Origin: "http://127.0.0.1:7860" },
  });
  const aca = r.headers.get("access-control-allow-origin") || "";
  (aca === "http://127.0.0.1:7860" ? ok : no)("loopback CORS echo", `got="${aca}"`);
} catch (e) { no("loopback CORS echo", String(e)); }

// 11. non-loopback origin blocked
try {
  const r = await fetch(`${BASE}/api/v1/duas`, {
    headers: { ...AUTH_HDR, Origin: "http://evil.example.com" },
  });
  const body = await r.text();
  (body.includes("cross-origin blocked") ? ok : no)("cross-origin blocked", `status=${r.status}`);
} catch (e) { no("cross-origin blocked", String(e)); }

// 12. known route methods: upload/busy with POST
try {
  const r = await fetch(`${BASE}/api/v1/upload/busy`, { method: "POST", headers: AUTH_HDR });
  const j = JSON.parse(await r.text());
  (r.status === 200 && j.ok === true ? ok : no)("busy POST 200", `status=${r.status} ok=${j.ok}`);
} catch (e) { no("busy POST 200", String(e)); }

console.log(`\nsmoke: ${pass} pass, ${fail} fail`);
process.exit(fail ? 1 : 0);
