"""Auto-QC: rendered video ki basic quality checks (no external deps).

Checks:
  1. duration >= 5s
  2. brightness: koi frame bilkul kaala/safed na ho
  3. variance: frames me difference ho (static/blank render pakra jaye)
  4. loudness: -30..-8 LUFS (audio na bohot kam na bohot zyada)

PILLAR 1 · pre-render content lint (DB-level, render se pehle):
  python qc.py --lint <dua_id>    ek dua ki content validation
  python qc.py --lint-all         poori DB: length/harakat/duplicate scan

Output: single-line JSON {"pass": bool, "reason": str|null, "checks": {...}}
Exit code hamesha 0 (server JSON parse karta hai); lint modes me
hard-fail par exit 2 (CI/scheduled runs pakad saken).
"""

import json
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DUAS_FILE = os.path.join(PROJECT_ROOT, "data", "duas.json")

URDU_WARN_WORDS = 60  # comfort limit (VIDEO-002 40s budget)
URDU_HARD_WORDS = 75  # server /api/add-dua cap
ARABIC_HARAKAT_MIN_LEN = 15  # isse lambi text me harakat honi chahiye

# PHASE 2 P0 · theme-aware variance floors. Light/soft scenes (manuscript
# paper preset, bright photo/sky backgrounds) keep subtle drift, so the harsh
# 1.0 floor falsely flags them as static. Light scenes -> 0.3 floor; rich/dark
# scenes keep the strict 1.0 gate (encoding noise < 0.5 caught either way).
LIGHT_VAR_FLOOR = 0.30
DARK_VAR_FLOOR = 1.00
LIGHT_THEMES = ("manuscript",)  # only light palette in remotion/src/themes.ts
BRIGHTNESS_LIGHT_CUE = 128.0  # avg gray 0-255: above = light scene
MANIFEST_DIR = os.path.join(PROJECT_ROOT, "remotion", "src", "data")

_DIACRITICS = re.compile(r"[\u064b-\u0652\u0670]")


def _norm_arabic(s):
    stripped = _DIACRITICS.sub("", s or "")
    stripped = stripped.replace("\u0640", "")
    return re.sub(r"\s+", " ", stripped).strip()


def _manifest_template(video_path):
    """Sidecar manifest (remotion/src/data/<dua_id>.json) ka template read."""
    stem = os.path.splitext(os.path.basename(video_path))[0]
    mpath = os.path.join(MANIFEST_DIR, stem + ".json")
    if not os.path.exists(mpath):
        return None
    try:
        with open(mpath, encoding="utf-8") as f:
            return (json.load(f).get("template") or "").strip().lower()
    except (OSError, ValueError):
        return None


def _load_duas():
    with open(DUAS_FILE, encoding="utf-8") as f:
        rows = json.load(f)
    return rows["duas"] if isinstance(rows, dict) and "duas" in rows else rows


def lint_dua(dua, all_norm_arabic=None):
    """Ek dua ko pre-render rules ke against check karta hai.

    Returns {"id", "issues": [...], "warnings": [...]}.
    """
    did = dua.get("id", "?")
    issues, warnings = [], []

    urdu = str(dua.get("urdu") or "").strip()
    urdu_words = len(urdu.split()) if urdu else 0
    if urdu_words > URDU_HARD_WORDS:
        issues.append(f"urdu {urdu_words} words > {URDU_HARD_WORDS} (VIDEO-002 cap)")
    elif urdu_words > URDU_WARN_WORDS:
        warnings.append(f"urdu {urdu_words} words > {URDU_WARN_WORDS} comfort")

    arabic = str(dua.get("arabic") or "").strip()
    bare = _norm_arabic(arabic)
    if len(bare) > ARABIC_HARAKAT_MIN_LEN and not _DIACRITICS.search(arabic):
        issues.append("missing harakat on long arabic text")

    if not str(dua.get("reference") or "").strip():
        warnings.append("empty reference")
    if not str(dua.get("title_en") or "").strip():
        warnings.append("missing title_en")

    if all_norm_arabic is not None and bare:
        self_key = (did, dua.get("category", ""))
        twins = all_norm_arabic.get(bare, set()) - {self_key}
        # Wahi arabic do contexts me (e.g. evening adhkar + nazar
        # protection) = jaiz reuse -> warning. Same category ke andar
        # duplicate = accidental double-add -> hard issue.
        same_cat = {t for t in twins if t[1] == dua.get("category")}
        if same_cat:
            issues.append("duplicate arabic in same category with: " + ", ".join(sorted(t[0] for t in same_cat)))
        elif twins:
            warnings.append("arabic reused across categories: " + ", ".join(sorted(t[0] for t in twins)))
    return {"id": did, "issues": issues, "warnings": warnings}


def _build_arabic_index(duas):
    idx = {}
    for d in duas:
        bare = _norm_arabic(str(d.get("arabic") or ""))
        if bare:
            idx.setdefault(bare, set()).add((d.get("id", "?"), d.get("category", "")))
    return idx


def run_lint(target=None):
    duas = _load_duas()
    index = _build_arabic_index(duas)
    scope = [d for d in duas if d.get("id") == target] if target else duas
    results = [lint_dua(d, index) for d in scope]
    failed = [r for r in results if r["issues"]]
    warned = [r for r in results if not r["issues"] and r["warnings"]]
    passed = not failed
    print(
        json.dumps(
            {
                "pass": passed,
                "reason": None if passed else "; ".join(f"{r['id']}: {r['issues'][0]}" for r in failed[:5]),
                "checks": {
                    "mode": "content-lint",
                    "scanned": len(results),
                    "failed_count": len(failed),
                    "warned_count": len(warned),
                    "failed": [{"id": r["id"], "issues": r["issues"]} for r in failed],
                    "warnings": [{"id": r["id"], "warnings": r["warnings"]} for r in warned[:25]],
                },
            },
            ensure_ascii=False,
        )
    )
    return 0 if passed else 2


import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
FRAME_W, FRAME_H = 48, 85


def run(args, timeout=120):
    return subprocess.run([FF] + args, capture_output=True, timeout=timeout)


def get_duration(path):
    r = run(["-i", path])
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", r.stderr.decode("utf8", "ignore"))
    if not m:
        return None
    h, mi, s, ms = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000.0


def frame_mean(path, ts):
    r = subprocess.run(
        [
            FF,
            "-ss",
            f"{ts:.2f}",
            "-i",
            path,
            "-frames:v",
            "1",
            "-vf",
            f"scale={FRAME_W}:{FRAME_H}",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        timeout=60,
    )
    data = r.stdout
    if len(data) < FRAME_W * FRAME_H:
        return None
    return sum(data) / len(data)


def get_loudness(path):
    r = run(["-i", path, "-af", "loudnorm=print_format=json", "-f", "null", "-"], timeout=300)
    txt = r.stderr.decode("utf8", "ignore")
    blocks = re.findall(r"\{[^{}]*input_i[^{}]*\}", txt)
    if not blocks:
        return None
    try:
        d = json.loads(blocks[-1])
        return {"i": float(d["input_i"]), "tp": float(d["input_tp"])}
    except (ValueError, KeyError):
        return None


def main():
    path = sys.argv[1]
    checks = {}
    reasons = []

    dur = get_duration(path)
    checks["duration_s"] = round(dur, 2) if dur else None
    dur_ok = dur is not None and dur >= 5.0
    checks["dur_ok"] = dur_ok
    if not dur_ok:
        reasons.append("video 5s se choti hai")

    fracs = [0.10, 0.22, 0.34, 0.46, 0.58, 0.70, 0.82, 0.92]
    means = []
    if dur:
        for f in fracs:
            m = frame_mean(path, min(dur * f, max(dur - 0.3, 0)))
            if m is not None:
                means.append(m)
    checks["frames_sampled"] = len(means)
    if means:
        lo, hi = min(means), max(means)
        checks["brightness_min"] = round(lo, 1)
        checks["brightness_max"] = round(hi, 1)
        bright_ok = all(8 < m < 247 for m in means)
        # PHASE 2 P0 · theme-aware variance: manuscript/light scenes use a
        # 0.3 floor (subtle paper/aurora drift is valid), dark scenes keep the
        # 1.0 gate. Sidecar may be cleaned up post-upload -> brightness cue.
        tpl = _manifest_template(path)
        light = bool(tpl and tpl in LIGHT_THEMES)
        if not tpl:
            light = (sum(means) / len(means)) >= BRIGHTNESS_LIGHT_CUE
        var_floor = LIGHT_VAR_FLOOR if light else DARK_VAR_FLOOR
        var_ok = (hi - lo) >= var_floor
        checks["bright_ok"] = bright_ok
        checks["template"] = tpl or "unknown"
        checks["variance_floor"] = round(var_floor, 2)
        checks["variance_ok"] = var_ok
        if not bright_ok:
            reasons.append("frame bohot dark/bright hai (blank render?)")
        if not var_ok:
            reasons.append("frames me koi farq nahi (static render?)")
    else:
        checks["bright_ok"] = False
        checks["variance_ok"] = False
        reasons.append("frames extract nahi ho sake")

    loud = get_loudness(path)
    checks["loudness_lufs"] = round(loud["i"], 1) if loud else None
    checks["loudness_tp"] = round(loud["tp"], 1) if loud else None
    # PILLAR 2 · broadcast gate: -14 LUFS anchor (±1.0), true peak <= -1.0 dBTP.
    loud_ok = loud is not None and abs(loud["i"] - (-14.0)) <= 1.0 and loud["tp"] <= -1.0
    checks["loud_ok"] = loud_ok
    if not loud_ok:
        reasons.append("audio loudness gate fail (target -14±1 LUFS, TP <= -1.0 dBTP)")

    passed = not reasons
    print(
        json.dumps(
            {
                "pass": passed,
                "reason": None if passed else "; ".join(reasons),
                "checks": checks,
            }
        )
    )


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--lint-all" in args:
        raise SystemExit(run_lint(None))
    if "--lint" in args:
        i = args.index("--lint")
        target = args[i + 1] if i + 1 < len(args) else None
        if not target:
            print("usage: qc.py --lint <dua_id> | --lint-all")
            raise SystemExit(1)
        raise SystemExit(run_lint(target))
    main()
