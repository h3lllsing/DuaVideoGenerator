"""PILLAR 1 · Bulk build engine — sequential audio+manifest factory.

Wraps the proven per-dua pipeline for scale:
    remotion/scripts/prepare_dua.py <id>   (TTS + merge, skip-if-exists)
    remotion/scripts/make_manifest.py <id> (timings + mastered audio + manifest)

Filters (--filter):
    missing-manifest   only duas without remotion/src/data/<id>.json  [default]
    category=<cat>     only duas in one category id (taxonomy v2 or legacy)
    all                every dua in the DB

Behaviour:
    - sequential processing, checkpoint-safe (prepare skips existing audio)
    - inter-dua pacing jitter 250-750 ms (edge-tts friendly)
    - 429 / 422 / rate-limit aware exponential-ish backoff with jitter
      (30-60 s cool-down, max 3 attempts; VIDEO-002 policy rejects are NOT
      retried - they are deterministic)
    - dry-run by default; pass --apply to actually build

Usage:
    python scripts/bulk_build.py                       # plan only
    python scripts/bulk_build.py --apply               # build missing
    python scripts/bulk_build.py --filter=category=family --apply
"""

import json
import os
import random
import subprocess
import sys
import time

PROJECT = r"H:\DuaVideoGenerator"
sys.path.append(PROJECT)

DATA_DIR = os.path.join(PROJECT, "data")
DUAS_FILE = os.path.join(DATA_DIR, "duas.json")
MANIFEST_DIR = os.path.join(PROJECT, "remotion", "src", "data")
PREPARE = os.path.join(PROJECT, "remotion", "scripts", "prepare_dua.py")
MANIFESTER = os.path.join(PROJECT, "remotion", "scripts", "make_manifest.py")

PACE_MIN, PACE_MAX = 0.25, 0.75  # seconds between duas
BACKOFF_MIN, BACKOFF_MAX = 30.0, 60.0  # rate-limit cool-down window
MAX_ATTEMPTS = 3
RATE_HINTS = ("429", "422", "rate limit", "ratelimit", "too many requests")


def load_duas():
    with open(DUAS_FILE, encoding="utf-8") as f:
        rows = json.load(f)
    return rows["duas"] if isinstance(rows, dict) else rows


def select_duas(duas, filt):
    if filt == "all":
        return list(duas), "all"
    if filt.startswith("category="):
        cat = filt.split("=", 1)[1].strip()
        sel = [d for d in duas if d.get("category") == cat]
        return sel, f"category={cat}"
    sel = [d for d in duas if not os.path.exists(os.path.join(MANIFEST_DIR, d["id"] + ".json"))]
    return sel, "missing-manifest"


def run_step(cmd):
    """Returns (exit_code, combined_output)."""
    p = subprocess.run(
        [sys.executable, cmd[0], cmd[1]], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    return p.returncode, out


def is_rate_limited(output):
    low = output.lower()
    return any(h in low for h in RATE_HINTS)


def process(dua_id):
    """Build one dua end-to-end with retries. Returns status string."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        code, out = run_step([PREPARE, dua_id])
        if code == 0:
            mcode, mout = run_step([MANIFESTER, dua_id])
            if mcode == 0:
                return "ok"
            print(f"    manifest failed (code {mcode}): {mout.splitlines()[-1] if mout else '?'}")
            return "manifest-failed"
        last_line = out.splitlines()[-1] if out else "?"
        if code == 3:
            print(f"    policy-reject (VIDEO-002): {last_line}")
            return "policy-reject"
        if is_rate_limited(out):
            wait = random.uniform(BACKOFF_MIN, BACKOFF_MAX)
            print(f"    attempt {attempt}/{MAX_ATTEMPTS} hit rate limit; cooling {wait:.1f}s ...")
            time.sleep(wait)
            continue
        print(f"    attempt {attempt}/{MAX_ATTEMPTS} failed: {last_line}")
        time.sleep(random.uniform(PACE_MIN * 4, PACE_MAX * 4))
    return "tts-failed"


def main():
    argv = sys.argv[1:]
    apply = "--apply" in argv
    filt = "missing-manifest"
    for a in argv:
        if a.startswith("--filter"):
            filt = a.split("=", 1)[1] if "=" in a else argv[argv.index(a) + 1]
            break
    limit = None
    for a in argv:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])

    duas, label = select_duas(load_duas(), filt)
    if limit:
        duas = duas[:limit]

    print(f"[plan] filter={label} -> {len(duas)} dua(s)")
    if not apply:
        for d in duas:
            print(f"  would build: {d['id']} ({d.get('category')})")
        print("[dry-run] pass --apply to execute")
        return 0

    stats = {"ok": 0, "tts-failed": 0, "manifest-failed": 0, "policy-reject": 0}
    failures = []
    t0 = time.time()
    for i, d in enumerate(duas, 1):
        did = d["id"]
        print(f"[{i}/{len(duas)}] {did} ({d.get('category')})")
        status = process(did)
        stats[status] = stats.get(status, 0) + 1
        if status != "ok":
            failures.append((did, status))
        if i < len(duas):
            time.sleep(random.uniform(PACE_MIN, PACE_MAX))

    dt = time.time() - t0
    print(
        f"\n[done] {dt / 60:.1f} min | ok={stats['ok']} "
        f"tts-failed={stats['tts-failed']} "
        f"manifest-failed={stats['manifest-failed']} "
        f"policy-reject={stats['policy-reject']}"
    )
    for did, st in failures:
        print(f"  FAILED: {did} -> {st}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
