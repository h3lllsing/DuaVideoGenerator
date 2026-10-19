"""Prepare vertical Shorts files from rendered dua videos (local only, no upload).

Usage:
    python make_shorts.py                     # all rendered videos <=58s
    python make_shorts.py --only id1,id2      # specific duas
    python make_shorts.py --dry-run           # plan only
    python make_shorts.py --force             # re-encode even if exists

Output: JSON on the LAST stdout line.
"""

import argparse
import glob
import io
import json
import os
import shutil
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SCRIPTS))
DATA_DIR = os.path.join(PROJECT, "remotion", "src", "data")
OUT_DIR = os.path.join(PROJECT, "remotion", "out")
SHORT_DIR = os.path.join(PROJECT, "remotion", "shorts", "out")
STATE_PATH = os.path.join(PROJECT, "data", "shorts_state_channel1.json")

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

MAX_SHORT_SECS = 58.0


def safe_title(title):
    import re

    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", title or "Dua").strip()
    return re.sub(r"[. ]+$", "", s) or "Dua"


def ffprobe_dur(path):
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True,
        text=True,
    )
    try:
        return float(r.stdout.strip().split("\n")[0])
    except Exception:
        return None


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def find_sources():
    out = {}
    for mf in glob.glob(os.path.join(DATA_DIR, "*.json")):
        if mf.endswith("ai_api_config.json"):
            continue
        try:
            with open(mf, encoding="utf-8") as f:
                m = json.load(f)
        except Exception:
            continue
        did = m.get("dua_id")
        title = m.get("title")
        dur = m.get("totalDuration")
        if not did or not title or not dur:
            continue
        src = os.path.join(OUT_DIR, safe_title(title) + ".mp4")
        if os.path.exists(src):
            out[did] = {
                "title": title,
                "src": src,
                "duration": float(dur),
                "manifest": mf,
                "reference": m.get("reference") or "",
                "channel": m.get("channel") or "",
            }
    return out


def encode_one(did, info, force):
    target = os.path.join(SHORT_DIR, did + ".short.mp4")
    state = load_state()
    prev = state.get(did) or {}
    if os.path.exists(target) and not force and prev.get("video_id"):
        return {"duaId": did, "status": "skipped", "note": "already done"}
    if os.path.exists(target) and not force and prev.get("shortHref") == target:
        return {"duaId": did, "status": "skipped", "note": "exists", "path": target}

    src_dur = ffprobe_dur(info["src"]) or info["duration"]
    cap = min(src_dur, MAX_SHORT_SECS)
    filter_spec = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
    cmd = [
        FFMPEG,
        "-y",
        "-i",
        info["src"],
        "-t",
        str(cap),
        "-vf",
        filter_spec,
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "21",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-shortest",
        target,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(target):
        return {"duaId": did, "status": "error", "note": (r.stderr or r.stdout)[-200:]}
    out_dur = ffprobe_dur(target)
    size_mb = round(os.path.getsize(target) / 1048576, 1)
    state.setdefault(did, {})["shortHref"] = target
    state.setdefault(did, {}).update(
        {
            "title": info["title"],
            "reference": info.get("reference", ""),
            "duration": round(out_dur or cap, 1),
            "sizeMB": size_mb,
        }
    )
    save_state(state)
    return {
        "duaId": did,
        "status": "made",
        "path": target,
        "dur": round(out_dur or cap, 1),
        "sizeMB": size_mb,
        "fromDur": round(src_dur, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="comma-separated dua_ids")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    sources = find_sources()
    order = sorted(sources)
    if args.only:
        want = [x.strip() for x in args.only.split(",") if x.strip()]
        sources = {k: v for k, v in sources.items() if k in want}
        order = sorted(sources)
        missing = [
            w for w in want if w not in sources and not os.path.exists(os.path.join(SHORT_DIR, w + ".short.mp4"))
        ]
    else:
        missing = []

    if args.dry_run:
        items = []
        for did in order:
            info = sources[did]
            items.append(
                {
                    "duaId": did,
                    "title": info["title"],
                    "srcDur": round(info["duration"], 1),
                    "plan": "encode" if sources else "n/a",
                }
            )
        print(json.dumps({"ok": True, "dryRun": True, "total": len(items), "items": items}, ensure_ascii=False))
        return 0

    results = [encode_one(did, sources[did], args.force) for did in order]
    made = [r for r in results if r["status"] == "made"]
    print(json.dumps({"ok": True, "total": len(results), "made": len(made), "items": results}, ensure_ascii=False))
    return 0 if len(made) == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
