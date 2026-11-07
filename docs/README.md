# Dua Video Generator — Docs

> **Status: DOCS-ONLY CHANGE PHASE (no code changed in this batch).**
> Everything written here is verified against fresh runs + live checks; items not yet verified are explicitly marked PENDING.

## Verified Current State (docs batch basis)

| Item | Value | Verified |
|---|---|---|
| Dua catalog size | **258** entries (`data/duas.json`, gitignored) | ✅ API live GET /api/v1/duas → `total: 258` |
| Reference partition | `{quran: 82, hadith: 165, other: 11}` | ✅ tests/test_verified_en.py snapshot + targeted run + FULL suite (578/578 PASS) |
| Last catalog additions | batch-7: +22 (204→226), batch-8: +32 (226→258) via Hisn-ul-Muslim dataset (se segment-based exact pull, Urdu-script normalization, assert-guarded inserts) | ✅ reload sanity + dup checks |
| Server health | dashboard 7860 (200), apps/server 7871 (bearer-auth) | ✅ live curl checks |
| Git HEAD | `f741f07` — `tests(duas-catalog): snapshot 258 duas (82 quran / 165 hadith / 11 other)` | ✅ |

## Doc Map

| Doc | Purpose | Fresh |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layered system design (verified import graph) | ✅ |
| [RUNBOOK.md](RUNBOOK.md) | Run / smoke / backup / restore / ops runbook | ✅ |
| [API.md](API.md) | Live API endpoints + auth + verified curl checks | ✅ |
| [CHANNEL_PLAYBOOK.md](CHANNEL_PLAYBOOK.md) | Noor-e-Iman channel strategy + policy/monetization/growth | ✅ |
| [AUDIT_CEO_SUMMARY.md](AUDIT_CEO_SUMMARY.md) | CEO summary, severity table, seedhi raaye, 90-day plan | ✅ |
| [AUDIT_FINDINGS.md](AUDIT_FINDINGS.md) | Consolidated 8-area audit findings (complete-audit set) | ✅ |

## Conventions

- English for technical docs; Roman Urdu conversational style stays in chat reports.
- Numbers in docs must be re-verified after every catalog change (see snapshot discipline).
- Anything marked PENDING in this set is NOT written as fact.

## PENDING items (not written as fact here)

- YouTube analytics views/retention source (Noor-e-Iman) — currently not resolving via portal post-YouTube-connect.
- External alert channel tokens (F-28) — open.
