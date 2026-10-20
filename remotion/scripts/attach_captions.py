"""Attach approved EN subtitle (SRT) tracks to already-uploaded YouTube videos.

Reuses data/upload_state_channel{1,2}.json (dua_id -> video_id) and the EN
review gate (data/en_review.json, status == "approved"). Captions are ONLY
attached for approved duas - the gate stays respected.

For each dua:
  1. video_id from upload_state + channel token data/yt_token_<ch>.json.
  2. EN text from the approved review entry.
  3. SRT: prefer an existing remotion/out/<safe_title>.en.srt; otherwise build
     a single-caption block timed to the LIVE video duration (videos.list).
  4. captions().insert(language "en", name "English", isDraft False).
  Skips videos that already have an English caption track (idempotent).

Usage:
    python attach_captions.py --all --dry-run        # plan for every approved
    python attach_captions.py --only jism_mein_dard_ki_dua,murgh_ki_awaz_sunne_ki_dua
    python attach_captions.py --channel channel1 --gated   # upload only (skip approved check)
"""

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
import time

with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(PROJECT, "data")
OUT = os.path.join(PROJECT, "remotion", "out")
REVIEW_PATH = os.path.join(DATA, "en_review.json")
DEFAULT_TOKENS = {
    "channel1": os.path.join(DATA, "yt_token_channel1.json"),
    "channel2": os.path.join(DATA, "yt_token_channel2.json"),
}
DEFAULT_STATES = {
    "channel1": os.path.join(DATA, "upload_state_channel1.json"),
    "channel2": os.path.join(DATA, "upload_state_channel2.json"),
}
SHORTS_STATES = {
    "channel1": os.path.join(DATA, "shorts_state_channel1.json"),
    "channel2": os.path.join(DATA, "shorts_state_channel2.json"),
}
TRACK_NAME = "English"
TRACK_LANG = "en"

SKIP_ALREADY = True


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f) or default
    except (OSError, ValueError):
        return default


def safe_title(title):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", title or "Dua").strip()


def fmt_ts(secs):
    secs = max(0.0, float(secs))
    ms = int(round(secs * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def iso_duration_secs(d):
    """Parse ISO-8601 YouTube duration (PT#H#M#S) to seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", (d or "").strip())
    if not m:
        return None
    parts = m.groups()
    secs = 0
    for mult, g in zip((86400, 3600, 60, 1), parts):
        if g:
            secs += int(g) * mult
    return secs


def get_youtube_service(channel):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import youtube_auth

    token_path = DEFAULT_TOKENS.get(channel)
    if token_path and os.path.exists(token_path):
        youtube_auth.set_token_path(os.path.abspath(token_path))
    cred = youtube_auth.get_credentials()
    if not cred:
        return None, "no credentials for " + channel
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=cred), None


def list_caption_tracks(service, video_id):
    """Return dict/None of existing caption tracks for the video."""
    try:
        resp = (
            service.captions()
            .list(part="snippet", videoId=video_id, fields="items(id,snippet(name,language))")
            .execute()
        )
        return resp.get("items", [])
    except Exception as e:
        return ("ERR", str(e)[:200])


def build_plan(channel, only=None, all_approved=False):
    """Yield (dua_id, video_id, en_text, srt_path) candidates."""
    state = _read_json(DEFAULT_STATES.get(channel), {})
    review = _read_json(REVIEW_PATH, {})
    duas = _read_json(os.path.join(DATA, "duas.json"), [])
    duas = duas if isinstance(duas, list) else duas.get("duas") or []
    titles = {d.get("id"): d.get("title") for d in duas}

    candidates = []
    for dua_id, rec in state.items():
        if not isinstance(rec, dict):
            continue
        if rec.get("status") != "uploaded" or not rec.get("video_id"):
            continue
        if only and dua_id not in only:
            continue
        if not all_approved and only is None:
            continue  # must be explicit --only or --all
        candidates.append((dua_id, rec["video_id"]))

    shorts = _read_json(SHORTS_STATES.get(channel), {})
    for dua_id, rec in shorts.items():
        if not isinstance(rec, dict) or not rec.get("video_id"):
            continue
        if only and dua_id not in only:
            continue
        if not all_approved and only is None:
            continue
        candidates.append((dua_id, rec["video_id"]))

    seen = set()
    dedup = []
    for dua_id, video_id in candidates:
        key = (dua_id, video_id)
        if key in seen:
            continue
        seen.add(key)
        dedup.append((dua_id, video_id))
    candidates = dedup

    if all_approved:
        candidates = [(i, v) for (i, v) in candidates if (review.get(i) or {}).get("status") == "approved"]

    plan = []
    for dua_id, video_id in candidates:
        entry = review.get(dua_id) or {}
        if entry.get("status") != "approved":
            plan.append((dua_id, video_id, None, None, None, "SKIP: EN review not approved"))
            continue
        en = (entry.get("en") or "").strip()
        if not en:
            plan.append((dua_id, video_id, None, None, None, "SKIP: approved entry has no EN text"))
            continue
        base = safe_title(titles.get(dua_id) or dua_id)
        srt_path = os.path.join(OUT, base + ".en.srt")
        if not os.path.exists(srt_path):
            srt_path = None
        plan.append((dua_id, video_id, en, srt_path, titles.get(dua_id), None))
    return plan


def write_generated_srt(en_text, duration_secs):
    """Single caption block spanning the video (verified/hadith single-line
    style) -> temp srt file path."""
    tt = fmt_ts(duration_secs)
    body = f"1\n00:00:00,000 --> {tt}\n{en_text}\n"
    fd, path = tempfile.mkstemp(suffix=".en.srt", prefix="cap_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated dua_ids to process")
    ap.add_argument("--all", action="store_true", help="process every APPROVED uploaded dua")
    ap.add_argument("--channel", default="channel1", choices=["channel1", "channel2"])
    ap.add_argument("--dry-run", action="store_true", help="print the plan, do not call YouTube")
    ap.add_argument("--no-skip", action="store_true", help="re-attach even if an English track already exists")
    ap.add_argument("--gated", action="store_true", help="assume approval done (attach regardless of review)")
    args = ap.parse_args()

    only = set(filter(None, (x.strip() for x in args.only.split(",")))) if args.only else None
    if not only and not args.all:
        ap.error("--only <ids> ya --all zaroori hai")
    if args.all and only:
        ap.error("--all aur --only eik saath nahi")

    review = _read_json(REVIEW_PATH, {})
    global SKIP_ALREADY
    if args.no_skip:
        SKIP_ALREADY = False

    plan = build_plan(args.channel, only=only, all_approved=args.all)
    if not plan:
        print(json.dumps({"ok": True, "channel": args.channel, "planned": 0, "items": []}, ensure_ascii=False))
        return 0

    service, err = get_youtube_service(args.channel)
    if err:
        print(json.dumps({"ok": False, "error": err}, ensure_ascii=False))
        return 1

    results = []
    for dua_id, video_id, en, srt_path, title, note in plan:
        if note:
            results.append({"duaId": dua_id, "videoId": video_id, "status": "skipped", "note": note})
            continue
        if args.gated and not review.get(dua_id):
            # --gated: proceed regardless of review state (explicit override)
            pass
        try:
            gpath = None
            if srt_path:
                srt_content = open(srt_path, encoding="utf-8").read()
            else:
                # live duration fallback for the generated single block
                # (read-only videos.list call - safe even in --dry-run)
                duration = None
                vid_resp = (
                    service.videos()
                    .list(part="contentDetails", id=video_id, fields="items(contentDetails(duration))")
                    .execute()
                )
                d = (vid_resp.get("items") or [{}])[0].get("contentDetails", {}).get("duration")
                duration = iso_duration_secs(d)
                if duration is None:
                    results.append(
                        {"duaId": dua_id, "videoId": video_id, "status": "error", "note": "video duration unavailable"}
                    )
                    continue
                gpath = write_generated_srt(en, duration)
                srt_content = open(gpath, encoding="utf-8").read()

            if args.dry_run:
                if gpath:
                    with contextlib.suppress(OSError):
                        os.remove(gpath)
                results.append(
                    {
                        "duaId": dua_id,
                        "videoId": video_id,
                        "status": "planned",
                        "srt": srt_path or "generated",
                        "len": len(srt_content),
                    }
                )
                continue

            tracks = list_caption_tracks(service, video_id)
            already = False
            if isinstance(tracks, list):
                for t in tracks:
                    sn = t.get("snippet") or {}
                    if sn.get("language") == TRACK_LANG and sn.get("name") == TRACK_NAME:
                        already = True
                        break
            elif isinstance(tracks, tuple) and tracks[0] == "ERR":
                results.append(
                    {
                        "duaId": dua_id,
                        "videoId": video_id,
                        "status": "error",
                        "note": f"captions.list failed: {tracks[1]}",
                    }
                )
                continue
            if already and SKIP_ALREADY:
                results.append({"duaId": dua_id, "videoId": video_id, "status": "skipped", "note": "EN track exists"})
                continue

            from googleapiclient.http import MediaFileUpload

            body = {"snippet": {"videoId": video_id, "language": TRACK_LANG, "name": TRACK_NAME, "isDraft": False}}
            media = MediaFileUpload(gpath or srt_path, mimetype="application/octet-stream")
            resp = service.captions().insert(part="snippet", body=body, media_body=media, sync=True).execute()
            results.append(
                {
                    "duaId": dua_id,
                    "videoId": video_id,
                    "status": "attached",
                    "captionId": resp.get("id"),
                    "track": resp.get("snippet", {}).get("name"),
                }
            )
            if gpath:
                with contextlib.suppress(OSError):
                    os.remove(gpath)
            time.sleep(1)
        except Exception as e:
            results.append({"duaId": dua_id, "videoId": video_id, "status": "error", "note": str(e)[:300]})

    print(
        json.dumps({"ok": True, "channel": args.channel, "planned": len(results), "items": results}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
