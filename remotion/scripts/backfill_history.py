"""Backfill data/upload_state.json from the legacy per-channel ledgers.

Why
---
``data/upload_state.json`` is the single cross-platform ledger the Phase 4
dashboard reads, but it started empty while YouTube already had history. This
script reconciles the two legacy ledgers into it **without inventing data**.

The numbers
-----------
    data/upload_state_channel1.json   90 entries  (long-form, authoritative)
    data/shorts_state_channel1.json   21 entries  (Shorts)
    ---------------------------------------------
    naive sum                        111   <- WRONG, all 21 short ids also
                                              appear in the long-form ledger
    unique dua_ids                    90   <- correct
    catalog duas with no YouTube      83   <- correct pending count

Why the 19 duplicates matter
----------------------------
19 of the 21 Shorts records carry the *same* ``video_id`` as the long-form
upload for that dua, which means the Shorts slot was copied from the long-form
ledger rather than filled by a real Shorts upload. Only 2 short ids
(``barish_ki_dua``, ``sachai_aur_imandari_ki_dua``) have a genuinely distinct
video id. The script trusts the long-form ledger and records Shorts detail in a
*separate* sub-record, so a real Shorts upload can never overwrite the
long-form one -- the exact bug class that produced these 19 duplicates.

Usage
-----
    python backfill_history.py --dry-run     # report only, writes nothing
    python backfill_history.py               # apply
    python backfill_history.py --force       # overwrite a populated ledger
    python backfill_history.py --include-orphans
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
except Exception:
    pass

from social import state as ustate  # noqa: E402

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(SCRIPTS))
DATA = os.path.join(PROJECT, "data")

LONG_LEDGER = os.path.join(DATA, "upload_state_channel1.json")
SHORT_LEDGER = os.path.join(DATA, "shorts_state_channel1.json")
CATALOG = os.path.join(DATA, "duas.json")
TARGET = os.path.join(DATA, "upload_state.json")

PLATFORMS = ("tiktok", "instagram", "facebook")


def load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except Exception as exc:
        print(f"  [warn] {os.path.basename(path)} unreadable: {exc}")
        return default


def platform_url(platform, pid, kind="short"):
    return ustate.platform_url(platform, pid, kind)


def build(dry_run: bool, include_orphans: bool):
    long_ledger = load(LONG_LEDGER, {})
    short_ledger = load(SHORT_LEDGER, {})
    catalog = load(CATALOG, [])
    catalog_ids = {d.get("id") for d in catalog if isinstance(d, dict) and d.get("id")}

    long_ok = {k: v for k, v in long_ledger.items()
               if isinstance(v, dict) and v.get("video_id")}
    short_ok = {k: v for k, v in short_ledger.items()
                if isinstance(v, dict) and v.get("video_id")}

    stats = {"long": len(long_ok), "shorts": len(short_ok),
             "unique": 0, "shorts_real": 0, "shorts_duplicate": 0,
             "orphans": 0, "skipped_outside_catalog": 0, "overwritten": 0}
    merged = ustate.load_state(TARGET)

    existing = [k for k in merged if not k.startswith("_")]
    if existing and not dry_run:
        stats["overwritten"] = len(existing)

    for dua_id in sorted(set(long_ok) | set(short_ok)):
        if dua_id not in catalog_ids and not include_orphans:
            stats["skipped_outside_catalog"] += 1
            continue

        entry = long_ok.get(dua_id)
        short = short_ok.get(dua_id)
        record = merged.get(dua_id, {})
        record = record if isinstance(record, dict) else {}

        yt = record.get("youtube") if isinstance(record.get("youtube"), dict) else {}

        if entry:
            # Long-form is authoritative: it is the mature ledger and carries
            # quota/privacy bookkeeping.
            yt.update({
                "status": ustate.UPLOADED,
                "phase": ustate.PHASE_COMPLETED,
                "url": platform_url("youtube", entry["video_id"], "long_form"),
                "platform_id": entry["video_id"],
                "uploaded_at": entry.get("uploaded_at"),
                "error": None,
                "retry_count": 0,
                "kind": "long_form",
                "privacy": entry.get("privacy"),
                "source_ledger": "upload_state_channel1.json",
            })
        else:
            yt.setdefault("status", ustate.UPLOADED)
            yt.setdefault("phase", ustate.PHASE_COMPLETED)
            yt["kind"] = yt.get("kind") or "short_form"

        # Shorts go in their own sub-record. Never overwrite the long-form id.
        if short:
            short_id = short["video_id"]
            distinct = not entry or short_id != entry.get("video_id")
            yt["youtube_shorts"] = {
                "status": ustate.UPLOADED if distinct else ustate.PENDING,
                "phase": ustate.PHASE_COMPLETED if distinct else ustate.PHASE_PENDING,
                "url": platform_url("youtube", short_id, "short_form") if distinct else None,
                "platform_id": short_id,
                "uploaded_at": short.get("uploaded_at"),
                "video_path": short.get("shortHref"),
                "duration": short.get("duration"),
                "trusted": distinct,
                "note": (None if distinct else
                         "video_id duplicates the long-form upload; treated as a "
                         "copied record, not a confirmed Shorts upload"),
            }
            if distinct:
                stats["shorts_real"] += 1
            else:
                stats["shorts_duplicate"] += 1

        if dua_id not in catalog_ids:
            record["not_in_catalog"] = True
            stats["orphans"] += 1

        record["youtube"] = yt
        for platform in PLATFORMS:
            if not isinstance(record.get(platform), dict):
                record[platform] = {
                    "status": ustate.PENDING,
                    "phase": ustate.PHASE_PENDING,
                    "url": None,
                    "platform_id": None,
                    "uploaded_at": None,
                    "error": None,
                    "retry_count": 0,
                }
        merged[dua_id] = record
        stats["unique"] += 1

    for dua_id in sorted(catalog_ids - set(merged)):
        record = {"youtube": {"status": ustate.PENDING, "phase": ustate.PHASE_PENDING,
                              "url": None, "platform_id": None, "uploaded_at": None,
                              "error": None, "retry_count": 0}}
        for platform in PLATFORMS:
            record[platform] = {"status": ustate.PENDING,
                                "phase": ustate.PHASE_PENDING, "url": None,
                                "platform_id": None, "uploaded_at": None,
                                "error": None, "retry_count": 0}
        merged[dua_id] = record

    return merged, stats, catalog_ids


def report(stats, catalog_ids, dry_run):
    verb = "would write" if dry_run else "wrote"
    print(f"  long-form ledger entries   : {stats['long']}")
    print(f"  shorts ledger entries      : {stats['shorts']}")
    print(f"  unique dua_ids             : {stats['unique']}")
    print(f"  confirmed real Shorts      : {stats['shorts_real']}")
    print(f"  duplicate (untrusted)      : {stats['shorts_duplicate']}")
    print(f"  skipped (not in catalog)   : {stats['skipped_outside_catalog']}"
          f"  [rerun with --include-orphans to keep them]")
    if stats["orphans"]:
        print(f"  flagged not_in_catalog     : {stats['orphans']}")
    catalog_total = len(catalog_ids)
    pending = catalog_total - stats["unique"]
    print(f"  catalog duas              : {catalog_total}")
    print(f"  pending YouTube uploads   : {max(pending, 0)}")
    if stats["overwritten"]:
        print(f"  [warn] overwrote {stats['overwritten']} pre-existing entries in the target")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="overwrite a target that already has entries")
    ap.add_argument("--include-orphans", action="store_true",
                    help="keep ledger ids that are not in the catalog")
    args = ap.parse_args()

    existing = [k for k in ustate.load_state(TARGET) if not k.startswith("_")]
    if existing and not args.dry_run and not args.force:
        print(f"  REFUSING to overwrite {len(existing)} existing entries in "
              f"{os.path.basename(TARGET)}; pass --force to proceed.")
        return 1

    merged, stats, catalog_ids = build(args.dry_run, args.include_orphans)
    report(stats, catalog_ids, args.dry_run)

    if args.dry_run:
        print("  dry run: nothing written")
        return 0

    # Safety copy of whatever we are about to replace.
    if os.path.isfile(TARGET):
        bak = TARGET + ".prebackfill"
        try:
            with open(TARGET, "r", encoding="utf-8") as src, \
                    open(bak, "w", encoding="utf-8") as dst:
                dst.write(src.read())
            print(f"  previous ledger saved to {os.path.basename(bak)}")
        except OSError as exc:
            print(f"  [warn] could not snapshot target: {exc}")

    ustate.save_state(merged, TARGET)

    written = len([k for k in ustate.load_state(TARGET) if not k.startswith("_")])
    print(f"  verified: {written} dua entries in {os.path.basename(TARGET)}")
    if written != len([k for k in merged if not k.startswith("_")]):
        print("  [error] write verification mismatch")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
