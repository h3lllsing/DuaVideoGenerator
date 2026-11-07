# Runbook — Dua Video Generator

## 0. Preconditions

- Python 3.11+ (CI: 3.11–3.12; local venv ruff/mypy caches in temp).
- Node 20 (CI) / Node 24 local type-stripping for `apps/server`.
- FFmpeg, edge-tts, Remotion deps installed.
- Secrets: `remotion/dashboard/auth.json` (key `"token"` — bearer token for 7871), YouTube OAuth tokens stored OUT of repo (gitignored); AI keys currently OFF.

## 1. Start (PM2)

- Dashboard: PM2 app `dua-studio` → `node remotion/dashboard/server.js` (port 7860).
- Apps server: `node apps/server/src/server.ts` (port 7871).

## 2. Smoke checks (fresh run)

1. `python -m pytest tests/test_verified_en.py -q --no-cov` → 22 passed.
2. Full suite: `python -m pytest -q` → 578 passed, coverage 66.02% (fail-under 15).
3. API: bearer token from `remotion/dashboard/auth.json` → `curl -s -H "Authorization: Bearer $tok" http://127.0.0.1:7871/api/v1/duas` → `.total` (verified: 258).
4. Remotion: `npm ci`, `npm audit --audit-level=high` (F-21 known fail), `tsc --noEmit`, `remotion bundle`.

## 3. Backup / Restore

- `data/duas.json` + `data/duas.json.bak*` chain (batch backups).
- `data/upload_state_channel1.json` (runtime ledger, tracked F-04 open).

## 4. If something breaks (runbook quick actions)

| Symptom | Action |
|---|---|
| Dashboard down | pm2 logs `dua-studio`; check EADDRINUSE (F-08/F-26) |
| API 7871 crash | F-26: crash handlers missing → add (open) |
| pm2 exit-loop | F-27: max_restarts=10 → low |
| CI ruff-format fail | F-20 → pin ruff / reformat |
| mypy fail | F-19 → numpy-stubs vs py3.11 |
| npm audit fail | F-21 → `npm audit fix` (dev deps) |

## 5. Quota / AI

- Quota ledger `data/quota_state.json`; dry-run upload runner + `apps/server/test/quota.mjs` (server-hon mode).
- AI dua import keys: currently OFF (no AI keys live).

---

> Runbook items marked open (F-26, F-27, F-28, F-19, F-20, F-21) are pending fixes; not invented here.
