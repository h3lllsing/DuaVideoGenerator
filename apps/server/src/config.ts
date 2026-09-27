/**
 * Static configuration: filesystem layout, platform registry, limits.
 *
 * Paths are derived from this file's location (apps/server/src/config.ts) so
 * the server works regardless of the working directory it is launched from.
 */
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** H:\DuaVideoGenerator */
export const PROJECT = path.resolve(HERE, "..", "..", "..");
export const REMOTION = path.join(PROJECT, "remotion");
export const SCRIPTS = path.join(REMOTION, "scripts");
export const SOCIAL = path.join(SCRIPTS, "social");
export const DATA = path.join(PROJECT, "data");

export const PY = process.env.DUA_PYTHON || "python";

/** Cross-platform ledger written by remotion/scripts/social/state.py */
export const UPLOAD_STATE = path.join(DATA, "upload_state.json");
export const CATALOG = path.join(DATA, "duas.json");

/** Bind to loopback only, matching remotion/dashboard/server.js (port 7860). */
export const PORT = Number(process.env.PORT || 7871);
export const HOST = process.env.HOST || "127.0.0.1";

/** Hard ceiling per upload, per the spec. Instagram container polling can be
 *  slow, so this is a safety net rather than a typical path. */
export const UPLOAD_TIMEOUT_MS = Number(process.env.UPLOAD_TIMEOUT_MS || 300_000);
export const ALL_PLATFORMS_TIMEOUT_MS = UPLOAD_TIMEOUT_MS * 4 + 30_000;

export const PLATFORMS = ["youtube", "tiktok", "instagram", "facebook"] as const;
export type Platform = (typeof PLATFORMS)[number];

export function isPlatform(value: string): value is Platform {
  return (PLATFORMS as readonly string[]).includes(value);
}

/**
 * Script that performs the upload for each platform.
 *
 * YouTube reuses the hardened remotion/scripts/upload_shorts.py rather than a
 * new adapter -- it already has retry, quota and the state integration. The
 * other three are the Phase 2 adapters.
 */
export const SCRIPT_FOR: Record<Platform, string> = {
  youtube: path.join(SCRIPTS, "upload_shorts.py"),
  tiktok: path.join(SOCIAL, "tiktok_upload.py"),
  instagram: path.join(SOCIAL, "instagram_upload.py"),
  facebook: path.join(SOCIAL, "facebook_upload.py"),
};

/** Platforms whose caption/duration limits differ enough to matter in the UI. */
export const PLATFORM_META: Record<Platform, { label: string; captionLimit: number }> = {
  youtube: { label: "YouTube", captionLimit: 5000 },
  tiktok: { label: "TikTok", captionLimit: 2200 },
  instagram: { label: "Instagram", captionLimit: 2200 },
  facebook: { label: "Facebook", captionLimit: 63206 },
};
