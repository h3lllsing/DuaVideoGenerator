"""Instagram Reels upload via the Instagram Graph API.

Wire protocol (local file, no public URL needed)
-----------------------------------------------
1. POST /{ig-user-id}/media          -- media_type=REELS, video=<binary>,
                                       transfer_encoding=resumable
   -> Location header (upload URL) + Instagram-Content-Length (resume offset)
2. PUT  <upload URL>                 -- remaining bytes, Content-Type:
                                       application/octet-stream
3. GET  /{container_id}?fields=status_code
   -> poll until status_code == "FINISHED" (processing is async, minutes)
4. POST /{ig-user-id}/media_publish  -- creation_id={container_id}

``video_url`` is avoided deliberately: that variant requires the asset to be
publicly fetchable, which a local render is not.

Prerequisites (see AUTH_SETUP.md)
---------------------------------
* Instagram Professional (Business or Creator) account.
* That account linked to a Facebook Page.
* A Meta app with ``instagram_basic``, ``instagram_content_publish``,
  ``pages_show_list``, ``pages_read_engagement`` permissions, reviewed.
* ``data/instagram_tokens.json`` with a non-expiring Page access token and the
  numeric ig_user_id.

Usage
-----
    python instagram_upload.py rozi_ki_dua --dry-run
    python instagram_upload.py rozi_ki_dua
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# `social` (the state package) lives one directory up, while `common` and
# `captions` live beside this file. Both roots are needed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from captions import build_caption                       # noqa: E402
from common import (CAPTION_LIMITS, UploadError, emit,    # noqa: E402
                    format_caption, load_tokens, log, probe_duration,
                    resolve_video, retry_call)
from social import state as ustate                       # noqa: E402

PLATFORM = "instagram"
GRAPH = "https://graph.instagram.com"
API_VERSION = "v21.0"
MAX_DURATION = 900        # 15 min, Instagram Reels ceiling
POLL_ATTEMPTS = 30
POLL_DELAY = 20


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
            return response.status, dict(response.headers), body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise UploadError(f"HTTP {exc.code} from {url.split('?')[0]}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise UploadError(f"network failure: {exc.reason}") from exc


def create_container(video_path: str, caption: str, ig_user_id: str,
                     token: str) -> str:
    """Step 1+2: resumable binary upload, returns the container id."""
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as fh:
        payload = fh.read()
    url = (f"{GRAPH}/{API_VERSION}/{ig_user_id}/media")
    fields = {
        "media_type": "REELS",
        "transfer_encoding": "resumable",
        "access_token": token,
    }
    body = "&".join(f"{k}={urllib.request.quote(str(v), safe='')}"
                    for k, v in fields.items())
    url = f"{url}?{body}"
    status, headers, parsed = _request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/octet-stream",
                 "Content-Length": str(len(payload)),
                 "Overshoot-Clone": "1"})
    if "error" in parsed:
        raise UploadError(f"container rejected: {json.dumps(parsed)[:400]}")
    container_id = parsed.get("id")
    upload_url = headers.get("Location") or headers.get("location")
    offset = headers.get("Instagram-Content-Length") or headers.get(
        "instagram-content-length") or 0
    if not container_id:
        raise UploadError(f"no container id returned: {json.dumps(parsed)[:300]}")
    if not upload_url:
        log("no upload Location returned; container accepted whole payload",
            err=True)
        return container_id
    offset = int(offset)
    if offset < size:
        log(f"resuming upload at byte {offset}/{size}")
        with open(video_path, "rb") as fh:
            fh.seek(offset)
            remaining = fh.read()
        _request(upload_url, data=remaining, method="PUT",
                 headers={"Content-Type": "application/octet-stream",
                          "Content-Length": str(len(remaining)),
                          "offset": str(offset)}, timeout=600)
    return container_id


def await_finished(container_id: str, token: str,
                   attempts=POLL_ATTEMPTS, delay=POLL_DELAY) -> str:
    """Step 3: Instagram transcodes asynchronously; poll until FINISHED."""
    url = (f"{GRAPH}/{API_VERSION}/{container_id}"
           f"?fields=status_code,status&access_token={urllib.request.quote(token)}")
    for attempt in range(1, attempts + 1):
        _, _, data = _request(url)
        code = data.get("status_code")
        detail = data.get("status")
        log(f"ig container {attempt}/{attempts}: {code} {detail or ''}")
        if code == "FINISHED":
            return container_id
        if code in ("ERROR", "EXPIRED", "REJECTED"):
            raise UploadError(f"container processing failed: {code} {detail}")
        if attempt < attempts:
            time.sleep(delay)
    raise UploadError(f"container still {code} after {attempts} checks "
                      f"({attempts * delay // 60} min) -- re-run with --retry to "
                      f"resume without re-uploading")


def publish_container(container_id: str, ig_user_id: str, token: str) -> str:
    """Step 4: make the processed container live. Returns the media id."""
    url = (f"{GRAPH}/{API_VERSION}/{ig_user_id}/media_publish")
    body = urllib.parse.urlencode({"creation_id": container_id,
                                   "access_token": token}).encode()
    _, _, data = _request(url, data=body, method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    if "error" in data:
        raise UploadError(f"media_publish rejected: {json.dumps(data)[:400]}")
    media_id = data.get("id")
    if not media_id:
        raise UploadError(f"media_publish returned no id: {json.dumps(data)[:300]}")
    return media_id


def upload_one(dua_id: str, kind: str, dry_run: bool) -> dict:
    tokens = load_tokens(PLATFORM, required=("page_access_token", "ig_user_id"),
                         allow_placeholder=dry_run)
    token, ig_user_id = tokens["page_access_token"], str(tokens["ig_user_id"])
    video_path = resolve_video(dua_id, kind)
    duration = probe_duration(video_path)
    caption = format_caption(build_caption(dua_id, PLATFORM), PLATFORM)

    if duration and duration > MAX_DURATION:
        raise UploadError(
            f"video is {duration:.0f}s, Instagram Reels caps at {MAX_DURATION}s "
            f"-- re-render shorter rather than trimming (no silent trim for IG)")

    if dry_run:
        return {"duaId": dua_id, "status": "dry_run", "file": video_path,
                "sizeMB": round(os.path.getsize(video_path) / 1048576.0, 2),
                "duration": duration, "caption_len": len(caption),
                "caption_limit": CAPTION_LIMITS[PLATFORM],
                "ig_user_id": ig_user_id,
                "note": "no network call; credentials not validated"}

    ustate.mark_uploading(dua_id, PLATFORM, video_path=video_path)
    try:
        container_id = retry_call("ig container", create_container, video_path,
                                  caption, ig_user_id, token)
        await_finished(container_id, token)
        media_id = retry_call("ig publish", publish_container, container_id,
                              ig_user_id, token)
    except Exception as exc:
        ustate.mark_failed(dua_id, PLATFORM, str(exc), video_path=video_path)
        raise
    url = ustate.platform_url(PLATFORM, media_id)
    ustate.mark_uploaded(dua_id, PLATFORM, url=url, platform_id=media_id,
                         video_path=video_path, extra={"container_id": container_id})
    return {"duaId": dua_id, "status": "uploaded", "platform_id": media_id,
            "url": url, "container_id": container_id, "duration": duration}


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload a dua as an Instagram Reel.")
    ap.add_argument("dua_id", nargs="?", default=None)
    ap.add_argument("--batch", default=None)
    ap.add_argument("--kind", default="short", choices=["short", "long"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ids = [x.strip() for x in (args.batch or args.dua_id or "").split(",")
           if x.strip()]
    if not ids:
        return emit({"ok": False, "error": "no dua_id given"}, 1)

    results = []
    for dua_id in ids:
        try:
            results.append(upload_one(dua_id, args.kind, args.dry_run))
        except Exception as exc:
            results.append({"duaId": dua_id, "status": "error",
                            "error": str(exc)[:400]})
    ok = [r for r in results if r["status"] in ("uploaded", "dry_run")]
    return emit({"ok": len(ok) == len(results), "platform": PLATFORM,
                 "uploaded": len([r for r in results if r["status"] == "uploaded"]),
                 "total": len(results), "items": results},
                0 if len(ok) == len(results) else 2)


if __name__ == "__main__":
    raise SystemExit(main())
