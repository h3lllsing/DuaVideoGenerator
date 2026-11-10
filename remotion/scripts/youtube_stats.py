"""Fetch YouTube video + channel statistics.

Usage:
    python youtube_stats.py --ids ID1,ID2,ID3 --channel channel1 [--token data/yt_token_channel1.json]

Output: JSON with per-video stats + channel stats to stdout.
"""

import argparse
import contextlib
import json
import os
import sys

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_TOKENS = {
    "channel1": os.path.join(PROJECT, "data", "yt_token_channel1.json"),
    "channel2": os.path.join(PROJECT, "data", "yt_token_channel2.json"),
}


def fetch_video_stats(service, video_ids):
    stats = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        resp = service.videos().list(part="statistics,contentDetails", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            vid = item["id"]
            s = item.get("statistics", {})
            cd = item.get("contentDetails", {})
            stats[vid] = {
                "viewCount": int(s.get("viewCount", 0)),
                "likeCount": int(s.get("likeCount", 0)),
                "commentCount": int(s.get("commentCount", 0)),
                "duration": cd.get("duration", ""),
            }
    return stats


def fetch_channel_stats(service):
    resp = service.channels().list(part="statistics,snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        return None
    ch = items[0]
    s = ch.get("statistics", {})
    return {
        "channelId": ch.get("id", ""),
        "title": ch.get("snippet", {}).get("title", ""),
        "subscriberCount": int(s.get("subscriberCount", 0)),
        "viewCount": int(s.get("viewCount", 0)),
        "videoCount": int(s.get("videoCount", 0)),
        "hiddenSubscriberCount": s.get("hiddenSubscriberCount", False),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="comma-separated YouTube video IDs (optional)")
    ap.add_argument("--channel", default="channel1", help="channel1 or channel2")
    ap.add_argument("--token", default=None, help="path to token json (overrides --channel)")
    args = ap.parse_args()

    token_path = args.token or DEFAULT_TOKENS.get(args.channel)
    if token_path and not os.path.isabs(token_path):
        token_path = os.path.join(PROJECT, token_path)

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import youtube_auth

        if token_path:
            youtube_auth.set_token_path(os.path.abspath(token_path))
        cred = youtube_auth.get_credentials()
        if not cred:
            print(json.dumps({"ok": False, "error": "auth failed - re-login needed"}))
            return 1
        try:
            from google.auth.transport.requests import Request as _GReq

            if getattr(cred, "expired", False) and getattr(cred, "refresh_token", None):
                cred.refresh(_GReq())
        except Exception as _re:
            print(json.dumps({"ok": False, "error": "token refresh failed - re-login needed: " + str(_re)[:200]}))
            return 1

        from googleapiclient.discovery import build

        service = build("youtube", "v3", credentials=cred)

        result = {"ok": True, "channel": None, "stats": {}}

        # Channel stats
        try:
            result["channel"] = fetch_channel_stats(service)
        except Exception as e:
            result["channelError"] = str(e)[:200]

        # Video stats
        video_ids = [x.strip() for x in args.ids.split(",") if x.strip()]
        if video_ids:
            try:
                result["stats"] = fetch_video_stats(service, video_ids)
            except Exception as e:
                result["videoError"] = str(e)[:200]

        print(json.dumps(result))
        return 0

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:300]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
