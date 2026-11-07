# API — Dua Video Generator (apps/server)

## Base

- Local: `http://127.0.0.1:7871`
- Auth: `Authorization: Bearer <token>` from `remotion/dashboard/auth.json` (`token` key).

## Verified Endpoint

### GET /api/v1/duas

```
curl.exe -s -H "Authorization: Bearer $tok" http://127.0.0.1:7871/api/v1/duas
```

Verified response shape:

```json
{ "ok": true, "total": <int>, "returned": <int>, "duas": [ { "id", "title", "category", "reference", "bismillah" } ] }
```

Verified state (docs batch): `total: 258` — catalog (`data/duas.json`) read live by server.

## Other (known)

- Upload endpoints under `/api/v1/upload/...` — bearer-protected (F-01 partially mitigated by token; origin check pending).
- Dashboard UI: port 7860 (`remotion/dashboard/server.js`), stats per video (views/likes/comments) + channel stats; quota tracking; duplicate prevention (upload gate ~90% Arabic-norm dup).

## Open API items

- F-26: 7871 upload API crash handlers missing (MEDIUM).
- F-01: 7871 auth/CORS partial (MEDIUM-HIGH) — bearer + origin whitelist recommended.
