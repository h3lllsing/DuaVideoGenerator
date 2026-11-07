# Audit — Better Results (Missing Components & YouTube Stats)

> Focus of this audit slice: **result improvement** (better videos / better stats handling), not system performance.
> Basis: existing verified pipeline + user-reported YouTube connect issue + audit state.

## Result Chain (Input → Generate → Output → Distribute → Feedback)

1. **Input:** `data/duas.json` — 258 authentic duas (verified partition 82/165/11).
2. **Generate:** TTS (edge-tts ar-SA-HamedNeural / ur-PK-AsadNeural) → karaoke word highlight → mastered audio (-14 LUFS) → remotion render (1080x1920, FPS 30, dark).
3. **Output:** rendered MP4 + per-video stats.
4. **Distribute:** upload via apps/server 7871 (dup gate ~90%, quota).
5. **Feedback:** YouTube stats (views/likes/comments) → dashboard 7860.

## Findings — Missing / Improvement Candidates for Better RESULTS

### F-R1 (HIGH): YouTube stats feedback loop gap
- **Finding:** user-reported — after YouTube connect, views/likes details not coming on portal.
- **Impact:** cannot compute better-result metrics (retention/CTR) → improvement loop broken.
- **Audit status:** OPEN — re-auth / stats endpoint verification needed.
- **FIX (this session):** `remotion/scripts/youtube_stats.py` me expired-access-token auto-refresh (`cred.refresh`) + structured auth-failure error add kiya (py_compile OK). Live API verification (token re-login state) pending.

### F-R2 (MEDIUM): Retention lever modules
- **Finding:** `remotion/scripts/make_manifest.py` mentions text-readable retention lever; karaoke/manifest tuning exists.
- **Improvement:** A/B caption/timing variants for retention.

### F-R3 (MEDIUM): Supporting component coverage
- **Finding:** background per-category (Pexels-generated) coverage vs 258 duas categories — some categories may lack assets (STEP2 H-01/H-02 open).
- **Impact:** result quality variance.

### F-R4 (LOW): Dup-gate threshold tuning
- **Finding:** upload.py dup gate ~90% stricter than dashboard (~85%) — plan-level expectation to avoid quota waste (F-16).

## Verdict — How results could get better

1. Fix YouTube stats ingestion (F-R1) → data-driven iteration.
2. Close STEP2 asset gaps (H-01/H-02) → richer backgrounds.
3. Retention experiments (F-R2) → better watch time.
4. Tune dup gate (F-R4) → no quota waste → more uploads → more results.

---

*Update (this session): F-R1 fix applied in `remotion/scripts/youtube_stats.py` (auto token refresh + structured errors); live re-auth verification pending. Audit slice findings written for docs.*
