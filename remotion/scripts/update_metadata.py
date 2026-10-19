"""Update YouTube video metadata (title/tags) in place.

Usage:
    python update_metadata.py --channel channel1 --video-id XXXX --title "New title"
    python update_metadata.py --channel channel1 --video-id XXXX --tags "tag1,tag2"

Metadata-only: calls service.videos().update(part="snippet") -- the video file
is NEVER touched. Requires youtube.upload scope (already present in token).

Output: JSON on the LAST stdout line: {"ok":true,...} or {"ok":false,"error":...}
"""

import argparse
import json
import os
import sys
import contextlib

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_TOKENS = {
    "channel1": os.path.join(PROJECT, "data", "yt_token_channel1.json"),
    "channel2": os.path.join(PROJECT, "data", "yt_token_channel2.json"),
}
MAX_TITLE = 100
MAX_TAGS = 500


def get_service(channel):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import youtube_auth

    token_path = DEFAULT_TOKENS.get(channel)
    if token_path and os.path.exists(token_path):
        youtube_auth.set_token_path(os.path.abspath(token_path))
    cred = youtube_auth.get_credentials()
    if not cred:
        raise RuntimeError("auth failed - re-login needed")
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=cred)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="channel1", help="channel1 or channel2")
    ap.add_argument("--video-id", required=True, help="YouTube video ID")
    ap.add_argument("--title", default=None, help="new title (optional)")
    ap.add_argument("--tags", default=None, help="comma-separated tags (optional)")
    args = ap.parse_args()

    if args.channel not in DEFAULT_TOKENS:
        print(json.dumps({"ok": False, "error": "bad channel"}, ensure_ascii=False))
        return 1
    if not args.title and not args.tags:
        print(json.dumps({"ok": False, "error": "title ya tags kuch to chahiye"}, ensure_ascii=False))
        return 1

    try:
        service = get_service(args.channel)

        # Fetch current snippet to preserve untouched fields (category, etc.)
        current = service.videos().list(part="snippet,status,contentDetails", id=args.video_id).execute()
        items = current.get("items", [])
        if not items:
            print(json.dumps({"ok": False, "error": "video not found"}, ensure_ascii=False))
            return 1

        snippet = items[0].get("snippet", {})
        if args.title:
            snippet["title"] = args.title.strip()[:MAX_TITLE]
        if args.tags is not None:
            tags = [t.strip() for t in args.tags.split(",") if t.strip()]
            snippet["tags"] = tags[:MAX_TAGS]

        body = {"id": args.video_id, "snippet": snippet}
        updated = service.videos().update(part="snippet", body=body).execute()
        out_sn = updated.get("snippet", {})
        print(
            json.dumps(
                {
                    "ok": True,
                    "videoId": args.video_id,
                    "title": out_sn.get("title", ""),
                    "tags": out_sn.get("tags", []),
                },
                ensure_ascii=False,
            )
        )
        return 0

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:300]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
