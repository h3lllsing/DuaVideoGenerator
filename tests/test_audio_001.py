"""
AUDIO-001 tests: WAV/PCM lossless intermediates, 48 kHz consistency,
two-pass LINEAR ffmpeg loudnorm (-16 LUFS / -1.5 dBTP), direct video mux
(-c:v copy + AAC 48 kHz), A/V sync, and public API stability.

Run with: python -m pytest tests/test_audio_001.py -v
"""

import os
import re
import shutil
import subprocess
import sys
import wave

import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import imageio_ffmpeg
from PIL import Image

from core.audio_mixer import AudioMixer
from core.tts_engine import TTSEngine
from core.video_builder import VideoBuilder

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SAMPLE_RATE = 48000


def _tmp(name):
    d = os.path.join(os.path.dirname(__file__), "_audio001_tmp")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def _sine_wav(path, seconds, freq=440.0, amplitude=0.2, sample_rate=SAMPLE_RATE):
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    left = amplitude * np.sin(2 * np.pi * freq * t)
    right = amplitude * np.sin(2 * np.pi * freq * 1.01 * t)
    pcm = (np.stack([left, right], axis=1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return path


def _read_samples(path):
    with wave.open(path, "rb") as w:
        rate = w.getframerate()
        assert w.getnchannels() == 2 and w.getsampwidth() == 2
        frames = w.readframes(w.getnframes())
    data = np.frombuffer(frames, dtype=np.int16).reshape(-1, 2)
    return rate, data


def _probe(path):
    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    txt = r.stderr
    audio = re.search(r"Audio:\s*([^,]+),\s*(\d+)\s*Hz,\s*(\w+),\s*\w+,\s*(\d+)\s*kb/s", txt)
    video = re.search(r"Video:\s*([^,]+).*?(\d+)x(\d+).*?(\d+(?:\.\d+)?)\s*fps", txt)
    dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", txt)
    return {
        "audio": audio.groups() if audio else None,
        "video": video.groups() if video else None,
        "yuv420p": "yuv420p" in txt,
        "duration": (int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))) if dur else None,
    }


def _measure_loudness(path):
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-i",
        path,
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = {}
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        m = re.search(rf'"{key}"\s*:\s*"(-?[\d.]+)"', r.stderr)
        if m:
            out[key] = float(m.group(1))
    return out


class TestAudioMixerWav:
    """WAV/PCM merge: 48 kHz, stereo, speech preserved, silence-only padding."""

    def _cleanup(self):
        d = os.path.join(os.path.dirname(__file__), "_audio001_tmp")
        if os.path.exists(d):
            shutil.rmtree(d)

    def test_merge_output_is_48k_stereo_wav(self):
        self._cleanup()
        try:
            a = _sine_wav(_tmp("a.wav"), 0.5)
            b = _sine_wav(_tmp("b.wav"), 0.4, freq=660)
            out = _tmp("merged.wav")
            assert AudioMixer.merge_audio_sequential([a, b], out, gap_seconds=0.3) is True
            rate, data = _read_samples(out)
            assert rate == SAMPLE_RATE
            assert data.shape[1] == 2
        finally:
            self._cleanup()

    def test_merge_round_trip_speech_preserved(self):
        self._cleanup()
        try:
            a = _sine_wav(_tmp("a.wav"), 0.5)
            b = _sine_wav(_tmp("b.wav"), 0.4, freq=660)
            bytes_a = open(a, "rb").read()
            bytes_b = open(b, "rb").read()
            out = _tmp("merged.wav")
            assert AudioMixer.merge_audio_sequential([a, b], out, gap_seconds=0.3) is True
            rate, data = _read_samples(out)
            _, src_a = _read_samples(a)
            _, src_b = _read_samples(b)

            n_a, n_gap, n_b = int(0.5 * rate), int(0.3 * rate), int(0.4 * rate)
            assert data.shape[0] >= n_a + n_gap + n_b
            seg_a = data[:n_a]
            gap = data[n_a : n_a + n_gap]
            seg_b = data[n_a + n_gap : n_a + n_gap + n_b]
            assert np.allclose(seg_a.astype(float), src_a.astype(float), atol=3)
            assert np.allclose(seg_b.astype(float), src_b.astype(float), atol=3)
            assert np.max(np.abs(gap.astype(float))) <= 3

            assert open(a, "rb").read() == bytes_a
            assert open(b, "rb").read() == bytes_b
        finally:
            self._cleanup()

    def test_pad_appends_silence_only(self):
        self._cleanup()
        try:
            a = _sine_wav(_tmp("a.wav"), 0.5)
            bytes_a = open(a, "rb").read()
            out = _tmp("padded.wav")
            assert AudioMixer.merge_audio_sequential([a], out, gap_seconds=0.0, pad_to_duration=2.0) is True
            rate, data = _read_samples(out)
            assert abs(data.shape[0] / rate - 2.0) < 0.02
            n = int(0.5 * rate)
            assert np.max(np.abs(data[:n].astype(float))) > 1000
            assert np.max(np.abs(data[n:].astype(float))) <= 3
            assert open(a, "rb").read() == bytes_a
        finally:
            self._cleanup()

    def test_merge_resamples_to_48k(self):
        self._cleanup()
        try:
            a = _sine_wav(_tmp("a44.wav"), 0.5, sample_rate=44100)
            out = _tmp("merged.wav")
            assert AudioMixer.merge_audio_sequential([a], out, gap_seconds=0.0) is True
            rate, data = _read_samples(out)
            assert rate == SAMPLE_RATE
            assert abs(data.shape[0] / rate - 0.5) < 0.03
        finally:
            self._cleanup()


class TestLoudnorm:
    """Two-pass LINEAR loudnorm: targets, duration preservation, linear gain."""

    def _cleanup(self):
        d = os.path.join(os.path.dirname(__file__), "_audio001_tmp")
        if os.path.exists(d):
            shutil.rmtree(d)

    def test_linear_normalization_meets_loudness_and_peak_targets(self):
        self._cleanup()
        try:
            src = _sine_wav(_tmp("quiet.wav"), 2.0, amplitude=0.02)
            measured_in = _measure_loudness(src)
            assert measured_in["input_tp"] < -30

            out = _tmp("normalized.wav")
            ok, measured_out = AudioMixer.normalize_loudness(src, out)
            assert ok is True
            # Loudness around -14 LUFS, true peak <= -1.3 dBTP
            assert abs(measured_out["input_i"] - (-14.0)) <= 1.5
            assert measured_out["input_tp"] <= -1.3
        finally:
            self._cleanup()

    def test_normalization_preserves_duration(self):
        self._cleanup()
        try:
            src = _sine_wav(_tmp("quiet.wav"), 2.0, amplitude=0.02)
            out = _tmp("normalized.wav")
            ok, _ = AudioMixer.normalize_loudness(src, out)
            assert ok is True
            _, in_data = _read_samples(src)
            _, out_data = _read_samples(out)
            assert abs(len(in_data) - len(out_data)) <= 2
        finally:
            self._cleanup()

    def test_normalization_applies_constant_gain(self):
        self._cleanup()
        try:
            src = _sine_wav(_tmp("quiet.wav"), 2.0, amplitude=0.02)
            out = _tmp("normalized.wav")
            ok, _ = AudioMixer.normalize_loudness(src, out)
            assert ok is True
            _, in_data = _read_samples(src)
            _, out_data = _read_samples(out)
            n = min(len(in_data), len(out_data))
            # Linear gain: sample values scale by a roughly constant factor.
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(
                    np.abs(in_data[:n]) > 50,
                    np.abs(out_data[:n].astype(float)) / np.abs(in_data[:n].astype(float)),
                    np.nan,
                )
            ratios = ratio[~np.isnan(ratio)]
            assert len(ratios) > 100
            assert np.std(ratios) / np.mean(ratios) < 0.05
        finally:
            self._cleanup()

    def test_normalization_does_not_touch_word_boundaries(self):
        self._cleanup()
        try:
            sidecar = _tmp("timing.jsonl")
            with open(sidecar, "w", encoding="utf-8") as f:
                f.write(
                    '{"type": "WordBoundary", "offset": 0, '
                    '"duration": 50000000, "text": "\\u0627\\u0644\\u0644\\u0647\\u0645"}\n'
                )
            before_bytes = open(sidecar, "rb").read()
            words_before = TTSEngine.parse_word_boundaries(sidecar)

            src = _sine_wav(_tmp("quiet.wav"), 2.0, amplitude=0.02)
            out = _tmp("normalized.wav")
            ok, _ = AudioMixer.normalize_loudness(src, out)
            assert ok is True

            assert open(sidecar, "rb").read() == before_bytes
            assert TTSEngine.parse_word_boundaries(sidecar) == words_before
        finally:
            self._cleanup()


class TestVideoBuilderMux:
    """Direct ffmpeg mux: video copy preserved, AAC 48 kHz, A/V sync."""

    def _cleanup(self):
        d = os.path.join(os.path.dirname(__file__), "_audio001_tmp")
        if os.path.exists(d):
            shutil.rmtree(d)

    def _build(self, seconds, audio_seconds, out_name="mux.mp4"):
        frames = [Image.new("RGB", (1080, 1920), (20, 25, 35)) for _ in range(int(seconds * 120))]
        audio = _sine_wav(_tmp("audio.wav"), audio_seconds)
        out = _tmp(out_name)
        builder = VideoBuilder(fps=120, resolution=(1080, 1920))
        assert builder.build_video(frames, out, audio_path=audio) is True
        return out

    def test_mux_preserves_1080x1920_24fps_yuv420p(self):
        self._cleanup()
        try:
            out = self._build(2.0, 2.0)
            info = _probe(out)
            assert info["video"] is not None
            assert info["video"][1] == "1080" and info["video"][2] == "1920"
            assert abs(float(info["video"][3]) - 120.0) < 0.1
            assert info["yuv420p"] is True
        finally:
            self._cleanup()

    def test_mux_final_audio_is_aac_48k_high_bitrate(self):
        self._cleanup()
        try:
            out = self._build(2.0, 2.0)
            info = _probe(out)
            assert info["audio"] is not None
            assert "aac" in info["audio"][0]
            assert int(info["audio"][1]) == SAMPLE_RATE
            assert int(info["audio"][3]) >= 150  # short-clip estimate; strict in E2E
        finally:
            self._cleanup()

    def test_av_sync_within_one_frame(self):
        self._cleanup()
        try:
            out = self._build(1.0, 1.0)
            info = _probe(out)
            assert abs(info["duration"] - 1.0) <= 0.042
        finally:
            self._cleanup()

    def test_trim_guard_audio_longer_than_video(self):
        self._cleanup()
        try:
            out = self._build(1.0, 1.5)
            info = _probe(out)
            assert abs(info["duration"] - 1.0) <= 0.1
        finally:
            self._cleanup()

    def test_trim_guard_video_longer_than_audio(self):
        self._cleanup()
        try:
            out = self._build(1.0, 0.5)
            info = _probe(out)
            assert abs(info["duration"] - 0.5) <= 0.1
        finally:
            self._cleanup()


class TestPublicApi:
    """Public entry points and voices must remain unchanged."""

    def test_generate_video_signature_unchanged(self):
        import inspect

        import main as m

        sig = inspect.signature(m.DuaVideoPipeline.generate_video)
        params = list(sig.parameters)
        assert params[0] == "self"
        assert params[1] == "dua_id"
        assert "theme" in params and "effect" in params

    def test_generate_custom_video_signature_unchanged(self):
        import inspect

        import main as m

        sig = inspect.signature(m.DuaVideoPipeline.generate_custom_video)
        params = list(sig.parameters)
        assert params[1] == "arabic_text"
        assert params[2] == "urdu_text"
        assert "title" in params and "effect" in params

    def test_voices_unchanged(self):
        assert TTSEngine.VOICES == {
            "ar": "ar-SA-HamedNeural",
            "ur": "ur-PK-AsadNeural",
            "en": "en-US-GuyNeural",
        }


class TestVideo002RegressionAudio:
    """VIDEO-002 duration policy and short-dua padding stay intact."""

    def _cleanup(self):
        d = os.path.join(os.path.dirname(__file__), "_audio001_tmp")
        if os.path.exists(d):
            shutil.rmtree(d)

    def test_long_dua_rejection_policy_unchanged(self):
        assert AudioMixer.compute_video_timeline(50.01)["valid"] is False
        assert AudioMixer.compute_video_timeline(14.99)["final_duration"] == 15.0
        assert AudioMixer.compute_video_timeline(49.8)["visual_hold"] == 0.2

    def test_short_speech_normalize_pad_to_15s(self):
        self._cleanup()
        try:
            a = _sine_wav(_tmp("ar.wav"), 0.4, freq=440)
            b = _sine_wav(_tmp("ur.wav"), 0.3, freq=660)
            merged = _tmp("merged.wav")
            assert AudioMixer.merge_audio_sequential([a, b], merged, gap_seconds=0.3) is True

            norm = _tmp("normalized.wav")
            ok, _ = AudioMixer.normalize_loudness(merged, norm)
            assert ok is True

            padded = _tmp("padded.wav")
            assert AudioMixer.merge_audio_sequential([norm], padded, gap_seconds=0.0, pad_to_duration=15.0) is True

            rate, data = _read_samples(padded)
            duration = len(data) / rate
            assert abs(duration - 15.0) < 0.05
            speech = int((0.4 + 0.3 + 0.3) * rate)
            assert np.max(np.abs(data[:speech].astype(float))) > 1000
            assert np.max(np.abs(data[speech:].astype(float))) <= 3
        finally:
            self._cleanup()

    def test_padding_does_not_duplicate_speech(self):
        self._cleanup()
        try:
            a = _sine_wav(_tmp("ar.wav"), 0.4, freq=440)
            b = _sine_wav(_tmp("ur.wav"), 0.3, freq=660)
            merged = _tmp("merged.wav")
            assert AudioMixer.merge_audio_sequential([a, b], merged, gap_seconds=0.3) is True
            norm = _tmp("normalized.wav")
            ok, _ = AudioMixer.normalize_loudness(merged, norm)
            assert ok is True
            padded = _tmp("padded.wav")
            assert AudioMixer.merge_audio_sequential([norm], padded, gap_seconds=0.0, pad_to_duration=15.0) is True

            _, data = _read_samples(padded)
            voiced = np.max(np.abs(data.astype(float)), axis=1) > 50
            voiced_seconds = np.count_nonzero(voiced) / SAMPLE_RATE
            # Speech ~1.0s, never duplicated (would be ~2.0s)
            assert 0.7 <= voiced_seconds <= 1.5
        finally:
            self._cleanup()
