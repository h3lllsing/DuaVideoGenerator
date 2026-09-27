# Upload API (Phase 3)

Thin HTTP wrapper over the Phase 2 Python uploaders. One writer rule: **Python owns
`data/upload_state.json`; this service only reads it and runs scripts.** That is why there
are no write races and no lock files to go stale.

## Zero dependencies, on purpose

This project already runs a dependency-free Node server (`remotion/dashboard/server.js`, port
7860). Phase 3 matches that: raw `node:http`, no `npm install`, no build step. Node 24 runs the
TypeScript directly via type stripping, so `src/**/*.ts` is the shipped code.

**Do not use `enum` or `namespace`** — Node strips types, it does not transpile them.

## Run

```powershell
cd H:\DuaVideoGenerator\apps\server
node src\server.ts          # or: npm start
```

Defaults to `http://127.0.0.1:7871` (the dashboard already owns 7860).

| Env var | Default | Purpose |
| --- | --- | --- |
| `PORT` | `7871` | HTTP port |
| `HOST` | `127.0.0.1` | Bind address; loopback only |
| `UPLOAD_TIMEOUT_MS` | `300000` | Per-upload ceiling (5 min) |
| `DUA_PYTHON` | `python` | Python interpreter |

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/v1/upload/youtube/:dua_id` | `upload_shorts.py` |
| POST | `/api/v1/upload/tiktok/:dua_id` | `social/tiktok_upload.py` |
| POST | `/api/v1/upload/instagram/:dua_id` | `social/instagram_upload.py` |
| POST | `/api/v1/upload/facebook/:dua_id` | `social/facebook_upload.py` |
| POST | `/api/v1/upload/all/:dua_id` | Sequential: YouTube → TikTok → Instagram → Facebook |
| POST | `/api/v1/upload/retry/:dua_id/:platform` | 409 if already completed |
| GET | `/api/v1/upload/status` | Whole ledger + per-platform tallies |
| GET | `/api/v1/upload/status/:dua_id` | One dua, all four platforms |
| GET | `/api/v1/duas` | Catalog joined with upload phase; `?q=` `?limit=` |
| GET | `/api/v1/upload/health` | Liveness |
| GET | `/api/v1/upload/busy` | In-flight lock keys |
| GET | `/api/v1/upload/quota` | Today's YouTube budget — the dashboard should poll this |

**Every POST accepts `?dry_run=1`**, which forwards `--dry-run` to the uploader. This is how the
whole surface is exercised without credentials, and dry-runs never write the ledger.

`:dua_id` is validated against `^[A-Za-z0-9_-]+$` before any process is spawned.

## Status codes

The status tells you *whose* problem it is, so the dashboard can react without string matching.

| Code | `failure` | Meaning |
| --- | --- | --- |
| 200 | `null` | Uploaded (or dry-run) |
| 400 | `invalid` | Malformed `dua_id` |
| 404 | — | Unknown platform or route |
| 409 | `busy` | Same dua+platform already running — **do not retry immediately** |
| **429** | **`quota`** | **YouTube daily budget spent — stop, try tomorrow** |
| 504 | `timeout` | Exceeded `UPLOAD_TIMEOUT_MS`; the child was killed |
| 502 | `failed` | The uploader ran and reported an error |
| 500 | `spawn` | Python could not be started at all |

`/all` returns 200 when all four succeed, **207** on partial failure with a per-platform
breakdown in `results`.

## YouTube quota guard

YouTube charges 1600 units per upload out of a 10000/day allowance. `upload.py` keeps a
2000-unit reserve, so the ceiling is 5/day. These constants are mirrored from
`remotion/scripts/upload.py:59-62`; if you change one, change both.

Without a guard in the API layer, `POST /upload/all` on 170 videos would fire 170 YouTube
uploads in a row and blow the budget in the first five — the dashboard would be a quota
firehose. `/all` returning 207 with one leg blocked is a deliberate choice: a spent YouTube
budget must not also cost you the TikTok, Instagram and Facebook posts.

Four things that are easy to get wrong here, and how this handles them:

**YouTube only.** TikTok, Instagram and Facebook have no unit budget. Charging 1600 units for a
Reel would make `/all` fail after five runs.

**Reserve before spawning, not record after.** `upload.py` calls `record_units()` *after* a
successful upload, so two uploads that both pass the pre-check both proceed and burn 3200 units
against a 1600 budget. Here the units are written to disk before the process starts and returned
if it fails. The trade-off is deliberate: a crash mid-upload burns a slot (you try tomorrow),
whereas the race spends quota you cannot get back.

**Account-wide, not ledger-wide.** Quota belongs to the YouTube account. `upload.py` works
against `upload_state_channel1.json` / `quota_state_channel1.json`; this API owns
`upload_state.json` / `quota_state.json`. Today's units are summed across **every**
`quota_state*.json` so neither half's uploads are invisible to the other.

**No daily-reset code.** The file is a flat `{ "YYYY-MM-DD": units }` map. Tomorrow's key is
absent and reads as 0. There is no counter to reset.

Usage is `max(units_from_quota, uploads_from_ledger) + in_flight`, matching `upload.py:540`. The
`max()` matters: after a partial failure the two sources can disagree, and trusting the smaller
one would re-grant budget that is already spent.

Writes go to `data/quota_state.json` via a same-directory temp file plus rename, pruned to 60
days, exactly like `save_quota()`. Dry-runs are never charged.

## Concurrency

A `Set` keyed `platform:duaId` holds in-flight uploads. A duplicate request gets 409 both from a
pre-spawn fast path and from inside the runner, so a double-click cannot start two uploads or
waste a Python process. Different duas run in parallel. The lock drains in a `finally`, so a
crashed upload cannot leak it.

This is in-process only. It deliberately does not cover the Python-side `autopilot.lock` that
`remotion/scripts/upload.py` uses — if you run that daemon, the two can still collide.

## Tests

```powershell
node src\server.ts                 # terminal 1
node test\concurrency.mjs          # terminal 2
node test\quota.mjs                # terminal 2
```

`concurrency.mjs` fires concurrent requests in a single Node process (PowerShell `Start-Job` has
~1s spin-up latency and cannot actually race the lock). Verifies: 409 on duplicates, no
over-rejection across different duas, no leaked locks.

`quota.mjs` walks the guard's whole decision surface — constants, non-YouTube platforms staying
free, the 429 wall, refunds on failure, `/all` partial success, dry-runs being free. It writes
`data/quota_state.json` for real because that is the file under test; it snapshots and restores
in a `finally`, so a failure cannot cost you a day's budget.

To exercise the kill path, start the server with a tiny budget:

```powershell
$env:UPLOAD_TIMEOUT_MS = "1"
$env:EXPECT_TIMEOUT = "1"
node src\server.ts
node test\concurrency.mjs
```

Expect 504 with `failure: "timeout"`.

## Not covered

- **Credentials.** Placeholder tokens let dry-runs pass; a real upload fails until you follow
  `remotion/scripts/social/AUTH_SETUP.md`.
- **Long uploads.** A 5-minute ceiling suits Shorts and Reels, not a 10-minute long-form.
- **Analytics.** Nothing here fetches likes or follower counts; the ledger tracks publish state
  and URLs only.
- **Persistence of locks.** Restarting the server clears `in_flight`; the Python lock files are
  the durable mechanism.
- **YouTube quota for `upload.py`.** This guard protects API-driven uploads only. Running
  `upload.py` directly still does its own check-and-record-after, so the two can still race each
  other in a single day.
