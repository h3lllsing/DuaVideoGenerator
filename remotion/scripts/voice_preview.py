#!/usr/bin/env python3
"""Generate a 3-second voice preview sample for a given edge-tts voice."""

import asyncio
import json
import os
import sys
import tempfile

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT)


SAMPLE_TEXTS = {
    "ar": "بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ",
    "ur": "اللہ کے نام سے شروع جو بڑا مہربان نہایت رحم والا ہے",
}


async def _preview(text: str, voice: str, lang: str, out_path: str) -> bool:
    import edge_tts

    rate = "-8%" if lang == "ar" else "-5%"
    pitch = "-2Hz" if lang == "ar" else "-1Hz"
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)
    return True


def main():
    if len(sys.argv) < 3:
        print("Usage: voice_preview.py <voice> <lang> [text] [out_path]", file=sys.stderr)
        sys.exit(1)

    voice = sys.argv[1]
    lang = sys.argv[2] if sys.argv[2] in ("ar", "ur") else "ar"
    text = sys.argv[3] if len(sys.argv) > 3 else SAMPLE_TEXTS.get(lang, SAMPLE_TEXTS["ar"])
    out_path = sys.argv[4] if len(sys.argv) > 4 else os.path.join(tempfile.gettempdir(), "voice_preview.mp3")

    # Truncate text to ~3 seconds worth (~15 words)
    words = text.split()
    if len(words) > 15:
        text = " ".join(words[:15])

    try:
        asyncio.run(_preview(text, voice, lang, out_path))
        print(json.dumps({"ok": True, "path": out_path}))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:200]}))
        sys.exit(1)


if __name__ == "__main__":
    main()
