"""Facebook Page Reels upload via the Graph API (resumable).

Wire protocol
-------------
1. POST /{page_id}/video_reels?upload_phase=start&access_token=...
   -> { video_id, upload_url }
2. PUT the MP4 bytes to upload_url (single PUT is accepted for files under
   the resumable threshold; chunked with Content-Range otherwise).
3. POST /{page_id}/video_reels?upload_phase=finish&video_id=...&description=...
   -> { id, success }

Duration note
-------------
Facebook Reels cap at 90 seconds. Rather than silently shipping a truncated
clip, ``trim_for_platform`` cuts the render to exactly 90s with ffmpeg and
records that fact in the ledger. Pass ``--no-trim`` to fail instead.

Prerequisites (see AUTH_SETUP.md)
---------------------------------
* A Facebook Page with publishing rights.
* A Meta app with ``pages_manage_posts``, ``pages_read_engagement``,
  ``pages_show_list`` reviewed.
* ``data/facebook_tokens.json`` with a Page access token and the numeric
  page_id. Page tokens do not expire while the user token behind them lives,
  but they do die if the user revokes the app.

Usage
-----
    python facebook_upload.py rozi_ki_dua --dry-run
    python facebook_upload.py rozi_ki_dua
    python facebook_upload.py rozi_ki_dua --no-trim
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# `social` (the state package) lives one directory up, while `common` and
# `captions` live beside this file. Both roots are needed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from captions import build_caption  # noqa: E402
from common import (
    CAPTION_LIMITS,
    CHUNK_BYTES,
    UploadError,
    chunked_put,  # noqa: E402
    emit,
    format_caption,
    load_tokens,
    log,
    probe_duration,
    resolve_video,
    retry_call,
    trim_for_platform,
)

from social import state as ustate  # noqa: E402

PLATFORM = "facebook"
GRAPH = "https://graph.facebook.com"
API_VERSION = "v26.0"
REEL_MAX_SECONDS = 90


def _request(url: str, data=None, method="GET", headers=None, timeout=300):
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {"_raw": raw[:500]}
            return body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise UploadError(f"HTTP {exc.code} from {url.split('?')[0]}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise UploadError(f"network failure: {exc.reason}") from exc


def start_upload(page_id: str, token: str, api_version: str = "") -> tuple:
    """Step 1: open a resumable upload session."""
    url = f"{GRAPH}/{api_version or API_VERSION}/{page_id}/video_reels?" + urllib.parse.urlencode(
        {"upload_phase": "start", "access_token": token}
    )
    data = _request(url, method="POST")
    if "error" in data:
        raise UploadError(f"start rejected: {json.dumps(data)[:400]}")
    video_id = data.get("video_id")
    upload_url = data.get("upload_url")
    if not video_id or not upload_url:
        raise UploadError(f"start response incomplete: {json.dumps(data)[:300]}")
    return video_id, upload_url


def send_bytes(upload_url: str, video_path: str) -> None:
    """Step 2: upload the file body."""
    size = os.path.getsize(video_path)
    if size <= CHUNK_BYTES:
        with open(video_path, "rb") as fh:
            payload = fh.read()
        request = urllib.request.Request(upload_url, data=payload, method="PUT")
        request.add_header("Content-Type", "video/mp4")
        request.add_header("Content-Length", str(len(payload)))
        request.add_header("offset", "0")
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                if response.status not in (200, 201, 202, 204):
                    raise UploadError(f"upload rejected: HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            raise UploadError(f"upload HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc
        log(f"uploaded {os.path.basename(video_path)} ({round(size / 1048576.0, 2)} MB)")
        return
    chunked_put(upload_url, video_path, headers={"Content-Type": "video/mp4"})


def finish_upload(page_id: str, token: str, video_id: str, description: str, api_version: str = "") -> str:
    """Step 3: publish. Returns the resulting post id."""
    url = f"{GRAPH}/{api_version or API_VERSION}/{page_id}/video_reels?" + urllib.parse.urlencode(
        {"upload_phase": "finish", "video_id": video_id, "description": description, "access_token": token}
    )
    data = _request(url, method="POST")
    if "error" in data:
        raise UploadError(f"finish rejected: {json.dumps(data)[:400]}")
    post_id = data.get("id") or video_id
    if not post_id:
        raise UploadError(f"finish returned no id: {json.dumps(data)[:300]}")
    return str(post_id)


def upload_one(dua_id: str, kind: str, allow_trim: bool, dry_run: bool) -> dict:
    tokens = load_tokens(PLATFORM, required=("page_access_token", "page_id"), allow_placeholder=dry_run)
    token, page_id = tokens["page_access_token"], str(tokens["page_id"])
    api_version = str(tokens.get("api_version") or API_VERSION)
    video_path = resolve_video(dua_id, kind)
    duration = probe_duration(video_path)
    description = format_caption(build_caption(dua_id, PLATFORM), PLATFORM)

    will_trim = bool(duration and duration > REEL_MAX_SECONDS)
    if will_trim and not allow_trim:
        raise UploadError(
            f"video is {duration:.0f}s, Facebook Reels cap at {REEL_MAX_SECONDS}s "
            f"-- pass --trim to cut it, or --no-trim to fail (current behaviour)"
        )

    if dry_run:
        return {
            "duaId": dua_id,
            "status": "dry_run",
            "file": video_path,
            "sizeMB": round(os.path.getsize(video_path) / 1048576.0, 2),
            "duration": duration,
            "caption_len": len(description),
            "caption_limit": CAPTION_LIMITS[PLATFORM],
            "would_trim_to": REEL_MAX_SECONDS if will_trim else None,
            "page_id": page_id,
            "note": "no network call; credentials not validated",
        }

    ustate.mark_uploading(dua_id, PLATFORM, video_path=video_path)
    try:
        final_path, trimmed = video_path, False
        if will_trim:
            final_path = trim_for_platform(video_path, dua_id, PLATFORM, REEL_MAX_SECONDS)
            trimmed = True
        video_id, upload_url = retry_call("fb start", start_upload, page_id, token, api_version)
        send_bytes(upload_url, final_path)
        post_id = retry_call("fb finish", finish_upload, page_id, token, video_id, description, api_version)
    except Exception as exc:
        ustate.mark_failed(dua_id, PLATFORM, str(exc), video_path=video_path)
        raise
    url = ustate.platform_url(PLATFORM, post_id)
    ustate.mark_uploaded(
        dua_id,
        PLATFORM,
        url=url,
        platform_id=post_id,
        video_path=video_path,
        extra={"trimmed": trimmed, "source_duration": duration, "posted_path": final_path},
    )
    return {
        "duaId": dua_id,
        "status": "uploaded",
        "platform_id": post_id,
        "url": url,
        "trimmed": trimmed,
        "duration": duration,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload a dua as a Facebook Reel.")
    ap.add_argument("dua_id", nargs="?", default=None)
    ap.add_argument("--batch", default=None)
    ap.add_argument("--kind", default="short", choices=["short", "long"])
    ap.add_argument(
        "--trim", dest="allow_trim", action="store_true", help=f"cut to {REEL_MAX_SECONDS}s when the render is longer"
    )
    ap.add_argument("--no-trim", dest="allow_trim", action="store_false", help="fail instead of trimming (default)")
    ap.add_argument("--dry-run", action="store_true")
    ap.set_defaults(allow_trim=False)
    args = ap.parse_args()

    ids = [x.strip() for x in (args.batch or args.dua_id or "").split(",") if x.strip()]
    if not ids:
        return emit({"ok": False, "error": "no dua_id given"}, 1)

    results = []
    for dua_id in ids:
        try:
            results.append(upload_one(dua_id, args.kind, args.allow_trim, args.dry_run))
        except Exception as exc:
            results.append({"duaId": dua_id, "status": "error", "error": str(exc)[:400]})
    ok = [r for r in results if r["status"] in ("uploaded", "dry_run")]
    return emit(
        {
            "ok": len(ok) == len(results),
            "platform": PLATFORM,
            "uploaded": len([r for r in results if r["status"] == "uploaded"]),
            "total": len(results),
            "items": results,
        },
        0 if len(ok) == len(results) else 2,
    )


if __name__ == "__main__":
    raise SystemExit(main())
