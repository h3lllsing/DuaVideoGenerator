/**
 * HTTP entry point. Zero runtime dependencies -- node:http only, matching
 * remotion/dashboard/server.js so this project keeps its no-npm-install
 * property. TypeScript runs directly via Node 24 type stripping, so there is
 * no build step either.
 *
 * Run:  node src/server.ts          (or: npm start)
 */
import http from "node:http";
import { HOST, PORT, PLATFORMS } from "./config.ts";
import { handle, type Ctx, type Reply } from "./routes/upload.ts";
import { busyKeys } from "./lib/runner.ts";

const MAX_BODY_BYTES = 1024 * 64; // 64 KB is plenty for query-only POSTs

function cors(res: http.ServerResponse): void {
  // Loopback-only service; the dashboard is served from another origin.
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Access-Control-Max-Age", "600");
}

function send(res: http.ServerResponse, reply: Reply): void {
  const body = JSON.stringify(reply.body, null, 2);
  cors(res);
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

  if (method === "OPTIONS") {
    cors(res);
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
        send(res, reply);
        logLine(method, url.pathname + url.search, reply.status, Date.now() - started);
        return;
      }
      if (url.pathname === "/api/v1/upload/busy") {
        send(res, { status: 200, body: { ok: true, in_flight: busyKeys() } });
        logLine(method, url.pathname, 200, Date.now() - started);
        return;
      }
      send(res, {
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
      send(res, { status: 500, body: { error: "internal error", detail: message } });
      logLine(method, url.pathname, 500, Date.now() - started);
    }
  });
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
