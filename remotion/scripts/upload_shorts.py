"""Upload prepared Shorts to YouTube (vertical <=60s videos become Shorts).

Usage:
    python upload_shorts.py --dry-run             # show plan for all prepared
    python upload_shorts.py                        # upload all (privacy: private)
    python upload_shorts.py --privacy public       # upload public
    python upload_shorts.py --only id1,id2         # specific duas
    python upload_shorts.py rozi_ki_dua --dry-run   # one dua (positional)
    python upload_shorts.py --privacy unlisted --dry-run

Idempotent: already-uploaded shorts in state are skipped.

Reliability: 3 attempts with exponential backoff (1s, 2s, 4s) on HTTP 5xx,
HTTP 429 and network errors, mirroring remotion/scripts/upload.py. Every
outcome is also recorded in the cross-platform ledger data/upload_state.json.

Output: JSON on the LAST stdout line.
"""

import argparse
import io
import json
import os
import socket
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SCRIPTS))
STATE_PATH = os.path.join(PROJECT, "data", "shorts_state_channel1.json")
DUAS_PATH = os.path.join(PROJECT, "data", "duas.json")
TOKEN_PATH = os.path.join(PROJECT, "data", "yt_token_channel1.json")
UNIFIED_STATE_PATH = os.path.join(PROJECT, "data", "upload_state.json")

CATEGORY_ID = "22"

MAX_ATTEMPTS = 3
BACKOFF_BASE = 1.0

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

try:
    from social import state as ustate
except ImportError:  # package missing -- degrade to channel-only tracking
    ustate = None


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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


def get_service():
    sys.path.insert(0, SCRIPTS)
    import youtube_auth

    youtube_auth.set_token_path(os.path.abspath(TOKEN_PATH))
    cred = youtube_auth.get_credentials()
    if not cred:
        return None
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=cred)


def build_meta(dua, rot, fallback=None):
    from metadata import build_description, build_tags

    title = dua.get("title") or (fallback or {}).get("title") or "Dua"
    ref = (dua.get("reference") or (fallback or {}).get("reference") or "").strip()
    full_title = f"{title} | {ref}" if ref else title
    tags = build_tags(dua, rot)
    if "shorts" not in tags:
        tags.insert(0, "shorts")
    desc = build_description(dua, rot, {})
    if "#Shorts" not in desc:
        desc = desc.rstrip() + "\n#Shorts\n"
    return {"title": full_title[:100], "description": desc, "tags": tags}


def _is_retryable(exc):
    """Transient failures worth another attempt: HTTP 5xx, 429, network."""
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        HttpError = ()
    if HttpError and isinstance(exc, HttpError):
        code = getattr(getattr(exc, "resp", None), "status", 0) or 0
        return code >= 500 or code == 429, f"HTTP {code}"
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError)):
        return True, "network timeout"
    if isinstance(exc, OSError):
        return True, f"network: {str(exc)[:80]}"
    return False, type(exc).__name__


def _upload_once(service, body, media_path, progress=False):
    """One full resumable upload. The request is rebuilt every attempt because
    MediaFileUpload holds a consumed byte stream once next_chunk has run."""
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(media_path, chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress:
            print("  progress: %d%%" % int(status.progress() * 100), file=sys.stderr)
    return response


def mirror_upload(service, body, media, progress=False, max_attempts=MAX_ATTEMPTS, backoff_base=BACKOFF_BASE):
    """Resumable upload with bounded exponential backoff.

    ``media`` may be a path (retried) or a prebuilt MediaFileUpload
    (single attempt -- its stream cannot be rewound).
    """
    if not isinstance(media, str):
        media_obj, path = media, None
    else:
        media_obj, path = None, media

    if path is not None and not os.path.isfile(path):
        raise FileNotFoundError("video file not found: {}".format(path))

    attempts, last = 0, None
    while True:
        try:
            if path is not None:
                return _upload_once(service, body, path, progress)
            return _upload_once_obj(service, body, media_obj, progress)
        except Exception as exc:
            retryable, why = _is_retryable(exc)
            if not retryable or attempts >= max_attempts - 1:
                if retryable:
                    print("  giving up after %d attempt(s): %s" % (attempts + 1, why), file=sys.stderr)
                raise
            attempts += 1
            wait = backoff_base * (2 ** (attempts - 1))
            print("  retry %d/%d in %.1fs (%s)" % (attempts, max_attempts, wait, why), file=sys.stderr)
            time.sleep(wait)


def _upload_once_obj(service, body, media_obj, progress=False):
    request = service.videos().insert(part="snippet,status", body=body, media_body=media_obj)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress:
            print("  progress: %d%%" % int(status.progress() * 100), file=sys.stderr)
    return response


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dua_id", nargs="?", default=None, help="single dua id (alias for --only)")
    ap.add_argument("--only", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--privacy", default="private", choices=["public", "unlisted", "private"])
    ap.add_argument(
        "--max-attempts", type=int, default=MAX_ATTEMPTS, help="upload attempts before giving up (default 3)"
    )
    ap.add_argument(
        "--backoff-base", type=float, default=BACKOFF_BASE, help="first backoff in seconds; doubles (default 1.0)"
    )
    ap.add_argument("--no-unified-state", action="store_true", help="skip writing data/upload_state.json")
    args = ap.parse_args()

    only = args.only
    if args.dua_id:
        only = args.dua_id if not only else only + "," + args.dua_id

    state = load_state()
    prepared = {k: v for k, v in state.items() if v.get("shortHref")}
    if only:
        want = [x.strip() for x in only.split(",") if x.strip()]
        prepared = {k: v for k, v in prepared.items() if k in want}
        if not prepared:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "total": 0,
                        "error": "no prepared short found for: {}".format(",".join(want)),
                        "prepared_count": len({k: v for k, v in load_state().items() if v.get("shortHref")}),
                    },
                    ensure_ascii=False,
                )
            )
            return 1

    duas = load_json(DUAS_PATH)
    if not isinstance(duas, list):
        duas = duas.get("duas", [])
    dua_map = {d.get("id"): d for d in duas if d.get("id")}

    order = sorted(prepared)
    plan = []
    for did in order:
        entry = prepared[did]
        dua = dua_map.get(did) or {}
        from metadata import Rot

        rot = Rot(did)
        meta = build_meta(dua, rot, entry)
        media_path = entry["shortHref"]
        plan.append(
            {
                "duaId": did,
                "title": meta["title"],
                "file": media_path,
                "fileExists": os.path.isfile(media_path),
                "sizeMB": (round(os.path.getsize(media_path) / 1048576.0, 2) if os.path.isfile(media_path) else None),
                "dur": entry.get("duration"),
                "privacy": args.privacy,
                "alreadyUploaded": bool(entry.get("video_id")),
            }
        )

    if args.dry_run:
        print(json.dumps({"ok": True, "dryRun": True, "total": len(plan), "items": plan}, ensure_ascii=False))
        return 0

    to_upload = [p for p in plan if not p["alreadyUploaded"]]
    if not to_upload:
        print(
            json.dumps(
                {"ok": True, "uploaded": 0, "skipped": len(plan), "note": "sab pehle se uploaded hain"},
                ensure_ascii=False,
            )
        )
        return 0

    service = get_service()
    if service is None:
        print(json.dumps({"ok": False, "error": "auth failed"}, ensure_ascii=False))
        return 1

    results = []
    track = ustate is not None and not args.no_unified_state
    for p in to_upload:
        did = p["duaId"]
        dua = dua_map.get(did) or {}
        from metadata import Rot

        rot = Rot(did)
        meta = build_meta(dua, rot, prepared[did])
        body = {
            "snippet": {
                "title": meta["title"],
                "description": meta["description"],
                "tags": meta["tags"],
                "categoryId": CATEGORY_ID,
                "defaultLanguage": "en",
            },
            "status": {"privacyStatus": args.privacy, "selfDeclaredMadeForKids": False},
        }
        media_path = prepared[did]["shortHref"]
        if track:
            ustate.mark_uploading(did, "youtube", video_path=media_path)
        try:
            if not os.path.isfile(media_path):
                raise FileNotFoundError("video file not found: {}".format(media_path))
            resp = mirror_upload(
                service, body, media_path, max_attempts=max(1, args.max_attempts), backoff_base=args.backoff_base
            )
            vid = resp.get("id")
            if not vid:
                raise RuntimeError("upload returned no video id")
            url = "https://youtube.com/shorts/" + vid
            state[did]["video_id"] = vid
            state[did]["privacy"] = args.privacy
            state[did]["uploaded_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
            save_state(state)
            if track:
                ustate.mark_uploaded(did, "youtube", url=url, platform_id=vid, video_path=media_path)
            results.append({"duaId": did, "status": "uploaded", "videoId": vid, "url": url})
        except Exception as e:
            note = str(e)[:300]
            if track:
                ustate.mark_failed(did, "youtube", note, video_path=media_path)
            results.append({"duaId": did, "status": "error", "note": note})
    ok = [r for r in results if r["status"] == "uploaded"]
    print(
        json.dumps(
            {"ok": ok or not results, "uploaded": len(ok), "total": len(to_upload), "items": results},
            ensure_ascii=False,
        )
    )
    return 0 if len(ok) == len(to_upload) else 2


if __name__ == "__main__":
    raise SystemExit(main())
