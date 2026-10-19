"""Sync YouTube channel videos against the dua database.

Usage:
  python scripts/youtube_sync.py --channel channel1
  python scripts/youtube_sync.py --channel channel2 --token data/yt_token_channel2.json

Output: JSON to stdout with matched videos:
  { "ok": true, "matches": [{ "duaId": "...", "videoId": "...", "title": "..." }] }

Matching strategy:
  1. Exact dua_id in video description (upload.py may embed it)
  2. Dua ID as substring of video title
  3. Fuzzy title match against dua database
"""

import argparse
import json
import os
import re
import sys
import contextlib

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT, "data")
DEFAULT_TOKENS = {
    "channel1": os.path.join(DATA_DIR, "yt_token_channel1.json"),
    "channel2": os.path.join(DATA_DIR, "yt_token_channel2.json"),
}


def load_duas():
    """Load dua database, return {id: {title, reference, ...}}."""
    try:
        with open(os.path.join(DATA_DIR, "duas.json"), encoding="utf-8") as f:
            raw = json.load(f)
        duas = raw if isinstance(raw, list) else raw.get("duas", [])
        return {d["id"]: d for d in duas if "id" in d}
    except Exception:
        return {}


def normalize(s):
    """Normalize text for comparison."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def match_dua(video_title, video_desc, dua_db):
    """Match a YouTube video to a dua ID. Returns duaId or None.

    Uses high-confidence matching only:
    1. Exact dua_id in video description
    2. Dua ID as substring of normalized title
    3. Key words from dua title appear in video title (at least 2 meaningful words)
    """
    title_lower = (video_title or "").lower()
    desc_lower = (video_desc or "").lower()

    # Strategy 1: Exact dua_id in description (highest confidence)
    for dua_id in dua_db:
        if dua_id in desc_lower:
            return dua_id

    # Strategy 2: Dua ID as exact substring of normalized title
    for dua_id in dua_db:
        norm_title = title_lower.replace(" ", "_").replace("-", "_").replace("'", "'")
        if dua_id in norm_title:
            return dua_id

    # Strategy 3: Key word matching — extract core keywords from dua title,
    # check if they appear in video title. Ignores filler words.
    stop_words = {
        "ki",
        "ka",
        "ke",
        "aur",
        "hai",
        "mein",
        "ko",
        "se",
        "pe",
        "ye",
        "wo",
        "jo",
        "koi",
        "kya",
        "kyun",
        "kab",
        "yah",
        "par",
        "nikalte",
        "wqt",
        "hote",
        "waqt",
        "baad",
        "pehle",
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "for",
        "to",
        "and",
    }
    best_match = None
    best_score = 0
    for dua_id, d in dua_db.items():
        dua_title = normalize(d.get("title", ""))
        vtitle = normalize(video_title)
        if not dua_title or not vtitle:
            continue
        dua_words = [w for w in dua_title.split() if w not in stop_words]
        vid_words = set(vtitle.split())
        if not dua_words:
            continue
        matched = [w for w in dua_words if w in vid_words]
        # Need at least 2 meaningful words matched, covering >=50% of dua keywords
        score = len(matched) / max(len(dua_words), 1)
        if score >= 0.5 and len(matched) >= 2 and score > best_score:
            best_score = score
            best_match = dua_id

    return best_match


def list_channel_videos(service):
    """List all videos on the authenticated user's channel."""
    videos = []
    # Get channel ID first
    try:
        ch_resp = service.channels().list(part="contentDetails", mine=True).execute()
        items = ch_resp.get("items", [])
        if not items:
            return videos
        uploadsPlaylist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception as e:
        print("ERROR getting channel:", e, file=sys.stderr)
        return videos

    # Paginate through uploads playlist
    next_page = None
    while True:
        try:
            kwargs = {
                "part": "snippet,contentDetails",
                "playlistId": uploadsPlaylist,
                "maxResults": 50,
            }
            if next_page:
                kwargs["pageToken"] = next_page
            resp = service.playlistItems().list(**kwargs).execute()
            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                content = item.get("contentDetails", {})
                videos.append(
                    {
                        "videoId": content.get("videoId", ""),
                        "title": snippet.get("title", ""),
                        "description": snippet.get("description", ""),
                        "publishedAt": snippet.get("publishedAt", ""),
                        "channelTitle": snippet.get("channelTitle", ""),
                    }
                )
            next_page = resp.get("nextPageToken")
            if not next_page:
                break
        except Exception as e:
            print("ERROR paginating:", e, file=sys.stderr)
            break

    return videos


def main():
    ap = argparse.ArgumentParser(description="Sync YouTube channel with dua database")
    ap.add_argument("--channel", default="channel1", help="channel1 or channel2")
    ap.add_argument("--token", default=None, help="path to token json (overrides --channel)")
    args = ap.parse_args()

    token_path = args.token or DEFAULT_TOKENS.get(args.channel)

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import youtube_auth

        if token_path:
            youtube_auth.set_token_path(os.path.abspath(token_path))
        cred = youtube_auth.get_credentials()
        if cred:
            pass
        if not cred:
            print(json.dumps({"ok": False, "error": "auth failed - re-login needed"}))
            return 1

        from googleapiclient.discovery import build

        service = build("youtube", "v3", credentials=cred)

        # List all channel videos
        videos = list_channel_videos(service)

        # Load dua database
        dua_db = load_duas()

        # Match each video to a dua
        matches = []
        unmatched = []
        for v in videos:
            dua_id = match_dua(v["title"], v["description"], dua_db)
            if dua_id:
                matches.append(
                    {
                        "duaId": dua_id,
                        "videoId": v["videoId"],
                        "title": v["title"],
                        "publishedAt": v["publishedAt"],
                    }
                )
            else:
                unmatched.append(
                    {
                        "videoId": v["videoId"],
                        "title": v["title"],
                        "publishedAt": v["publishedAt"],
                    }
                )

        result = {
            "ok": True,
            "channel": args.channel,
            "totalVideos": len(videos),
            "matchedDuas": len(matches),
            "unmatchedVideos": len(unmatched),
            "matches": matches,
            "unmatched": unmatched[:20],  # cap for readability
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0

    except ImportError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "google libs missing - pip install google-auth-oauthlib google-api-python-client",
                }
            )
        )
        return 1
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:300]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
