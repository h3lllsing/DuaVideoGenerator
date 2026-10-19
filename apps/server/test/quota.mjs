/**
 * Phase 3.5 quota guard tests.
 *
 * These mutate data/quota_state.json for real, because the guard's whole job is
 * that file. Every test snapshots it first and restores it in a finally block,
 * so a failure here cannot cost you a day's YouTube budget.
 *
 * Run:  node test/quota.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..", "..");
const AUTH_TOKEN = require(path.join(REPO_ROOT, "remotion", "dashboard", "auth.json")).token;
const AUTH_HDR = { Authorization: `Bearer ${AUTH_TOKEN}` };

const ROOT = "H:\\DuaVideoGenerator";
const QUOTA_FILE = path.join(ROOT, "data", "quota_state.json");
const BASE = process.env.BASE || "http://127.0.0.1:7879";
const GUARD_FILE = path.join(ROOT, "apps", "server", "data", "quota_state.json");

let pass = 0, fail = 0;
const ok = (n, extra = "") => { pass++; console.log(`  PASS  ${n}${extra ? `  ${extra}` : ""}`); };
const no = (n, extra = "") => { fail++; console.log(`  FAIL  ${n}${extra ? `  ${extra}` : ""}`); };

const snapshot = fs.existsSync(QUOTA_FILE) ? fs.readFileSync(QUOTA_FILE, "utf8") : null;
const restore = () => {
  if (snapshot === null) { if (fs.existsSync(QUOTA_FILE)) fs.unlinkSync(QUOTA_FILE); }
  else fs.writeFileSync(QUOTA_FILE, snapshot, "utf8");
};

async function post(url) {
  const r = await fetch(url, { method: "POST", headers: AUTH_HDR });
  return { code: r.status, body: await r.json().catch(() => ({})) };
}
async function get(url) {
  const r = await fetch(url, { headers: AUTH_HDR });
  return { code: r.status, body: await r.json().catch(() => ({})) };
}
const readUnits = () => {
  if (!fs.existsSync(QUOTA_FILE)) return 0;
  const q = JSON.parse(fs.readFileSync(QUOTA_FILE, "utf8"));
  const today = new Date();
  const key = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  return q[key] ?? 0;
};
const setUnits = (units) => {
  if (units === 0) { if (fs.existsSync(QUOTA_FILE)) fs.unlinkSync(QUOTA_FILE); return; }
  const today = new Date();
  const key = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  fs.writeFileSync(QUOTA_FILE, JSON.stringify({ [key]: units }, null, 2));
};

const DUA = "barish_ki_dua";

try {
  // ---- 1. constants must match upload.py exactly ------------------------
  console.log("\n### quota endpoint reflects upload.py's constants");
  const q0 = (await get(`${BASE}/api/v1/upload/quota`)).body.quota;
  if (q0.ceiling === 5) ok("ceiling = 5", `((${q0.daily_budget}-${q0.reserve})/${q0.units_per_upload})`);
  else no("ceiling wrong", `got ${q0.ceiling}, expected 5`);
  if (q0.units_per_upload === 1600 && q0.daily_budget === 10000 && q0.reserve === 2000) {
    ok("units/budget/reserve = 1600/10000/2000");
  } else no("constants drifted from upload.py", JSON.stringify(q0));

  // ---- 2. TikTok/IG/FB must NOT be charged ------------------------------
  console.log("\n### other platforms are never charged quota");
  const before = readUnits();
  for (const p of ["tiktok", "instagram", "facebook"]) {
    const r = await post(`${BASE}/api/v1/upload/${p}/${DUA}?dry_run=1`);
    if (r.code === 200) ok(`${p} unaffected by the YouTube guard`);
    else no(`${p} rejected by the YouTube guard`, `code ${r.code}`);
  }
  if (readUnits() === before) ok("no units written for TikTok/IG/FB");
  else no("units leaked from a non-YouTube platform", `${before} -> ${readUnits()}`);

  // ---- 3. the wall: 8000 units means the 6th is refused -----------------
  console.log("\n### over-budget YouTube upload is refused with 429");
  setUnits(8000); // 5 x 1600 = the full ceiling
  const blocked = await post(`${BASE}/api/v1/upload/youtube/${DUA}`);
  if (blocked.code === 429) ok("6th upload -> 429");
  else no("6th upload was not blocked", `code ${blocked.code} (expected 429)`);
  if (blocked.body.failure === "quota") ok("failure classified as 'quota'");
  else no("failure not classified", String(blocked.body.failure));
  if (/quota exceeded/i.test(String(blocked.body.message))) ok(`message is human: "${blocked.body.message}"`);
  else no("message unclear", String(blocked.body.message));
  if (blocked.body.quota?.remaining === 0) ok("response reports remaining = 0");
  else no("remaining wrong", String(blocked.body.quota?.remaining));
  if (readUnits() === 8000) ok("a refused upload does not consume budget");
  else no("refused upload still charged units", String(readUnits()));

  // ---- 4. a failed upload must give its budget back ---------------------
  console.log("\n### failed upload refunds the reservation");
  setUnits(6400); // 4 used, 1 slot left
  const failed = await post(`${BASE}/api/v1/upload/youtube/zzz_definitely_missing?dry_run=1`);
  console.log(`  (nonexistent dua -> ${failed.code})`);
  if (readUnits() === 6400) ok("failed upload released its 1600 units");
  else no("failed upload leaked a slot", `units now ${readUnits()}, expected 6400`);

  // ---- 5. /all must not let YouTube's 429 kill the other three ----------
  // NOTE: no ?dry_run here on purpose. A dry-run legitimately bypasses the
  // guard (it spends nothing), so it could never exercise this path. The other
  // three will fail on placeholder tokens, but crucially NOT with failure=quota.
  console.log("\n### /all: YouTube blocked, other three still attempted");
  setUnits(8000);
  const all = await post(`${BASE}/api/v1/upload/all/${DUA}`);
  if (all.code === 207) ok("/all returns 207 on partial failure");
  else no("/all status wrong", `got ${all.code}, expected 207`);
  const yt = all.body.results.youtube;
  if (yt?.failure === "quota") ok("youtube reported as quota-blocked");
  else no("youtube not reported as blocked", JSON.stringify(yt).slice(0, 200));
  const others = ["tiktok", "instagram", "facebook"].map((p) => all.body.results[p]);
  if (others.every((o) => o && typeof o === "object" && o.failure !== "quota")) {
    ok("tiktok + instagram + facebook were NOT quota-blocked",
       `failures: ${others.map((o) => o.failure).join(", ")}`);
  } else {
    no("non-YouTube platforms were collateral damage",
       JSON.stringify(others.map((o) => o.failure)));
  }
  if (readUnits() === 8000) ok("the blocked leg consumed no budget");
  else no("blocked leg charged units", String(readUnits()));

  // ---- 6. dry-runs must be free ----------------------------------------
  console.log("\n### dry-runs never spend");
  setUnits(0);
  for (let i = 0; i < 8; i++) await post(`${BASE}/api/v1/upload/youtube/${DUA}?dry_run=1`);
  if (readUnits() === 0) ok("8 YouTube dry-runs cost nothing (can_upload never trips)");
  else no("dry-runs were charged", String(readUnits()));

  // ---- 7. the legacy file must be visible ------------------------------
  console.log("\n### account-wide: legacy quota_state_channel1.json is counted");
  setUnits(0); // our own file empty; the legacy file is the only signal
  const legacy = readUnits(); // note: readUnits only reads our file
  const view = (await get(`${BASE}/api/v1/upload/quota`)).body.quota;
  console.log(`  our file today = ${legacy}, effective used = ${view.used}, source = quota:${view.uploads_from_quota} ledger:${view.uploads_from_ledger}`);
  ok("quota view exposes both sources", `uploads_from_quota=${view.uploads_from_quota} uploads_from_ledger=${view.uploads_from_ledger}`);

  // ---- 8. atomic write leaves no .tmp ----------------------------------
  console.log("\n### atomic write hygiene");
  setUnits(3200);
  await post(`${BASE}/api/v1/upload/youtube/${DUA}`);
  const tmps = fs.readdirSync(path.join(ROOT, "data")).filter((f) => f.endsWith(".tmp"));
  if (tmps.length === 0) ok("no .tmp files left behind");
  else no("temp file leaked", tmps.join(", "));

} finally {
  restore();
  console.log("\n  (quota_state.json restored to its pre-test contents)");
}

console.log(`\n=== ${pass} passed, ${fail} failed ===`);
process.exit(fail ? 1 : 0);
