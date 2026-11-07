/**
 * Upload API -- the 8 endpoints from the spec, plus GET /api/v1/duas which
 * Phase 4's dashboard needs to list the catalog.
 *
 * Design notes
 * ------------
 * * The API is a thin, honest wrapper. It does not fabricate results: whatever
 *   the Python uploader prints on its last stdout line is what comes back, and
 *   the Python side owns all writes to upload_state.json. One writer, no races.
 * * `?dry_run=1` is threaded through to the script, which is how the whole
 *   surface is testable without credentials.
 * * /all runs sequentially, in platform order, so one failure never masks
 *   another and quota-limited YouTube goes first.
 */
import { ALL_PLATFORMS_TIMEOUT_MS, PLATFORMS, UPLOAD_TIMEOUT_MS, isPlatform, type Platform } from "../config.ts";
import { loadCatalog, loadLedger, phaseOf, platformPhases, platformRecord, tally, type DuaEntry, type PlatformRecord } from "../lib/state.ts";
import { busyKeys, isBusy, runUpload, validDuaId, type RunResult, type Failure } from "../lib/runner.ts";
import { QuotaExceeded, commit, isGuarded, release, reserve, view } from "../lib/quota.ts";

export interface Ctx {
  method: string;
  pathname: string;
  query: URLSearchParams;
  params: Record<string, string>;
}

export interface Reply {
  status: number;
  body: unknown;
}

type Handler = (ctx: Ctx) => Promise<Reply>;

interface Route {
  method: string;
  pattern: RegExp;
  handler: Handler;
  keys: string[];
}

/** Build a RegExp from "/upload/:platform/:dua_id" plus its capture names. */
function route(method: string, path: string, handler: Handler): Route {
  const keys: string[] = [];
  const source = path.replace(/:([A-Za-z_]+)/g, (_m, name: string) => {
    keys.push(name);
    return "([^/]+)";
  });
  const safeHandler: Handler = async (ctx) => {
    try {
      return await handler(ctx);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { status: 500, ok: false, error: msg } as unknown as Reply;
    }
  };
  return { method, pattern: new RegExp(`^${source}/?$`), handler: safeHandler, keys };
}

function extract(routeDef: Route, pathname: string): Record<string, string> | null {
  const match = routeDef.pattern.exec(pathname);
  if (!match) return null;
  const params: Record<string, string> = {};
  routeDef.keys.forEach((key, i) => {
    params[key] = decodeURIComponent(match[i + 1] ?? "");
  });
  return params;
}

function wantsDryRun(ctx: Ctx): boolean {
  const v = ctx.query.get("dry_run") ?? ctx.query.get("dryRun");
  return v === "1" || v === "true";
}

function shape(run: RunResult): Record<string, unknown> {
  return {
    status: run.ok ? "\u2705" : "\u274c",
    ok: run.ok,
    dua_id: run.duaId,
    platform: run.platform,
    url: extractUrl(run),
    message: run.error ?? (run.ok ? "uploaded" : "failed"),
    failure: run.failure,
    exit_code: run.exitCode,
    duration_ms: run.durationMs,
    dry_run: run.dryRun,
    detail: run.result,
    stderr_tail: run.ok || !run.stderr ? undefined : run.stderr.slice(-600),
  };
}

/**
 * Map the runner's failure classification onto HTTP. This is what lets a
 * double-click get 409 (fix your request) instead of 502 (something broke).
 */
const STATUS_FOR: Record<Failure, number> = {
  busy: 409,
  invalid: 400,
  quota: 429,
  timeout: 504,
  spawn: 500,
  failed: 502,
};

function replyFor(run: RunResult): Reply {
  return { status: run.ok ? 200 : STATUS_FOR[run.failure ?? "failed"], body: shape(run) };
}

/** Build a synthetic RunResult so quota rejections flow through one path. */
function quotaReply(exc: unknown, platform: string, duaId: string): Reply {
  const detail = exc instanceof QuotaExceeded ? exc.detail : view(platform);
  const run: RunResult = {
    ok: false, duaId, platform: platform as Platform, exitCode: null, result: null,
    error: exc instanceof Error ? exc.message : String(exc),
    failure: "quota", stderr: "", durationMs: 0, dryRun: false,
  };
  return { status: 429, body: { ...shape(run), quota: detail } };
}

/**
 * Run one upload with the YouTube quota guard wrapped around it.
 *
 * Reserve -> run -> commit on success / release on anything else. The guard is
 * skipped for dry-runs, which spend nothing, and for platforms with no unit
 * budget.
 */
async function guardedUpload(platform: string, duaId: string, dryRun: boolean): Promise<Reply> {
  if (!isPlatform(platform)) {
    return { status: 404, body: { error: `unknown platform '${platform}'`, expected: PLATFORMS } };
  }
  if (duaId && !validDuaId(duaId)) {
    return { status: 400, body: { error: `invalid dua_id '${duaId}'` } };
  }
  if (isBusy(platform, duaId)) {
    return {
      status: 409,
      body: { ok: false, dua_id: duaId, platform, message: `an upload for ${duaId} on ${platform} is already running` },
    };
  }

  const guarded = isGuarded(platform) && !dryRun;
  if (guarded) {
    try {
      reserve(platform, duaId);
    } catch (exc) {
      return quotaReply(exc, platform, duaId);
    }
  }
  try {
    const run = await runUpload(platform, duaId, dryRun, UPLOAD_TIMEOUT_MS);
    if (guarded) {
      if (run.ok) commit(platform, duaId);
      else release(platform, duaId);
    }
    return replyFor(run);
  } catch (exc) {
    if (guarded) release(platform, duaId);
    throw exc;
  }
}

/** Prefer the URL the script reported; fall back to the ledger. */
function extractUrl(run: RunResult): string | null {
  const items = run.result?.items;
  if (Array.isArray(items) && items.length) {
    const first = items[0] as Record<string, unknown> | undefined;
    if (first && typeof first.url === "string") return first.url;
  }
  return null;
}

async function uploadOne(platform: string, duaId: string, dryRun: boolean): Promise<Reply> {
  return guardedUpload(platform, duaId, dryRun);
}

const routes: Route[] = [
  route("POST", "/api/v1/upload/all/:dua_id", async (ctx) => {
    const { dua_id: duaId } = ctx.params;
    const dryRun = wantsDryRun(ctx);
    const results: Record<string, unknown> = {};
    let anyFailed = false;
    for (const platform of PLATFORMS) {
      // Sequential on purpose: one failure never masks another, and YouTube
      // (the quota-limited one) goes first so its budget is spent deliberately.
      const reply = await guardedUpload(platform, duaId, dryRun);
      results[platform] = reply.body;
      if (reply.status !== 200) anyFailed = true;
    }
    return {
      // 429 from YouTube alone is still a partial success for the other three.
      status: anyFailed ? 207 : 200,
      body: {
        ok: !anyFailed,
        dua_id: duaId,
        dry_run: dryRun,
        results,
        note: anyFailed ? "partial failure: see per-platform results" : undefined,
        budget_ms: ALL_PLATFORMS_TIMEOUT_MS,
        quota: view("youtube"),
      },
    };
  }),

  route("POST", "/api/v1/upload/retry/:dua_id/:platform", async (ctx) => {
    const { dua_id: duaId, platform } = ctx.params;
    if (!isPlatform(platform)) {
      return { status: 404, body: { error: `unknown platform '${platform}'`, expected: PLATFORMS } };
    }
    const before = currentRecord(duaId, platform);
    if (before && phaseOf(before) === "completed") {
      return {
        status: 409,
        body: {
          error: `${duaId} is already completed on ${platform}`,
          url: before.url ?? null,
          hint: "use the ledger directly to re-post; retry is for failed uploads",
        },
      };
    }
    // The uploader resets retry_count and clears the stale error when it marks
    // the record 'uploading', so no state write is needed here. A retry still
    // costs a full 1600 units, so it goes through the same guard.
    const reply = await guardedUpload(platform, duaId, wantsDryRun(ctx));
    return { status: reply.status, body: { ...(reply.body as object), previous: before ?? null } };
  }),

  route("POST", "/api/v1/upload/:platform/:dua_id", async (ctx) => {
    return uploadOne(ctx.params.platform, ctx.params.dua_id, wantsDryRun(ctx));
  }),

  route("GET", "/api/v1/upload/status", async () => {
    const ledger = loadLedger();
    const duas: Record<string, DuaEntry> = {};
    let tracked = 0;
    for (const [key, value] of Object.entries(ledger)) {
      if (key.startsWith("_") || !value) continue;
      duas[key] = value as DuaEntry;
      tracked += 1;
    }
    return {
      status: 200,
      body: { ok: true, total: tracked, stats: tally(), duas },
    };
  }),

  route("GET", "/api/v1/upload/status/:dua_id", async (ctx) => {
    const { dua_id: duaId } = ctx.params;
    const entry = loadLedger()[duaId] as DuaEntry | undefined;
    if (!entry) {
      return { status: 404, body: { error: `no upload state for '${duaId}'` } };
    }
    const platforms: Record<string, unknown> = {};
    for (const platform of PLATFORMS) {
      const record = platformRecord(entry, platform);
      platforms[platform] = record
        ? { ...record, phase: phaseOf(record) }
        : { status: "\u23f3", phase: "pending", url: null, error: null, retry_count: 0 };
    }
    return { status: 200, body: { ok: true, dua_id: duaId, platforms } };
  }),

  route("GET", "/api/v1/duas", async (ctx) => {
    const duas = loadCatalog();
    const ledger = loadLedger();
    const limit = Number(ctx.query.get("limit") || 0);
    const search = (ctx.query.get("q") || "").trim().toLowerCase();
    let rows = duas.map((d) => {
      const entry = ledger[d.id] as DuaEntry | undefined;
      return { id: d.id, title: d.title, category: d.category, platforms: platformPhases(entry) };
    });
    if (search) {
      rows = rows.filter((r) => r.id.toLowerCase().includes(search) || r.title.toLowerCase().includes(search));
    }
    const total = rows.length;
    if (limit > 0) rows = rows.slice(0, limit);
    return { status: 200, body: { ok: true, total, returned: rows.length, duas: rows } };
  }),

  route("GET", "/api/v1/upload/quota", async () => {
    return { status: 200, body: { ok: true, quota: view("youtube") } };
  }),

  route("GET", "/api/v1/upload/health", async () => {
    return { status: 200, body: { ok: true, service: "dua-upload-server", platforms: PLATFORMS } };
  }),
];

export async function handle(ctx: Ctx): Promise<Reply | null> {
  for (const routeDef of routes) {
    if (routeDef.method !== ctx.method) continue;
    const params = extract(routeDef, ctx.pathname);
    if (params) {
      return routeDef.handler({ ...ctx, params });
    }
  }
  return null;
}

function currentRecord(duaId: string, platform: string): PlatformRecord | null {
  return platformRecord(loadLedger()[duaId] as DuaEntry | undefined, platform);
}
