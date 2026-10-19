"""
Shared pytest fixtures for DuaVideoGenerator test suite.
"""

import os
import sys

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.project_info import PROJECT


@pytest.fixture
def project():
    """Return the PROJECT singleton instance."""
    return PROJECT


@pytest.fixture
def tmp_dir(tmp_path):
    """Return a temporary directory for test artifacts."""
    return tmp_path


@pytest.fixture
def sample_image():
    """Return a 1080x1920 RGB test image."""
    from PIL import Image

    return Image.new("RGB", (1080, 1920), (20, 25, 35))


@pytest.fixture
def sample_rgba_image():
    """Return a 1080x1920 RGBA test image with transparency."""
    from PIL import Image

    return Image.new("RGBA", (1080, 1920), (20, 25, 35, 200))


@pytest.fixture
def sample_frames(sample_image):
    """Return a list of 10 test frames."""
    return [sample_image.copy() for _ in range(10)]


@pytest.fixture
def sample_dua_data():
    """Return sample dua data for testing."""
    return {
        "id": "test_dua_001",
        "category": "morning",
        "arabic": "بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ",
        "urdu": "اللہ کے نام سے شروع جو بڑا مہربان نہایت رحم والا ہے",
        "title": "Bismillah",
        "translation": "In the name of Allah, the Most Gracious, the Most Merciful",
    }


@pytest.fixture
def mock_tts(monkeypatch):
    """Mock TTS engine for offline testing — generates silent WAV files."""
    import wave
    import struct

    def _mock_generate(text, language, output_path, timing_path=None, voice=None):
        """Generate a 1-second silent WAV as TTS mock."""
        sample_rate = 24000
        duration = max(0.5, min(3.0, len(text.split()) * 0.3))
        n_frames = int(sample_rate * duration)
        with wave.open(output_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack("<" + "h" * n_frames, *([0] * n_frames)))
        if timing_path:
            import json

            words = text.split()
            step = duration / max(len(words), 1)
            with open(timing_path, "w", encoding="utf-8") as f:
                for i, w in enumerate(words):
                    f.write(json.dumps({"text": w, "offset": i * step, "duration": step}) + "\n")
        return True

    def _mock_generate_both(
        ar_text, ur_text, ar_output, ur_output, ar_timing=None, ur_timing=None, ar_voice=None, ur_voice=None
    ):
        ok_ar = _mock_generate(ar_text, "ar", ar_output, ar_timing, ar_voice)
        ok_ur = _mock_generate(ur_text, "ur", ur_output, ur_timing, ur_voice)
        return (ok_ar, ok_ur)

    monkeypatch.setattr("core.tts_engine.TTSEngine.generate_audio", staticmethod(_mock_generate))
    monkeypatch.setattr("core.tts_engine.TTSEngine.generate_both", staticmethod(_mock_generate_both))
    return _mock_generate
