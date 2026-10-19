"""Re-master existing dua audio through the studio chain (no re-TTS).

Runs make_manifest.main() for every dua whose temp artifacts already
exist. Regenerates public/audio/<id>.mp3 with MASTER_FILTER polish and
rewrites manifests (same data). Safe to re-run.
"""

import json
import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import make_manifest  # noqa: E402


def main():
    with open(os.path.join(PROJECT, "data", "duas.json"), encoding="utf-8") as f:
        duas = json.load(f)
    if not isinstance(duas, list):
        duas = duas.get("duas", [])

    ok, skip, fail = 0, 0, 0
    for dua in duas:
        did = dua["id"]
        needed = [
            os.path.join(make_manifest.TEMP, f"{did}_ar_timing.jsonl"),
            os.path.join(make_manifest.TEMP, f"{did}_ur_timing.jsonl"),
            os.path.join(make_manifest.TEMP, f"{did}_merged.wav"),
        ]
        if not all(os.path.exists(p) for p in needed):
            print("SKIP (no artifacts):", did)
            skip += 1
            continue
        try:
            make_manifest.main(did)
            print("OK:", did)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print("FAIL:", did, "-", e)
            fail += 1

    print(f"\nDone. mastered={ok} skipped={skip} failed={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
