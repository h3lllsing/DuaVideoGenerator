/**
 * Runs a Python uploader as a child process and normalises the result.
 *
 * Mirrors the proven pattern from remotion/dashboard/routes/youtube.js:
 *   spawn(PY, args, { cwd: REMOTION, windowsHide: true })
 * with two additions the spec requires -- a hard timeout and a per-dua lock so
 * a double-click cannot start two uploads for the same video.
 */
import { spawn } from "node:child_process";
import {
  PLATFORMS,
  PY,
  REMOTION,
  SCRIPT_FOR,
  UPLOAD_TIMEOUT_MS,
  isPlatform,
  type Platform,
} from "../config.ts";

export type Failure = "busy" | "invalid" | "quota" | "timeout" | "spawn" | "failed";

export interface RunResult {
  ok: boolean;
  duaId: string;
  platform: Platform;
  exitCode: number | null;
  /** Parsed JSON from the script's last stdout line, when present. */
  result: Record<string, unknown> | null;
  error: string | null;
  /** Why the run did not succeed; null on success. Drives the HTTP status. */
  failure: Failure | null;
  stderr: string;
  durationMs: number;
  dryRun: boolean;
}

/** In-flight uploads, keyed `${platform}:${duaId}`, for the 409 guard. */
const inFlight = new Set<string>();

export function isBusy(platform: string, duaId: string): boolean {
  return inFlight.has(`${platform}:${duaId}`);
}

export function busyKeys(): string[] {
  return [...inFlight];
}

/** Reject anything that could escape the data directory or inject arguments. */
export function validDuaId(duaId: string): boolean {
  return (
    typeof duaId === "string" &&
    duaId.length > 0 &&
    duaId.length <= 120 &&
    /^[A-Za-z0-9_-]+$/.test(duaId)
  );
}

export function buildArgs(platform: Platform, duaId: string, dryRun: boolean): string[] {
  const script = SCRIPT_FOR[platform];
  const args = [script, duaId];
  if (dryRun) args.push("--dry-run");
  return args;
}

export async function runUpload(
  platform: string,
  duaId: string,
  dryRun = false,
  timeoutMs = UPLOAD_TIMEOUT_MS,
): Promise<RunResult> {
  const started = Date.now();

  if (!isPlatform(platform)) {
    return fail(platform as Platform, duaId, dryRun, started, "invalid",
      `unknown platform '${platform}' (expected ${PLATFORMS.join(", ")})`);
  }
  if (!validDuaId(duaId)) {
    return fail(platform, duaId, dryRun, started, "invalid",
      `invalid dua_id '${duaId}' (letters, digits, _ and - only)`);
  }
  const key = `${platform}:${duaId}`;
  if (inFlight.has(key)) {
    return fail(platform, duaId, dryRun, started, "busy",
      `an upload for ${duaId} on ${platform} is already running`);
  }

  inFlight.add(key);
  try {
    return await spawnScript(platform, duaId, dryRun, timeoutMs, started);
  } finally {
    inFlight.delete(key);
  }
}

function spawnScript(
  platform: Platform,
  duaId: string,
  dryRun: boolean,
  timeoutMs: number,
  started: number,
): Promise<RunResult> {
  return new Promise((resolve) => {
    const args = buildArgs(platform, duaId, dryRun);
    let child: ReturnType<typeof spawn>;
    try {
      child = spawn(PY, args, { cwd: REMOTION, windowsHide: true });
    } catch (exc) {
      resolve(fail(platform, duaId, dryRun, started, "spawn",
        `failed to spawn python: ${String(exc)}`));
      return;
    }

    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let settled = false;

    // The uploader prints progress with \r on stderr; keep it bounded so a
    // 300 MB upload cannot grow the buffer without limit.
    const cap = 1_000_000;
    child.stdout?.on("data", (chunk) => {
      stdout += chunk.toString();
      if (stdout.length > cap) stdout = stdout.slice(-cap);
    });
    child.stderr?.on("data", (chunk) => {
      stderr += chunk.toString();
      if (stderr.length > cap) stderr = stderr.slice(-cap);
    });

    const timer = setTimeout(() => {
      timedOut = true;
      try {
        child.kill("SIGKILL");
      } catch {
        /* already gone */
      }
    }, timeoutMs);

    const finish = (exitCode: number | null, spawnError: string | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const parsed = parseLastJson(stdout);
      const durationMs = Date.now() - started;

      if (timedOut) {
        resolve({
          ok: false, duaId, platform, exitCode, result: parsed, durationMs, dryRun,
          failure: "timeout",
          stderr: stderr.slice(-4000),
          error: `timed out after ${formatBudget(timeoutMs)}`,
        });
        return;
      }
      if (spawnError) {
        resolve({
          ok: false, duaId, platform, exitCode, result: parsed, durationMs, dryRun,
          failure: "spawn",
          stderr: stderr.slice(-4000), error: spawnError,
        });
        return;
      }
      // Exit code 0 is clean; the uploaders use 2 for "some items failed".
      const ok = exitCode === 0;
      resolve({
        ok, duaId, platform, exitCode, result: parsed, durationMs, dryRun,
        failure: ok ? null : "failed",
        stderr: stderr.slice(-4000),
        error: ok ? null : errorFrom(parsed, stderr, exitCode),
      });
    };

    child.on("error", (exc) => finish(null, `spawn error: ${exc.message}`));
    child.on("close", (code) => finish(code, null));
  });
}

/** The uploaders print a JSON object on the LAST stdout line; earlier lines
 *  are human progress text. */
export function parseLastJson(stdout: string): Record<string, unknown> | null {
  const lines = stdout.split(/\r?\n/).filter((l) => l.trim().startsWith("{"));
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    try {
      const parsed = JSON.parse(lines[i]);
      if (parsed && typeof parsed === "object") return parsed as Record<string, unknown>;
    } catch {
      /* keep scanning backwards */
    }
  }
  return null;
}

/** 300000 -> "5m", 1000 -> "1s", 1 -> "1ms" (never the useless "0s"). */
export function formatBudget(ms: number): string {
  if (ms >= 60_000) return `${Math.round(ms / 60_000)}m`;
  if (ms >= 1000) return `${Math.round(ms / 1000)}s`;
  return `${Math.round(ms)}ms`;
}

function errorFrom(
  parsed: Record<string, unknown> | null,
  stderr: string,
  exitCode: number | null,
): string {
  const items = parsed?.items;
  if (Array.isArray(items) && items.length) {
    const messages = items
      .map((i) => (i && typeof i === "object" ? (i as Record<string, unknown>).error : null))
      .filter((m): m is string => typeof m === "string");
    if (messages.length) return messages.join(" | ").slice(0, 500);
  }
  const tail = stderr.trim().split(/\r?\n/).filter(Boolean).slice(-3).join(" | ");
  return tail || `exited with code ${exitCode}`;
}

function fail(
  platform: Platform,
  duaId: string,
  dryRun: boolean,
  started: number,
  failure: Failure,
  error: string,
): RunResult {
  return {
    ok: false, duaId, platform, exitCode: null, result: null, error, failure,
    stderr: "", durationMs: Date.now() - started, dryRun,
  };
}
