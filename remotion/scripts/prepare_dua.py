"""Standalone TTS + audio merge for one dua (feeds Remotion pipeline).

Produces in temp:
  <id>_ar.mp3, <id>_ur.mp3, <id>_ar_timing.jsonl, <id>_ur_timing.jsonl,
  <id>_merged.wav  (loudness-normalized + padded to VIDEO-002 policy)

Skips work when outputs already exist (pass --force to redo).
"""

import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(PROJECT)

import contextlib

from moviepy import AudioFileClip

from core.audio_mixer import AudioMixer
from core.dua_database import DB
from core.tts_engine import TTSEngine

# Hierarchy: har dua Bismillah se shuru hoti hai. Data me likhna zaroori
# nahi — pipeline khud prepend karti hai (agar pehle se na ho).
BISMILLAH_AR = "\u0628\u0650\u0633\u0652\u0645\u0650 \u0627\u0644\u0644\u0651\u064e\u0647\u0650 \u0627\u0644\u0631\u0651\u064e\u062d\u0652\u0645\u064e\u0670\u0646\u0650 \u0627\u0644\u0631\u0651\u064e\u062d\u0650\u064a\u0645\u0650"
BISMILLAH_UR_FIXED = (
    "\u0634\u0631\u0648\u0639 \u0627\u0644\u0644\u06c1 \u06a9\u06d2 \u0646\u0627\u0645 \u0633\u06d2 "
    "\u062c\u0648 \u0628\u0691\u0627 \u0645\u06c1\u0631\u0628\u0627\u0646 "
    "\u0646\u06c1\u0627\u06cc\u062a \u0631\u062d\u0645 \u0648\u0627\u0644\u0627 \u06c1\u06d2"
)


def _strip_diacritics(s):
    return "".join(c for c in s if not ("\u064b" <= c <= "\u0652" or c == "\u0670"))


def with_bismillah(arabic, urdu):
    """Prepend Bismillah to Arabic + fixed meaning to Urdu (idempotent)."""
    bare = _strip_diacritics(arabic.strip())
    bare_bis = _strip_diacritics(BISMILLAH_AR)
    ar_out = arabic.strip()
    if not bare.startswith(bare_bis[:10]):
        ar_out = BISMILLAH_AR + " " + ar_out
    ur_out = urdu.strip()
    # Skip agar pehle se Bismillah hai (fixed phrase) YA tarjuma khud
    # "اللہ کے نام سے" se shuru hota hai (warna double ho jata hai)
    already = "\u0634\u0631\u0648\u0639 \u0627\u0644\u0644\u06c1" in ur_out or ur_out.startswith(
        "\u0627\u0644\u0644\u06c1 \u06a9\u06d2 \u0646\u0627\u0645 \u0633\u06d2"
    )
    if not already:
        ur_out = BISMILLAH_UR_FIXED + " " + ur_out
    return ar_out, ur_out


# TTS pronunciation fixes (sirf awaz ke liye, stored/display text nahi)
_PRONOUNCE_AR = {
    "\ufdfa": "\u0635\u064e\u0644\u0651\u064e\u0649 \u0627\u0644\u0644\u0651\u064e\u0647\u064f "
    "\u0639\u064e\u0644\u064e\u064a\u0652\u0647\u0650 \u0648\u064e\u0633\u064e\u0644\u0651\u064e\u0645\u064e",
    "\u0640": "",
}


def apply_pronunciation(text, lang):
    out = text
    if lang == "ar":
        for k, v in _PRONOUNCE_AR.items():
            out = out.replace(k, v)
    out = "".join(c for c in out if c.isprintable() or c == "\n")
    return out


def exists_all(paths):
    return all(os.path.exists(p) for p in paths)


def main(dua_id, force=False, only=None):
    dua = DB.get_dua_by_id(dua_id)
    if not dua:
        print("ERROR: dua not found:", dua_id)
        return 1
    if dua.get("archived"):
        print(
            "NOTE: entry is ARCHIVED (superseded_by: {}) - legacy files kept, prefer the replacement parts".format(
                ", ".join(dua.get("superseded_by") or [])
            )
        )

    temp = os.path.join(PROJECT, "temp")
    ar = os.path.join(temp, f"{dua_id}_ar.mp3")
    ur = os.path.join(temp, f"{dua_id}_ur.mp3")
    ar_t = os.path.join(temp, f"{dua_id}_ar_timing.jsonl")
    ur_t = os.path.join(temp, f"{dua_id}_ur_timing.jsonl")
    merged = os.path.join(temp, f"{dua_id}_merged.wav")

    if not force and only is None and exists_all([ar, ur, ar_t, ur_t, merged]):
        print("SKIP: all audio artifacts exist for", dua_id)
        return 0

    tts = TTSEngine()
    if dua.get("bismillah", True):
        ar_text, ur_text = with_bismillah(dua["arabic"], dua["urdu"])
    else:
        print("bismillah: OFF (dua setting) - raw text use ho raha hai")
        ar_text, ur_text = dua["arabic"].strip(), dua["urdu"].strip()
    ar_text = apply_pronunciation(ar_text, "ar")
    ur_text = apply_pronunciation(ur_text, "ur")
    need_ar = only in (None, "ar")
    need_ur = only in (None, "ur")

    if need_ar or need_ur:
        ar_voice = dua.get("voice_arabic") if need_ar else None
        ur_voice = dua.get("voice_urdu") if need_ur else None
        print(
            "[1/3] TTS (parallel, ar_voice={}, ur_voice={})...".format(
                ar_voice or "default Hamed", ur_voice or "default Asad"
            )
        )

        if need_ar and need_ur:
            ar_ok, ur_ok = tts.generate_both(
                ar_text, ur_text, ar, ur, ar_timing=ar_t, ur_timing=ur_t, ar_voice=ar_voice, ur_voice=ur_voice
            )
        elif need_ar:
            ar_ok = tts.generate_audio(ar_text, "ar", ar, timing_path=ar_t, voice=ar_voice)
            ur_ok = True
        else:
            ar_ok = True
            ur_ok = tts.generate_audio(ur_text, "ur", ur, timing_path=ur_t, voice=ur_voice)

        if not ar_ok:
            print("ERROR: arabic tts failed")
            return 1
        if not ur_ok:
            print("ERROR: urdu tts failed")
            return 1

    if not (os.path.exists(ar) and os.path.exists(ur)):
        print(
            "OK partial: sirf {} side bana - dusra side missing, merge nahi ho sakta".format(
                "urdu" if need_ur else "arabic"
            )
        )
        return 0

    print("[2/3] Merging...")
    if not AudioMixer.merge_audio_sequential([ar, ur], merged, gap_seconds=0.3):
        print("ERROR: merge failed")
        return 1

    clip = AudioFileClip(merged)
    speech_dur = clip.duration
    clip.close()

    timeline = AudioMixer.compute_video_timeline(speech_dur)
    if not timeline.get("valid"):
        print("ERROR: duration policy rejected:", timeline.get("reason"))
        return 3
    final_duration = timeline["final_duration"]

    print(f"[3/3] Normalize + pad to {final_duration:.2f}s...")
    base, ext = os.path.splitext(merged)
    normalized = f"{base}.normalized{ext}"
    if AudioMixer.normalize_loudness(merged, normalized):
        ok = AudioMixer.merge_audio_sequential([normalized], merged, gap_seconds=0.0, pad_to_duration=final_duration)
        if os.path.exists(normalized):
            with contextlib.suppress(OSError):
                os.remove(normalized)
    else:
        ok = AudioMixer.merge_audio_sequential([ar, ur], merged, gap_seconds=0.3, pad_to_duration=final_duration)
    if not ok:
        print("ERROR: pad failed")
        return 1

    print(f"OK merged={merged} final={final_duration:.2f}s")
    return 0


if __name__ == "__main__":
    did = sys.argv[1] if len(sys.argv) > 1 else ""
    if not did:
        print("usage: prepare_dua.py <dua_id> [--force] [--only ar|ur]")
        raise SystemExit(1)
    only = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        if i + 1 < len(sys.argv):
            only = sys.argv[i + 1]
            if only not in ("ar", "ur"):
                print("ERROR: --only ar ya ur")
                raise SystemExit(1)
    raise SystemExit(main(did, force="--force" in sys.argv, only=only))
