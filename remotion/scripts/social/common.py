"""Shared plumbing for the Phase 2 platform uploaders.

Every platform script is a thin adapter over this module: resolve the file,
read the caption, probe the duration, validate the token, retry, then hand the
bytes to the platform's own wire protocol. Keeping this in one place is what
stops ``load_state``/``load_json``/retry logic from being copy-pasted a third,
fourth and fifth time.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPTS_DIR))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SHARE_KIT = os.path.join(PROJECT_ROOT, "share_kit")
LONG_OUT = os.path.join(PROJECT_ROOT, "remotion", "out")
SHORT_OUT = os.path.join(PROJECT_ROOT, "remotion", "shorts", "out")
TRIM_DIR = os.path.join(PROJECT_ROOT, "remotion", "out", "_platform_trim")

FFMPEG_CANDIDATES = (
    r"C:\Program Files\iGoWeb\Video2Master\tools\ffmpeg.exe",
    os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget"
        r"_Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe",
    ),
    r"C:\ffmpeg\bin\ffmpeg.exe",
)
CHUNK_BYTES = 8 * 1024 * 1024
MAX_ATTEMPTS = 3
BACKOFF_BASE = 1.0

_BINARIES = {}


def _resolve_binary(name: str):
    """Find ffmpeg/ffprobe without trusting a single hardcoded path.

    Order: explicit env var -> PATH -> imageio's bundled copy -> known install
    locations. Returns None when absent; callers raise a clear error.
    """
    if name in _BINARIES:
        return _BINARIES[name]
    found = None
    env_key = f"DUAVID_{name.upper()}"
    candidate = os.environ.get(env_key)
    if candidate and os.path.isfile(candidate):
        found = candidate
    if not found:
        import shutil

        which = shutil.which(name)
        if which:
            found = which
    if not found and name == "ffmpeg":
        try:
            import imageio_ffmpeg

            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and os.path.isfile(exe):
                found = exe
        except Exception:
            pass
    if not found:
        for path in FFMPEG_CANDIDATES:
            exe = os.path.join(os.path.dirname(path), name + ".exe")
            if os.path.isfile(exe):
                found = exe
                break
    if found and not os.path.isfile(found):
        found = None
    _BINARIES[name] = found
    return found


def ffmpeg_path() -> str:
    return _resolve_binary("ffmpeg")


def ffprobe_path() -> str:
    return _resolve_binary("ffprobe")


# Caption ceilings. Kept in one table so the UI and every uploader agree.
CAPTION_LIMITS = {
    "youtube_long": 5000,
    "youtube_short": 5000,
    "tiktok": 2200,
    "instagram": 2200,
    "facebook": 63206,
}


class UploadError(Exception):
    """Raised for a failure the caller should record and surface."""


def log(message: str, *, err: bool = False) -> None:
    print(("  [err] " if err else "  ") + message, file=sys.stderr if err else sys.stdout, flush=True)


def load_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        if default is not None:
            return default
        raise UploadError(f"file not found: {path}")
    except json.JSONDecodeError as exc:
        raise UploadError(f"invalid JSON in {path}: {exc}")


_TITLE_CACHE = {}


def title_for(dua_id: str):
    """Catalog title for a dua, or None.

    Cached per process: the catalog is read once, not once per upload.
    """
    if dua_id in _TITLE_CACHE:
        return _TITLE_CACHE[dua_id]
    if not _TITLE_CACHE:
        try:
            for dua in load_json(os.path.join(DATA_DIR, "duas.json"), []) or []:
                if isinstance(dua, dict) and dua.get("id"):
                    _TITLE_CACHE[dua["id"]] = (dua.get("title") or "").strip() or None
        except Exception:
            pass
        _TITLE_CACHE.setdefault(dua_id, None)
    return _TITLE_CACHE.get(dua_id)


def resolve_video(dua_id: str, kind: str = "short", require_short: bool = False) -> str:
    """Locate the rendered MP4 for a dua.

    ``kind='short'`` prefers the vertical export, ``kind='long'`` the full
    render. The two directories do **not** share a naming convention:
    shorts are ``{dua_id}.short.mp4`` while long renders are the catalog
    title (``Sabr Ka Ajr Ki Dua.mp4``), so both spellings are tried. Raises
    with the searched paths when nothing matches, so the caller never reaches
    the network with a missing file.
    """
    if not dua_id or os.sep in dua_id or (os.altsep and os.altsep in dua_id):
        raise UploadError(f"invalid dua_id: {dua_id!r}")
    title = title_for(dua_id)
    candidates = []
    if kind == "short":
        candidates += [os.path.join(SHORT_OUT, f"{dua_id}.short.mp4"), os.path.join(SHORT_OUT, f"{dua_id}.mp4")]
    if kind == "long" or not require_short:
        if title:
            candidates += [os.path.join(LONG_OUT, f"{title}.mp4")]
        candidates += [os.path.join(LONG_OUT, f"{dua_id}.mp4"), os.path.join(LONG_OUT, f"{dua_id}.long.mp4")]
    for path in candidates:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    raise UploadError(
        "no rendered video for '%s' (looked in: %s)"
        % (dua_id, ", ".join(os.path.relpath(c, PROJECT_ROOT) for c in candidates))
    )


def probe_duration(path: str):
    """Duration in seconds via ffprobe, or None when unavailable."""
    probe = ffprobe_path()
    if not probe:
        log("ffprobe not found; cannot read durations", err=True)
        return None
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return round(float(json.loads(out.stdout)["format"]["duration"]), 2)
    except (subprocess.SubprocessError, ValueError, KeyError, OSError) as exc:
        log(f"ffprobe could not read duration of {os.path.basename(path)}: {exc}", err=True)
        return None


def load_caption(dua_id: str) -> str:
    """Read share_kit/<dua_id>.txt, else fall back to the catalog title."""
    path = os.path.join(SHARE_KIT, f"{dua_id}.txt")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        title = None
        for dua in load_json(os.path.join(DATA_DIR, "duas.json"), []) or []:
            if isinstance(dua, dict) and dua.get("id") == dua_id:
                title = dua.get("title")
                break
        return (title or dua_id).strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise UploadError(f"unreadable caption file {path}: {exc}")


def format_caption(text: str, platform: str) -> str:
    """Trim to the platform limit on a line boundary, preserving hashtags.

    The trailing hashtag block is kept intact when possible because it is the
    discovery mechanism on TikTok/Reels; a hard cut would orphan them.
    """
    limit = CAPTION_LIMITS.get(platform)
    if not limit or not text:
        return text
    if len(text) <= limit:
        return text
    body, _, tags = text.rpartition("\n")
    if tags.startswith("#") and body and len(body) + 1 + len(tags) <= limit:
        return text
    if tags.startswith("#") and len(tags) < limit:
        room = limit - len(tags) - 1
        head = body[:room] if body else text[:room]
        head = head[: head.rfind("\n") + 1] or head
        return (head + tags)[:limit]
    return text[:limit].rsplit("\n", 1)[0]


def load_tokens(platform: str, required=(), allow_placeholder: bool = False) -> dict:
    """Load and validate a credential file for a platform.

    ``allow_placeholder=True`` downgrades the placeholder guard to a warning so
    ``--dry-run`` still produces a useful plan before you have credentials.
    A real upload always passes False and hard-fails on placeholders.
    """
    path = os.path.join(DATA_DIR, f"{platform}_tokens.json")
    if not os.path.isfile(path):
        raise UploadError(
            f"missing {os.path.basename(path)} -- see remotion/scripts/social/AUTH_SETUP.md for how to create it"
        )
    data = load_json(path, {})
    if not isinstance(data, dict):
        raise UploadError(f"{os.path.basename(path)} must contain a JSON object")
    if data.get("_placeholder"):
        message = (
            f"{os.path.basename(path)} still holds PLACEHOLDER values -- "
            f"replace them with real credentials (see AUTH_SETUP.md)"
        )
        if not allow_placeholder:
            raise UploadError(message)
        log("WARNING: " + message, err=True)
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise UploadError(f"{os.path.basename(path)} missing required field(s): {', '.join(missing)}")
    return data


def trim_for_platform(src: str, dua_id: str, platform: str, seconds: float) -> str:
    """Return a copy of ``src`` cut to ``seconds``.

    Used only where a platform's hard cap is below our render length (Facebook
    Reels). Raises rather than uploading a partial file if ffmpeg fails.
    """
    os.makedirs(TRIM_DIR, exist_ok=True)
    dst = os.path.join(TRIM_DIR, f"{dua_id}_{platform}_trimmed.mp4")
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise UploadError(f"ffmpeg not found (set DUAVID_FFMPEG to the full path) -- cannot trim for {platform}")
    if os.path.isfile(dst) and probe_duration(dst) and probe_duration(dst) <= seconds + 1:
        return dst
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        src,
        "-t",
        str(seconds),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        dst,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(dst):
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise UploadError(f"ffmpeg trim failed for {platform}: {' | '.join(tail)}")
    log(f"trimmed {os.path.basename(src)} -> {os.path.basename(dst)} (cap {seconds:.0f}s)")
    return dst


def chunked_put(url: str, path: str, headers=None, chunk=CHUNK_BYTES, progress: bool = True) -> None:
    """PUT a file to ``url`` in chunks. Used by the resumable protocols."""
    import urllib.request

    size = os.path.getsize(path)
    sent = 0
    with open(path, "rb") as fh:
        while sent < size:
            blob = fh.read(chunk)
            if not blob:
                break
            request = urllib.request.Request(url, data=blob, method="PUT")
            for key, value in (headers or {}).items():
                request.add_header(key, value)
            request.add_header("Content-Length", str(len(blob)))
            request.add_header("Content-Range", f"bytes {sent}-{sent + len(blob) - 1}/{size}")
            with urllib.request.urlopen(request, timeout=300) as response:
                if response.status not in (200, 201, 202, 204):
                    raise UploadError(f"chunk PUT rejected: HTTP {response.status}")
            sent += len(blob)
            if progress:
                pct = int(sent * 100 / size) if size else 100
                print(f"\r  uploading {pct:3d}%", end="", file=sys.stderr, flush=True)
    if progress:
        print(file=sys.stderr)


def retry_call(
    label: str, fn, *args, max_attempts=MAX_ATTEMPTS, backoff_base=BACKOFF_BASE, retry_on=(UploadError,), **kwargs
):
    """Call ``fn`` with bounded exponential backoff.

    Reuses :func:`upload_shorts._is_retryable` semantics by treating an
    :class:`UploadError` as transient only when it says so via ``transient``.
    """
    attempts = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            transient = isinstance(exc, retry_on) or _looks_transient(exc)
            if not transient or attempts >= max_attempts - 1:
                raise
            attempts += 1
            wait = backoff_base * (2 ** (attempts - 1))
            log(f"{label}: retry {attempts}/{max_attempts} in {wait:.1f}s ({str(exc)[:90]})", err=True)
            time.sleep(wait)


def _looks_transient(exc: Exception) -> bool:
    text = str(exc).lower()
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if any(
        k in text
        for k in ("http 5", "http 429", "timeout", "temporarily", "connection reset", "timed out", "try again")
    ):
        return True
    return False


def emit(payload: dict, code: int = 0) -> int:
    """Print the machine-readable result line the API layer parses."""
    print(json.dumps(payload, ensure_ascii=False))
    return code
