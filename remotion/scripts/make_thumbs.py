"""Render high-CTR thumbnail pngs (ThumbCard comp) for all uploaded videos.

Local-only. Upload camera later covers thumbs_state_channel1.json.

Usage:
    python make_thumbs.py --dry-run
    python make_thumbs.py                # render missing thumbs
    python make_thumbs.py --only id1,id2

Output: JSON on the LAST stdout line.
"""

import argparse
import io
import json
import os
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SCRIPTS))
REMOTION = os.path.join(PROJECT, "remotion")
THUMB_DIR = os.path.join(REMOTION, "out", "thumbs")
DATA = os.path.join(PROJECT, "data")
UT_PATH = os.path.join(DATA, "upload_state_channel1.json")
SH_PATH = os.path.join(DATA, "shorts_state_channel1.json")
MANIFEST_DIR = os.path.join(REMOTION, "src", "data")
THUMBS_STATE = os.path.join(DATA, "thumbs_state_channel1.json")

REMOTION_BIN = os.path.join(REMOTION, "node_modules", ".bin", "remotion.cmd")
MIN_OK = 20 * 1024


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f) or default
    except (OSError, ValueError):
        return default


def duas_map():
    duas = _read_json(os.path.join(DATA, "duas.json"), [])
    if not isinstance(duas, list):
        duas = duas.get("duas") or []
    cfg = _read_json(os.path.join(REMOTION, "dashboard", "config.json"), {})
    return {
        "duas": {d.get("id"): d for d in duas if d.get("id")},
        "channel": (cfg.get("channelName") or "Noor-e-Iman").strip(),
    }


def props_path_for(dua_id, dmap):
    """Return a props JSON wrapped as {"data": {...}} for thumbnail-card."""
    manifest = os.path.join(MANIFEST_DIR, dua_id + ".json")
    cache = os.path.join(THUMB_DIR, "_props")
    os.makedirs(cache, exist_ok=True)
    out = os.path.join(cache, dua_id + ".json")
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8") as f:
            m = json.load(f)
    else:
        info = dmap["duas"].get(dua_id) or {}
        title = info.get("title") or dua_id.replace("_", " ").title()
        ref = (info.get("reference") or "").strip()
        arabic = (info.get("arabic") or "").strip()
        m = {
            "dua_id": dua_id,
            "title": title,
            "reference": ref,
            "arabicWords": [{"t": w} for w in arabic.split()[:6]],
            "template": "dark",
            "channel": {"name": dmap["channel"]},
        }
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"data": m}, f, ensure_ascii=False)
    return out


def render_one(dua_id, dmap):
    props = props_path_for(dua_id, dmap)
    target = os.path.join(THUMB_DIR, dua_id + ".png")
    r = subprocess.run(
        [REMOTION_BIN, "still", "thumbnail-card", target, "--props=" + props],
        capture_output=True,
        text=True,
        cwd=REMOTION,
    )
    if r.returncode != 0 or not os.path.exists(target):
        return {"duaId": dua_id, "status": "error", "note": (r.stderr or r.stdout)[-200:]}
    size = os.path.getsize(target)
    return {"duaId": dua_id, "status": "ok", "sizeKB": size // 1024}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    ut = _read_json(UT_PATH, {})
    sh = _read_json(SH_PATH, {})
    wanted = {}
    for dua_id, rec in ut.items():
        if not dua_id:
            continue
        wanted.setdefault(dua_id, {})["video_id"] = (rec or {}).get("video_id")
    for dua_id, rec in sh.items():
        if not dua_id:
            continue
        w = wanted.setdefault(dua_id, {})
        w.setdefault("video_id", (rec or {}).get("video_id"))

    order = sorted(wanted)
    if args.only:
        sel = [x.strip() for x in args.only.split(",") if x.strip()]
        want_filtered = {k: v for k, v in wanted.items() if k in sel}
        order = sorted(want_filtered)
        wanted = want_filtered

    pending = []
    for dua_id in order:
        thumb = os.path.join(THUMB_DIR, dua_id + ".png")
        if os.path.exists(thumb) and os.path.getsize(thumb) >= MIN_OK:
            continue
        pending.append(dua_id)

    if args.dry_run:
        print(
            json.dumps(
                {"ok": True, "dryRun": True, "total": len(order), "missing": len(pending), "ids": pending},
                ensure_ascii=False,
            )
        )
        return 0

    prev = _read_json(THUMBS_STATE, {})
    dmap = duas_map()
    results = []
    for dua_id in pending:
        r = render_one(dua_id, dmap)
        if r["status"] == "ok":
            prev[dua_id] = {
                "video_id": wanted[dua_id].get("video_id"),
                "thumb": os.path.join(THUMB_DIR, dua_id + ".png"),
                "sizeKB": r["sizeKB"],
            }
        results.append(r)
        tmp = THUMBS_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(prev, f, ensure_ascii=False, indent=2)
        os.replace(tmp, THUMBS_STATE)

    ok = [r for r in results if r["status"] == "ok"]
    print(json.dumps({"ok": True, "rendered": len(ok), "total": len(results), "items": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
