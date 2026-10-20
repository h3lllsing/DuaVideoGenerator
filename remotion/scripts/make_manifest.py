"""Generate Remotion manifest JSON from dua data + TTS timing sidecars."""

import json
import os
import shutil
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT)
import contextlib

import config as project_config

REMOTION = os.path.join(PROJECT, "remotion")
TEMP = os.path.join(PROJECT, "temp")

TICKS = 10_000_000
GAP_SECONDS = 0.30


# ffmpeg/ffprobe binaries (imageio_ffmpeg bundling — ffprobe sits beside exe).
def _media_bins():
    import imageio_ffmpeg

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    return exe, os.path.join(os.path.dirname(exe), "ffprobe.exe")


FFMPEG, FFPROBE = None, None


def _init_bins():
    global FFMPEG, FFPROBE
    if FFMPEG is None:
        FFMPEG, FFPROBE = _media_bins()


def _ffprobe():
    _init_bins()
    return FFPROBE if os.path.isfile(FFPROBE) else "ffprobe"


def _ffmpeg():
    _init_bins()
    return FFMPEG if os.path.isfile(FFMPEG) else "ffmpeg"


# PILLAR 2 · broadcast loudness targets (mirrors core/audio_mixer.py).
# Master chain is now: tonal/dynamics filters -> TWO-PASS LINEAR loudnorm
# (via AudioMixer) -> mp3 encode. Dynamic single-pass loudnorm is gone,
# so compressor makeup gain is transparent and no gain-pumping occurs.
LOUDNESS_TARGET = -14.0  # LUFS integrated
TRUE_PEAK_TARGET = -1.0  # dBTP ceiling
LRA_TARGET = 11.0

# PILLAR 2 · codec priming compensation. MP3/AAC encoders prepend a
# priming window (~2112 samples @48k ~= 44 ms) that shifts every word
# slightly late during playback. Word timestamps are moved earlier by
# this constant so on-screen karaoke lands frame-accurate.
PRIMING_COMPENSATION_S = 0.044

# Studio mastering: rumble cut + warmth + clarity + compression +
# light masjid ambience. Loudness normalization happens AFTER this
# chain as a separate linear two-pass step (see master_audio).
MASTER_FILTER = (
    "highpass=f=70,"
    "bass=g=2.5,"
    "equalizer=f=3000:t=q:w=1:g=1.5,"
    "acompressor=threshold=-18dB:ratio=3:attack=10:release=200,"
    "aecho=0.6:0.25:60|120:0.12|0.08"
)

CATEGORY_THEME = {
    "sleep": "mosque",
    "evening": "mosque",
    "morning": "sunset",
    "travel": "sunset",
    "food": "emerald",
    "bathroom": "emerald",
    "prayer": "manuscript",
    # PILLAR 1 · taxonomy v2 aliases (legacy ids above stay untouched)
    "protection": "dark",
    "rizq": "emerald",
    "forgiveness": "manuscript",
    "morning_evening": "sunset",
    "guidance": "manuscript",
    "health": "ocean",
    "anxiety_relief": "ocean",
    "gratitude": "eid",
    "family": "royal",
    "occasions": "ramadan",
}


def master_audio(wav_src, audio_dst):
    """merged.wav -> mastered mp3 (PILLAR 2 three-stage master).

    Stage 1: tonal/dynamics polish chain (MASTER_FILTER) -> temp WAV
    Stage 2: AudioMixer TWO-PASS LINEAR loudnorm (-14 LUFS / -1.0 dBTP)
    Stage 3: transparent 192k mp3 encode. No dynamic loudnorm anywhere,
    so compressor makeup gain stays transparent (no gain-pumping).
    """
    import subprocess

    import imageio_ffmpeg

    sys.path.append(PROJECT)
    from core.audio_mixer import AudioMixer

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    base, _ = os.path.splitext(audio_dst)
    chained = f"{base}.chain.wav"
    normalized = f"{base}.norm.wav"
    try:
        subprocess.run(
            [
                exe,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                wav_src,
                "-af",
                MASTER_FILTER,
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                chained,
            ],
            capture_output=True,
            check=True,
        )
        ok, _measured = AudioMixer.normalize_loudness(chained, normalized)
        if not ok:
            raise RuntimeError("two-pass linear loudnorm failed")
        subprocess.run(
            [exe, "-y", "-hide_banner", "-loglevel", "error", "-i", normalized, "-b:a", "192k", audio_dst],
            capture_output=True,
            check=True,
        )
    finally:
        for tmp in (chained, normalized):
            if os.path.exists(tmp):
                with contextlib.suppress(OSError):
                    os.remove(tmp)


# STYLE-ROTATION v2 (2026-08-23): anti dark-monotony rebalance.
# Categories that previously collapsed onto "dark"/single themes now rotate
# between visually distinct, category-appropriate themes (seeded by dua id,
# so every re-render of the same dua stays identical).
CATEGORY_ROTATIONS = {
    "protection": ("desert", "qadr"),
    "guidance": ("royal", "manuscript"),
    "gratitude": ("eid", "emerald"),
    "health": ("ocean", "emerald"),
}
GENERAL_ROTATION = ("manuscript", "dark", "royal", "emerald")

VALID_THEMES = (
    "dark",
    "mosque",
    "sunset",
    "manuscript",
    "emerald",
    "ocean",
    "desert",
    "royal",
    "ramadan",
    "eid",
    "qadr",
)


def _seed_pick(seq, seed):
    return seq[sum(map(ord, str(seed))) % len(seq)]


def resolve_theme(dua):
    t = (dua.get("template") or "").strip().lower()
    # Explicit non-dark choice always wins. "dark" stamps are treated as the
    # legacy default (import-loader era) and fall through to rotation so the
    # library stops collapsing onto one look.
    if t and t in VALID_THEMES and t != "dark":
        return t
    cat = dua.get("category", "")
    if cat == "general":
        return _seed_pick(GENERAL_ROTATION, dua["id"])
    rot = CATEGORY_ROTATIONS.get(cat)
    if rot:
        return _seed_pick(rot, dua["id"])
    return CATEGORY_THEME.get(cat, "dark")


def _probe_stream(path):
    """Return (w, h) video dimensions or (w, h) image size using ffprobe.
    Returns (0, 0) on any failure."""
    try:
        import subprocess

        cmd = [
            _ffprobe(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.split()
        if len(out) >= 2:
            return int(out[0]), int(out[1])
    except Exception:
        pass
    return 0, 0


def _washed_out_score(path):
    """Return 0-100 saturation of a representative frame using ffmpeg's
    signalstats SATAVG metadata (0 = grey, 100 = fully saturated).
    Returns None on failure so caller can fall back to resolution-only."""
    try:
        import subprocess

        tmp = os.path.join(TEMP, "bg_gate_frame.png")
        os.makedirs(TEMP, exist_ok=True)
        r = subprocess.run(
            [
                _ffmpeg(),
                "-v",
                "error",
                "-ss",
                "3",
                "-i",
                path,
                "-frames:v",
                "1",
                "-vf",
                "signalstats,metadata=print:file=-",
                tmp,
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
        for line in (r.stderr or "").splitlines():
            if "SATAVG=" in line:
                return float(line.split("=")[-1].strip())
    except Exception:
        pass
    return None


def _bg_quality_ok(src_path, is_video):
    """Premium quality gate for a background candidate.

    - Resolution: chhoti media (e.g. 540p stock) ko reject karte hain taake
      upscale mush (blurry) na ho.
    - Washed-out: faded/grey-white stock (saturation < ~18%) ko reject
      karte hain taake text readable rahe (retention lever).
    """
    w, h = _probe_stream(src_path)
    # Shorts 1080x1920 ke liye portrait cover: smallest side bhi HD honi
    # chahiye taake upscale blur na ho (540p stock => reject).
    # Videos: portrait 540x960 stock motion backgrounds accept hote hain
    # (dark scrim + particles ke niche upscale softness negligible), images
    # strict 800 par rehte hain.
    min_dim = 540 if is_video else 800
    if min(w, h) < min_dim:
        return False
    if is_video:
        sat = _washed_out_score(src_path)
        if sat is not None and sat < 18:
            return False
    else:
        sat = _washed_out_score(src_path)
        if sat is not None and sat < 18:
            return False
    return True


def resolve_bg(dua):
    """Pick a DOWNLOADED background (photo/video) for this dua via the
    asset registry, copy it into remotion/public/backgrounds/, and return
    (rel_path, kind). Returns (None, None) when no loadable asset exists
    (falls back to the procedural gradient).

    Quality gate: candidates jo low-res (blurry) ya washed-out (faded) hain
    unhe exclude kiya jata hai, taake har dua ko vibrant + readable backdrop
    mile. Deterministic (dua_id seeded) rehta hai.
    """
    category = (dua.get("category") or "").strip() or None
    dua_id = dua.get("id", "")
    try:
        from core.asset_registry import AssetRegistry

        reg = AssetRegistry()
    except Exception as e:
        print(f"[bg] asset registry unavailable: {e}")
        return None, None

    excluded = set()
    prefer_video = bool(getattr(project_config, "BACKGROUND_PREFER_VIDEO", True))
    sel = reg.select_background(dua_id, category, exclude_ids=tuple(excluded), prefer_video=prefer_video)
    src_path = ""
    while sel.get("kind") == "asset":
        p = sel.get("path", "")
        ext = os.path.splitext(p)[1].lower() if p else ""
        is_video = ext in (".mp4", ".webm", ".mov")
        if p and os.path.isfile(p) and _bg_quality_ok(p, is_video):
            src_path = p
            break
        # candidate fail → agli best category asset try karo
        excluded.add(sel.get("asset_id", ""))
        sel = reg.select_background(dua_id, category, exclude_ids=tuple(excluded))
    else:
        return None, None

    if not src_path or not os.path.isfile(src_path):
        return None, None

    _, ext = os.path.splitext(src_path)  # .jpg or .mp4
    is_video = ext.lower() in (".mp4", ".webm", ".mov")
    kind = "video" if is_video else "image"

    # destination: remotion/public/backgrounds/<dua_id>.<ext>
    bg_dir = os.path.join(REMOTION, "public", "backgrounds")
    os.makedirs(bg_dir, exist_ok=True)
    dst = os.path.join(bg_dir, "{}.{}".format(dua_id, ext.lstrip(".")))
    if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src_path):
        try:
            shutil.copyfile(src_path, dst)
        except OSError as e:
            print(f"[bg] copy fail: {e}")
            return None, None

    return "backgrounds/{}.{}".format(dua_id, ext.lstrip(".")), kind


def media_duration(path):
    import re
    import subprocess

    import imageio_ffmpeg

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run([exe, "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not m:
        raise RuntimeError("no duration for " + path)
    h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mn * 60 + s


def read_words(path):
    words = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("type") != "WordBoundary":
                continue
            offset = ev.get("offset")
            duration = ev.get("duration")
            if offset is None or duration is None:
                print("WARN: WordBoundary missing offset/duration - skipped", file=sys.stderr)
                continue
            # PILLAR 2: shift earlier by the encoder priming window so
            # highlights land frame-accurate during AAC playback.
            start = max(0.0, offset / TICKS - PRIMING_COMPENSATION_S)
            end = max(start, (offset + duration) / TICKS - PRIMING_COMPENSATION_S)
            words.append({"t": ev.get("text", ""), "start": round(start, 3), "end": round(end, 3)})
    return words


def main(dua_id="rabbana_hasanah"):
    out_dir = os.path.join(REMOTION, "src", "data")
    out_path = os.path.join(out_dir, f"{dua_id}.json")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        print("manifest already exists:", out_path)
        return
    with open(os.path.join(PROJECT, "data", "duas.json"), encoding="utf-8") as f:
        duas = json.load(f)
    if not isinstance(duas, list):
        duas = duas.get("duas", [])
    dua = next(d for d in duas if d["id"] == dua_id)

    ar_words = read_words(os.path.join(TEMP, f"{dua_id}_ar_timing.jsonl"))
    ur_words = read_words(os.path.join(TEMP, f"{dua_id}_ur_timing.jsonl"))

    ar_dur = media_duration(os.path.join(TEMP, f"{dua_id}_ar.mp3"))
    urdu_base = ar_dur + GAP_SECONDS
    for w in ur_words:
        w["start"] = round(w["start"] + urdu_base, 3)
        w["end"] = round(w["end"] + urdu_base, 3)

    import wave

    with wave.open(os.path.join(TEMP, f"{dua_id}_merged.wav")) as w:
        total = w.getnframes() / w.getframerate()

    if total < 1.0:
        raise RuntimeError(f"merged audio too short ({total:.3f}s < 1.0s) - reject manifest")

    wav_path = os.path.join(TEMP, f"{dua_id}_merged.wav")
    if not os.path.exists(wav_path) or os.path.getsize(wav_path) <= 0:
        raise RuntimeError("merged wav missing or zero bytes: " + wav_path)

    if not ar_words:
        raise RuntimeError("no arabic WordBoundary events for " + dua_id)
    if not ur_words:
        raise RuntimeError("no urdu WordBoundary events for " + dua_id)

    arabic_end = ar_words[-1]["end"]
    urdu_start = max(ur_words[0]["start"] - 0.05, 0.0)

    audio_dir = os.path.join(REMOTION, "public", "audio")
    os.makedirs(audio_dir, exist_ok=True)
    audio_dst = os.path.join(audio_dir, f"{dua_id}.mp3")
    master_audio(wav_path, audio_dst)
    if not os.path.exists(audio_dst) or os.path.getsize(audio_dst) <= 0:
        raise RuntimeError("mastered mp3 missing or zero bytes: " + audio_dst)

    manifest = {
        "dua_id": dua_id,
        "title": dua["title"],
        "reference": dua["reference"],
        "fps": getattr(project_config, "VIDEO_FPS", 30),
        "width": 1080,
        "height": 1920,
        "totalDuration": round(total, 3),
        "audioFile": f"audio/{dua_id}.mp3",
        "template": resolve_theme(dua),
        "arabicWords": ar_words,
        "urduWords": ur_words,
        "sections": {
            "arabicEnd": round(arabic_end, 3),
            "urduStart": round(urdu_start, 3),
        },
    }
    bg_path, bg_kind = resolve_bg(dua)
    if bg_path:
        manifest["background"] = bg_path
        manifest["backgroundKind"] = bg_kind
        print("background:", bg_path, "|", bg_kind)
    if dua.get("masterpiece"):
        manifest["masterpiece"] = True

    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard", "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as cf:
                cfg = json.load(cf)
            if cfg.get("channelName") or cfg.get("handle"):
                manifest["channel"] = {"name": cfg.get("channelName", ""), "handle": cfg.get("handle", "")}
        except Exception:
            pass

    sfx_dir = os.path.join(REMOTION, "public", "sfx")
    sfx = {}
    for name in ("whoosh", "riser", "tick"):
        if os.path.exists(os.path.join(sfx_dir, name + ".mp3")):
            sfx[name] = f"sfx/{name}.mp3"
    if sfx:
        manifest["sfx"] = sfx

    out_dir = os.path.join(REMOTION, "src", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{dua_id}.json")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    os.replace(tmp_path, out_path)

    print("manifest:", out_path)
    print("audio:", audio_dst)
    print("arabic words:", len(ar_words), "| urdu words:", len(ur_words))
    print(f"total: {total:.2f}s | arabicEnd: {arabic_end:.2f} | urduStart: {urdu_start:.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "rabbana_hasanah")
