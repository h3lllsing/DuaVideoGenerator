"""Delete useless temp build-files of RENDERED videos.

After an MP4 is baked, the TTS audio / merged wav / timing sidecars in
temp folder serve no purpose (they are only needed to BUILD the video).
This script removes them for every dua whose final MP4 exists, and frees
disk space.

Usage:
  python scripts/cleanup_temp.py            # delete (report first)
  python scripts/cleanup_temp.py --dry-run  # show what would be deleted

Never touches: out mp4/txt, thumbs, src/data manifests, duas.json, or
temp files of UNRENDERED duas.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "remotion", "scripts"))
import contextlib

from upload import safe_title  # same naming logic as the uploader

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP = os.path.join(PROJECT, "temp")
OUT = os.path.join(PROJECT, "remotion", "out")
THUMBS = os.path.join(OUT, "thumbs")
PUBLIC_AUDIO = os.path.join(PROJECT, "remotion", "public", "audio")
BACKGROUNDS = os.path.join(PROJECT, "remotion", "public", "backgrounds")
DB = os.path.join(PROJECT, "data", "duas.json")
YT_LEDGER1 = os.path.join(PROJECT, "data", "upload_state_channel1.json")
YT_LEDGER2 = os.path.join(PROJECT, "data", "upload_state_channel2.json")

# Per-dua junk in temp (only needed to BUILD; free once the MP4 is baked)
JUNK_EXT = ("_ar.mp3", "_ur.mp3", "_merged.wav", "_ar_timing.jsonl", "_ur_timing.jsonl", "_look.json")

# Fixed-name leaks that are regenerated each run â€” always safe to scrub
FIXED_JUNK = ("bg_gate_frame.png",)


def _load_locked_ids():
    """Return set of duaIds that are uploaded (locked) in YouTube ledger."""
    locked = set()
    for lp in (YT_LEDGER1, YT_LEDGER2):
        try:
            raw = json.load(open(lp, encoding="utf-8-sig"))
            for dua_id, v in raw.items():
                if v and v.get("status") == "uploaded":
                    locked.add(dua_id)
        except (OSError, ValueError):
            pass
    return locked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    arr = json.load(open(DB, encoding="utf-8-sig"))
    locked_ids = _load_locked_ids()
    deleted = [0]
    freed = [0]
    skipped_ids = 0
    skipped_locked = 0

    # 1) Fixed-name leaks (bg_gate_frame.png) â€” always, regardless of render
    for fname in FIXED_JUNK:
        p = os.path.join(TEMP, fname)
        if os.path.exists(p):
            freed[0] += os.path.getsize(p)
            deleted[0] += 1
            if not args.dry_run:
                with contextlib.suppress(OSError):
                    os.remove(p)

    for d in arr:
        dua_id = d.get("id") or ""
        if dua_id in locked_ids:
            skipped_locked += 1
            continue
        mp4 = os.path.join(OUT, safe_title(d.get("title") or "") + ".mp4")
        if not os.path.exists(mp4):
            skipped_ids += 1
            continue
        # (a) per-dua temp artifacts: audio/timing/look
        for ext in JUNK_EXT:
            p = os.path.join(TEMP, dua_id + ext)
            if os.path.exists(p):
                freed[0] += os.path.getsize(p)
                deleted[0] += 1
                if not args.dry_run:
                    with contextlib.suppress(OSError):
                        os.remove(p)
        # (b) id-based thumbnail (genThumb writes out/thumbs/{id}.png)
        # KEPT: thumbnails are required by the upload ready-check
        # (upload.py -> "no thumb" skip). They are NOT regenerated on
        # server restart, so deleting them here breaks uploads.
        # (c) background asset copied to public/backgrounds/{id}.{ext}
        bg_pfx = os.path.join(BACKGROUNDS, dua_id + ".")
        if os.path.isdir(BACKGROUNDS):
            for bf in os.listdir(BACKGROUNDS):
                if bf.startswith(bg_pfx):
                    p = os.path.join(BACKGROUNDS, bf)
                    freed[0] += os.path.getsize(p)
                    deleted[0] += 1
                    if not args.dry_run:
                        with contextlib.suppress(OSError):
                            os.remove(p)

    # stray temp files that belong to no known dua (custom/test) - report only
    known = {d.get("id") or "" for d in arr}
    strays = [
        f
        for f in os.listdir(TEMP)
        if os.path.isfile(os.path.join(TEMP, f)) and f.rsplit("_", 1)[0] not in known and f not in FIXED_JUNK
    ]

    print(f"rendered dua       : {len(arr) - skipped_ids - skipped_locked}")
    print(f"unrendered (kept)  : {skipped_ids}")
    print(f"locked/uploaded    : {skipped_locked} (skipped)")
    print("files {}        : {}".format("scanned (would del)" if args.dry_run else "deleted", deleted[0]))
    print("space {}           : {:.1f} MB".format("reclaimable" if args.dry_run else "freed", freed[0] / 1048576.0))
    print(f"stray temp files   : {len(strays)} (untouched - check manually)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
