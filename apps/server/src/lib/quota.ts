/**
 * YouTube daily quota guard.
 *
 * Semantics are copied from remotion/scripts/upload.py so the two systems
 * cannot disagree, but with one deliberate improvement described under
 * "Reserve, don't record" below.
 *
 * ## Reserve, don't record
 *
 * upload.py calls record_units() *after* a successful upload. Two uploads that
 * both pass the pre-check therefore both proceed, and the real account burns
 * 3200 units against a 1600-unit budget. Here the units are written to disk
 * *before* the process is spawned, and returned if it fails. The trade-off is
 * deliberate: a crash mid-upload burns a slot (safe, you just try tomorrow),
 * whereas the race in upload.py spends real quota you cannot get back.
 *
 * ## Account-wide, not ledger-wide
 *
 * Quota belongs to the YouTube account, not to a ledger file. The legacy
 * upload.py works against upload_state_channel1.json / quota_state_channel1.json
 * while this API owns upload_state.json. Reading only one file would let the
 * other half's uploads go unseen and overshoot the same account, so today's
 * units are summed across every quota_state*.json present.
 *
 * ## YouTube only
 *
 * TikTok, Instagram and Facebook have no unit budget. Charging 1600 units for
 * a Reel would make /all permanently fail after five runs.
 *
 * ## "Daily reset" needs no code
 *
 * The file is a flat { "YYYY-MM-DD": units } map. Tomorrow's key is simply
 * absent, and a missing key reads as 0. There is no counter to reset.
 */
import fs from "node:fs";
import path from "node:path";
import { DATA } from "../config.ts";
import { loadLedger, phaseOf, platformRecord, type DuaEntry } from "./state.ts";

/** Mirrors upload.py:59-62. Do not drift. */
export const UPLOAD_UNITS = 1600;
export const DAILY_BUDGET = 10_000;
export const QUOTA_RESERVE = 2000;
export const DAILY_CEILING = Math.floor((DAILY_BUDGET - QUOTA_RESERVE) / UPLOAD_UNITS); // 5

/** upload.py prunes anything older than this. */
const RETENTION_DAYS = 60;

/** Quota applies to YouTube only. */
const GUARDED = new Set(["youtube"]);

export function isGuarded(platform: string): boolean {
  return GUARDED.has(platform);
}

/** The file this API owns, derived by upload.py's quota_path_for() rule. */
export const QUOTA_FILE = path.join(DATA, "quota_state.json");

/** Units reserved by in-flight uploads in this process, keyed platform:duaId. */
const reservations = new Map<string, number>();

type QuotaMap = Record<string, number>;

function today(): string {
  // Local date, matching Python's date.today().isoformat().
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function readQuota(file: string): QuotaMap {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: QuotaMap = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (/^\d{4}-\d{2}-\d{2}$/.test(k) && Number.isFinite(Number(v))) out[k] = Number(v);
    }
    return out;
  } catch {
    return {};
  }
}

function writeQuota(file: string, q: QuotaMap): void {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - RETENTION_DAYS);
  const floor = cutoff.toISOString().slice(0, 10);
  const pruned: QuotaMap = {};
  for (const [k, v] of Object.entries(q)) if (k >= floor) pruned[k] = v;
  // Same atomic dance as state.py: temp file in the same dir, then rename.
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(pruned, null, 2)}\n`, "utf8");
  fs.renameSync(tmp, file);
}

/** Every quota file present, so no writer can hide spend from this guard. */
function quotaFiles(): string[] {
  let names: string[] = [];
  try {
    names = fs.readdirSync(DATA);
  } catch {
    return [QUOTA_FILE];
  }
  const found = names
    .filter((n) => /^quota_state.*\.json$/.test(n))
    .map((n) => path.join(DATA, n));
  return found.length ? found : [QUOTA_FILE];
}

/** Units spent today across every quota file. */
export function unitsToday(): number {
  const key = today();
  return quotaFiles().reduce((sum, file) => sum + (readQuota(file)[key] ?? 0), 0);
}

/**
 * YouTube uploads that completed today according to the UNIFIED ledger.
 *
 * upload.py's uploads_today() tests `status == "uploaded"`, but this ledger
 * stores a display glyph plus a machine phase, so that function would always
 * return 0 here. Counting on `phase` is the correct equivalent.
 */
export function ledgerUploadsToday(): number {
  const key = today();
  const ledger = loadLedger();
  let n = 0;
  for (const [duaId, value] of Object.entries(ledger)) {
    if (duaId.startsWith("_") || !value) continue;
    const record = platformRecord(value as DuaEntry, "youtube");
    if (!record) continue;
    if (phaseOf(record) === "completed" && String(record.uploaded_at ?? "").startsWith(key)) n += 1;
  }
  return n;
}

export interface QuotaView {
  platform: string;
  units_per_upload: number;
  daily_budget: number;
  reserve: number;
  ceiling: number;
  units_spent_today: number;
  uploads_from_quota: number;
  uploads_from_ledger: number;
  reserved_in_flight: number;
  used: number;
  remaining: number;
  can_upload: boolean;
  date: string;
}

/**
 * Effective usage = max(quota file, unified ledger) + in-flight reservations.
 *
 * The max() mirrors upload.py:540. Either source can be ahead of the other
 * after a partial failure, and trusting the smaller one would re-grant budget
 * that is already spent.
 */
export function view(platform = "youtube"): QuotaView {
  const units = unitsToday();
  const uploadsFromQuota = Math.floor(units / UPLOAD_UNITS);
  const uploadsFromLedger = ledgerUploadsToday();
  const reserved = reservations.get(platform) ?? 0;
  const used = Math.max(uploadsFromQuota, uploadsFromLedger) + reserved;
  const remaining = Math.max(DAILY_CEILING - used, 0);
  return {
    platform,
    units_per_upload: UPLOAD_UNITS,
    daily_budget: DAILY_BUDGET,
    reserve: QUOTA_RESERVE,
    ceiling: DAILY_CEILING,
    units_spent_today: units,
    uploads_from_quota: uploadsFromQuota,
    uploads_from_ledger: uploadsFromLedger,
    reserved_in_flight: reserved,
    used,
    remaining,
    can_upload: remaining > 0,
    date: today(),
  };
}

export class QuotaExceeded extends Error {
  readonly detail: QuotaView;
  constructor(detail: QuotaView) {
    super(
      `Daily quota exceeded: ${detail.used}/${detail.ceiling} YouTube uploads used ` +
      `(+${detail.reserve}-unit reserve). Try tomorrow.`,
    );
    this.name = "QuotaExceeded";
    this.detail = detail;
  }
}

/**
 * Claim one upload's worth of budget. Call BEFORE spawning the uploader.
 * Persists immediately so a crash cannot hand the same slot out twice.
 */
export function reserve(platform: string, _duaId: string): QuotaView {
  if (!isGuarded(platform)) return view(platform);
  const before = view(platform);
  if (!before.can_upload) throw new QuotaExceeded(before);

  const file = QUOTA_FILE;
  const q = readQuota(file);
  const key = today();
  q[key] = (q[key] ?? 0) + UPLOAD_UNITS;
  writeQuota(file, q);
  reservations.set(platform, (reservations.get(platform) ?? 0) + 1);
  return view(platform);
}

/** Give the budget back after a failed or rejected upload. */
export function release(platform: string, _duaId: string): void {
  if (!isGuarded(platform)) return;
  const held = reservations.get(platform) ?? 0;
  if (held <= 0) return;
  reservations.set(platform, held - 1);

  const q = readQuota(QUOTA_FILE);
  const key = today();
  const next = (q[key] ?? 0) - UPLOAD_UNITS;
  if (next > 0) q[key] = next;
  else delete q[key];
  writeQuota(QUOTA_FILE, q);
}

/** Upload succeeded: the units stay spent, just stop counting it as held. */
export function commit(platform: string, _duaId: string): void {
  if (!isGuarded(platform)) return;
  const held = reservations.get(platform) ?? 0;
  if (held > 0) reservations.set(platform, held - 1);
}

/** Test hook: forget in-flight reservations without touching the file. */
export function _resetReservations(): void {
  reservations.clear();
}
