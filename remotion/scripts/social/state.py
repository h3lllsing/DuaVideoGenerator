"""Unified, atomic upload-state ledger for all platforms.

Single source of truth for "did this dua go out, where, and did it fail".
Replaces the per-script duplicated ``load_state``/``save_state`` helpers.

Default ledger: ``data/upload_state.json``

Schema
------
{
  "_meta": {
    "schema_version": 1,
    "platforms": ["youtube", "tiktok", "instagram", "facebook"],
    "updated_at": "2026-09-27T10:30:00+00:00"
  },
  "rozi_ki_dua": {
    "youtube": {
      "status": "\u2705",              # UPLOADED  (completed)
      "phase": "completed",           # machine-readable twin of `status`
      "url": "https://youtube.com/shorts/abc",
      "platform_id": "abc",
      "uploaded_at": "2026-09-27T10:30:00+00:00",
      "error": null,
      "retry_count": 0
    }
  }
}

Status model
------------
`status` is the display glyph required by the dashboard spec. `phase` is the
machine-readable value the API and UI should branch on. Both are always written
together, so callers never have to string-match an emoji.

    PENDING    "\u23f3"   not started / queued
    UPLOADING  "\u23f3"   in flight (UI renders a spinner)
    UPLOADED   "\u2705"   terminal success
    FAILED     "\u274c"   terminal failure, retryable

Concurrency
-----------
``atomic_write`` holds a re-entrant in-process lock and writes via
``.tmp`` + ``os.replace`` so a reader can never observe a torn file. That
guarantees per-process safety; ordering *between* concurrent OS processes is
the caller's job (the API layer serialises uploads per dua_id).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone

# --- paths ---------------------------------------------------------------
SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPTS_DIR))
DEFAULT_STATE_PATH = os.path.join(PROJECT_ROOT, "data", "upload_state.json")

# --- status constants ----------------------------------------------------
PENDING = "\u23f3"      # hourglass
UPLOADING = "\u23f3"   # hourglass + spinner in UI
UPLOADED = "\u2705"     # white heavy check mark
FAILED = "\u274c"       # cross mark

PHASE_PENDING = "pending"
PHASE_UPLOADING = "uploading"
PHASE_COMPLETED = "completed"
PHASE_FAILED = "failed"

GLYPH_BY_PHASE = {
    PHASE_PENDING: PENDING,
    PHASE_UPLOADING: UPLOADING,
    PHASE_COMPLETED: UPLOADED,
    PHASE_FAILED: FAILED,
}
# Reverse map. PENDING and UPLOADING deliberately share one glyph, so the
# collision resolves to PENDING: a hand-edited bare hourglass means "not
# started". Callers that mean "in flight" pass phase= explicitly.
PHASE_BY_GLYPH = {}
for _phase, _glyph in GLYPH_BY_PHASE.items():
    PHASE_BY_GLYPH.setdefault(_glyph, _phase)

PLATFORMS = ("youtube", "tiktok", "instagram", "facebook")
SCHEMA_VERSION = 1

# --- internals -----------------------------------------------------------
_LOCK = threading.RLock()
_WRITE_LOCKS: dict = {}


def _now() -> str:
    """UTC ISO-8601 with explicit offset, second precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _blank_state() -> dict:
    return {
        "_meta": {
            "schema_version": SCHEMA_VERSION,
            "platforms": list(PLATFORMS),
            "updated_at": _now(),
        }
    }


def _normalise_state(state) -> dict:
    if not isinstance(state, dict):
        return _blank_state()
    meta = state.setdefault("_meta", {})
    if not isinstance(meta, dict):
        meta = {}
        state["_meta"] = meta
    meta.setdefault("schema_version", SCHEMA_VERSION)
    meta.setdefault("platforms", list(PLATFORMS))
    return state


def _lock_for(path: str) -> threading.RLock:
    with _LOCK:
        lock = _WRITE_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _WRITE_LOCKS[path] = lock
        return lock


def is_terminal(phase: str) -> bool:
    """True when no further transition is expected without a manual retry."""
    return phase in (PHASE_COMPLETED, PHASE_FAILED)


def phase_of(status) -> str:
    """Map a stored ``status`` value to its machine-readable phase.

    Tolerates legacy/plain values ("uploaded", "error") so a hand-edited
    ledger still reads correctly.
    """
    if not status:
        return PHASE_PENDING
    text = str(status).strip()
    if text in PHASE_BY_GLYPH:
        return PHASE_BY_GLYPH[text]
    low = text.lower()
    if low in ("uploaded", "completed", "success", "ok"):
        return PHASE_COMPLETED
    if low in ("error", "failed", "failure"):
        return PHASE_FAILED
    if low in ("uploading", "running", "in_progress"):
        return PHASE_UPLOADING
    if low in ("queued", "pending", ""):
        return PHASE_PENDING
    return PHASE_PENDING


# --- public API ----------------------------------------------------------
def load_state(file_path: str = None):
    """Load the ledger. Never raises: a corrupt/unreadable file yields a
    fresh skeleton, so a bad write can never brick the upload pipeline."""
    path = file_path or DEFAULT_STATE_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _normalise_state(json.load(fh))
    except FileNotFoundError:
        return _blank_state()
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        # Keep the damaged file for forensics instead of overwriting it.
        try:
            broken = path + ".corrupt"
            if not os.path.exists(broken):
                os.replace(path, broken)
        except OSError:
            pass
        sys_warn = f"corrupt ledger moved aside: {path} ({exc})"
        try:
            import sys
            print(f"[state] WARNING: {sys_warn}", file=sys.stderr, flush=True)
        except Exception:
            pass
        return _blank_state()


def atomic_write(file_path: str, data) -> str:
    """Serialise ``data`` to ``file_path`` atomically and durably.

    Writes to a temp file in the same directory, fsyncs, then ``os.replace``s
    it into place. Readers see either the old file or the new one, never a
    partial write.
    """
    path = os.path.abspath(file_path)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with _lock_for(path):
        fd, tmp = tempfile.mkstemp(
            dir=directory or None, prefix=os.path.basename(path) + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return path


def save_state(state: dict, file_path: str = None) -> str:
    """Persist ``state``, refreshing ``_meta.updated_at``."""
    path = file_path or DEFAULT_STATE_PATH
    payload = _normalise_state(state)
    payload.setdefault("_meta", {})["updated_at"] = _now()
    return atomic_write(path, payload)


def record_phase(record) -> str:
    """Phase of a stored record.

    Prefers the explicit ``phase`` field and falls back to decoding the
    glyph, so ledgers written before the field existed still read correctly.
    """
    if not isinstance(record, dict):
        return PHASE_PENDING
    stored = record.get("phase")
    if stored in GLYPH_BY_PHASE:
        return stored
    return phase_of(record.get("status"))


def get_dua_status(dua_id: str, platform: str, file_path: str = None):
    """Return the stored record for one dua+platform, or None.

    A record is returned even when empty so callers can distinguish
    "never attempted" from "attempted and failed".
    """
    if not dua_id or not platform:
        return None
    state = load_state(file_path)
    dua = state.get(dua_id)
    if not isinstance(dua, dict):
        return None
    record = dua.get(platform)
    return record if isinstance(record, dict) else None


def get_phase(dua_id: str, platform: str, file_path: str = None) -> str:
    """Convenience wrapper: machine-readable phase for one dua+platform."""
    return record_phase(get_dua_status(dua_id, platform, file_path))


def update_dua_status(dua_id, platform, status=UPLOADED, url=None, error=None,
                      file_path=None, platform_id=None, video_path=None,
                      count_retry=False, extra=None, phase=None) -> dict:
    """Merge an update into the ledger and persist it.

    Parameters
    ----------
    dua_id, platform : str
        Target slot.
    status : str
        A glyph from this module, or a plain word ("uploaded"/"failed").
        Defaults to UPLOADED.
    phase : str, optional
        Explicit machine phase. Required to express UPLOADING, because
        PENDING and UPLOADING share a glyph. Derived from ``status`` if
        omitted.
    url, error, platform_id, video_path : optional metadata
    count_retry : bool
        Increment ``retry_count`` instead of resetting it. Set True on each
        failure so the dashboard can surface repeated trouble.
    extra : dict
        Platform-specific fields to merge in.

    Returns the stored record.
    """
    path = file_path or DEFAULT_STATE_PATH
    phase = phase or phase_of(status)

    with _lock_for(os.path.abspath(path)):
        state = load_state(path)
        dua = state.get(dua_id)
        if not isinstance(dua, dict):
            dua = {}
            state[dua_id] = dua
        record = dua.get(platform)
        if not isinstance(record, dict):
            record = {"status": PENDING, "phase": PHASE_PENDING,
                      "url": None, "platform_id": None, "uploaded_at": None,
                      "error": None, "retry_count": 0}
        previous_phase = record_phase(record)
        previous_retries = record.get("retry_count") or 0

        record["status"] = GLYPH_BY_PHASE.get(phase, status or PENDING)
        record["phase"] = phase
        record["retry_count"] = (
            previous_retries + 1 if count_retry else 0
        )
        record["updated_at"] = _now()

        # A fresh attempt clears the stale failure reason; callers that want
        # the old text preserved after a new failure pass `error` again.
        record["error"] = (str(error)[:500] if error else None)

        if platform_id is not None:
            record["platform_id"] = str(platform_id)
        if video_path is not None:
            record["video_path"] = str(video_path)
        if url is not None:
            record["url"] = str(url)
        if phase == PHASE_COMPLETED:
            record["url"] = str(url) if url else record.get("url")
            record["uploaded_at"] = _now()
        elif phase in (PHASE_PENDING, PHASE_UPLOADING):
            record["uploaded_at"] = None

        if extra and isinstance(extra, dict):
            for key, value in extra.items():
                record[key] = value

        # A new attempt after a terminal failure: reset counters cleanly.
        if phase == PHASE_UPLOADING and previous_phase in (
                PHASE_COMPLETED, PHASE_FAILED):
            record["retry_count"] = 0
            record["error"] = None

        dua[platform] = record
        save_state(state, path)

    return record


def mark_queued(dua_id, platform, **kw) -> dict:
    """Slot reserved, waiting to start (renders as the hourglass)."""
    return update_dua_status(dua_id, platform, PENDING, error=None,
                             phase=PHASE_PENDING, **kw)


def mark_uploading(dua_id, platform, **kw) -> dict:
    """Upload in flight (UI shows a spinner)."""
    return update_dua_status(dua_id, platform, UPLOADING, error=None,
                             phase=PHASE_UPLOADING, **kw)


def mark_uploaded(dua_id, platform, url=None, **kw) -> dict:
    """Terminal success."""
    return update_dua_status(dua_id, platform, UPLOADED, url=url, **kw)


def mark_failed(dua_id, platform, error, **kw) -> dict:
    """Terminal failure; increments ``retry_count``."""
    return update_dua_status(dua_id, platform, FAILED, error=error,
                             count_retry=True, **kw)


def summary(file_path: str = None) -> dict:
    """Per-platform tallies for the dashboard stats bar.

    {"total": 170, "youtube": {"uploaded": 90, "failed": 5, "pending": 75}, ...}
    """
    state = load_state(file_path)
    counts = {p: {PHASE_COMPLETED: 0, PHASE_FAILED: 0,
                  PHASE_UPLOADING: 0, PHASE_PENDING: 0} for p in PLATFORMS}
    duas = 0
    for key, value in state.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        duas += 1
        for platform, record in value.items():
            if platform not in counts or not isinstance(record, dict):
                continue
            counts[platform][record_phase(record)] += 1
    return {"total": duas, "platforms": counts}


def platform_url(platform: str, platform_id: str, kind: str = "short") -> str:
    """Best-effort public permalink for a platform id.

    ``kind`` selects the YouTube URL shape: long-form lives at /watch?v=,
    Shorts at /shorts/. Other platforms ignore it.
    """
    if not platform_id:
        return None
    pid = str(platform_id)
    if platform == "youtube":
        if kind == "long_form":
            return f"https://www.youtube.com/watch?v={pid}"
        return f"https://youtube.com/shorts/{pid}"
    if platform == "tiktok":
        return f"https://www.tiktok.com/video/{pid}"
    if platform == "instagram":
        return f"https://www.instagram.com/reel/{pid}/"
    if platform == "facebook":
        return f"https://www.facebook.com/reel/{pid}"
    return None


if __name__ == "__main__":  # quick self-test
    import tempfile as _tf

    probe = os.path.join(_tf.mkdtemp(), "state.json")
    mark_queued("probe", "youtube", file_path=probe)
    assert get_dua_status("probe", "youtube", probe)["phase"] == PHASE_PENDING
    mark_uploading("probe", "youtube", file_path=probe)
    assert get_phase("probe", "youtube", probe) == PHASE_UPLOADING
    mark_failed("probe", "youtube", "boom", file_path=probe)
    assert get_dua_status("probe", "youtube", probe)["retry_count"] == 1
    mark_uploaded("probe", "youtube", url=platform_url("youtube", "abc"),
                  file_path=probe)
    rec = get_dua_status("probe", "youtube", probe)
    assert rec["phase"] == PHASE_COMPLETED and rec["url"].endswith("/abc")
    assert summary(probe)["platforms"]["youtube"]["completed"] == 1
    print("state.py self-test OK ->", probe)
