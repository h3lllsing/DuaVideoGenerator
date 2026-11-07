# Audit Findings — Noor-e-Iman / Dua Video Generator

> **Phase:** Complete-audit deliverable (docs-only phase; NO code changes made in this write).
> **Living source of truth:** `SYSTEM_DOCS/09_ISSUES_FINDINGS.md` (F-01…F-28).
> **This doc consolidates** the 8 audit areas into one findings set written for the docs phase.

## Method / Verification basis

- Live test runs: `pytest tests/test_verified_en.py -q --no-cov` (22 passed); full `pytest -q` (578 passed, 66.02% cov).
- Live API: `GET /api/v1/duas` → `total: 258` (bearer token from `remotion/dashboard/auth.json`).
- Catalog inserts: assert-guarded (id/arabic/field checks) + reload sanity; dedupe via extended normalization (Urdu-script ہ/ی/ک mapped).
- Git: HEAD `f36ada7` (docs phase).

## Area 1 — Business & Channel Analytics (Noor-e-Iman)

- **Finding:** Local + hosted analytics source NOT currently functional for Noor-e-Iman views/likes — user-confirmed local limitation; hosted not configured now.
- **Impact:** Growth/retention/monetization-eligibility decisions cannot be data-backed now.
- **Content engine (positive):** catalog 169→258 compounding; partition verified.
- **Status:** PENDING — analytics source reconnect needed.

## Area 2 — YouTube Policy Risk

- **Finding:** single-template repetitive/mass-produced content risk; duplicate-content + AI-metadata risk.
- **Mitigation:** upload dup gate (~90% Arabic-norm, F-16); AI import dup check.
- **Status:** MONITORED (open policy review pending).

## Area 3 — Deeni Content Durability

- **Finding:** Arabic/reference/tarjuma integrity via Hisn-ul-Muslim exact-pull + script normalization + assert-guarded inserts; auto sub-dup skip (4 caught in batch-8).
- **Snapshot discipline:** every batch → recompute → update snapshot (now 258: 82/165/11).
- **Status:** VERIFIED-CLEAN for inserted batches.

## Area 4 — Security

- **Finding:** F-01 partial (7871 bearer added; CORS/origin open), F-26 crash handlers missing.
- Tokens gitignored; OAuth tokens out of repo; AI keys OFF.
- **Status:** OPEN items F-01/F-26.

## Area 5 — Code & Architecture

- **Finding:** F-22 RESOLVED (config sync); F-24 open (main.py god-CLI); import graph clean, no cycles; 3 UIs by design.

## Area 6 — Testing & Reliability

- **Finding:** full suite 578/578 PASS; F-19/F-20/F-21 open (mypy/ruff/npm); coverage 66.02% (fail-under 15).

## Area 7 — Operations

- **Finding:** F-27 (pm2 max_restarts), F-28 (external alerts) open; F-03…F-14 tracked; backup/restore drills documented.

## Area 8 — Docs Truthfulness

- **Finding:** docs in `docs/` (new set) vs SYSTEM_DOCS/09 — consistency pass needed; ruff-format on markdown noted (F-20).

## Verdict

- **Complete-audit conclusion (docs phase):** system core is green post-catalog-batch; remaining risk concentrated in (a) analytics availability, (b) CI gates, (c) API resilience, (d) ops alerting, (e) content-policy monitoring.
- **No code changes in this phase** — findings only + docs.

## Next (pending, user-driven)

1. Analytics source reconnect for Noor-e-Iman (views/retention).
2. CI gate fixes (F-19/F-20/F-21) — code-adjacent, future batch.
3. API/ops hardening (F-01/F-26/F-27/F-28) — future batch.
