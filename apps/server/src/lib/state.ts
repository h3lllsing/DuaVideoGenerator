/**
 * Read-side helpers over the Python-owned state files.
 *
 * The ledger schema lives in remotion/scripts/social/state.py. This module
 * mirrors only the read path plus the derived views the dashboard needs, so
 * there is exactly one writer (Python) and no write races between processes.
 */
import fs from "node:fs";
import { CATALOG, UPLOAD_STATE } from "../config.ts";

export type Phase = "pending" | "uploading" | "completed" | "failed";

export interface PlatformRecord {
  status?: string;
  phase?: Phase;
  url?: string | null;
  platform_id?: string | null;
  uploaded_at?: string | null;
  error?: string | null;
  retry_count?: number;
  [key: string]: unknown;
}

/**
 * The ledger stores platforms DIRECTLY under the dua key:
 *
 *   "aafiyat_aur_sehat_ki_dua": { "youtube": {...}, "tiktok": {...}, ... }
 *
 * This is owned by remotion/scripts/social/state.py (see update_dua_status,
 * which does `dua.get(platform)`). There is no `platforms` wrapper. A reader
 * that assumes one silently reports every entry as pending, so the lookup
 * below tolerates both shapes and prefers the canonical flat one.
 */
export type DuaEntry = Record<string, unknown> & { platforms?: Record<string, PlatformRecord> };

export interface Ledger {
  _meta?: Record<string, unknown>;
  [duaId: string]: DuaEntry | Record<string, unknown> | undefined;
}

function readJson<T>(file: string, fallback: T): T {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8")) as T;
  } catch {
    return fallback;
  }
}

export function loadLedger(): Ledger {
  const raw = readJson<Record<string, unknown>>(UPLOAD_STATE, {});
  const out: Ledger = {};
  for (const [key, value] of Object.entries(raw)) {
    if (key.startsWith("_")) {
      out._meta = value as Record<string, unknown>;
      continue;
    }
    if (value && typeof value === "object") {
      out[key] = value as DuaEntry;
    }
  }
  return out;
}

export interface CatalogDua {
  id: string;
  title: string;
  category?: string;
  reference?: string;
  bismillah?: boolean;
}

export function loadCatalog(): CatalogDua[] {
  const raw = readJson<unknown>(CATALOG, []);
  const list = Array.isArray(raw) ? raw : (raw as { duas?: unknown[] })?.duas ?? [];
  return (list as Record<string, unknown>[])
    .filter((d) => d && typeof d.id === "string")
    .map((d) => ({
      id: d.id as string,
      title: (d.title as string) || d.id,
      category: d.category as string | undefined,
      reference: d.reference as string | undefined,
      bismillah: d.bismillah as boolean | undefined,
    }));
}

export function phaseOf(record: PlatformRecord | undefined): Phase {
  if (!record) return "pending";
  if (record.phase && ["pending", "uploading", "completed", "failed"].includes(record.phase)) {
    return record.phase as Phase;
  }
  const map: Record<string, Phase> = {
    "\u2705": "completed",
    "\u274c": "failed",
    "\u23f3": "pending",
  };
  return map[String(record.status ?? "")] ?? "pending";
}

/** Single source of truth for "what does this platform's record look like".
 *  Flat first (canonical), nested as a fallback. */
export function platformRecord(entry: DuaEntry | undefined, platform: string): PlatformRecord | null {
  if (!entry) return null;
  const flat = entry[platform];
  if (flat && typeof flat === "object") return flat as PlatformRecord;
  const nested = entry.platforms?.[platform];
  if (nested && typeof nested === "object") return nested;
  return null;
}

/** Phase for every platform of one dua, always returning all four keys. */
export function platformPhases(entry: DuaEntry | undefined): Record<string, Phase> {
  const out: Record<string, Phase> = {};
  for (const platform of PLATFORM_ORDER) out[platform] = phaseOf(platformRecord(entry, platform) ?? undefined);
  return out;
}

const PLATFORM_ORDER = ["youtube", "tiktok", "instagram", "facebook"] as const;

export function statusFor(duaId: string, platform: string): PlatformRecord | null {
  return platformRecord(loadLedger()[duaId] as DuaEntry | undefined, platform);
}

export interface Tally {
  completed: number;
  failed: number;
  pending: number;
  uploading: number;
}

export function tally(): { total: number; platforms: Record<string, Tally> } {
  const ledger = loadLedger();
  const platforms: Record<string, Tally> = {};
  let total = 0;
  for (const [key, value] of Object.entries(ledger)) {
    if (key.startsWith("_") || !value) continue;
    total += 1;
    const entry = value as DuaEntry;
    for (const platform of PLATFORM_ORDER) {
      platforms[platform] ??= { completed: 0, failed: 0, pending: 0, uploading: 0 };
      platforms[platform][phaseOf(platformRecord(entry, platform) ?? undefined)] += 1;
    }
  }
  return { total, platforms };
}
