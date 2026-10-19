"""
Tests for core.easing module
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.easing import (
    CURVES,
    apple,
    apply,
    clamp01,
    ease_in,
    ease_in_out,
    ease_out,
    ease_out_back,
    ease_out_cubic,
    ease_out_expo,
    ease_out_quart,
    ease_out_quint,
    material,
)


class TestClamp01:
    """Test clamp01 boundary conditions."""

    def test_clamp_at_zero(self):
        assert clamp01(0.0) == 0.0

    def test_clamp_at_one(self):
        assert clamp01(1.0) == 1.0

    def test_clamp_below_zero(self):
        assert clamp01(-0.5) == 0.0

    def test_clamp_above_one(self):
        assert clamp01(1.5) == 1.0

    def test_clamp_midpoint(self):
        assert clamp01(0.5) == 0.5


class TestEaseOutFamily:
    """Test ease-out curves."""

    def test_ease_out_at_zero(self):
        assert ease_out(0.0) == 0.0

    def test_ease_out_at_one(self):
        assert ease_out(1.0) == 1.0

    def test_ease_out_midpoint(self):
        # 1 - (1-0.5)^3 = 1 - 0.125 = 0.875
        assert abs(ease_out(0.5) - 0.875) < 1e-10

    def test_ease_out_cubic_alias(self):
        assert ease_out_cubic(0.5) == ease_out(0.5)

    def test_ease_out_quart_at_zero(self):
        assert ease_out_quart(0.0) == 0.0

    def test_ease_out_quart_at_one(self):
        assert ease_out_quart(1.0) == 1.0

    def test_ease_out_quint_at_zero(self):
        assert ease_out_quint(0.0) == 0.0

    def test_ease_out_quint_at_one(self):
        assert ease_out_quint(1.0) == 1.0

    def test_ease_out_expo_at_zero(self):
        assert ease_out_expo(0.0) == 0.0

    def test_ease_out_expo_near_one(self):
        assert abs(ease_out_expo(0.999) - 1.0) < 0.01


class TestEaseInFamily:
    """Test ease-in curves."""

    def test_ease_in_at_zero(self):
        assert ease_in(0.0) == 0.0

    def test_ease_in_at_one(self):
        assert ease_in(1.0) == 1.0

    def test_ease_in_midpoint(self):
        # 0.5^3 = 0.125
        assert abs(ease_in(0.5) - 0.125) < 1e-10


class TestEaseInOut:
    """Test ease-in-out curves."""

    def test_ease_in_out_at_zero(self):
        assert ease_in_out(0.0) == 0.0

    def test_ease_in_out_at_one(self):
        assert ease_in_out(1.0) == 1.0

    def test_ease_in_out_midpoint(self):
        # Symmetric: midpoint maps to midpoint
        assert abs(ease_in_out(0.5) - 0.5) < 1e-10


class TestEaseOutBack:
    """Test ease-out-back overshoot."""

    def test_ease_out_back_at_zero(self):
        assert abs(ease_out_back(0.0)) < 1e-10  # floating point precision

    def test_ease_out_back_at_one(self):
        assert ease_out_back(1.0) == 1.0

    def test_ease_out_back_overshoot(self):
        # Should exceed 1.0 at some point
        values = [ease_out_back(p) for p in [0.5, 0.6, 0.7, 0.8, 0.9]]
        assert max(values) > 1.0


class TestAppleAndMaterial:
    """Test Apple and Material Design curves."""

    def test_apple_at_zero(self):
        assert apple(0.0) == 0.0

    def test_apple_at_one(self):
        assert apple(1.0) == 1.0

    def test_material_at_zero(self):
        assert material(0.0) == 0.0

    def test_material_at_one(self):
        assert material(1.0) == 1.0


class TestApply:
    """Test apply() dispatcher."""

    def test_apply_valid_name(self):
        assert abs(apply("ease_in", 0.5) - 0.125) < 1e-10

    def test_apply_unknown_defaults(self):
        assert apply("nonexistent", 0.5) == ease_out(0.5)

    def test_apply_none_name(self):
        assert apply(None, 0.5) == ease_out(0.5)

    def test_apply_empty_string(self):
        assert apply("", 0.5) == ease_out(0.5)


class TestCurvesRegistry:
    """Test CURVES registry completeness."""

    def test_curves_has_10_keys(self):
        assert len(CURVES) == 10

    def test_all_curves_at_zero(self):
        for name, fn in CURVES.items():
            if name == "ease_out_back":
                continue  # skip overshoot curve
            assert fn(0.0) == 0.0, f"{name} failed at p=0"

    def test_all_curves_at_one(self):
        for name, fn in CURVES.items():
            if name == "ease_out_back":
                continue  # overshoot
            if name == "ease_out_expo":
                continue  # approaches 1.0 asymptotically
            assert fn(1.0) == 1.0, f"{name} failed at p=1"


class TestMonotonicity:
    """Test that curves are monotonically non-decreasing."""

    def test_monotonicity(self):
        points = [0.0, 0.25, 0.5, 0.75, 1.0]
        for name, fn in CURVES.items():
            if name == "ease_out_back":
                continue  # skip overshoot curve
            values = [fn(p) for p in points]
            for i in range(1, len(values)):
                assert values[i] >= values[i - 1], f"{name} not monotonic"
