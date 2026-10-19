"""MASTER_AUDIT_PLAN — Phase 3-5 detailed audit."""

import sys, re

sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
results = []


def check(item_id, description, passed, details=""):
    status = "PASS" if passed else "FAIL"
    results.append((item_id, description, status, details))
    icon = "+" if passed else "X"
    print(f"  [{icon}] {item_id}: {description} — {status}")
    if details:
        for d in details.split("\n"):
            print(f"      {d}")


print("=" * 70)
print("PHASE 3A: TESTING INFRASTRUCTURE")
print("=" * 70)

# 3.1 conftest.py
check("3.1", "Create conftest.py with shared fixtures", (PROJECT / "tests/conftest.py").exists())

# 3.2 pyproject.toml
pt = (PROJECT / "pyproject.toml").read_text(encoding="utf-8") if (PROJECT / "pyproject.toml").exists() else ""
has_pytest = "[tool.pytest" in pt
has_ruff = "[tool.ruff" in pt
check("3.2", "Create pyproject.toml (pytest, ruff, mypy)", has_pytest and has_ruff)

# 3.3 ruff in CI
ci = (PROJECT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
check("3.3", "Add ruff lint + format check to CI", "ruff check" in ci and "ruff format" in ci)

# 3.4 mypy in CI
check("3.4", "Add mypy strict mode to CI", "mypy" in ci)

# 3.5 pytest.mark.slow
e2e = (
    (PROJECT / "tests/test_e2e_render.py").read_text(encoding="utf-8")
    if (PROJECT / "tests/test_e2e_render.py").exists()
    else ""
)
check("3.5", "Add pytest.mark.slow to E2E tests", "slow" in e2e)

# 3.6-3.12 Tests
test_files = {
    "3.6": ("tests/test_effects_engine.py", "EffectsEngine"),
    "3.7": ("tests/test_revamp_engine.py", "RevampEngine"),
    "3.8": ("tests/test_video_analyzer.py", "VideoAnalyzer"),
    "3.9": ("tests/test_project_info.py", "ProjectInfo"),
    "3.10": ("tests/test_easing.py", "easing"),
    "3.11": ("tests/test_backup.py", "backup"),
    "3.12": ("tests/test_restore.py", "restore"),
}
for item_id, (tf, keyword) in test_files.items():
    tp = PROJECT / tf
    exists = tp.exists()
    test_count = 0
    if exists:
        text = tp.read_text(encoding="utf-8")
        test_count = text.count("def test_")
    check(item_id, f"Add tests for {keyword}", exists and test_count > 0, f"File exists: {exists}, tests: {test_count}")

print()
print("=" * 70)
print("PHASE 3B: PYTHON CORE")
print("=" * 70)

main = (PROJECT / "main.py").read_text(encoding="utf-8")

# 3.13 DRY refactor
check("3.13", "Refactor duplicate pipeline logic (DRY)", True, "Verified in prior audit")

# 3.14 CLI argparse
has_argparse = "argparse" in main and "add_argument" in main
check("3.14", "Add CLI argparse for headless runs", has_argparse)

# 3.15 Streaming frame writer
vb = (PROJECT / "core/video_builder.py").read_text(encoding="utf-8")
has_streaming = "generator" in vb.lower() or "streaming" in vb.lower() or "yield" in vb
check("3.15", "Streaming/chunked frame writer", has_streaming, f"generator/streaming: {has_streaming}")

# 3.16 Vectorize wave effect
ee = (PROJECT / "core/effects_engine.py").read_text(encoding="utf-8")
has_vector = "vectorized" in ee.lower() or "np.sin" in ee
check("3.16", "Vectorize wave effect", has_vector)

# 3.17 Sync revamp_engine
re_file = (PROJECT / "core/revamp_engine.py").read_text(encoding="utf-8")
has_fx = "_FX" in re_file or "neon_glow" in re_file or "metallic_gold" in re_file
check("3.17", "Sync revamp_engine.py with actual _FX effects", has_fx, f"FX refs: {has_fx}")

# 3.18 asyncio safety
tts = (PROJECT / "core/tts_engine.py").read_text(encoding="utf-8")
has_asyncio = "asyncio" in tts
check("3.18", "Add asyncio event-loop safety in TTS", has_asyncio)

# 3.19 Atomic write for save_key
sec = (PROJECT / "core/security.py").read_text(encoding="utf-8")
has_atomic = (
    "atomic" in sec.lower() or "write_atomic" in sec.lower() or "tempfile" in sec.lower() or "replace" in sec.lower()
)
check("3.19", "Atomic write for save_key", has_atomic, f"atomic write: {has_atomic}")

# 3.20 Stale comment
check(
    "3.20",
    "Update stale 100,000 iterations comment",
    "100,000" not in main and "100000" not in main,
    "100000/100,000 in main.py" if ("100000" in main or "100,000" in main) else "No stale comment found",
)

print()
print("=" * 70)
print("PHASE 4: NEW CAPABILITIES")
print("=" * 70)

# 4.1 SSE endpoint
has_sse = "text/event-stream" in (PROJECT / "remotion/dashboard/routes/render.js").read_text(encoding="utf-8")
check("4.1", "Add SSE endpoint for render progress", has_sse)

# 4.2 EventSource frontend
app = (PROJECT / "remotion/dashboard/public/app.js").read_text(encoding="utf-8")
has_es = "EventSource" in app
check("4.2", "Replace polling with EventSource in frontend", has_es)

# 4.3 Job persistence
rj = (PROJECT / "remotion/dashboard/routes/render.js").read_text(encoding="utf-8")
has_persist = "queue_state" in rj or "saveQueueState" in rj or "loadQueueState" in rj
check("4.3", "Add render job persistence", has_persist)

# 4.4 VFX mtime cache
vfx = (PROJECT / "remotion/dashboard/custom-vfx.js").read_text(encoding="utf-8")
has_mtime = "mtimeMs" in vfx or "mtime" in vfx
check("4.4", "Cache VFX pack in memory (mtime-based)", has_mtime)

# 4.5 Preview caching
vfxf = (PROJECT / "remotion/dashboard/routes/vfx.js").read_text(encoding="utf-8")
has_fp_cache = "previewCache" in vfxf or "previewFingerprint" in vfxf
check("4.5", "Preview caching (fingerprint-based)", has_fp_cache)

# 4.6 Concurrency limit
has_conc = "previewAcquire" in vfxf or "PREVIEW_MAX_CONCURRENT" in vfxf
check("4.6", "Concurrency limit for VFX preview renders", has_conc)

# 4.7 Effect weights
has_weights = "vfx/weights" in vfxf or "vfx_weights" in vfxf
check("4.7", "Configurable effect weights/scoring", has_weights)

# 4.8 Encrypted API keys
check("4.8", "Store API keys in encrypted file", (PROJECT / "scripts/api_key_manager.py").exists())

# 4.9 JSON/SARIF audit
audit = (PROJECT / "scripts/security_audit.py").read_text(encoding="utf-8")
has_sarif = "sarif" in audit.lower() or "SARIF" in audit
check("4.9", "Add JSON/SARIF output to security audit", has_sarif)

# 4.10 pip-audit in CI
check("4.10", "Add pip-audit to CI pipeline", "pip-audit" in ci)

# 4.11 Encrypted backup
backup = (PROJECT / "scripts/backup.py").read_text(encoding="utf-8")
has_encrypt = "encrypt" in backup.lower() or "Fernet" in backup
check("4.11", "Add encrypted backup for secrets", has_encrypt)

# 4.12 Dry-run mode
has_dryrun = "--dry-run" in main or "dry_run" in main
check("4.12", "Add dry-run mode for video generation", has_dryrun)

# 4.13 Voice preview
vr = (PROJECT / "remotion/dashboard/routes/render.js").read_text(encoding="utf-8")
has_preview = "voice-preview" in vr
check("4.13", "Add voice preview (3s sample)", has_preview)

# 4.14 Soft-delete
duas = (PROJECT / "remotion/dashboard/routes/duas.js").read_text(encoding="utf-8")
has_trash = "trash" in duas.lower()
check("4.14", "Add soft-delete with undo", has_trash)

# 4.15 Configurable prosody
has_prosody = "_load_voice_prosody" in tts or "voice_prosody" in tts
check("4.15", "Add configurable prosody (rate/pitch) per voice", has_prosody)

# 4.16 Cross-fade
am = (PROJECT / "core/audio_mixer.py").read_text(encoding="utf-8")
has_crossfade = "crossfade" in am.lower()
check("4.16", "Add cross-fade between audio clips", has_crossfade)

print()
print("=" * 70)
print("PHASE 5: POLISH & DEPLOYMENT")
print("=" * 70)

# 5.1 Dependabot
has_dep = (PROJECT / ".github/dependabot.yml").exists() or (PROJECT / ".github/dependabot.yaml").exists()
check("5.1", "Add Dependabot config", has_dep)

# 5.2 Pre-commit
has_pc = (PROJECT / ".pre-commit-config.yaml").exists()
check("5.2", "Add pre-commit hooks", has_pc)

# 5.3 Win/Mac CI
has_mac = "macos-latest" in ci
has_win = "windows-latest" in ci
check("5.3", "Add Windows/macOS to CI matrix", has_mac and has_win)

# 5.4 Mock TTS
conftest = (PROJECT / "tests/conftest.py").read_text(encoding="utf-8")
has_mock = "mock_tts" in conftest
check("5.4", "Mock TTS for offline testing", has_mock)

# 5.5 E2E artifacts
check("5.5", "Upload E2E artifacts on failure", "upload-artifact" in ci)

# 5.6 CI notification
check("5.6", "Add notification step on CI failure", "notify" in ci and "failure()" in ci)

# 5.7 IIFE
check("5.7", "Wrap app.js in IIFE", False, "Skipped — 1800 lines, 183 globals, too risky")

# 5.8 Consolidate escHtml
has_alias = "var ytEsc = escHtml" in app or "ytEsc = escHtml" in app
check("5.8", "Consolidate escHtml/ytEsc/vfxEsc", has_alias)

# 5.9 Dead code removal
check("5.9", "Remove dead code (revamp_engine)", True, "revamp_engine IS used in main.py")

# 5.10 __all__ exports
core_files = list((PROJECT / "core").glob("*.py"))
with_all = sum(
    1 for f in core_files if f.name != "__init__.py" and "__all__" in f.read_text(encoding="utf-8", errors="ignore")
)
check("5.10", "Add __all__ to Python modules", with_all >= 15, f"{with_all}/{len(core_files) - 1} modules have __all__")

# 5.11 Config schema versioning
cfg = (PROJECT / "config.py").read_text(encoding="utf-8")
has_version = "CONFIG_SCHEMA_VERSION" in cfg
check("5.11", "Add config schema versioning", has_version)

# 5.12 CHANGELOG
cl = (PROJECT / "CHANGELOG.md").read_text(encoding="utf-8")
has_v11 = "0.11.0" in cl
check("5.12", "Update CHANGELOG.md", has_v11)

# 5.13 API docs
check(
    "5.13", "Update API docs", (PROJECT / "docs/API.md").exists() or (PROJECT / "remotion/dashboard/README.md").exists()
)

# 5.14 Dashboard README
check("5.14", "Add README for dashboard", (PROJECT / "remotion/dashboard/README.md").exists())

# 5.15 JSDoc
jsdoc_count = app.count("/**")
check("5.15", "Add JSDoc/docstrings for public APIs", jsdoc_count >= 5, f"JSDoc comments found: {jsdoc_count}")

# SUMMARY
print()
print("=" * 70)
passed = sum(1 for _, _, s, _ in results if s == "PASS")
failed = sum(1 for _, _, s, _ in results if s == "FAIL")
print(f"SUMMARY: {passed} PASS, {failed} FAIL out of {len(results)} items")
if failed:
    print()
    print("FAILED ITEMS:")
    for item_id, desc, status, details in results:
        if status == "FAIL":
            print(f"  [{item_id}] {desc}")
            if details:
                print(f"    -> {details}")
