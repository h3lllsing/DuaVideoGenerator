"""
Tests for core.effects_engine module
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from core.effects_engine import EffectsEngine


class TestEffectsEngineInit:
    """Test EffectsEngine initialization."""

    def test_default_dimensions(self):
        engine = EffectsEngine()
        assert engine.width == 1080
        assert engine.height == 1920

    def test_custom_dimensions(self):
        engine = EffectsEngine(640, 480)
        assert engine.width == 640
        assert engine.height == 480

    def test_effects_registry_has_11(self):
        engine = EffectsEngine()
        assert len(engine.effects) == 11


class TestApplyEffect:
    """Test apply_effect dispatcher."""

    def test_known_effect_dispatch(self):
        engine = EffectsEngine()
        img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))
        result = engine.apply_effect("neon_glow", img, 0, 10)
        assert result.size == (1080, 1920)

    def test_unknown_effect_fallback(self):
        engine = EffectsEngine()
        img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))
        result = engine.apply_effect("nonexistent", img, 0, 10)
        assert result.size == (1080, 1920)


class TestNeonGlow:
    """Test neon_glow effect."""

    def test_output_same_size(self):
        engine = EffectsEngine()
        img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))
        result = engine.neon_glow(img, 5, 10)
        assert result.size == (1080, 1920)


class TestMetallicGold:
    """Test metallic_gold effect."""

    def test_output_same_size(self):
        engine = EffectsEngine()
        img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))
        result = engine.metallic_gold(img, 5, 10)
        assert result.size == (1080, 1920)


class TestTypewriter:
    """Test typewriter effect."""

    def test_frame_zero_empty(self):
        engine = EffectsEngine()
        img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))
        result = engine.typewriter(img, 0, 10)
        assert result.size == (1080, 1920)

    def test_full_frame_complete(self):
        engine = EffectsEngine()
        img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))
        result = engine.typewriter(img, 10, 10)
        assert result.size == (1080, 1920)


class TestWave:
    """Test wave effect."""

    def test_output_same_size(self):
        engine = EffectsEngine()
        img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))
        result = engine.wave(img, 5, 10)
        assert result.size == (1080, 1920)


class TestGlitch:
    """Test glitch effect."""

    def test_deterministic(self):
        engine = EffectsEngine()
        img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))
        r1 = engine.glitch(img, 5, 10)
        r2 = engine.glitch(img, 5, 10)
        assert np.array_equal(np.array(r1), np.array(r2))


class TestApplyToFrames:
    """Test apply_to_frames method."""

    def test_empty_list(self):
        engine = EffectsEngine()
        result = engine.apply_to_frames([], "neon_glow")
        assert result == []

    def test_none_effect(self):
        engine = EffectsEngine()
        frames = [Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))]
        result = engine.apply_to_frames(frames, None)
        assert len(result) == 1

    def test_invalid_effect_returns_original(self):
        engine = EffectsEngine()
        frames = [Image.new("RGBA", (1080, 1920), (255, 255, 255, 255))]
        result = engine.apply_to_frames(frames, "invalid_effect")
        assert len(result) == 1


class TestApplyPlan:
    """Test apply_plan method."""

    def test_empty_frames(self):
        engine = EffectsEngine()
        result = engine.apply_plan([], [])
        assert result == []

    def test_plan_length_mismatch(self):
        engine = EffectsEngine()
        frames = [Image.new("RGB", (1080, 1920), (255, 255, 255)) for _ in range(5)]
        plan = [{"specs": []}] * 3  # mismatched length
        result = engine.apply_plan(frames, plan)
        assert len(result) == 5  # returns unchanged


class TestFxVignette:
    """Test _fx_vignette effect."""

    def test_strength_zero_no_change(self):
        engine = EffectsEngine()
        arr = np.full((1920, 1080, 3), 128, dtype=np.uint8)
        result = engine._fx_vignette(arr, {"strength": 0.0}, 42, 0, 10)
        np.testing.assert_array_equal(result, arr)


class TestFxGrain:
    """Test _fx_grain effect."""

    def test_strength_zero_no_change(self):
        engine = EffectsEngine()
        arr = np.full((1920, 1080, 3), 128, dtype=np.uint8)
        result = engine._fx_grain(arr, {"strength": 0.0}, 42, 0, 10)
        np.testing.assert_array_equal(result, arr)


class TestFxBreathing:
    """Test _fx_breathing effect."""

    def test_amp_zero_no_change(self):
        engine = EffectsEngine()
        arr = np.full((1920, 1080, 3), 128, dtype=np.uint8)
        result = engine._fx_breathing(arr, {"amp": 0.0}, 42, 0, 10)
        np.testing.assert_array_equal(result, arr)


class TestFxGoldShimmer:
    """Test _fx_gold_shimmer effect."""

    def test_intensity_zero_no_change(self):
        engine = EffectsEngine()
        arr = np.full((1920, 1080, 3), 128, dtype=np.uint8)
        result = engine._fx_gold_shimmer(arr, {"intensity": 0.0}, 42, 0, 10)
        np.testing.assert_array_equal(result, arr)


class TestFxRtlReveal:
    """Test _fx_rtl_reveal effect."""

    def test_fraction_one_output_same_size(self):
        engine = EffectsEngine()
        arr = np.full((1920, 1080, 3), 128, dtype=np.uint8)
        result = engine._fx_rtl_reveal(arr, {"fraction": 1.0}, 42, 0, 10)
        assert result.shape == arr.shape


class TestFxWordPulse:
    """Test _fx_word_pulse effect."""

    def test_strength_zero_no_change(self):
        engine = EffectsEngine()
        arr = np.full((1920, 1080, 3), 128, dtype=np.uint8)
        result = engine._fx_word_pulse(arr, 0.0, (255, 215, 0), 42)
        np.testing.assert_array_equal(result, arr)
