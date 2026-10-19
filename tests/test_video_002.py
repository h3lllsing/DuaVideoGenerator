"""
VIDEO-002 tests: 15-50s duration policy, exact 30 FPS gate, short-dua padding,
long-dua hold reduction, and edge-tts word-boundary parsing.

Run with: python -m pytest tests/test_video_002.py -v
"""

import os
import shutil
import sys
import wave

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from core.audio_mixer import AudioMixer
from core.quality_checker import QualityChecker
from core.tts_engine import TTSEngine
from core.video_builder import VideoBuilder


class TestDurationPolicy:
    """VIDEO-002 timeline policy (compute_video_timeline)."""

    def test_short_speech_pads_to_minimum(self):
        timeline = AudioMixer.compute_video_timeline(5.0)
        assert timeline["valid"] is True
        assert timeline["final_duration"] == 15.0
        assert timeline["visual_hold"] == 10.0

    def test_speech_just_below_minimum_pads(self):
        timeline = AudioMixer.compute_video_timeline(14.99)
        assert timeline["valid"] is True
        assert timeline["final_duration"] == 15.0

    def test_minimum_speech_gets_default_hold(self):
        timeline = AudioMixer.compute_video_timeline(15.0)
        assert timeline["valid"] is True
        assert timeline["final_duration"] == 15.5
        assert timeline["visual_hold"] == 0.5

    def test_normal_speech_valid(self):
        timeline = AudioMixer.compute_video_timeline(20.0)
        assert timeline["valid"] is True
        assert timeline["final_duration"] == 20.5

    def test_near_max_reduces_hold(self):
        timeline = AudioMixer.compute_video_timeline(49.8)
        assert timeline["valid"] is True
        assert timeline["final_duration"] <= 50.0
        assert timeline["visual_hold"] == 0.2

    def test_exact_max_has_no_hold(self):
        timeline = AudioMixer.compute_video_timeline(50.0)
        assert timeline["valid"] is True
        assert timeline["final_duration"] == 50.0
        assert timeline["visual_hold"] == 0.0

    def test_over_max_speech_is_hard_failure(self):
        timeline = AudioMixer.compute_video_timeline(50.01)
        assert timeline["valid"] is False
        assert timeline["final_duration"] is None

    def test_negative_speech_rejected(self):
        timeline = AudioMixer.compute_video_timeline(-1.0)
        assert timeline["valid"] is False


class TestQualityCheckerVideo002:
    """QualityChecker duration boundaries, exact FPS, config-driven values."""

    def test_min_duration_configured(self):
        qc = QualityChecker()
        assert qc.min_duration == 15.0
        assert qc.max_duration == 50.0
        assert qc.required_fps == 30.0

    def test_duration_boundaries(self):
        qc = QualityChecker()
        assert qc.validate_duration(14.99) is False
        assert qc.validate_duration(15.00) is True
        assert qc.validate_duration(49.99) is True
        assert qc.validate_duration(50.00) is True
        assert qc.validate_duration(50.01) is False

    def test_fps_exact_30(self):
        qc = QualityChecker()
        assert qc.validate_fps(30.0) is True
        assert qc.validate_fps(29.98) is False
        assert qc.validate_fps(45.0) is False

    def test_resolution_unchanged(self):
        qc = QualityChecker()
        assert qc.validate_resolution(1080, 1920) is True
        assert qc.validate_resolution(1088, 1920) is False
        assert qc.validate_resolution(720, 1280) is False

    def test_check_video_reports_short_duration_failure(self):
        tmp_dir = os.path.join(os.path.dirname(__file__), "_video002_tmp")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        try:
            builder = VideoBuilder(fps=80, resolution=(1080, 1920))
            frame = Image.new("RGB", (1080, 1920), (20, 25, 35))
            output_path = os.path.join(tmp_dir, "short.mp4")
            assert builder.build_video([frame] * 80, output_path) is True

            results = QualityChecker().check_video(output_path)
            assert results["valid"] is False
            assert results["video_info"]["width"] == 1080
            assert results["video_info"]["height"] == 1920
            assert results["video_info"]["fps"] == 80
            assert any("Duration:" in i and "FAIL" in i for i in results["issues"])
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestWordBoundaryParser:
    """edge-tts WordBoundary JSONL parsing (100ns ticks -> seconds)."""

    def _write_sample(self, path):
        lines = [
            '{"type": "WordBoundary", "offset": 0, "duration": 50000000, "text": "\\u0627\\u0644\\u0644\\u0647\\u0645"}',
            '{"type": "WordBoundary", "offset": 50000000, "duration": 40000000, "text": "\\u0627\\u0646\\u064a"}',
            '{"type": "SentenceBoundary", "offset": 0, "duration": 100, "text": "x"}',
            "not-valid-json",
            '{"type": "WordBoundary", "offset": 90000000, "duration": 30000000, "text": "\\u0627\\u0633\\u0627\\u0644\\u0643"}',
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def test_parse_valid_boundaries(self):
        tmp = os.path.join(os.path.dirname(__file__), "_v002_timing.jsonl")
        try:
            self._write_sample(tmp)
            words = TTSEngine.parse_word_boundaries(tmp)
            assert len(words) == 3
            assert words[0]["word"] == "\u0627\u0644\u0644\u0647\u0645"
            assert words[0]["offset"] == 0.0
            assert words[0]["duration"] == 5.0
            assert words[0]["end"] == 5.0
            assert words[1]["offset"] == 5.0
            assert words[1]["duration"] == 4.0
            assert words[1]["end"] == 9.0
            assert words[2]["offset"] == 9.0
            assert words[2]["duration"] == 3.0
            assert words[2]["end"] == 12.0
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_missing_file_returns_empty(self):
        assert TTSEngine.parse_word_boundaries(os.path.join(os.path.dirname(__file__), "_nope.jsonl")) == []


class TestAudioMixerPadding:
    """merge_audio_sequential pad_to_duration appends silence, speech unchanged."""

    def _make_wav(self, path, seconds, sample_rate=44100):
        with wave.open(path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            n = int(sample_rate * seconds)
            w.writeframes(b"\x00\x00\x00\x00" * n)

    def test_pad_appends_silence_without_touching_speech(self):
        tmp_dir = os.path.join(os.path.dirname(__file__), "_v002_audio_tmp")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        try:
            wav1 = os.path.join(tmp_dir, "a.wav")
            wav2 = os.path.join(tmp_dir, "b.wav")
            self._make_wav(wav1, 0.5)
            self._make_wav(wav2, 0.4)
            bytes1 = open(wav1, "rb").read()
            bytes2 = open(wav2, "rb").read()

            unpadded = os.path.join(tmp_dir, "unpadded.wav")
            assert AudioMixer.merge_audio_sequential([wav1, wav2], unpadded, gap_seconds=0.0) is True
            from moviepy import AudioFileClip

            speech_dur = AudioFileClip(unpadded).duration

            padded = os.path.join(tmp_dir, "padded.wav")
            assert AudioMixer.merge_audio_sequential([wav1, wav2], padded, gap_seconds=0.0, pad_to_duration=3.0) is True
            padded_dur = AudioFileClip(padded).duration

            # Speech sources unchanged (not stretched, not duplicated)
            assert open(wav1, "rb").read() == bytes1
            assert open(wav2, "rb").read() == bytes2

            # Speech preserved; track padded with silence to ~3.0s
            assert abs(speech_dur - 0.9) < 0.1
            assert abs(padded_dur - 3.0) < 0.15
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
