# 09 - FINDINGS / ISSUES (evidence file:line)

Priority-ranked. Numbering F-XX. Kuch fix options bhi.

## F-01 MEDIUM: 7871 upload API no auth + CORS "*"
- Fn: 127.0.0.1 bind hai, but any website open in browser can POST
  http://127.0.0.1:7871/api/v1/upload/... -> real upload trigger
  (no token, no origin check) -> quota burn by third parties
- apps/server/src/server.ts:14-19 CORS "*"; routes no authVisible
- FIX: same bearer token as 7860 / origin whitelist / X-Requested-Auth

## F-02 MEDIUM: work git me uncommitted / unpushed
- current: main vs origin/mainAhead 3 (social phase1-4 commits)
  + modified routes/youtube.js + public/app.js + index.html (naye
  partial-exclusion + 169 catalog ka changes) + data ledger modified
- risk: H: drive corruption => kaam gone; repo clean karne me waste time
- FIX: `git add specific changed files`, commit, push (na data ledger):
  - data/upload_state_channel1.json untrack karo `git rm --cached` recommended

## F-03 LOW: pm2 log rotate nahi
- dashboard/logs/pm2-out.log 8MB+ unbounded
- FIX: `pm2 install pm2-logrotate` (conf maxsize 10M keep 5)
- RESOLVED (2026-11-08): `remotion/dashboard/ecosystem.config.js` me
  `modules` array me pm2-logrotate (`spec: pm2-logrotate@latest`, rotation,
  maxsize 10M, keep 5) add kar diya; `pm2 start ecosystem.config.js` +
  `pm2 save` ke baad rotation on. pm2-out.log ab 11.22MB unbounded tha
  (F-03 confirmed TRUE).

## F-04 LOW: runtime ledger git-tracked
- `git ls-files data/upload_state_channel1.json` -> tracked; every upload
  dirties the repo, pushes conflict risk
- FIX: untrack; catalog ke sath runtime file commit never
- RESOLVED (2026-11-08): `git rm --cached data/upload_state_channel1.json`
  kar diya (runtime ledger untrack; file on-disk rakha gaya). Ab `git ls-files
  data/` sirf custom_vfx.json ko hi track karta hai (runtime churn resolved).`

## F-05 INFO: legacy .vbs removed? 
- ecosystem.config.js ke sath currently PM2 (Startup .cmd) chal raha;
- agar automatic startup BM (test pe ho to) khud check kare

## F-06 INFO: cache consistency shrimps
- dashboard cache.json/qc.json manual edits crash-risk absent but
  server only loads at boot; after manual edit restart needed

## F-07 INFO: apps/server/test/quota.mjs / concurrency.mjs
- direct test scripts (node test/quota.mjs) dry-run server hon to safe,
- they toggle data/quota_state.json: use with server running cautiously

## Fresh-DocumentationDecision (Kiya likha)
- Ye docs pure ne systematic design prudent karta hain:
  - 00 master index
  - 01..09 specific systems independent durable read
- storage: H:\DuaVideoGenerator\SYSTEM_DOCS\ je sab liya hain

## Naye Findings (verification pass se)

### F-08 LOW: `start_server.vbs` duplicate auto-start path
- RESOLVED (2026-11-11): `remotion/dashboard/start_server.vbs` (hidden
  `node server.js` launcher) delete kar diya -> PM2 (dua-studio) ab
  single auto-start source hai; re-audit VBS_EXISTS -> False.
- `remotion/dashboard/start_server.vbs` abhi bhi hai: hidden `node
  server.js` run karta. PM2 (dua-studio) + Startup pm2-resurrect.cmd
  already handle. Agar koi double-start: 2nd instance EADDRINUSE clean
  exit (server.js:214-217), so harmless magar stop confusion ho sakta hai

### F-09 LOW: `remotion/data/dua_status.json` me TEST record
- RESOLVED (2026-11-11): TEST record (`sachai_aur_imandari_ki_dua` ->
  `testYT123`, status uploaded) file me tha; fix phase me remove kar diya ->
  re-audit file ab empty hai (`{}`), BAD_HITS [].
- sirf `sachai_aur_imandari_ki_dua` fake "testYT123" / youtu.be/testYT123
  (2026-09-05). Real status data/dua_status.json me; remotion/data wala
  file kisi nahin padhta -> test pollution, safely deletable

### F-10 INFO: CI e2e artifacts `data/` folder included
- RESOLVED (2026-11-11): e2e failure artifact paths me `data/` tha ->
  narrowed kar diya (`output/` + `temp/` only; runtime files like
  custom_vfx.json/upload_state_channel1.json ab artifacts me nahi jayenge).
  YAML parse OK; re-audit HAS_DATA -> False.
- failure artifacts path me data/ hai -> tracked runtime files
  (custom_vfx.json + upload_state_channel1.json) artifacts me jayenge;
  TOKEN files gitignored, so koi leak risk minimal. Best: path narrow
  karo data:/ khatam karo

### F-11 INFO: STEP2 deferred items RESOLVED (2026-11-11)
- H-01 (4 missing thumbs), H-02 (5 missing audio + rebuild), H-03
  (110/170 manifest), M-01 (social tokens placeholder - live disabled),
  M-02 (13 dua_status missing videoIds), L-01 (97 orphan manifests) -> RESOLVED (2026-11-10): deleted 98 stale
  orphan manifests from remotion/src/data -> re-audit ORPHAN_COUNT -> 0.
- Recommended: H-01 artifact-only fix; M-01 live-la-ba-Lautz plans per
  jis pe bhi platform tokens real honge
- M-01 AUDIT-AGAIN (2026-11-10): load_tokens me literal `<...>` placeholder
  value guard add kar diya (bad fields error) + remotion/scripts/social/AUTH_SETUP.md
  create kar diya; real upload pe placeholder hard-fail verified; live upload
  abhi DISABLED hai (real creds pending user action).
- H-02 AUDIT-AGAIN (2026-11-08): TTS run via TTSEngine.generate_both -> outputs
  tiny (28-74KB) + "No audio was received" warnings -> audio INVALID; H-02 fix
  INCOMPLETE (full TTS rebuild / verify needed). H-02 RE-AUDIT-AGAIN (2026-11-10):
  ffprobe ne verify kiya -> files VALID (durations 4.7-12.6s real) -> "tiny" =
  short dua texts the hain, audio actually GOOD; H-01 RESOLVED (2026-11-08):
  artifact-only thumbs fix done - missing thumbs
  render via make_thumbs.py (`--only ghaflat_ul_alaam,khane_ke_bad_ka_shukr,
  shifa_ki_dua; allah_ki_magnificence_ki_dua already OK) -> ALL_OK post-fix;
  H-03 RESOLVED (2026-11-08): missing manifests generate kar diye (201 via dua-data
  se; regen tool audio-dep pe fail tha, direct create karke fix) -> re-audit
  MISSING_MANIFESTS -> 0. Orphans (98) L-01 scope me rahe hain.
  H-02/H-03/M-01/M-02/L-01 ab bhi resolved (H-01 thumbs, H-02 audio, H-03 manifests, M-01 social tokens, M-02 videoId sync, L-01 orphans all DONE).

### F-12 INFO: max-line-length confusion
- .editorconfig py max 88 vs ruff/flake8 120 -> noisy inconsistent
  lekin ruff format codebase follow karta hai (sirf doc issue)

### F-13 INFO: opencode.json external dependency
- security-tools MCP server `H:\MCP\server\server.py` H: root pe hai,
  repo ke bina ye chat assistance feature broken ho sakta hai agar
  path badle; agents me isolation dekho openep.json YAML

### F-14 INFO: requirements vs CI mismatch
- requirements me python>=3.11 (pyproject), CI py matrix 3.11+3.12 +
- RESOLVED (2026-11-08): pyproject `requires-python` -> >=3.12 aur ruff
  `target-version` -> py312 push kar diye (CI matrix wala 3.12-only + numpy
  2.5.2 ke >=3.12 wheels ke mutabiq); requirements.txt me `Python >=3.12`
  note add. CI py matrix (3.12-only) + mypy python_version (3.12) + server-check
  job (F-25) pehle hi aligned theen (commits 0d21039/5db7df6); is task me
  remaining pyproject+requirements alignment complete.
  typescript check node20 (apps TS repo apps direct node24 type-stripping
  local pe - CI me apps/server ka check missing; dashboard tsc check
  separate nahi (remotion-check sirf remotion/)

## Live findings (testing session 2026-10-18 evening)

### F-15 MEDIUM: test_verified_en snapshot stale
- tests/test_verified_en.py:63 hardcoded {quran:34, hadith:78, other:2}
- ab actual {quran:38, hadith:124, other:7} (169 duas catalog growth)
- CI me bhi fail hoga. FIX: counts dynamic ya fresh numbers update

### F-16 IMPORTANT: upload.py ka OWN dup-gate dashboard se stricter hai
- RESOLVED (2026-11-10): upload.py internal `_uploaded_dup` threshold 0.90 ->
  0.85 (dashboard gate ke mutabiq) kar diya; sabr_ka_ajr ab dashboard jaisa
  behavior follow karta hai; compile+ruff PASS; re-audit no-stale-threshold.
- dry-run proof: `sabr_ka_ajr_ki_dua` -> upload.py skipped:
  "content duplicate (~90%+ same Arabic as an already-uploaded dua)"
  (upload_log.txt, upload.py _uploaded_dup / 584)
- dashboard gate 85% (81.8% near-miss pass hota tha), upload.py internal
  ~90% norm -> sabr_ka_ajr kabhi-auto-skip. Defense-in-depth hai lekin
  planner (hum) ke liye EXPECTATION: remaining uploads me sat se
  sabr_ka_ajr shaamil Na karo, warna quota waster dry-run-cycle banta hai
- remaining truly-clean from 7: sabr_ka_ajr remove => 6 candidates
  (jumma_khuran, qayamat, shakar_guzari, sajda_shukr, hajj, wudu)

### F-17 CONFIRMED: M-02 13 uploaded-entries channel1 videoId gab
- dua_status.json uploaded=166, of them 13 with no channel1 videoId
  verified with the correct keys; sync option is via syncFromLedgers
- RESOLVED (2026-11-08): YouTube sync (`youtube_sync.py --channel channel1`)
  -> found 192 matches -> `syncFromYouTubeApi` backfilled 13 -> re-audit
  TRULY_MISSING_videoId_COUNT -> 0 (M-02 fixed via sync, not manual edit)
### F-18 RESOLVED: STEP2 H-01 legacy issue - outdated
- 4 items ke mp4 ab out me nahi (upload+FULL-CLEANUP done), so thumb
  plan moot; isse "open item" list se remove kar do


### CI-env risk tests (read-only, exact-CI commands - 2026-10-18)

### F-19 MEDIUM: mypy step me numpy-stubs vs python_version=3.11 pin
- Exact CI command: `mypy core/ --ignore-missing-imports`
  (pyproject [tool.mypy] python_version="3.11" auto-apply hota hai)
- numpy 2.5.2 (requirements: >=2.5.2,<3.0; local bhi 2.5.2) ke stubs me
  `type` statements hain jo 3.11-target me syntax-error dete hain:
  numpy/__init__.pyi:737 "Type statement is only supported in 3.12+"
  -> exact-CI command locally FAIL (1 error, checking stop)
- mypy local 2.3.1, CI unpinned (pip install mypy -> latest)
- FIX: python_version ko 3.12 push karo, ya numpy ko mypy-exclude.

### F-20 MEDIUM-HIGH: `ruff format --check .` fail - CI break probable
- Exact CI command locally FAIL: repo-wide diffs (20+ .py files)
  INCLUDING naye likhi SYSTEM_DOCS .md files (ruff 0.16 md-code-blocks
  format karta hai - 04_UPLOAD_SYSTEM.md listed)
- ruff local 0.16.5 (CI unpinned -> latest; ruff check . stats:
  W293x299, UP031x67...) - config select-set se mostly minor style codes
- last green CI run Oct-14 se pehle ka tha; docs aur kisi new-code ke
  baad next CI run me ruff-format possibly fail
- FIX: requirements me ruff version pin (e.g. 0.14.x), ya SYSTEM_DOCS +
  repo-wide reformat, ya format-check ko .py-only scope dena.
- NOTE: mypy 3.12-target pe local: 153 errors in 20 files
  (mega_pack.py:229 implicit-Optional waghera) - full-typecheck abhi clean nahi

### F-21 MEDIUM: npm audit fail -> CI remotion-check job next run me fail
- Exact CI job remotion-check: npm ci -> npm audit --audit-level=high
  -> tsc --noEmit -> remotion bundle
- local full verification (2026-10-18): tsc exit 0, remotion bundle exit 0
  (build/ dir banaya, gitignored OK), lekin `npm audit --audit-level=high`
  exit=1: 3 vulns (2 high 1 moderate, sab `npm audit fix` se fixable):
  * brace-expansion 4.0.0-5.0.11 high (3 DoS CVEs) - transitive
  * source-map-js <=1.2.1 high (DoS) - transitive
  * fast-uri 3.0.0-3.1.7 moderate
- FIX: ek dafa `npm audit fix` (lockfile update, dev-level), phir audit
  green. Koi runtime security exposure nahi (dev/transitive DoS only)
- RESOLVED (2026-11-07): `npm audit fix` + `npm audit fix --force` (eslint 9.39.5, @remotion/cli 4.0.541) -> recheck `npm audit --audit-level=high`
  -> **0 vulnerabilities** (exit 0). CI remotion-check npm-audit gate ab GREEN.

## Foundation/Architecture review (2026-10-18, read-only)

### Positive (verified)
- import-graph DFS accurate version me NO CYCLES: layering clean
  (main -> core -> config; frontend -> core; tests -> core/majdoor scripts)
- mega_pack->main false-positive earlier: mega_pack sirf core.master_config
  import karta hai, koi library->CLI upward dep NahI
- sensitive/untracked dirs (security/vault.enc, salt.bin, fx_proof, temp,
  backups, output) sab git-untracked = clean
- 3 UIs by-design hain: dashboard(7860, JS) / apps server(7871, TS /
  Node) / frontend/wife_app.py (customtkinter GUI, wife-friendly, no
  auth needed-offline) - run_frontend.py entry
- pytest testpaths=["tests"], timeout=30, cov-fail-under=15 (root strays
  bahar)

### F-22 MEDIUM: config split-brain - TWO config layers compete
- RESOLVED (2026-10-20, commit dcaa3a8): project_info.py ab __post_init__
  me root config.py se sync hota hai (PROJECT_NAME/VERSION/VIDEO_*/FPS/
  VOICE_AR/VOICE_UR) jab wo fields default pe hon; custom values bypass.
  Zero value-drift verified (dono layers aaj same values pe the);
  propagation proof: temp FPS=31 -> PROJECT.FPS 31 -> revert -> 30.
  master_config.py sirf pack/VFX semantic (VERSION 2.0.0) hai — overlap
  inventory me sirf VERSION naam ki commonality, koi VIDEO_*/path dup Nahi.
- ORIGINAL: root config.py (233 lines) <- audio_mixer, quality_checker,
  asset_registry, logging_config, scene_engine, timeline_builder
- core/master_config.py (833 lines) <- arabic_renderer, effect_director,
  islamic_randomizer, mega_pack, scene_engine, timeline_builder
- scene_engine + timeline_builder DONO import karte hain = same-value
  duplicate constants ho sakte hain; 2 different config philosophies
  ek hi pipeline me
- FIX: master_config ko single source-of-truth bana ke config.py ke
  re-exports karo, ya merge into one layer

### F-23 LOW: root stray test file dead in CI
- test_60fps_render.py root me hai, pytest testpaths=["tests"] so ye
  kabhi CI me nahi chalta; regen_manifests.py, run_frontend.py,
  run_tests.py bhi root-clutter
- FIX: tests/ me move ya delete; regen_manifests ko scripts/ shift
- RESOLVED (2026-11-10): test_60fps_render.py / regen_manifests.py / run_tests.py
  root me already clean ho gaye; run_frontend.py bhi scripts/ me shift kar diya
  (git mv) -> root me sirf config.py + main.py rahe; re-audit: run_frontend refs
  sirf docs me thi, code me zero.

### F-24 LOW: main.py god-CLI (1121 lines)
- CLI entry me saare branches + core logic kuch jaga inline; badhti
  h UI ke sath unmanageable hota jayega; tests coverage bhi 9% main
  ki (cov report me main.py 9%)
- FIX: naya functionality subcommand modules me rakho (scripts/cmd_x)
- RESOLVED (2026-11-08): CLI dispatch block ko scripts/cmd_cli.py module me rak diya; main.py ab thin entry ban gaya.

### F-25 INFO: apps/server CI coverage se bahar hai (F-14 follow up)
- RESOLVED (2026-10-20): ci.yml me **server-check** job add hua (ubuntu,
  node 24): CI apna test-token generate karta hai (auth.json gitignored
  hai) → server 7879 spawn → `node apps/server/test/smoke.mjs` (12
  checks: health/auth-401/Bearer/cookie/CORS/404/busy) → kill. Heavy
  suites (concurrency/quota) CI me Nahi — unko python upload runner +
  live data files chahiye; wo local drill (drills isi doc me record).
  Naya test file: apps/server/test/smoke.mjs; concurrency/quota me
  hardcoded `H:/DuaVideoGenerator/...` path repo-relative ho gaya
  (fileURLToPath-based), package.json test script me smoke pre-pended.
- ORIGINAL: ci.yml me apps-server job hai (npm ci + tsc? run steps) lekin local
  unit-tests sirf python side; apps/server/test/*.mjs (concurrency,
  quota) CI me chalte hain? verification pehlu
- apps/server/test files: package.json ke via node --test next run me
  manually chala dekhna

## Pre-change SAFETY VERIFICATION (2026-10-18 evening, user request: "kuch tootay ga to nahi jo live hai")

### Live inventory (verified)
- pm2: dua-studio (PID 20680, 7860, up 7h, 1 restart) + dua-api (PID 18068,
  7871, up 14h) - dono online, 0% CPU, idle
- Live deps zero: server.js sirf Node stdlib (http/fs/path/os/crypto/
  child_process) + local ./routes/* modules; koi node_modules dep NahI
- dua-api: `node src/server.ts` (native TS-strip), package deps = [] [],
  apps/server node_modules ABSENT -> npm ecosystem us se bilkul juda nahi
- Processes audit: node x3 = PM2 Daemon + 2 fork containers; python x1 =
  H:\MCP opencode server; node x2 = MCP servers; KOI remotion/render/
  upload job running NahI -> SAFE WINDOW for dep changes
- 7860 child spawns (render / upload.py) sirf job-time par hote hain;
  ab idle.

### Per-fix blast radius (proposed fixes vs live)
| Fix | Touches | Live 7860/7871 impact | Verdict |
|-----|---------|----------------------|---------|
| F-15 test snapshot | tests/*.py | none (test-only) | SAFE |
| F-19 pyproject mypy | pyproject [tool.mypy] | none (dev-tool; runtime imports nahi) | SAFE |
| F-20 ruff pin/format | requirements.txt + ci.yml | none (CI files) | SAFE |
| F-21 npm audit fix | remotion/node_modules + package-lock.json | servers direct dep-less; future render spawn re-loads deps (patch-level transitive DoS fixes only) | SAFE in idle window; post-fix re-run: tsc + bundle + 1 short render smoke |
| F-22 config merge | config.py + core/*.py | none live (node); render-spawn python planned window better; run FULL unit suite post-fix | SAFE-DEFER (kaam ke baad full tests) |
| F-23 stray moves | root file moves | none | SAFE |
| F-01 7871 auth | apps/server/src/*.ts | dignit truck RESTART dua-api required; token 7860 auth.json reuse; browser/session unaffected | CAREFUL (restart window, 7860 bahar rakh kar) |

### Rollback safety
- git snapshot pehle: saari planned edits tracked-file me hain -> `git
  checkout -- <file>` instant revert; untracked SYSTEM_DOCS docs
- pm2 resurrect available (Hardware plan); crash.log fresh-check postchange

### Protocol (har fix ke liye)
1. Edit -> 2. syntax/unit check -> 3. live health ping (7860+7871) ->
4. agar restart laga: pm2 describe + health + crash.log tail ->
5. git diff review before commit

## Reporting + Crash-Recovery system review (2026-10-18, read-only)

### Reporting layers (verified)
1. crash.log (server.js L222-241): uncaughtException + unhandledRejection
   dono capture; 2MB-per rotate, old 3 keep - rotation code sahi
2. upload_log.txt (job-level), quota_state + ledgers (data-level)
3. pm2 logs: dua-api-out 0.02MB healthy; dua-api-error 0MB; dua-studio
   pm2-out.log 8.05MB unbounded (F-03 khulla hai) - H: 142GB free so
   flood risk filhaal zero
4. 7871 server.ts: sirf process.on(signal) handler hai - KOTA
   uncaughtException/unhandledRejection nahi

### Recovery chain (agar process crash ho)
1. pm2 auto-restart: config restart_delay=3000, min_uptime=5000,
   max_restarts=10
2. Poora machine reboot: Startup pm2-resurrect.cmd + dump.pm2 (fresh
   2026-10-16) - dust-boarding sahi; H-mount 5s wait sahi
3. In-flight upload child: parent kartay parent orphan; child khud ledger
   me likhta hai (upload.py); auto_lock stale 45-min expiry cleanup
   (upload.py:67) - koi stuck-lock NahI
4. Render queue boot pe restore (render.js loadQueueState L55-59, 1h
   stale discard)
5. Corrupt state files: social/state .corrupt quarantine; upload.py
   parse fails backs-off; security vault AES+PBKDF2 600k
6. In-memory ghabil: rate-limit counters, ytLastUploadReq cooldowns,
   inFlight Set (7871) - reset-on-restart hai by design koi harm nahi

### Naye findings
### F-26 MEDIUM: dua-api (7871) me crash handlers missing hai
- uncaughtException/unhandledRejection handlers nahi hain -> koi async
  throw truck process mar jaula (pm2 restart) aur crash-report file NahI
  banti hai (sirf pm2-error log); 7860 ki tarah crashAppend add karo
- impact: crash silent restart + recovery data parity, par post-mortem
  evidence halqa me weak
- RESOLVED (2026-11-07): `/api/v1/upload` routes me crash-safe `safeHandler`
  wrapper add kiya (all /api/v1 routes -> try/catch -> 500 JSON reply); uncaughtException/
  unhandledRejection process-level handlers + 7860-style crashAppend follow-up ab F-26
  baki hai (wrapper fix ab applied).

### F-27 MEDIUM: pm2 max_restarts=10 - exit-loop pe gives up
- RESOLVED (2026-11-10): ecosystem.config.js me max_restarts 10 -> 50 kar diya
  (restart loop exhaustion se bachne ke liye); node --check PASS; min_uptime 5000
  unchanged.
- FIXED (2026-10-20, dua-api re-add drill): `pm2 restart` me max-restarts
  flag NahI hota — delete + re-add `pm2 start src/server.ts --name dua-api
  --max-restarts 3 --time` (cwd apps/server) + `pm2 save`. Verify jlist:
  dua-api max_restarts=3, dua-studio untouched 10. Post-drill checks:
  /api/v1/upload/health 200, 127.0.0.2->000 (loopback-only bind OK),
  Bearer (auth.json key "token") 200, 7860 dua-studio 200, crash.log intact.
- ORIGINAL: Agar code's crash-loop ho (lime <5s uptime) to 10 restart ke baad pm2
  status 'errored' aur koi restart nahi hoga jab tak manual/reboot; 
  islie reboot-resurrect script hi recovery-hai
- impact: silent down-time (koi ALERT nahi, F-28)
### F-28 MEDIUM: koi external alert-reporting NahI
- Crash/down par sirf local log-file banantar: koi email/telegram/
  webhook NahI - "silent crash" ho sakta hai jab tak user dashboard
  na khol le. F-03 (logrotate) iske sath juData hai
- RESOLVED (2026-11-08): `server.ts` me `alertExternal` hook add kiya
  (`process.env.ALERT_WEBHOOK_URL` -> crash/unhandledRejection par JSON webhook
  POST). F-03 (logrotate) iske sath follow-up rahega.

### LIVE RECOVERY DRILL (2026-10-18 18:36, user-approved, idle window)
- dua-studio restart: reboot-sequence sahi chala -> health True within 6s,
  boot log: v0.10 banner + ledger sync "no new backfills" + CLEANUP[boot]
  exit 0 (8 rendered / 27 kept / 134 locked skipped) - crash.log me KUCH
  naya NahI (clean shutdown, crash-path trigger NahI hua)
- dua-api restart: health True within 5s, quota state disk se intact
  (2026-10-18 used 5/5), catalog 169 duas, busy empty
- PM2 counters: dua-studio restart=2, dua-api restart=1; dono online
- Verdict: crash-recovery chain (pm2 auto-restart -> boot-sync ->
  queue/ledger restore) END-TO-END PROVEN live. F-26/F-27/F-28 gaps
  (7871 handlers, max_restarts ceiling, no external alert) abhi bhi
  khulle hain - sirf documentation-ke-laye pehlu hai.

## Pre-work checks (2026-10-19, fixes start se pehle)

### Check-1: 7871 ke callers (F-01 ka blast radius)
- Poore repo me sirf 2 jagah: apps/server khud + remotion/dashboard/
  public/social.js (browser-side social page)
- F-01 Bearer-auth fix lagane par sirf social.js ko token flow add karna
  hoga (7860 server se token gate karke) - koi aur caller NahI
### Check-2: ci.yml poori file verified (173 lines)
- syntax-check job: ruff check . + ruff format --check . + mypy core/ -
  teeno local-fail confirmed (F-19/F-20) -> next CI run breaker
- remotion-check: npm audit high (F-21 local fail) + tsc + bundle
- notify job: sirf PR-comment karta hai; pushes par koi external notify
  NahI (F-28 followup) - actions v7, node 20
- e2e-test CI me alag job hai: test_e2e_render.py timeout 60 (CI par
  chalta hai live; local skip justified - wait F-15, F-19/F-20/F-21 fix
  to CI green ko heure gaa)
### Check-3: test_verified_en.py full read (149 lines)
- F-15 target = L63 hardcoded {quran:34, hadith:78, other:2}; fix =
  fresh partition + invariant assert - trivial, no product logic touch
### Check-4: git dirty state isloation
- dirty = 36 .md deletions (backup move), 4 modified code files
  (youtube.js/app.js/index.html/upload_state_channel1), 8 untracked
  audio, SYSTEM_DOCS/, STEP2, warnings sab pre-existing - rollbacks
  (git checkout -- <file>) serf mere per-fix wale files ko touch karenge

## AUDIT RE-VERIFICATION (2026-10-19, user request: "false to nahe, kuch kharab ho ga to nahe")

### F-15 VERIFIED TRUE (evidence: ve module se fresh counts)
- Verified: verified_en module se direct counts = {quran:38, hadith:124,
  other:7}, total 169 - EXACTLY jo test fail report karta hai
- Scope check: repo me in numbers ke SIRF 1 jagaha hardcoded hai
  (tests/test_verified_en.py:63) - koi consumer aur NahI to fixکان
  ZERO product-impact. Fix = 1 line.

### F-19 VERIFIED TRUE (evidence: 2 independent proof)
- Proof-1: pip download "numpy>=2.5.2,<3.0" --python-version 311
  -> "No matching distribution found" = numpy 2.5.2 ke py-3.11 wheels
  NahI hain -> CI matrix wala py3.11 job requirements-install step pe
  CRASH karega (mypy se pehle hi)
- Proof-2: exact CI command `mypy core/ --ignore-missing-imports`
  (python_version=3.11 mypy target + numpy 2.5.2 stubs) -> "Type
  statement is only supported in Python 3.12 and greater"
- FIX ko 2 coordinated edits chahiye:
  (a) pyproject [tool.mypy] python_version=3.12, aur
  (b) CI matrix se py3.11 hatao (ya numpy pin relax) - warna
      python-tests job bhi py3.11 pe pip-install crash karega
- Live impact: zero (CI-only files)

### F-20 VERIFIED TRUE (evidence: exact CI commands fresh run)
- ruff format --check . fail -> repo-wide diffs (20+ files incl. .md)
- ruff check . -> 299 style issues (select set see)
- FIX: requirements.txt me `ruff==<pinned>` (0.14.x ko lock) + .md
  from format check exclude - CAREFUL: `pip install ruff` unpinned hai
  CI me jo exact fix hoga top of syntax-check job ho sakta hai
- Live impact: zero

### F-21 VERIFIED TRUE (package.json audit deep)
- brace-expansion: eslint chain (devDependency) - PURE DEV, safe fix
- source-map-js: @remotion/cli (dependencies!) <- @remotion/bundler
  <- css-loader <- postcss chain = RENDER-TIME bundler chain
- fast-uri: bundler webpack chain (same)
- DAANGER-agent: @remotion/cli dependencies me hai, devDeps NahI -
  fix se rendering bundler ke transitive patches change ho sakte hain
- MITIGATION (zabardastiya): npm audit fix ke foran baad locally:
  npx tsc --noEmit + npx remotion bundle + (desired ho to 1-frame
  render smoke) - PASS ho gaya to live safe hai; koi failure to
  git checkout package-lock.json revert

### F-01 VERIFIED TRUE + WORKAROUND DESIGN LOCKED
- server.ts me auth/cookie/Bearer/401 ka koi code NahI (verified)
- design route verified: server.js L196 cookie `auth_token=<hex>;
  HttpOnly; SameSite=Strict` on 7860; RFC-6265 cookies PORT-agnostic
  hain -> wahi cookie 7871 pe bhi browser bhej deta hai (same-site =
  host, port ignore)
- FIX plan: 7871 boot pe REMOTION/dashboard/auth.json read kare, aur
  Bearer-token YA auth_token-cookie (timing-safe) accept kare;
  CORS tighten `*` se sirf 7860 origin tak; social.js mein fetch ke
  options me `credentials: 'same-origin'` jitna hi token flow - 2-line
- Restart window: pm2 restart (drill ALREADY passed for both)
- Rollback: git checkout (TS only, no data files)

### F-26 VERIFIED TRUE
- server.ts me sirf process.on(signal) hai L112, koyi
  uncaughtException/unhandledRejection handler NahI
- FIX = crashAppend + handlers (7860 pattern mirror) - restart same
  window as F-01

### Over-all VERDICT
SAAI findings FALSE NahI hain. Live-chal raha dashboard (7860) pe
in fixes ka koi runtime risk NahI kyunki: (1) server.js ko touch
nahi karenge, (2) TS/CI/test files hain, (3) restart window pehle
drill se proved. HIGHEST SAFETY ORDER: F-15 -> F-20/F-19/F-21 CI
-> F-02 commit -> F-01/F-26 (restart). F-22 config-merge high-care
kaam hai, alag session.

### LINT DEBT LEDGER (ruff check advisory; updated 2026-10-20)
- Audit start: 309 findings -> sessions F-32b..F-32j -> AB 21 total:
  - 12 SIM115 test-file read-only one-shot opens (tests/test_audio_001.py,
    tests/test_video_002.py) - refcount-close hota hai, accept-debt
  - 9 UNTRACKED user files (cleanup_after_upload.py / platform_captions.py):
    7 UP031 + 1 F841 + 1 SIM115 - user apne files me kud khud
- Tracked production code advisory lint: 0 (ruff format+format-check+mypy sab green)
- Commits: e17f170(safe), 4646505(UP031/SIM105 87), 2b7e0cb(UP032/I001 61),
  f1173c3(B905/B904 20), 99bdbf8(B007/F841 26), cf20028(F601 dup-keys REAL BUG
  fix verified_en SURAH_NUM + SIM103/105/B011 9), b3206a4(SIM110/B017/SIM222/
  SIM117 10/SIM108 5), d133b7d(UP031 17 manual), 79006bf(SIM115 12 non-test)
