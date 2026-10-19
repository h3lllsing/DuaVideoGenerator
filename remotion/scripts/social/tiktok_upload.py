"""TikTok upload via the Content Posting API (direct file upload).

Wire protocol (v2)
------------------
1. POST https://open.tiktokapis.com/v2/post/publish/video/init/
   body: access_token, video_info{sha256,size,chunk_size,duration}, source_info
   -> { data: { publish_id, upload_url } }
2. PUT the raw MP4 bytes to upload_url in chunks (Content-Range headers).
3. Poll POST /v2/post/publish/status/fetch/ until status_code == PUBLISH_COMPLETE.

v1 endpoints (/v1.2/video/publish/, /v1.2/video/publish/) are still accepted by
some apps; ``--api-version v1`` switches to them.

Prerequisites (see AUTH_SETUP.md)
---------------------------------
* TikTok developer app with Content Posting API approved for your audience.
* OAuth code+PKCE login for a TikTok account with video-posting scope.
* ``data/tiktok_tokens.json`` populated with real values.

Usage
-----
    python tiktok_upload.py rozi_ki_dua
    python tiktok_upload.py rozi_ki_dua --dry-run
    python tiktok_upload.py rozi_ki_dua --kind long
    python tiktok_upload.py --batch dua_a,dua_b
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# `social` (the state package) lives one directory up, while `common` and
# `captions` live beside this file. Both roots are needed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from captions import build_caption  # noqa: E402
from common import (
    CAPTION_LIMITS,
    UploadError,
    chunked_put,
    emit,  # noqa: E402
    format_caption,
    load_tokens,
    log,
    probe_duration,
    resolve_video,
    retry_call,
)
from social import state as ustate  # noqa: E402

PLATFORM = "tiktok"
HOST = "https://open.tiktokapis.com"
V2 = {
    "init": "/v2/post/publish/video/init/",
    "status": "/v2/post/publish/status/fetch/",
}
V1 = {
    "init": "/v1.2/video/publish/",
    "status": "/v1.2/video/query/",
}
PRIVACY = {
    "public_to_all": 1,  # SUDO - everyone
    "friends": 2,
    "private": 3,
}


def _post(url: str, payload: dict, headers=None, timeout=90):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json; charset=UTF-8")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise UploadError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise UploadError(f"network failure calling {url}: {exc.reason}") from exc


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def init_upload(video_path: str, caption: str, access_token: str, privacy: str, api_version: str) -> tuple:
    """Step 1: open a publish session and get the upload_url."""
    size = os.path.getsize(video_path)
    duration = int(probe_duration(video_path) or 0)
    if duration <= 0:
        raise UploadError("could not read video duration -- TikTok requires it in video_info")
    chunk = 8 * 1024 * 1024
    if api_version == "v2":
        payload = {
            "access_token": access_token,
            "video_info": {
                "chunk_size": chunk,
                "size": size,
                "duration": int(duration),
                "sha256": file_sha256(video_path),
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk,
                "total_chunk_count": (size + chunk - 1) // chunk,
            },
            "post_info": {
                "title": caption,
                "privacy_level": PRIVACY[privacy],
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
        }
    else:
        payload = {
            "access_token": access_token,
            "video": {"chunk_size": chunk, "size": size, "duration": int(duration), "sha256": file_sha256(video_path)},
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk,
                "total_chunk_count": (size + chunk - 1) // chunk,
            },
            "post_info": {"title": caption, "privacy_level": PRIVACY[privacy]},
        }
    response = _post(HOST + V2["init"] if api_version == "v2" else HOST + V1["init"], payload)
    if response.get("code", 0) != 0 or "error" in str(response.get("message", "")).lower():
        raise UploadError(f"init rejected: {json.dumps(response)[:400]}")
    data = response.get("data") or response
    publish_id = data.get("publish_id")
    upload_url = data.get("upload_url")
    if not publish_id or not upload_url:
        raise UploadError(f"init response missing publish_id/upload_url: {json.dumps(response)[:300]}")
    return publish_id, upload_url


def upload_bytes(upload_url: str, video_path: str) -> None:
    """Step 2: stream the file. TikTok accepts a single PUT for file uploads."""
    chunked_put(upload_url, video_path, headers={"Content-Type": "video/mp4"})


def fetch_status(publish_id: str, access_token: str, api_version: str, attempts=6, delay=10) -> str:
    """Step 3: confirm publication. TikTok processes asynchronously."""
    url = HOST + (V2["status"] if api_version == "v2" else V1["status"])
    for attempt in range(1, attempts + 1):
        payload = {"access_token": access_token, "publish_id": publish_id}
        if api_version == "v1":
            payload = {"access_token": access_token, "publish_id": publish_id}
        response = _post(url, payload)
        data = response.get("data") or {}
        status = data.get("status") or data.get("status_code")
        log(f"tiktok status check {attempt}/{attempts}: {status}")
        if status in ("PUBLISH_COMPLETE", "PUBLISH_COMPLETE ", "COMPLETE"):
            return publish_id
        if status in ("FAILED", "PUBLISH_FAILED") or data.get("fail_reason"):
            raise UploadError(f"publish failed: {data.get('fail_reason') or status}")
        if attempt < attempts:
            time.sleep(delay)
    log(f"status still {status} after {attempts} checks -- treat as in-flight, re-run later to confirm", err=True)
    return publish_id


def upload_one(dua_id: str, kind: str, privacy: str, api_version: str, dry_run: bool) -> dict:
    tokens = load_tokens(PLATFORM, required=("access_token",), allow_placeholder=dry_run)
    access_token = tokens["access_token"]
    video_path = resolve_video(dua_id, kind)
    duration = probe_duration(video_path)
    caption = format_caption(build_caption(dua_id, PLATFORM), PLATFORM)

    if dry_run:
        return {
            "duaId": dua_id,
            "status": "dry_run",
            "file": video_path,
            "sizeMB": round(os.path.getsize(video_path) / 1048576.0, 2),
            "duration": duration,
            "caption_len": len(caption),
            "caption_limit": CAPTION_LIMITS[PLATFORM],
            "privacy": privacy,
            "api_version": api_version,
            "note": "no network call; credentials not validated",
        }

    ustate.mark_uploading(dua_id, PLATFORM, video_path=video_path)
    try:
        publish_id, upload_url = retry_call(
            "tiktok init", init_upload, video_path, caption, access_token, privacy, api_version
        )
        upload_bytes(upload_url, video_path)
        publish_id = retry_call("tiktok status", fetch_status, publish_id, access_token, api_version)
    except Exception as exc:
        ustate.mark_failed(dua_id, PLATFORM, str(exc), video_path=video_path)
        raise
    url = ustate.platform_url(PLATFORM, publish_id)
    ustate.mark_uploaded(dua_id, PLATFORM, url=url, platform_id=publish_id, video_path=video_path)
    return {
        "duaId": dua_id,
        "status": "uploaded",
        "platform_id": publish_id,
        "url": url,
        "file": video_path,
        "duration": duration,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload a dua to TikTok.")
    ap.add_argument("dua_id", nargs="?", default=None)
    ap.add_argument("--batch", default=None, help="comma-separated dua ids")
    ap.add_argument("--kind", default="short", choices=["short", "long"])
    ap.add_argument("--privacy", default="public_to_all", choices=sorted(PRIVACY))
    ap.add_argument("--api-version", default="v2", choices=["v1", "v2"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ids = [x.strip() for x in (args.batch or args.dua_id or "").split(",") if x.strip()]
    if not ids:
        return emit({"ok": False, "error": "no dua_id given"}, 1)

    results = []
    for dua_id in ids:
        try:
            results.append(upload_one(dua_id, args.kind, args.privacy, args.api_version, args.dry_run))
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
