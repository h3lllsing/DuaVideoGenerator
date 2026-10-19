"""Quick 60fps E2E render test — bathroom_exit dua."""

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.dua_database import DB
from core.quality_checker import QualityChecker
from main import DuaVideoPipeline

print("=== 60fps E2E Render Test: bathroom_exit ===")
t0 = time.time()
p = DuaVideoPipeline()
ok = p.generate_video("bathroom_exit")
elapsed = time.time() - t0

if ok:
    dua = DB.get_dua_by_id("bathroom_exit")
    title = dua.get("title", "Dua")
    safe = re.sub(r"[<>:/\\|?*\x00-\x1f]+", "", title).strip()
    out = os.path.join("output", dua.get("category", "general"), f"{safe}.mp4")
    if os.path.exists(out):
        qc = QualityChecker()
        r = qc.check_video(out)
        info = r["video_info"]
        sz = os.path.getsize(out) / (1024 * 1024)
        print(f"\nFile:     {out}")
        print(f"Size:     {sz:.1f} MB")
        print(f"Duration: {info['duration']:.1f}s")
        print(f"FPS:      {info['fps']}")
        print(f"Res:      {info['width']}x{info['height']}")
        print(f"Valid:    {r['valid']}")
        print(f"Time:     {elapsed:.1f}s")
    else:
        print(f"Output not found at {out}")
else:
    print("Pipeline FAILED")
