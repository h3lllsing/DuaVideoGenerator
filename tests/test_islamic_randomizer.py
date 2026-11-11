"""Tests for core.islamic_randomizer (ISLAMIC Randomizer + Constraints)."""

import random

from core.islamic_randomizer import IslamicConstraints, IslamicRandomizer


class TestIslamicConstraints:
    def test_category_allowed_peaceful(self):
        assert IslamicConstraints.is_category_allowed("nature") is True

    def test_category_allowed_forbidden(self):
        assert IslamicConstraints.is_category_allowed("alcohol") is False

    def test_get_halal_palette_returns_dict(self):
        pal = IslamicConstraints.get_halal_palette(random.Random(42))
        assert isinstance(pal, dict)
        assert len(pal) > 0

    def test_validate_content_ok(self):
        assert IslamicConstraints.validate_content("بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ", "اللہ کے نام سے شروع", "Bismillah") is True

    def test_validate_content_empty_arabic(self):
        assert IslamicConstraints.validate_content("", "urdu text", "title") is False

    def test_validate_content_empty_urdu(self):
        assert IslamicConstraints.validate_content("arab text", "", "title") is False


class TestIslamicRandomizer:
    def test_generate_returns_ultra_config(self):
        r = IslamicRandomizer(seed="42")
        cfg = r.generate()
        assert cfg is not None
        assert hasattr(cfg, "arabic_font")
        assert hasattr(cfg, "palette")

    def test_preview_returns_str(self):
        r = IslamicRandomizer(seed="42")
        prev = r.preview()
        assert isinstance(prev, str)
        assert len(prev) > 0
