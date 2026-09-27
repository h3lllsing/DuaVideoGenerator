/**
 * Phase 3 verification: true concurrency via a single Node process (PowerShell
 * Start-Job has ~1s spin-up latency, so it cannot actually race the lock).
 * Run:  node _phase3_concurrency.mjs
 */
const BASE = process.env.BASE || "http://127.0.0.1:7879";
const DUA = "barish_ki_dua";

let pass = 0, fail = 0;
const ok = (n) => { pass++; console.log(`  PASS  ${n}`); };
const no = (n, extra = "") => { fail++; console.log(`  FAIL  ${n}  ${extra}`); };

async function post(url) {
  const r = await fetch(url, { method: "POST" });
  const body = await r.json().catch(() => ({}));
  return { code: r.status, body };
}

// --- 1. true race: 6 concurrent requests, same platform + same dua ---------
console.log(`\n### 6 concurrent POST /upload/tiktok/${DUA}?dry_run=1`);
const t0 = Date.now();
const results = await Promise.all(
  Array.from({ length: 6 }, () => post(`${BASE}/api/v1/upload/tiktok/${DUA}?dry_run=1`)),
);
console.log(`  elapsed=${Date.now() - t0}ms  codes=[${results.map(r => r.code).join(", ")}]`);

const locked = results.filter(r => r.code === 409);
const clean = results.filter(r => r.code === 200);
const allowed = new Set([200, 409]);
if (Number(process.env.EXPECT_TIMEOUT)) allowed.add(504); // 1ms budget: 504 is the correct answer
const bad = results.filter(r => !allowed.has(r.code));

if (locked.length > 0) ok(`lock rejected ${locked.length} duplicate(s) with 409`);
else no("lock never fired", "no request overlapped the in-flight window");

if (bad.length > 0) {
  no(`${bad.length} response(s) were neither 200 nor 409`,
     JSON.stringify(bad[0].body).slice(0, 400));
} else ok("no spurious non-409 rejections under concurrency");

if (bad.length === 0 && results.length === 6) {
  ok(`accounted for all 6 (${clean.length} ran, ${locked.length} locked, ${results.length - clean.length - locked.length} other)`);
} else {
  no("responses unaccounted", JSON.stringify(results.map(r => r.code)));
}

// the 409 body must be actionable
if (locked.length) {
  const msg = String(locked[0].body?.message ?? locked[0].body?.error ?? "");
  if (/already running/i.test(msg)) ok(`409 body explains itself: "${msg}"`);
  else no("409 body unhelpful", JSON.stringify(locked[0].body).slice(0, 200));
}

// --- 2. lock must be per-(platform,dua), not global ------------------------
console.log("\n### different dua + same platform should NOT be locked");
const [a, b] = await Promise.all([
  post(`${BASE}/api/v1/upload/tiktok/barish_ki_dua?dry_run=1`),
  post(`${BASE}/api/v1/upload/tiktok/sachai_aur_imandari_ki_dua?dry_run=1`),
]);
console.log(`  codes=[${a.code}, ${b.code}]`);
if (Number(process.env.EXPECT_TIMEOUT)) {
  console.log("  (skipped: a 1ms budget makes this case meaningless)");
} else if (a.code === 200 && b.code === 200) {
  ok("distinct duas run in parallel, neither locked");
} else {
  no("lock is too coarse or over-rejecting", `codes=[${a.code}, ${b.code}]`);
}

// --- 3. in_flight must drain to empty (no leaked locks) --------------------
console.log("\n### /busy must drain after all runs");
const busy = await (await fetch(`${BASE}/api/v1/upload/busy`)).json();
if (Array.isArray(busy.in_flight) && busy.in_flight.length === 0) ok("no leaked locks");
else no("leaked in-flight locks", JSON.stringify(busy.in_flight));

// --- 4. a run that outlives the budget must be killed, not hang ------------
// Set UPLOAD_TIMEOUT_MS=1 when starting the server for this check; a normal
// dry-run takes ~250ms so a 1ms budget is guaranteed to trip.
console.log(`\n### timeout enforcement (server started with UPLOAD_TIMEOUT_MS=${process.env.EXPECT_TIMEOUT ?? "default"})`);
const t1 = Date.now();
const to = await post(`${BASE}/api/v1/upload/tiktok/${DUA}?dry_run=1`);
const el = Date.now() - t1;
console.log(`  code=${to.code} elapsed=${el}ms failure=${JSON.stringify(to.body?.failure)} message=${JSON.stringify(to.body?.message)}`);
if (Number(process.env.EXPECT_TIMEOUT)) {
  if (el < 15000) ok(`timed out in ${el}ms without hanging`);
  else no("timeout did not fire", `took ${el}ms`);
  if (/timed out/i.test(String(to.body?.message ?? ""))) ok("timeout surfaces a clear error");
  else no("timeout error unclear", String(to.body?.message));
  if (to.body?.failure === "timeout") ok("timeout is classified as failure=timeout");
  else no("timeout not classified", String(to.body?.failure));
}

console.log(`\n=== ${pass} passed, ${fail} failed ===`);
process.exit(fail ? 1 : 0);
