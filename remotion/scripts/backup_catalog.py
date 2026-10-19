"""Back up data/duas.json to a safe, verified location.

Why this is P0
--------------
``data/duas.json`` holds the master catalog (170 duas) and is **untracked and
git-ignored**. A single disk failure destroys it irrecoverably. A backup that
writes to an unverified target is worse than no backup, because it manufactures
false confidence -- so this script refuses to report success unless it can
re-read the file it just wrote and prove it matches the source.

Usage
-----
    python backup_catalog.py                       # back up now
    python backup_catalog.py --list                # show existing backups
    python backup_catalog.py --dest E:\\backups     # override destination
    python backup_catalog.py --keep 30             # retain newest 30
    python backup_catalog.py --allow-unsafe-dest   # bypass destination checks

Exit codes
----------
    0  backup written and verified
    1  backup failed / destination rejected / verification mismatch
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SCRIPTS))
SOURCE = os.path.join(PROJECT, "data", "duas.json")
LOG_PATH = os.path.join(PROJECT, "logs", "backup_catalog_log.jsonl")

# The task brief specified D:\backups. D: is a ~100 MB "System Reserved"
# partition on a USB flash device -- writing the catalog there risks filling a
# boot partition and still gives no off-disk protection. E: is a separate
# physical disk (SAMSUNG MZ7TE256HMHP) from the H: source (INTEL SSDSC2BW180A3H),
# so it is the correct default. Override with --dest if your layout differs.
DEFAULT_DEST = r"E:\backups\dua-video-generator"

# Volume labels that must never host a backup: boot/reserved partitions.
BLOCKED_LABELS = {"system reserved", "efi system partition", "msr", "reserved"}
MIN_FREE_MB = 50
MIN_FREE_MULTIPLE = 10  # dest needs >= 10x the payload


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def volume_info(path: str) -> dict:
    """Volume label + capacity for the drive holding ``path``."""
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    label = fs = ""
    try:
        buf = ctypes.create_unicode_buffer(261)
        fsbuf = ctypes.create_unicode_buffer(261)
        serial, maxcomp, flags = (ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong())
        if ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            buf,
            261,
            ctypes.byref(serial),
            ctypes.byref(maxcomp),
            ctypes.byref(flags),
            fsbuf,
            261,
        ):
            label, fs = buf.value, fsbuf.value
    except Exception:
        pass
    try:
        usage = shutil.disk_usage(root)
        total, free = usage.total, usage.free
    except OSError:
        total = free = 0
    return {"root": root, "label": label, "fs": fs, "total": total, "free": free, "free_mb": free // (1024 * 1024)}


def validate_dest(dest: str, source: str) -> tuple:
    """Return (ok, reasons). Rejects targets that cannot be a real backup."""
    reasons = []
    info = volume_info(dest)
    src_info = volume_info(source)

    label = (info["label"] or "").strip().lower()
    if label in BLOCKED_LABELS:
        reasons.append(
            f"destination volume {info['root']} is labelled "
            f"'{info['label'] or '?'}' -- a boot/reserved partition, unsafe for data"
        )
    if info["free_mb"] < MIN_FREE_MB:
        reasons.append(
            f"destination volume {info['root']} has only {info['free_mb']} MB free (minimum {MIN_FREE_MB} MB)"
        )
    try:
        payload = os.path.getsize(source)
        if info["free"] and info["free"] < payload * MIN_FREE_MULTIPLE:
            reasons.append(
                f"destination free space ({info['free_mb']} MB) is under "
                f"{MIN_FREE_MULTIPLE}x the source size ({payload // 1024} KB)"
            )
    except OSError:
        pass
    if src_info["root"] and info["root"] == src_info["root"]:
        reasons.append(
            f"destination is on the same volume as the source ({info['root']}) -- "
            f"that is a copy, not a backup; it will not survive disk failure"
        )

    if not reasons:
        try:
            os.makedirs(dest, exist_ok=True)
            if not os.access(dest, os.W_OK):
                reasons.append(f"destination is not writable: {dest}")
        except OSError as exc:
            reasons.append(f"cannot create destination {dest}: {exc}")
    return (not reasons), reasons, info


def log_event(event: str, **fields) -> None:
    record = {"ts": now_iso(), "event": event, "pid": os.getpid()}
    record.update(fields)
    line = json.dumps(record, ensure_ascii=False)
    print("  " + line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        print(f"  [warn] could not append to log: {exc}", file=sys.stderr, flush=True)


def verify_backup(backup_path: str, source: str) -> tuple:
    """Re-read the written file and prove it matches the source.

    Three independent checks: it must parse as JSON, hold the same number of
    entries, and be semantically *and* byte-wise identical.
    """
    problems = []
    try:
        with open(backup_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return False, [f"backup is not valid readable JSON: {exc}"]

    try:
        with open(source, encoding="utf-8") as fh:
            original = json.load(fh)
    except Exception as exc:
        return False, [f"source became unreadable during backup: {exc}"]

    src_count = len(original) if isinstance(original, list) else -1
    bak_count = len(data) if isinstance(data, list) else -1
    if src_count != bak_count:
        problems.append(f"entry count mismatch: source {src_count} != backup {bak_count}")
    if data != original:
        problems.append("content mismatch: parsed backup differs from parsed source")
    if sha256(source) != sha256(backup_path):
        problems.append("sha256 mismatch: backup is not byte-identical to source")
    return (not problems), problems


def prune(dest: str, keep: int, pattern: str = "duas_*.json") -> list:
    try:
        files = sorted(
            (
                os.path.join(dest, f)
                for f in os.listdir(dest)
                if f.startswith("duas_") and f.endswith(".json") and not f.endswith(".corrupt")
            ),
            key=os.path.getmtime,
            reverse=True,
        )
    except OSError:
        return []
    removed = []
    for stale in files[max(keep, 1) :]:
        try:
            os.remove(stale)
            removed.append(stale)
        except OSError:
            pass
    return removed


def list_backups(dest: str) -> int:
    if not os.path.isdir(dest):
        print(f"  no backup directory yet: {dest}")
        return 0
    files = sorted(
        (f for f in os.listdir(dest) if f.startswith("duas_") and f.endswith(".json")),
        key=lambda f: os.path.getmtime(os.path.join(dest, f)),
        reverse=True,
    )
    if not files:
        print(f"  no backups found in {dest}")
        return 0
    print(f"  {len(files)} backup(s) in {dest}:")
    for name in files:
        full = os.path.join(dest, name)
        print(
            f"    {name}  {os.path.getsize(full) / 1024:8.1f} KB  "
            f"{datetime.fromtimestamp(os.path.getmtime(full)):%Y-%m-%d %H:%M}"
        )
    return len(files)


def do_backup(source: str, dest: str, keep: int, allow_unsafe: bool) -> int:
    if not os.path.isfile(source):
        log_event("failed", reason="source missing", source=source)
        return 1

    payload = os.path.getsize(source)
    ok, reasons, info = validate_dest(dest, source)
    print(f"  source      : {source} ({payload / 1024:.1f} KB)")
    print(f"  destination : {dest}")
    print(
        f"  volume      : {info['root']} label={info['label'] or '(none)'} "
        f"free={info['free_mb']} MB fs={info['fs'] or '?'}"
    )

    if not ok and not allow_unsafe:
        log_event("failed", reason="unsafe destination", dest=dest, problems=reasons)
        print("  REFUSING to write:", file=sys.stderr)
        for reason in reasons:
            print(f"    - {reason}", file=sys.stderr)
        print(
            "  Pick a different volume, e.g. --dest E:\\backups, or pass --allow-unsafe-dest to override deliberately.",
            file=sys.stderr,
        )
        return 1
    if not ok:
        log_event("warning", reason="unsafe destination accepted by flag", dest=dest, problems=reasons)
        print("  WARNING: proceeding despite destination problems (--allow-unsafe-dest)")

    try:
        with open(source, encoding="utf-8") as fh:
            entries = json.load(fh)
    except Exception as exc:
        log_event("failed", reason=f"source unreadable: {exc}")
        return 1
    count = len(entries) if isinstance(entries, list) else -1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = os.path.join(dest, f"duas_{stamp}.json")
    os.makedirs(dest, exist_ok=True)

    tmp_fd, tmp = tempfile.mkstemp(dir=dest, prefix="duas_", suffix=".tmp")
    os.close(tmp_fd)
    try:
        # Verbatim byte-for-byte copy. Re-serialising would normalise the
        # formatting, which both diverges from the source and makes a
        # sha256 comparison impossible to satisfy.
        shutil.copyfile(source, tmp)
        with open(tmp, "rb+") as fh:
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except Exception as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        log_event("failed", reason=f"write error: {exc}", dest=target)
        return 1

    verified, problems = verify_backup(target, source)
    if not verified:
        # Never leave an unverified file where --list would present it as a
        # good backup. Quarantine it so it can still be inspected.
        suspect = target + ".unverified"
        try:
            os.replace(target, suspect)
        except OSError:
            try:
                os.remove(target)
            except OSError:
                pass
            suspect = target
        log_event("failed", reason="verification failed", backup=target, quarantined=suspect, problems=problems)
        print("  VERIFICATION FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"    - {problem}", file=sys.stderr)
        print(f"  suspect file quarantined: {suspect}", file=sys.stderr)
        return 1

    for old in prune(dest, keep):
        log_event("pruned", file=os.path.basename(old))
        print(f"  pruned old backup: {os.path.basename(old)}")

    log_event(
        "backup_ok",
        source=source,
        backup=target,
        entries=count,
        bytes=payload,
        dest_volume=info["root"],
        dest_label=info["label"],
        verified=True,
        sha256=sha256(target)[:16],
    )
    print(f"  OK  {count} entries -> {target}  (sha256 {sha256(target)[:16]}... verified)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Back up the dua catalog.")
    ap.add_argument("--dest", default=DEFAULT_DEST, help="backup directory")
    ap.add_argument("--source", default=SOURCE, help="catalog to back up")
    ap.add_argument("--keep", type=int, default=30, help="retain newest N backups")
    ap.add_argument("--list", action="store_true", help="list backups and exit")
    ap.add_argument("--allow-unsafe-dest", action="store_true", help="skip destination safety checks")
    args = ap.parse_args()

    if args.list:
        list_backups(args.dest)
        return 0
    return do_backup(args.source, args.dest, args.keep, args.allow_unsafe_dest)


if __name__ == "__main__":
    raise SystemExit(main())
