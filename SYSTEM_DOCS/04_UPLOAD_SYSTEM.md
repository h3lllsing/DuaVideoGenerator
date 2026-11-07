# 04 - UPLOAD SYSTEM (YouTube + 3 platforms)

## A) YouTube path (dashboard 7860)
UI "youtube hub" -> POST /api/youtube/upload (dashboard/routes/youtube.js)
- ytStartUploadJob: dedup gates -> resolved picks -> spawn upload.py
- NAYA FLOW (uncommitted 2026-10-18): partial batch exclusion:
  - gateUploadBatch() per item mark: channel dup / cross-channel /
    arabic-dup sim>=0.85 check
  - blocked[] = only dup ultras; accepted items continue; 409 only ALL-blocked
  - msgs include similarity + matched details; UI toast + box
- upload.py (793): ledger data/upload_state_channel{1,2}.json + quota
  quota_state_channel{1,2}.json; units per op: upload 1600, thumbs set 50,
  captions attach 400; DAILY_BUDGET=10000, RESERVE=2000 => 5/day cap
- full-cleanup after live upload success: mp4+thumb+txt sidecars deleted
- legacy longs path (data/upload_state.json via backfill)

## B) unified short path (7871 + remotion/scripts/upload_shorts.py)
apps/server (TS, no deps, node >=22.6 type-stripping):
- config.ts: PROJECT paths, PLATFORMS [youtube,tiktok,instagram,facebook],
  UPLOAD_TIMEOUT_MS=300s; runner.ts: array-spawn windowsHide + hard timeout +
  per-platform lock; NOT SHELL
- routes/uplooad.ts: /api/v1/upload/:platform/:dua_id[?dry_run=1],
  /api/v1/upload/all/:dua_id, /retry/:dua_id/:platform, /status, /duas,
  /quota, /health, /busy
- quota.ts: mirror of upload.py per-platform counters (data/quota_state.json)
- state.ts: reads unified data/upload_state.json (written state.py phases)
- 7871 server.ts: CORS Access-Control-Allow-Origin "*" no auth (dekho 08/09)
  binding 127.0.0.1 default, OPTIONS preflight, json responses

## social adapters (social/*.py)
- common: ffmpeg/ffprobe binary path helper, tokens loader per-platform,
  trim_for_platform (TikTok/IG <=2200 chars), retry_call + _looks_transient
- tiktok: Content Posting API v2: SHA256 init -> PUT chunks -> status poll,
  tokens data/tiktok_tokens.json (api_version param v26 default from file)
- instagram: Graph API container (REELS media resumable upload), wait,
  publish; tokens data/instagram_tokens.json
- facebook: page reels resumable (start/PUT/finish), tokens data/facebook_tokens.json
- state.py: phases queued->uploading->uploaded|failed; atomic writes +
  file lock per lua state; summary()/platform_url()

## Quota rules (upload.py)
```
DAILY_BUDGET=10000; QUOTA_RESERVE=2000; effective daily ceiling 8000
units; upload 1600 + thumbs 50 + captions 400 => math: ceil ~5/day
```
- reset daily by date key local; cross-check resumable leftovers aborted
- autopilot lock data/auto_runs.log append; autopilot 3 N oldest-first

## EN caption rule
- attach_captions.py reads en_review.json approved only, per-channel ledger
- verified_en.py builds quran (Sahih Intl alquran.cloud) ya hadith translations
  (+AI fallback + cooldown state data/en_ai_cooldown.json)

## Auth secrets handling (kahan kya)
- client_secret.json (root + data/, same file hash) = OAuth client creds public
- yt_token_channel1.json = refresh_token (e.g. key token, refresh_token, ...)
- auth.json (dashboard token), ai_api_config.json (AI key), gemini_api_key.txt
- .gitignore covers these + yt_token.json + tokens.json globs

## Addendum: EXACT quota constants (upload.py source-verified)
```python
UPLOAD_UNITS = 1600  # upload.py:59
DAILY_BUDGET = 10000  # upload.py:60
QUOTA_RESERVE = 2000  # upload.py:61
DAILY_CEILING = (10000 - 2000) // 1600  # = 5 (upload.py:62)
```
- THUMB_DIR = remotion/out/thumbs (upload.py:50); MAX_THUMB_BYTES 2MB
  (_shrink_thumb auto-shrink >2MB -> resize)
- resolve_item() order (upload.py:287-335): manifest check -> mp4 (out/
  <Title>.mp4) -> thumb (out/thumbs/<dua_id>.png with LEGACY title-name
  self-heal migration shamo -> "thumb migrated (title->id)") -> sidecar
  .txt regen via metadata.py subprocess -> fallback title
- `full_cleanup_after_upload()`: live success -> mp4 + thumb + txt + build
  artifacts deleted; ledger/video state recorded first
- upload.py:124 - `do_live_upload()` intentionally never calls captions API;
  captions ka separate script attach_captions.py (right gate pe)

## Addendum: runner.ts (7871) FULL READ - safe execution
- In-memory `inFlight` Set keyed `${platform}:${duaId}` -> 409 busy guard
- `validDuaId()` regex `^[A-Za-z0-9_-]+$` len<=120 => path/arg injection
  foundations off (arguments fixed array, no shell), spawn(PY,[script, id,
  --dry-run],{cwd: REMOTION, windowsHide}) (runner.ts:106)
- stdout/stderr capped 1MB ring tail - huge uploads buffer bloated nahi
- Hard timeout: setTimeout -> child.kill(SIGKILL) after UPLOAD_TIMEOUT_MS
  (300s; all-platforms = 4x + 30s)
- exit semantics: 0 clean, else failed (errorFrom: items[].error join else
  last 3 stderr lines); parseLastJson (): LAST '{"' line JSON parse
- failures types: busy | invalid | quota | timeout | spawn | failed
## Addendum: social/state.py unified ledger (FULL READ)
- schema_version=1, platforms [youtube,tiktok,instagram,facebook],
  default data/upload_state.json
- phases: pending -> uploading -> completed|failed (glyph-free machine
  fields + human legacy back-compat "uploaded"/"error" tolerated)
- `load_state()` NEVER raises: corrupt file `.corrupt` rename quarantine +
  fresh skeleton Continue; writes: per-path RLock + mkstemp + fsync +
  os.replace; updated_at UTC ISO
## Addendum FINAL: apps/server 7871 (upload.ts full read)
- Routes: /all sequential-in-platform-order (youtube FIRST deliberate;
  failures dont mask; 207 partial-failure code (upload.ts:168-193))
- guardedUpload(): reserve -> spawn -> commit-on-ok / release-on-fail
  wrap (quota unit safety, dry-run never reserves) (118-151)
- HTTP quota status: busy 409 / invalid 400 / quota 429 / timeout 504 /
  spawn 500 / failed 502 (STATUS_FOR 87-94)
- retry endpoint: completed phase 409 block (Again already live),
  retry full 1600-unit cost (195-216)
- /api/v1/duas: catalog join ledger platforms phases + search filter q
- quota.ts (full): reservations Map honor; `unitsToday()` = sum across
  ALL `quota_state*.json` files (data dir sweep), date local
- `view()` used = max(quotaFileUploads, ledgerUploadsToday) + reserved
  (mirror upload.py:540 max-of-sources rule) (162-174)
- `ledgerUploadsToday()` phase-aware (glyph back-compat); `writeQuota`
  RETENTION_DAYS prune (old days delete)
- QuotaExceeded detail attached 429 body
- CONCLUSION: 7871 quota guards strong, mirrors upload.py; only gap =
  no token auth (F-01)
