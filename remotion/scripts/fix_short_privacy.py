"""Fix: set all published Shorts to public (privacy was not applied on upload).

Run AFTER daily quota reset (writes are blocked while quota is exhausted).
Idempotent: videos already public are skipped.

Usage:
    python fix_short_privacy.py --dry-run          # show which shorts are private
    python fix_short_privacy.py                    # make all private shorts public
    python fix_short_privacy.py --limit 3          # only 3 per day (gradual rollout)

Idempotent: videos already public are skipped.
"""

import argparse
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SCRIPTS))
DATA = os.path.join(PROJECT, "data")
SH_PATH = os.path.join(DATA, "shorts_state_channel1.json")
TOKEN_PATH = os.path.join(DATA, "yt_token_channel1.json")

CHANNELS_OK = ("public", "unlisted")


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
    ap.add_argument("--limit", type=int, default=None, help="max shorts to make public in this run")
    args = ap.parse_args()

    sh = load_json(SH_PATH)
    ids = [rec["video_id"] for rec in sh.values() if rec and rec.get("video_id")]
    ids = sorted(set(ids))
    if not ids:
        print(json.dumps({"ok": False, "note": "no shorts in state"}))
        return 1

    yt = get_service()
    if not yt:
        print(json.dumps({"ok": False, "note": "auth failed"}))
        return 1

    status = {}
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="status", id=",".join(ids[i : i + 50])).execute()
        for it in r.get("items", []):
            status[it["id"]] = it["status"]["privacyStatus"]

    to_fix = [vid for vid in ids if status.get(vid, "private") not in CHANNELS_OK]
    if args.limit:
        to_fix = to_fix[: args.limit]
    already = [vid for vid in ids if status.get(vid, "") in CHANNELS_OK]
    print("shorts: %d | already public/unlisted: %d | private: %d" % (len(ids), len(already), len(to_fix)), flush=True)

    if args.dry_run:
        print(json.dumps({"ok": True, "dryRun": True, "private": to_fix}, ensure_ascii=False))
        return 0

    fixed, failed = [], []
    for vid in to_fix:
        try:
            yt.videos().update(part="status", body={"id": vid, "status": {"privacyStatus": "public"}}).execute()
            fixed.append(vid)
        except Exception as e:
            failed.append({"video_id": vid, "error": str(e)[-160:]})
    print(
        json.dumps(
            {"ok": True, "fixed": len(fixed), "failed": len(failed), "fixed_ids": fixed, "errors": failed},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
