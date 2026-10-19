"""Full voice regeneration: fresh solemn TTS + mastering for all duas.

Order per dua: prepare_dua(--force) -> make_manifest (master+manifest).
Exit 3 from prepare = duration policy reject -> recorded, loop continues.
"""

import json
import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
SCRIPTS = os.path.join(PROJECT, "remotion", "scripts")


def run(args):
    return subprocess.run([PY] + args, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main():
    with open(os.path.join(PROJECT, "data", "duas.json"), encoding="utf-8") as f:
        duas = json.load(f)
    if not isinstance(duas, list):
        duas = duas.get("duas", [])

    ok, blocked, fail = [], [], []
    for i, dua in enumerate(duas, 1):
        did = dua["id"]
        print(f"[{i}/{len(duas)}] {did}", flush=True)
        p = run([os.path.join(SCRIPTS, "prepare_dua.py"), did, "--force"])
        if p.returncode == 3:
            print("  POLICY BLOCKED (>25s)")
            blocked.append(did)
            continue
        if p.returncode != 0:
            print("  PREPARE FAIL exit", p.returncode)
            fail.append(did)
            continue
        m = run([os.path.join(SCRIPTS, "make_manifest.py"), did])
        if m.returncode != 0:
            print("  MANIFEST FAIL")
            fail.append(did)
            continue
        print("  OK")
        ok.append(did)

    print("\n===== SUMMARY =====")
    print("regenerated:", len(ok))
    print("policy blocked ({}): {}".format(len(blocked), ", ".join(blocked)))
    print("failed ({}): {}".format(len(fail), ", ".join(fail)))
    return 0 if not fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
