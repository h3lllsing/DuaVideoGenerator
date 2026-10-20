"""
Tests for core.revamp_engine module
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.revamp_engine import AVAILABLE_EFFECTS, RevampEngine


class TestRevampEngineInit:
    """Test RevampEngine initialization."""

    def test_init_populates_effects(self):
        engine = RevampEngine()
        assert len(engine.effects) == 15

    def test_init_populates_colors(self):
        engine = RevampEngine()
        assert len(engine.color_schemes) == 5


class TestGetAvailableEffects:
    """Test get_available_effects method."""

    def test_returns_copy(self):
        engine = RevampEngine()
        effects = engine.get_available_effects()
        effects.append("fake_effect")
        assert "fake_effect" not in engine.get_available_effects()

    def test_contents(self):
        engine = RevampEngine()
        effects = engine.get_available_effects()
        expected = [
            "neon_glow",
            "metallic_gold",
            "typewriter",
            "bounce",
            "wave",
            "glitch",
            "bloom_glow",
            "gold_shimmer",
            "breathing",
            "rtl_reveal",
            "glitch_v2",
            "word_pulse",
            "aurora",
            "title_hook",
            "summary_card",
        ]
        assert effects == expected


class TestGetAvailableColors:
    """Test get_available_colors method."""

    def test_returns_correct_schemes(self):
        engine = RevampEngine()
        colors = engine.get_available_colors()
        assert sorted(colors) == ["cyan", "gold", "green", "purple", "red"]


class TestColorSchemesStructure:
    """Test color scheme structure."""

    def test_has_required_keys(self):
        engine = RevampEngine()
        for _name, scheme in engine.color_schemes.items():
            assert "primary" in scheme
            assert "secondary" in scheme
            assert "background" in scheme

    def test_tuples_are_valid_rgb(self):
        engine = RevampEngine()
        for _name, scheme in engine.color_schemes.items():
            for key in ("primary", "secondary", "background"):
                assert isinstance(scheme[key], tuple)
                assert len(scheme[key]) == 3
                assert all(0 <= v <= 255 for v in scheme[key])


class TestMutationIsolation:
    """Test that instances are isolated from module-level mutations."""

    def test_instance_not_affected_by_module_mutation(self):
        engine = RevampEngine()
        original_count = len(engine.effects)
        AVAILABLE_EFFECTS.append("rogue_effect")
        assert len(engine.effects) == original_count
        AVAILABLE_EFFECTS.pop()

    def test_multiple_instances_independent(self):
        e1 = RevampEngine()
        e2 = RevampEngine()
        e1.effects.append("custom")
        assert "custom" not in e2.effects
