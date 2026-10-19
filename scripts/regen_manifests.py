"""Regenerate all Remotion manifests with current config FPS."""
import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(PROJECT, "remotion", "scripts", "make_manifest.py")
DATA_DIR = os.path.join(PROJECT, "data")

with open(os.path.join(DATA_DIR, "duas.json"), encoding="utf-8") as f:
    import json
    raw = json.load(f)
    duas = raw if isinstance(raw, list) else raw.get("duas", [])

count = 0
for dua in duas:
    dua_id = dua.get("id", "")
    if not dua_id:
        continue
    r = subprocess.run([sys.executable, SCRIPT, dua_id], capture_output=True, text=True, cwd=PROJECT)
    if r.returncode == 0:
        count += 1
        print(f"  OK: {dua_id}")
    else:
        print(f"  FAIL: {dua_id}: {r.stderr[-200:]}")

print(f"\nDone: {count}/{len(duas)} manifests regenerated")
