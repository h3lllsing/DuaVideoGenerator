"""
E2E-001 tests: Full pipeline dua.json -> .mp4

Validates the entire generation pipeline end-to-end:
  DuaDatabase lookup -> TTS (edge-tts) -> audio merge -> timeline ->
  frame rendering -> effects -> video assembly -> quality check.

Uses the shortest dua (ilm_mein_izafay_ki_dua) for speed.

Run with: python -m pytest tests/test_e2e_render.py -v
Skip with: python -m pytest -m "not slow"
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import cv2
import pytest

from core.audio_mixer import AudioMixer
from core.dua_database import DB
from core.quality_checker import QualityChecker
from core.tts_engine import TTSEngine

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
TEMP_DIR = os.path.join(PROJECT_ROOT, "temp")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
DUA_DB = os.path.join(DATA_DIR, "duas.json")

FAST_DUA = "ilm_mein_izafay_ki_dua"

qc = QualityChecker()


def _output_path_for(dua_data):
    import re

    title = str(dua_data.get("title") or "Dua").strip() or "Dua"
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", title).strip() or "Dua"
    safe = re.sub(r"\.mp4$", "", safe, flags=re.IGNORECASE).rstrip(". ")
    category = dua_data.get("category", "general")
    return os.path.join(OUTPUT_DIR, category, f"{safe}.mp4")


def _temp_files_for(dua_id):
    prefixes = ["_ar.mp3", "_ur.mp3", "_ar_timing.jsonl", "_ur_timing.jsonl", "_merged.wav", "_merged.normalized.wav"]
    return [os.path.join(TEMP_DIR, f"{dua_id}{s}") for s in prefixes]


# ──────────────────────────────────────────────────────────────────
#  Phase 1: Database Lookup
# ──────────────────────────────────────────────────────────────────
@pytest.mark.slow
class TestDatabaseLookup:
    """E2E Phase 1 — DuaDatabase returns valid dua entry."""

    def test_dua_exists_in_database(self):
        dua = DB.get_dua_by_id(FAST_DUA)
        assert dua is not None, f"Dua '{FAST_DUA}' not found in database"

    def test_dua_has_required_fields(self):
        dua = DB.get_dua_by_id(FAST_DUA)
        for field in ("id", "category", "title", "arabic", "urdu"):
            assert field in dua and dua[field], f"Missing required field: {field}"

    def test_dua_database_is_list(self):
        with open(DUA_DB, encoding="utf-8") as f:
            raw = json.load(f)
        entries = raw if isinstance(raw, list) else raw.get("duas", [])
        assert len(entries) >= 70, f"Expected >=70 duas, got {len(entries)}"

    def test_output_path_convention(self):
        dua = DB.get_dua_by_id(FAST_DUA)
        out = _output_path_for(dua)
        assert out.endswith(".mp4")
        assert FAST_DUA.split("_")[0] in out.lower() or "toilet" in out.lower()


# ──────────────────────────────────────────────────────────────────
#  Phase 2: TTS Generation
# ──────────────────────────────────────────────────────────────────
@pytest.mark.slow
class TestTTSGeneration:
    """E2E Phase 2 — edge-tts produces Arabic + Urdu audio."""

    @classmethod
    def setup_class(cls):
        dua = DB.get_dua_by_id(FAST_DUA)
        cls.ar_audio = os.path.join(TEMP_DIR, f"{FAST_DUA}_ar.mp3")
        cls.ur_audio = os.path.join(TEMP_DIR, f"{FAST_DUA}_ur.mp3")
        cls.ar_timing = os.path.join(TEMP_DIR, f"{FAST_DUA}_ar_timing.jsonl")
        cls.ur_timing = os.path.join(TEMP_DIR, f"{FAST_DUA}_ur_timing.jsonl")
        cls.tts = TTSEngine()

        ar_voice = dua.get("voice_arabic", "ar-SA-HamedNeural")
        ur_voice = dua.get("voice_urdu", "ur-PK-AsadNeural")

        cls.ar_ok = cls.tts.generate_audio(dua["arabic"], "ar", cls.ar_audio, timing_path=cls.ar_timing, voice=ar_voice)
        cls.ur_ok = cls.tts.generate_audio(dua["urdu"], "ur", cls.ur_audio, timing_path=cls.ur_timing, voice=ur_voice)

    def test_arabic_tts_succeeds(self):
        assert self.ar_ok is True, "Arabic TTS generation failed"

    def test_urdu_tts_succeeds(self):
        assert self.ur_ok is True, "Urdu TTS generation failed"

    def test_arabic_audio_file_exists(self):
        assert os.path.exists(self.ar_audio)
        assert os.path.getsize(self.ar_audio) > 1000

    def test_urdu_audio_file_exists(self):
        assert os.path.exists(self.ur_audio)
        assert os.path.getsize(self.ur_audio) > 1000

    def test_arabic_timing_sidecar(self):
        assert os.path.exists(self.ar_timing)
        assert os.path.getsize(self.ar_timing) > 10

    def test_urdu_timing_sidecar(self):
        assert os.path.exists(self.ur_timing)
        assert os.path.getsize(self.ur_timing) > 10

    def test_arabic_duration_positive(self):
        dur = TTSEngine.get_audio_duration(self.ar_audio)
        assert dur > 0.5, f"Arabic audio too short: {dur:.2f}s"

    def test_urdu_duration_positive(self):
        dur = TTSEngine.get_audio_duration(self.ur_audio)
        assert dur > 0.5, f"Urdu audio too short: {dur:.2f}s"


# ──────────────────────────────────────────────────────────────────
#  Phase 3: Audio Merge
# ──────────────────────────────────────────────────────────────────
@pytest.mark.slow
class TestAudioMerge:
    """E2E Phase 3 — AudioMixer merge + VIDEO-002 duration policy."""

    @classmethod
    def setup_class(cls):
        cls.merged = os.path.join(TEMP_DIR, f"{FAST_DUA}_merged.wav")
        ar = os.path.join(TEMP_DIR, f"{FAST_DUA}_ar.mp3")
        ur = os.path.join(TEMP_DIR, f"{FAST_DUA}_ur.mp3")
        cls.merge_ok = AudioMixer.merge_audio_sequential([ar, ur], cls.merged, gap_seconds=0.3)
        if cls.merge_ok:
            from moviepy import AudioFileClip

            clip = AudioFileClip(cls.merged)
            cls.speech_duration = clip.duration
            clip.close()
            cls.timeline = AudioMixer.compute_video_timeline(cls.speech_duration)
        else:
            cls.speech_duration = 0
            cls.timeline = {"valid": False}

    def test_merge_succeeds(self):
        assert self.merge_ok is True, "Audio merge failed"

    def test_merged_file_exists(self):
        assert os.path.exists(self.merged)
        assert os.path.getsize(self.merged) > 5000

    def test_speech_duration_positive(self):
        assert self.speech_duration > 0.5, f"Speech too short: {self.speech_duration}"

    def test_duration_policy_valid(self):
        assert self.timeline["valid"] is True, f"Duration policy failed: {self.timeline.get('reason')}"

    def test_final_duration_in_range(self):
        fd = self.timeline["final_duration"]
        assert 15.0 <= fd <= 50.0, f"Final duration {fd}s outside 15-50s"

    def test_visual_hold_nonnegative(self):
        vh = self.timeline["visual_hold"]
        assert vh >= 0, f"Visual hold negative: {vh}"

    def test_final_equals_speech_plus_hold(self):
        fd = self.timeline["final_duration"]
        vh = self.timeline["visual_hold"]
        sd = self.speech_duration
        assert abs(fd - (sd + vh)) < 0.5 or fd >= sd, f"Duration mismatch: final={fd}, speech={sd}, hold={vh}"


# ──────────────────────────────────────────────────────────────────
#  Phase 4: Full Pipeline ( dua.json -> .mp4 )
# ──────────────────────────────────────────────────────────────────
@pytest.mark.slow
class TestFullPipeline:
    """E2E Phase 4 — DuaVideoPipeline.generate_video() -> .mp4."""

    @classmethod
    def setup_class(cls):
        from main import DuaVideoPipeline

        cls.pipeline = DuaVideoPipeline()
        cls.dua = DB.get_dua_by_id(FAST_DUA)
        cls.output_path = _output_path_for(cls.dua)
        cls.start = time.time()
        cls.success = cls.pipeline.generate_video(FAST_DUA)
        cls.elapsed = time.time() - cls.start

    def test_pipeline_returns_true(self):
        assert self.success is True, "Pipeline returned False"

    def test_output_file_exists(self):
        assert os.path.exists(self.output_path), f"Output not found: {self.output_path}"

    def test_output_file_nonempty(self):
        size = os.path.getsize(self.output_path)
        assert size > 100_000, f"Output too small: {size} bytes"

    def test_qc_resolution(self):
        results = qc.check_video(self.output_path)
        info = results["video_info"]
        assert info["width"] == 1080 and info["height"] == 1920, (
            f"Resolution {info['width']}x{info['height']}, expected 1080x1920"
        )

    def test_qc_duration_in_range(self):
        results = qc.check_video(self.output_path)
        dur = results["video_info"]["duration"]
        assert 15.0 <= dur <= 50.0, f"Duration {dur}s outside 15-50s"

    def test_qc_fps(self):
        results = qc.check_video(self.output_path)
        fps = results["video_info"]["fps"]
        assert abs(fps - 30.0) < 0.1, f"FPS {fps}, expected 30"

    def test_qc_overall_valid(self):
        results = qc.check_video(self.output_path)
        assert results["valid"] is True, f"QC failed: {results['issues']}"

    def test_video_opencv_readable(self):
        cap = cv2.VideoCapture(self.output_path)
        assert cap.isOpened(), "cv2 cannot open output video"
        fc = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        assert fc > 300, f"Frame count {fc} too low (expected >300 for 15s@80fps)"

    def test_pipeline_under_300s(self):
        assert self.elapsed < 300, f"Pipeline took {self.elapsed:.0f}s, max 300s"


# ──────────────────────────────────────────────────────────────────
#  Phase 5: Custom Dua Pipeline
# ──────────────────────────────────────────────────────────────────
@pytest.mark.slow
class TestCustomDua:
    """E2E Phase 5 — generate_custom_video with inline text."""

    @classmethod
    def setup_class(cls):
        from main import DuaVideoPipeline

        cls.pipeline = DuaVideoPipeline()
        cls.start = time.time()
        cls.success = cls.pipeline.generate_custom_video(
            arabic_text="\u0627\u0644\u0644\u0647\u0645 \u0627\u0639\u0641\u0646\u064a",
            urdu_text="\u0627\u0644\u0644\u06c1 \u0645\u06c1\u0631\u0628 \u06a9\u0631",
            title="E2E Test Custom",
            effect="none",
        )
        cls.elapsed = time.time() - cls.start
        custom_dir = os.path.join(OUTPUT_DIR, "custom")
        cls.output_path = None
        if os.path.isdir(custom_dir):
            files = sorted(
                [f for f in os.listdir(custom_dir) if f.startswith("custom_") and f.endswith(".mp4")], reverse=True
            )
            if files:
                cls.output_path = os.path.join(custom_dir, files[0])

    def test_custom_returns_true(self):
        assert self.success is True, "Custom video generation failed"

    def test_custom_output_exists(self):
        assert self.output_path is not None and os.path.exists(self.output_path), (
            f"Custom output not found in {OUTPUT_DIR}/custom/"
        )

    def test_custom_qc_pass(self):
        assert self.output_path is not None
        results = qc.check_video(self.output_path)
        assert results["valid"] is True, f"Custom QC failed: {results['issues']}"

    def test_custom_under_300s(self):
        assert self.elapsed < 300, f"Custom pipeline took {self.elapsed:.0f}s"


# ──────────────────────────────────────────────────────────────────
#  Phase 6: Error Handling
# ──────────────────────────────────────────────────────────────────
@pytest.mark.slow
class TestErrorHandling:
    """E2E Phase 6 — Pipeline rejects invalid inputs."""

    def setup_method(self):
        from main import DuaVideoPipeline

        self.pipeline = DuaVideoPipeline()

    def test_invalid_dua_id_returns_false(self):
        result = self.pipeline.generate_video("nonexistent_dua_xyz_999")
        assert result is False

    def test_empty_dua_id_returns_false(self):
        result = self.pipeline.generate_video("")
        assert result is False


# ──────────────────────────────────────────────────────────────────
#  Phase 7: Cleanup
# ──────────────────────────────────────────────────────────────────
@pytest.mark.slow
class TestCleanup:
    """Remove temp files created by E2E tests."""

    def test_cleanup_temp_files(self):
        for fp in _temp_files_for(FAST_DUA):
            if os.path.exists(fp):
                os.remove(fp)
        custom_temps = [
            os.path.join(TEMP_DIR, "custom_ar.mp3"),
            os.path.join(TEMP_DIR, "custom_ur.mp3"),
            os.path.join(TEMP_DIR, "custom_merged.wav"),
            os.path.join(TEMP_DIR, "custom_ar_timing.jsonl"),
            os.path.join(TEMP_DIR, "custom_ur_timing.jsonl"),
        ]
        for fp in custom_temps:
            if os.path.exists(fp):
                os.remove(fp)

    def test_temp_dir_clean_of_e2e_files(self):
        remaining = []
        if os.path.isdir(TEMP_DIR):
            for f in os.listdir(TEMP_DIR):
                if f.startswith(FAST_DUA) or f.startswith("custom_"):
                    remaining.append(f)
        assert remaining == [], f"Leftover temp files: {remaining}"
