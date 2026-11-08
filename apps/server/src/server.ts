/**
 * HTTP entry point. Zero runtime dependencies -- node:http only, matching
 * remotion/dashboard/server.js so this project keeps its no-npm-install
 * property. TypeScript runs directly via Node 24 type stripping, so there is
 * no build step either.
 *
 * Run:  node src/server.ts          (or: npm start)
 */
import http from "node:http";
import fs from "node:fs";
import crypto from "node:crypto";
import path from "node:path";
import { AUTH_TOKEN, CRASH_LOG, HOST, PORT, PLATFORMS } from "./config.ts";
import { handle, type Ctx, type Reply } from "./routes/upload.ts";
import { busyKeys } from "./lib/runner.ts";

const MAX_BODY_BYTES = 1024 * 64; // 64 KB is plenty for query-only POSTs

function isLoopbackOrigin(origin: string): boolean {
  return /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i.test(origin);
}

function cors(origin: string, res: http.ServerResponse): void {
  // Loopback-only service; echo the origin so the browser may attach the
  // auth_token cookie spontaneously (port-agnostic per RFC 6265).
  res.setHeader("Vary", "Origin");
  if (!origin || !isLoopbackOrigin(origin)) return;
  res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Access-Control-Allow-Credentials", "true");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Access-Control-Max-Age", "600");
}

function parseCookies(header: string | undefined): Record<string, string> {
  const cookies: Record<string, string> = {};
  if (!header) return cookies;
  for (const pair of header.split(";")) {
    const idx = pair.indexOf("=");
    if (idx > 0) cookies[pair.slice(0, idx).trim()] = pair.slice(idx + 1).trim();
  }
  return cookies;
}

function timingSafeCompare(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) return false;
  try {
    return crypto.timingSafeEqual(bufA, bufB);
  } catch (_) {
    return false;
  }
}

function verifyAuth(req: http.IncomingMessage): boolean {
  const auth = req.headers.authorization ?? "";
  if (auth.startsWith("Bearer ") && timingSafeCompare(auth.slice(7), AUTH_TOKEN)) return true;
  const cookies = parseCookies(req.headers.cookie);
  return Boolean(cookies.auth_token && timingSafeCompare(cookies.auth_token, AUTH_TOKEN));
}

function send(req: http.IncomingMessage, res: http.ServerResponse, reply: Reply): void {
  const body = JSON.stringify(reply.body, null, 2);
  cors(req.headers.origin ?? "", res);
  res.writeHead(reply.status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
  });
  res.end(body);
}

function logLine(method: string, url: string, status: number, ms: number): void {
  const stamp = new Date().toISOString();
  console.log(`${stamp} ${method} ${url} -> ${status} (${ms}ms)`);
}

const server = http.createServer((req, res) => {
  const started = Date.now();
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "127.0.0.1"}`);
  const method = (req.method ?? "GET").toUpperCase();

  const origin = req.headers.origin ?? "";
  if (origin && !isLoopbackOrigin(origin) && url.pathname.startsWith("/api/")) {
    cors(origin, res);
    res.writeHead(403, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok: false, error: "cross-origin blocked" }));
    logLine(method, url.pathname, 403, Date.now() - started);
    return;
  }
  // /api/v1/upload/health stays open (README health checks); everything else
  // requires Bearer or the auth_token cookie the dashboard already set.
  if (url.pathname.startsWith("/api/") &&
      url.pathname !== "/api/v1/upload/health" && !verifyAuth(req)) {
    cors(origin, res);
    res.writeHead(401, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok: false, error: "unauthorized" }));
    logLine(method, url.pathname, 401, Date.now() - started);
    return;
  }
  if (method === "OPTIONS") {
    cors(origin, res);
    res.writeHead(204);
    res.end();
    return;
  }

  // Drain and discard any body: every endpoint here is query/path driven, but
  // an unread socket body can stall keep-alive connections.
  req.on("data", () => {});
  req.on("end", async () => {
    const ctx: Ctx = { method, pathname: url.pathname, query: url.searchParams, params: {} };
    try {
      const reply = await handle(ctx);
      if (reply) {
        send(req, res, reply);
        logLine(method, url.pathname + url.search, reply.status, Date.now() - started);
        return;
      }
      if (url.pathname === "/api/v1/upload/busy") {
        send(req, res, { status: 200, body: { ok: true, in_flight: busyKeys() } });
        logLine(method, url.pathname, 200, Date.now() - started);
        return;
      }
      send(req, res, {
        status: 404,
        body: { error: "no such route", method, path: url.pathname,
                routes: [
                  "GET  /api/v1/duas",
                  "GET  /api/v1/upload/health",
                  "GET  /api/v1/upload/busy",
                  "GET  /api/v1/upload/status",
                  "GET  /api/v1/upload/status/:dua_id",
                  "POST /api/v1/upload/:platform/:dua_id[?dry_run=1]",
                  "POST /api/v1/upload/all/:dua_id[?dry_run=1]",
                  "POST /api/v1/upload/retry/:dua_id/:platform[?dry_run=1]",
                ] },
      });
      logLine(method, url.pathname, 404, Date.now() - started);
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      console.error(`${new Date().toISOString()} ERROR ${method} ${url.pathname}:`, exc);
      send(req, res, { status: 500, body: { error: "internal error", detail: message } });
      logLine(method, url.pathname, 500, Date.now() - started);
    }
  });
});

function crashAppend(msg: string): void {
  try {
    const dir = path.dirname(CRASH_LOG);
    if (fs.existsSync(CRASH_LOG) && fs.statSync(CRASH_LOG).size > 2 * 1024 * 1024) {
      const stamp = new Date().toISOString().slice(0, 10);
      try { fs.renameSync(CRASH_LOG, path.join(dir, `crash-${stamp}.log`)); } catch (_) {}
      const olds = fs.readdirSync(dir)
        .filter((n) => /^crash-\d{4}-\d{2}-\d{2}\.log$/.test(n)).sort();
      while (olds.length > 3) {
        try { fs.unlinkSync(path.join(dir, String(olds.shift()))); } catch (_) {}
      }
    }
    fs.appendFileSync(CRASH_LOG, `${new Date().toISOString()} ${msg}\n`);
  } catch (_) {
    /* best effort -- never crash because of the crash logger */
  }
}
async function alertExternal(msg: string): Promise<void> {
  const url = process.env.ALERT_WEBHOOK_URL ?? "";
  if (!url) return;
  try {
    await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ time: new Date().toISOString(), msg }) });
  } catch (_) { /* best effort -- never crash because of the alert */ }
}
process.on("uncaughtException", (e) => {
  const msg = e instanceof Error ? (e.stack ?? e.message) : String(e);
  console.error(`${new Date().toISOString()} CRASH ${msg}`);
  crashAppend(msg);
  void alertExternal(msg);
});
process.on("unhandledRejection", (e) => {
  const msg = e instanceof Error ? (e.stack ?? e.message) : String(e);
  console.error(`${new Date().toISOString()} REJECTION ${msg}`);
  crashAppend(msg);
  void alertExternal(msg);
});

server.on("error", (exc: NodeJS.ErrnoException) => {
  if (exc.code === "EADDRINUSE") {
    console.error(
      `Port ${PORT} is already in use. The remotion dashboard uses 7860.\n` +
      `Start this server on a different port:  set PORT=7872 && node src/server.ts`,
    );
    process.exit(1);
  }
  throw exc;
});

server.listen(PORT, HOST, () => {
  console.log(`dua-upload-server listening on http://${HOST}:${PORT}`);
  console.log(`platforms: ${PLATFORMS.join(", ")}`);
  console.log(`dry-run any upload:  POST /api/v1/upload/tiktok/<dua_id>?dry_run=1`);
  console.log(`catalog:             GET  /api/v1/duas`);
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    console.log(`\n${signal} received, closing.`);
    server.close(() => process.exit(0));
    // Do not let a hung child keep the process alive forever.
    setTimeout(() => process.exit(0), 3000).unref();
  });
}
