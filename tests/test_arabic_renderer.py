"""
ARABIC-001 tests: ArabicRenderer HarfBuzz shaping, FreeType rasterization,
width measurement, ink-tight rendering, word highlight geometry, gradient
recoloring, and edge cases (empty, diacritics, non-Arabic, long text).

Run with: python -m pytest tests/test_arabic_renderer.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from core.arabic_renderer import (
    ArabicRenderer,
    _is_arabic,
    apply_vertical_gradient,
    measure_text_width,
    render_text,
)

BISMILLAH = "\u0628\u0650\u0633\u0652\u0645\u0650 \u0627\u0644\u0644\u0651\u064e\u0647\u0650"
RABBANA = (
    "\u0631\u0628\u064e\u0646\u064e\u0627 \u0622\u062a\u0650\u0646\u064e\u0627 \u0641\u064a "
    "\u0627\u0644\u0642\u064e\u0644\u0652\u0628\u0650 \u0633\u064e\u062e\u0651\u0631\u064e\u062a\u064e\u0646\u064e\u0627 "
    "\u0641\u064e\u0627\u0633\u0652\u062e\u0651\u0631\u064e\u0644\u064e\u0646\u064e\u0627 "
    "\u0642\u064e\u0644\u0652\u0628\u064b\u0627 \u0637\u064e\u064a\u0651\u0650\u0628\u064b\u0627"
)
SHORT_AR = "\u0627\u0644\u0644\u0647\u0645 \u0627\u0646\u064a \u0627\u0633\u0623\u0644\u0643 \u0627\u0644\u0639\u0627\u0641\u064a\u0629"
LATIN_TEXT = "Hello World"
MIXED_TEXT = "\u0627\u0644\u0644\u0647\u0645 Hello 123"
SINGLE_CHAR = "\u0627\u0644\u0644\u0647"
LONG_TEXT = "\u0627\u0644\u0644\u0647\u0645 " * 30

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")


def _pick_font():
    for name in ("Amiri-Bold.ttf", "Amiri-Regular.ttf", "NotoNaskhArabic-Regular.ttf"):
        fp = os.path.join(FONT_DIR, name)
        if os.path.exists(fp):
            return fp
    return None


# ──────────────────────────────────────────────────────────────────
#  Phase 1: Unicode Detection
# ──────────────────────────────────────────────────────────────────
class TestIsArabic:
    """_is_arabic() Unicode block detection."""

    def test_bismillah_is_arabic(self):
        assert _is_arabic(BISMILLAH) is True

    def test_short_arabic_is_arabic(self):
        assert _is_arabic(SHORT_AR) is True

    def test_latin_not_arabic(self):
        assert _is_arabic(LATIN_TEXT) is False

    def test_empty_not_arabic(self):
        assert _is_arabic("") is False

    def test_digits_not_arabic(self):
        assert _is_arabic("12345") is False

    def test_mixed_has_arabic(self):
        assert _is_arabic(MIXED_TEXT) is True

    def test_arabic_punctuation(self):
        assert _is_arabic("\u061f") is True  # Arabic question mark U+061F

    def test_persian_urdu_script(self):
        assert _is_arabic("\u0639\u0631\u0628\u06cc") is True  # Perso-Arabic


# ──────────────────────────────────────────────────────────────────
#  Phase 2: Instantiation & Font Loading
# ──────────────────────────────────────────────────────────────────
class TestInstantiation:
    """ArabicRenderer __init__ and font resolution."""

    def test_default_init_loads(self):
        r = ArabicRenderer()
        assert r.font_path is not None
        assert os.path.exists(r.font_path)

    def test_explicit_font(self):
        fp = _pick_font()
        if fp:
            r = ArabicRenderer(font_path=fp)
            assert r.font_path == fp

    def test_font_is_amiri_bold(self):
        r = ArabicRenderer()
        assert "Amiri" in os.path.basename(r.font_path)

    def test_upem_positive(self):
        r = ArabicRenderer()
        r._load()
        assert r._upem > 0


# ──────────────────────────────────────────────────────────────────
#  Phase 3: HarfBuzz Shaping
# ──────────────────────────────────────────────────────────────────
class TestShaping:
    """_shape() HarfBuzz output structure."""

    def setup_method(self):
        self.r = ArabicRenderer()
        self.r._load()

    def test_returns_list(self):
        result = self.r._shape(BISMILLAH, 48)
        assert isinstance(result, list)

    def test_nonempty_for_arabic(self):
        result = self.r._shape(BISMILLAH, 48)
        assert len(result) > 0

    def test_glyph_tuple_structure(self):
        result = self.r._shape(SINGLE_CHAR, 48)
        assert len(result) > 0
        g = result[0]
        assert len(g) == 6  # (glyph_index, x_adv, y_adv, x_off, y_off, cluster)

    def test_glyph_indices_positive(self):
        result = self.r._shape(SINGLE_CHAR, 48)
        for g in result:
            assert g[0] >= 0, "glyph_index must be non-negative"

    def test_cluster_values_nonnegative(self):
        result = self.r._shape(BISMILLAH, 48)
        for g in result:
            assert g[5] >= 0, "cluster must be non-negative"

    def test_empty_text_no_glyphs(self):
        try:
            result = self.r._shape("", 48)
            assert len(result) == 0
        except (TypeError, RuntimeError):
            pass  # empty string not supported by _shape

    def test_single_char_one_or_more_glyphs(self):
        result = self.r._shape(SINGLE_CHAR, 48)
        assert len(result) >= 1


# ──────────────────────────────────────────────────────────────────
#  Phase 4: Width Measurement
# ──────────────────────────────────────────────────────────────────
class TestMeasureWidth:
    """measure_width() pixel width calculation."""

    def setup_method(self):
        self.r = ArabicRenderer()

    def test_empty_returns_zero(self):
        assert self.r.measure_width("", 48) == 0.0

    def test_single_char_positive(self):
        w = self.r.measure_width(SINGLE_CHAR, 48)
        assert w > 0

    def test_longer_text_wider(self):
        w1 = self.r.measure_width(SINGLE_CHAR, 48)
        w2 = self.r.measure_width(SHORT_AR, 48)
        assert w2 > w1

    def test_size_scales_width(self):
        w_small = self.r.measure_width(BISMILLAH, 24)
        w_large = self.r.measure_width(BISMILLAH, 72)
        assert w_large > w_small * 2  # at least 2x

    def test_width_proportional_to_size(self):
        w24 = self.r.measure_width(BISMILLAH, 24)
        w48 = self.r.measure_width(BISMILLAH, 48)
        ratio = w48 / w24
        assert 1.8 < ratio < 2.2, f"Expected ~2x ratio, got {ratio}"

    def test_latin_text_has_width(self):
        w = self.r.measure_width(LATIN_TEXT, 48)
        assert w > 0


# ──────────────────────────────────────────────────────────────────
#  Phase 5: Render Line
# ──────────────────────────────────────────────────────────────────
class TestRenderLine:
    """render_line() PIL image output properties."""

    def setup_method(self):
        self.r = ArabicRenderer()

    def test_returns_pil_image(self):
        img = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        assert isinstance(img, Image.Image)

    def test_rgba_mode(self):
        img = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        assert img.mode == "RGBA"

    def test_has_content(self):
        img = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        arr = np.array(img)
        assert arr[:, :, 3].max() > 0, "Image has no opaque pixels"

    def test_empty_text_returns_image(self):
        try:
            img = self.r.render_line("", 48, (255, 255, 255), None, 0)
            assert img.width >= 1
            assert img.height >= 1
        except (TypeError, RuntimeError):
            pass  # empty string not supported by underlying shaper

    def test_size_scales_output(self):
        img_s = self.r.render_line(BISMILLAH, 24, (255, 255, 255), None, 0)
        img_l = self.r.render_line(BISMILLAH, 72, (255, 255, 255), None, 0)
        assert img_l.width > img_s.width
        assert img_l.height > img_s.height

    def test_outline_widens_image(self):
        img_no = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        img_out = self.r.render_line(BISMILLAH, 48, (255, 255, 255), (0, 0, 0), 3)
        assert img_out.width >= img_no.width
        assert img_out.height >= img_no.height

    def test_color_appears_in_image(self):
        img = self.r.render_line(BISMILLAH, 72, (255, 0, 0), None, 0)
        arr = np.array(img)
        red_mask = (arr[:, :, 0] > 100) & (arr[:, :, 3] > 100)
        assert red_mask.sum() > 0, "Expected red pixels in image"

    def test_pad_invariance(self):
        img1 = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0, pad=0)
        img2 = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0, pad=20)
        a1 = np.array(img1)
        a2 = np.array(img2)
        ink1 = a1[:, :, 3] > 0
        ink2 = a2[:, :, 3] > 0
        assert ink1.sum() == ink2.sum(), "Pad should not change ink pixel count"

    def test_long_text_renders(self):
        img = self.r.render_line(LONG_TEXT, 36, (255, 255, 255), None, 0)
        assert img.width > 0
        arr = np.array(img)
        assert arr[:, :, 3].max() > 0


# ──────────────────────────────────────────────────────────────────
#  Phase 6: Harakat / Diacritics
# ──────────────────────────────────────────────────────────────────
class TestHarakat:
    """Diacritics (harakat) are preserved in rendering."""

    def setup_method(self):
        self.r = ArabicRenderer()

    def test_bismillah_has_content_above_baseline(self):
        img = self.r.render_line(BISMILLAH, 72, (255, 255, 255), None, 0)
        arr = np.array(img)
        h = arr.shape[0]
        top_half = arr[: h // 2, :, 3]
        assert top_half.max() > 0, "No pixels in top half (harakat above baseline)"

    def test_bismillah_has_content_below_baseline(self):
        img = self.r.render_line(BISMILLAH, 72, (255, 255, 255), None, 0)
        arr = np.array(img)
        h = arr.shape[0]
        bottom_half = arr[h // 2 :, :, 3]
        assert bottom_half.max() > 0, "No pixels in bottom half (kasra below baseline)"

    def test_with_harakat_wider_than_without(self):
        bare = "\u0627\u0644\u0644\u0647"  # Allah (no diacritics)
        diac = "\u0627\u0644\u0644\u0651\u064e\u0647\u0650"  # Allah (with shadda+fatha+end)
        w_bare = self.r.measure_width(bare, 48)
        w_diac = self.r.measure_width(diac, 48)
        assert w_diac >= w_bare


# ──────────────────────────────────────────────────────────────────
#  Phase 7: Determinism
# ──────────────────────────────────────────────────────────────────
class TestDeterminism:
    """Same input -> identical pixel output."""

    def setup_method(self):
        self.r = ArabicRenderer()

    def test_same_render_twice_identical(self):
        img1 = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        img2 = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        assert img1.tobytes() == img2.tobytes()

    def test_same_width_twice_identical(self):
        w1 = self.r.measure_width(BISMILLAH, 48)
        w2 = self.r.measure_width(BISMILLAH, 48)
        assert w1 == w2

    def test_same_word_spans_twice_identical(self):
        ws1 = self.r.word_spans(BISMILLAH, 48)
        ws2 = self.r.word_spans(BISMILLAH, 48)
        assert ws1 == ws2

    def test_different_instances_same_font_same_output(self):
        r1 = ArabicRenderer()
        r2 = ArabicRenderer()
        img1 = r1.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        img2 = r2.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        assert img1.tobytes() == img2.tobytes()


# ──────────────────────────────────────────────────────────────────
#  Phase 8: Word Spans
# ──────────────────────────────────────────────────────────────────
class TestWordSpans:
    """word_spans() word-level highlight geometry."""

    def setup_method(self):
        self.r = ArabicRenderer()

    def test_returns_dict(self):
        ws = self.r.word_spans(BISMILLAH, 48)
        assert isinstance(ws, dict)
        assert "words" in ws
        assert "width" in ws

    def test_empty_text(self):
        ws = self.r.word_spans("", 48)
        assert ws["words"] == []
        assert ws["width"] == 0

    def test_single_word(self):
        ws = self.r.word_spans(SINGLE_CHAR, 48)
        assert len(ws["words"]) >= 1
        assert ws["width"] > 0

    def test_multi_word(self):
        ws = self.r.word_spans(BISMILLAH, 48)
        assert len(ws["words"]) >= 2

    def test_word_spans_have_required_keys(self):
        ws = self.r.word_spans(BISMILLAH, 48)
        for w in ws["words"]:
            assert "i" in w
            assert "x0" in w
            assert "x1" in w
            assert w["x0"] < w["x1"], "x0 must be less than x1"

    def test_word_spans_ordered_by_index(self):
        ws = self.r.word_spans(BISMILLAH, 48)
        indices = [w["i"] for w in ws["words"]]
        assert indices == sorted(indices)

    def test_word_spans_nonoverlapping(self):
        ws = self.r.word_spans(BISMILLAH, 48)
        spans = [(w["x0"], w["x1"]) for w in ws["words"]]
        spans.sort()
        for i in range(1, len(spans)):
            assert spans[i][0] >= spans[i - 1][1], "Word spans should not overlap"

    def test_spans_within_render_width(self):
        ws = self.r.word_spans(BISMILLAH, 48)
        img = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        for w in ws["words"]:
            assert w["x0"] >= 0
            assert w["x1"] <= img.width, f"Word x1={w['x1']} > img width={img.width}"


# ──────────────────────────────────────────────────────────────────
#  Phase 9: Gradient Recoloring
# ──────────────────────────────────────────────────────────────────
class TestGradient:
    """apply_vertical_gradient() recoloring."""

    def setup_method(self):
        self.r = ArabicRenderer()

    def test_returns_rgba(self):
        img = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        result = apply_vertical_gradient(img, (255, 215, 0), (180, 120, 0))
        assert result.mode == "RGBA"

    def test_preserves_alpha(self):
        img = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        alpha_before = np.array(img)[:, :, 3].copy()
        result = apply_vertical_gradient(img, (255, 215, 0), (180, 120, 0))
        alpha_after = np.array(result)[:, :, 3]
        assert np.array_equal(alpha_before, alpha_after)

    def test_changes_rgb_values(self):
        img = self.r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        rgb_before = np.array(img)[:, :, :3].copy()
        result = apply_vertical_gradient(img, (255, 0, 0), (0, 0, 255))
        rgb_after = np.array(result)[:, :, :3]
        assert not np.array_equal(rgb_before, rgb_after)

    def test_gradient_varies_vertically(self):
        img = self.r.render_line(BISMILLAH, 144, (255, 255, 255), None, 0)
        result = apply_vertical_gradient(img, (255, 0, 0), (0, 0, 255))
        arr = np.array(result)
        h = arr.shape[0]
        top_r = arr[h // 4, :, 0].mean()
        bot_r = arr[3 * h // 4, :, 0].mean()
        assert top_r > bot_r, "Red channel should be higher at top than bottom"


# ──────────────────────────────────────────────────────────────────
#  Phase 10: Module-Level Helpers
# ──────────────────────────────────────────────────────────────────
class TestModuleHelpers:
    """render_text() and measure_text_width() module-level shortcuts."""

    def test_render_text_returns_image(self):
        img = render_text(BISMILLAH, 48, (255, 255, 255), None, 0)
        assert isinstance(img, Image.Image)
        assert img.mode == "RGBA"

    def test_measure_text_width_returns_positive(self):
        w = measure_text_width(BISMILLAH, 48)
        assert w > 0

    def test_render_text_matches_instance(self):
        r = ArabicRenderer()
        img_mod = render_text(BISMILLAH, 48, (255, 255, 255), None, 0)
        img_inst = r.render_line(BISMILLAH, 48, (255, 255, 255), None, 0)
        assert img_mod.tobytes() == img_inst.tobytes()

    def test_measure_matches_instance(self):
        r = ArabicRenderer()
        w_mod = measure_text_width(BISMILLAH, 48)
        w_inst = r.measure_width(BISMILLAH, 48)
        assert w_mod == w_inst
