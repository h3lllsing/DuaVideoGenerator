"""Upload rendered thumbnail pngs to YouTube videos.

Reads data/thumbs_state_channel1.json (dua_id -> {video_id, thumb}).

Usage:
    python upload_thumbs.py --dry-run
    python upload_thumbs.py
    python upload_thumbs.py --only dua1,dua2

Write op: thumbnails().set = 50 quota units each.
Idempotent: a thumbnail already custom-set is recorded; optional re-set.
"""

import argparse
import contextlib
import json
import os
import sys
import time

SYSOUT = None
with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SCRIPTS))
DATA = os.path.join(PROJECT, "data")
TH_PATH = os.path.join(DATA, "thumbs_state_channel1.json")
TOKEN_PATH = os.path.join(DATA, "yt_token_channel1.json")


def load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError:
        return {}


def get_service():
    import youtube_auth

    youtube_auth.set_token_path(os.path.abspath(TOKEN_PATH))
    cred = youtube_auth.get_credentials()
    if not cred:
        return None
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=cred)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--no-skip", action="store_true", help="re-set thumb even if state says done")
    args = ap.parse_args()

    state = load_json(TH_PATH)
    items = []
    for dua_id, rec in sorted(state.items()):
        if not isinstance(rec, dict) or not rec.get("video_id") or not rec.get("thumb"):
            continue
        if args.only and dua_id not in args.only.split(","):
            continue
        if rec.get("thumbSet") and not args.no_skip:
            continue
        if not os.path.exists(rec["thumb"]):
            continue
        items.append((dua_id, rec["video_id"], rec["thumb"]))
    print(f"thumbs pending: {len(items)}", flush=True)
    if args.dry_run:
        print(
            json.dumps(
                {"ok": True, "dryRun": True, "pending": len(items), "ids": [x[0] for x in items]}, ensure_ascii=False
            )
        )
        return 0

    yt = get_service()
    if not yt:
        print(json.dumps({"ok": False, "error": "auth"}))
        return 1
    from googleapiclient.http import MediaFileUpload

    done, failed = [], []
    for dua_id, video_id, thumb in items:
        try:
            media = MediaFileUpload(thumb, mimetype="image/png")
            yt.thumbnails().set(videoId=video_id, media_body=media).execute()
            state[dua_id]["thumbSet"] = True
            state[dua_id]["thumbSetAt"] = str(time.strftime("%Y-%m-%dT%H:%M:%S"))
            done.append(dua_id)
        except Exception as e:
            failed.append({"dua_id": dua_id, "video_id": video_id, "error": str(e)[-160:]})
        if (len(done) + len(failed)) % 20 == 0:
            tmp = TH_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, TH_PATH)
        time.sleep(0.4)
    tmp = TH_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, TH_PATH)
    print(json.dumps({"ok": True, "set": len(done), "failed": len(failed), "errors": failed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
