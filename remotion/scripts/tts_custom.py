"""Custom Voice Only TTS: custom arabic/urdu -> mastered mp3 jo
remotion/public/audio/ me SAVE hota hai (portal list me nahi aata).
Server /api/tts-custom isko chalata hai."""

import json
import os
import re
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(PROJECT)
sys.path.append(os.path.join(PROJECT, "remotion", "scripts"))

from make_manifest import master_audio  # noqa: E402

from core.audio_mixer import AudioMixer  # noqa: E402
from core.tts_engine import TTSEngine  # noqa: E402


def main():
    payload_path = sys.argv[1]
    with open(payload_path, encoding="utf-8") as f:
        payload = json.load(f)

    out = os.path.join(PROJECT, "temp", "custom")
    os.makedirs(out, exist_ok=True)
    ar = os.path.join(out, "custom_ar.mp3")
    ur = os.path.join(out, "custom_ur.mp3")
    mg = os.path.join(out, "custom_merged.wav")

    ar_text = (payload.get("arabic") or "").strip()
    ur_text = (payload.get("urdu") or "").strip()
    name = payload.get("name") or ""
    if not re.fullmatch(r"[a-z0-9_]{1,60}", name):
        import time

        name = "custom_" + time.strftime("%Y%m%d_%H%M%S")

    ok_a = False
    if ar_text:
        ok_a = TTSEngine.generate_audio(ar_text, "ar", ar)
    ok_u = False
    if ur_text:
        ok_u = TTSEngine.generate_audio(ur_text, "ur", ur)

    src = None
    if ok_a and ok_u:
        if AudioMixer.merge_audio_sequential([ar, ur], mg, gap_seconds=0.3):
            src = mg
    elif ok_a:
        src = ar
    elif ok_u:
        src = ur

    saved = None
    if src and os.path.exists(src):
        audio_dir = os.path.join(PROJECT, "remotion", "public", "audio")
        os.makedirs(audio_dir, exist_ok=True)
        dst = os.path.join(audio_dir, name + ".mp3")
        try:
            master_audio(src, dst)
        except Exception as e:
            print(f"[Master Error] {e}")
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            saved = name + ".mp3"

    print(json.dumps({"okA": ok_a, "okU": ok_u, "merged": bool(ok_a and ok_u), "saved": saved}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
