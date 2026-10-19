"""
Arabic/Urdu Renderer (HarfBuzz + FreeType).

Replaces the arabic_reshaper + python-bidi + naive PIL approach, which:
  1. DROPPED all diacritics (arabic_reshaper 3.0.0 `reshape()` deletes harakat).
  2. Reversed multi-line order (wrap ran on the bidi-reordered visual string).
  3. Could not position harakat (PIL without libraqm has no GPOS).

This module shapes the LOGICAL text with HarfBuzz (uharfbuzz): contextual
letter forms, ligatures, and harakat WITH proper GPOS mark positioning, then
rasterizes the glyphs with FreeType (freetype-py) and composites them into a
tight RGBA surface. Fully offline, no system DLLs, deterministic.

Bidi note: HarfBuzz shapes one directional run; for these dua Shorts every
Arabic/Urdu line is a single RTL run, so we shape with direction=RTL and draw
the glyphs left->right (HarfBuzz already emits them in visual order).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

__all__ = ["ArabicRenderer", "apply_vertical_gradient", "render_text", "measure_text_width"]

# Arabic-script Unicode blocks (auto RTL detection).
_ARABIC_BLOCKS = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
)

# Hebrew blocks (also RTL)
_HEBREW_BLOCKS = (
    (0x0590, 0x05FF),  # Hebrew
    (0xFB1D, 0xFB4F),  # Hebrew Presentation Forms
)


def _is_rtl_char(ch: str) -> bool:
    """Check if a character is RTL (Arabic/Hebrew)."""
    o = ord(ch)
    return any(a <= o <= b for a, b in _ARABIC_BLOCKS + _HEBREW_BLOCKS)


def _is_arabic(text: str) -> bool:
    for ch in text:
        if _is_rtl_char(ch):
            return True
    return False


def _split_bidi_runs(text: str) -> list[tuple[str, str]]:
    """
    Split text into directional runs: [(direction, text_segment), ...]
    direction is "rtl" or "ltr"

    Neutral characters (spaces, punctuation) are grouped with the
    PREVIOUS run to avoid breaking RTL/LTR flows.
    """
    if not text:
        return []

    # Characters that are "neutral" - they join the surrounding context
    _NEUTRAL = set(" \t\n\r.,;:!?-()[]{}'\"@#$%^&*+=<>/\\|~`")

    runs = []
    first_rtl = _is_rtl_char(text[0])
    current_dir = "rtl" if first_rtl else "ltr"
    current_chars = [text[0]]

    for ch in text[1:]:
        if ch in _NEUTRAL:
            # Neutral chars join the current run
            current_chars.append(ch)
            continue

        ch_dir = "rtl" if _is_rtl_char(ch) else "ltr"
        if ch_dir == current_dir:
            current_chars.append(ch)
        else:
            runs.append((current_dir, "".join(current_chars)))
            current_dir = ch_dir
            current_chars = [ch]

    runs.append((current_dir, "".join(current_chars)))
    return runs


# Import fonts from master config - SINGLE SOURCE OF TRUTH
from core.master_config import MASTER_FONTS
from typing import cast


class ArabicRenderer:
    """Cached HarfBuzz + FreeType renderer for Arabic-script text."""

    def __init__(self, font_path: str | None = None, font_key: str | None = None):
        if font_key and font_key in MASTER_FONTS:
            font_info = MASTER_FONTS[font_key]
            font_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts", font_info["file"]
            )
        elif font_path is None:
            font_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts", "Amiri-Bold.ttf"
            )
            if not os.path.exists(font_path):
                candidates = [
                    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts", name)
                    for name in ("Amiri-Regular.ttf", "NotoNaskhArabic-Regular.ttf")
                ]
                for c in candidates:
                    if os.path.exists(c):
                        font_path = c
                        break
        self.font_path = font_path
        self._hb_face = None
        self._hb_font = None
        self._ft_face = None
        self._upem = 1000
        self._warned = False

    # -- lazy fonts ----------------------------------------------------
    def _load(self):
        if self._hb_font is None:
            try:
                import freetype
                import uharfbuzz as hb
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("arabic_renderer needs uharfbuzz + freetype-py: %r" % exc)
            with open(self.font_path, "rb") as f:
                self._hb_face = hb.Face(f.read())
            self._hb_font = hb.Font(self._hb_face)
            assert self._hb_face is not None
            self._upem = self._hb_face.upem
            self._ft_face = freetype.Face(self.font_path)

    def _shape(self, text: str, size: int, direction: str = "rtl"):
        """Shape logical text -> (glyph_index, x_adv, y_adv, x_off, y_off,
        cluster) in FONT UNITS. Handles bidirectional text by splitting
        into directional runs and shaping each separately.

        For RTL base direction: LTR segments are embedded within RTL flow.
        Returns list aligned to visual L->R order.
        ``cluster`` is the LOGICAL char index each glyph belongs to."""
        import uharfbuzz as hb

        self._load()

        if not text:
            return []

        # Check if text has mixed directions
        runs = _split_bidi_runs(text)
        has_mixed = len(runs) > 1

        if not has_mixed:
            # Pure RTL or pure LTR - shape normally
            buf = hb.Buffer()
            buf.add_str(text)
            buf.direction = direction
            buf.script = "Arab" if direction == "rtl" else "Latn"
            buf.language = "ar" if direction == "rtl" else "en"
            hb.shape(self._hb_font, buf)

            out = []
            for gi, gp in zip(buf.glyph_infos, buf.glyph_positions):
                out.append((gi.codepoint, gp.x_advance, gp.y_advance, gp.x_offset, gp.y_offset, gi.cluster))
            return out
        else:
            # Mixed text - shape each run separately
            # For RTL base direction, the visual order is:
            # LTR runs appear as-is (left to right), RTL runs appear reversed
            # We need to concatenate in visual order
            all_glyphs = []
            offset = 0

            for run_dir, run_text in runs:
                buf = hb.Buffer()
                buf.add_str(run_text)
                buf.direction = run_dir
                buf.script = "Arab" if run_dir == "rtl" else "Latn"
                buf.language = "ar" if run_dir == "rtl" else "en"
                hb.shape(self._hb_font, buf)

                for gi, gp in zip(buf.glyph_infos, buf.glyph_positions):
                    all_glyphs.append(
                        (gi.codepoint, gp.x_advance, gp.y_advance, gp.x_offset, gp.y_offset, gi.cluster + offset)
                    )
                offset += len(run_text)

            return all_glyphs

    # -- measurement ---------------------------------------------------
    def measure_width(self, text: str, size: int) -> float:
        """Total shaped width in pixels at `size`."""
        if not text:
            return 0.0
        self._load()
        total = float(sum(g[1] for g in self._shape(text, size)))
        return total * size / self._upem

    # -- rendering -----------------------------------------------------
    def render_line(
        self,
        text: str,
        size: int,
        color=(255, 255, 255),
        outline_color=(10, 12, 20),
        outline_width=0,
        direction: str = "rtl",
        pad: int | None = None,
    ) -> Image.Image:
        """
        Render one shaped line to an ink-tight RGBA surface.

        TWO-PASS approach: pass 1 rasterizes every glyph and unions their
        exact ink bounding boxes (marks can and DO extend beyond the font's
        ascender/descender box, e.g. stacked shadda+fatha); pass 2 allocates
        a canvas exactly that size (+pad) and blits. This makes clipping
        impossible regardless of font metrics.

        Args:
            text: LOGICAL text (harakat included, NOT pre-reshaped).
            size: Font pixel size.
            color: RGB text color.
            outline_color: RGB outline color (None -> no outline).
            outline_width: Outline thickness in pixels (8-direction blit).
            direction: "rtl" for Arabic/Urdu, "ltr" otherwise.
            pad: Extra transparent margin around ink (default ~size/24).
        """
        pieces, _, _ = self._rasterize(text, size, direction)
        if not pieces:
            return Image.new("RGBA", (1, int(size * 1.2)), (0, 0, 0, 0))

        if pad is None:
            pad = max(2, size // 24)
        if outline_width and outline_color:
            # outline stamps extend r px beyond the ink bbox on all sides
            pad += max(1, int(outline_width)) + 1
        x0, y0, w, h = self._ink_canvas(pieces, pad)

        def draw(col, dx=0, dy=0):
            cv = np.zeros((h, w), dtype=np.uint8)
            for arr, px, py in pieces:
                X, Y = px - x0 + dx, py - y0 + dy
                region = cv[Y : Y + arr.shape[0], X : X + arr.shape[1]]
                np.maximum(region, arr, out=region)
            return cv

        base = None
        if outline_width and outline_color:
            # Real outline: stamp the outline color at 8 offsets around each
            # glyph, then the fill color is drawn on top (fg covers center).
            r = max(1, int(outline_width))
            for dx in (-r, 0, r):
                for dy in (-r, 0, r):
                    if dx == 0 and dy == 0:
                        continue
                    layer = draw(outline_color, dx, dy)
                    base = layer if base is None else np.maximum(base, layer)
        fg = draw(color)

        if base is not None:
            out = Image.fromarray(base).convert("RGBA")
            out.putalpha(Image.fromarray(base))
            fg_img = Image.fromarray(fg).convert("RGBA")
            fg_img.putalpha(Image.fromarray(fg))
            out.paste(fg_img, (0, 0), fg_img)
        else:
            out = Image.fromarray(fg).convert("RGBA")
            out.putalpha(Image.fromarray(fg))

        return out

    def _rasterize(self, text: str, size: int, direction: str = "rtl"):
        """Pass 1: shape + rasterize every glyph.

        Returns (pieces, min_xy, max_xy_end) where each piece is
        (bitmap_u8_2d, x, y) with (x, y) the bitmap's top-left in
        baseline-relative coords (y grows DOWN, marks above baseline have
        negative y). The union bbox covers ALL ink incl. harakat overflow.
        """
        import freetype

        self._load()
        glyphs = self._shape(text, size, direction)
        scale = size / self._upem
        face = self._ft_face
        assert face is not None
        face.set_pixel_sizes(0, size)

        pieces = []
        min_x = min_y = 1 << 30
        max_x = max_y = -(1 << 30)
        pen_x = 0.0
        for gid, x_adv, y_adv, x_off, y_off, _cluster in glyphs:
            face.load_glyph(gid, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
            bmp = face.glyph.bitmap
            if bmp.buffer is not None and bmp.rows > 0 and bmp.width > 0:
                buf = np.array(bmp.buffer, dtype=np.uint8)
                pitch = bmp.pitch
                if buf.size >= bmp.rows * pitch and pitch >= bmp.width:
                    arr = buf.reshape(bmp.rows, pitch)[:, : bmp.width].copy()
                else:
                    arr = buf.reshape(bmp.rows, bmp.width)
                bx = int(round(pen_x + x_off * scale)) + face.glyph.bitmap_left
                by = -face.glyph.bitmap_top - int(round(y_off * scale))
                pieces.append((arr, bx, by))
                min_x = min(min_x, bx)
                min_y = min(min_y, by)
                max_x = max(max_x, bx + bmp.width)
                max_y = max(max_y, by + bmp.rows)
            pen_x += x_adv * scale
        if not pieces:
            return [], (0, 0), (1, 1)
        return pieces, (min_x, min_y), (max_x, max_y)

    @staticmethod
    def _ink_canvas(pieces, pad):
        """Union bbox of all pieces -> (x0, y0, width, height) incl. pad."""
        min_x = min(p[1] for p in pieces) - pad
        min_y = min(p[2] for p in pieces) - pad
        max_x = max(p[1] + p[0].shape[1] for p in pieces) + pad
        max_y = max(p[2] + p[0].shape[0] for p in pieces) + pad
        return min_x, min_y, max_x - min_x, max_y - min_y

    def render_styled(
        self,
        text: str,
        size: int,
        color=(255, 255, 255),
        style: str = "solid",
        glow_color=(212, 175, 55),
        gradient_top=(255, 240, 185),
        gradient_bottom=(216, 178, 80),
        direction: str = "rtl",
    ) -> Image.Image:
        """
        Render text with various styles.

        Styles:
        - solid: plain text with optional outline
        - outline: text with visible stroke
        - glow: text with neon glow effect
        - gradient: vertical gradient fill
        - gold_gradient: gold gradient fill
        - shadow: text with drop shadow
        """
        if style == "solid":
            return self.render_line(
                text, size, color=color, outline_color=(10, 12, 20), outline_width=2, direction=direction
            )
        elif style == "outline":
            return self.render_line(
                text, size, color=color, outline_color=(0, 0, 0), outline_width=4, direction=direction
            )
        elif style == "glow":
            base = self.render_line(text, size, color=color, direction=direction)
            glow = base.filter(ImageFilter.GaussianBlur(radius=8))
            enhancer = ImageEnhance.Brightness(glow)
            glow = enhancer.enhance(1.8)
            result = Image.new("RGBA", base.size, (0, 0, 0, 0))
            result = Image.alpha_composite(result, glow)
            result = Image.alpha_composite(result, base)
            return result
        elif style == "gradient":
            base = self.render_line(text, size, color=(255, 255, 255), direction=direction)
            return cast(Image.Image, apply_vertical_gradient(base, gradient_top, gradient_bottom))
        elif style == "gold_gradient":
            base = self.render_line(text, size, color=(255, 255, 255), direction=direction)
            return cast(Image.Image, apply_vertical_gradient(base, (255, 240, 185), (216, 178, 80)))
        elif style == "shadow":
            base = self.render_line(text, size, color=color, direction=direction)
            shadow = self.render_line(text, size, color=(0, 0, 0), direction=direction)
            result = Image.new("RGBA", (base.width + 8, base.height + 8), (0, 0, 0, 0))
            s_rgba = shadow.convert("RGBA")
            s_arr = np.array(s_rgba)
            s_arr[:, :, 3] = (s_arr[:, :, 3] * 0.6).astype(np.uint8)
            shadow_rgba = Image.fromarray(s_arr)
            result.paste(shadow_rgba, (6, 6), shadow_rgba)
            result.paste(base, (0, 0), base)
            return result
        else:
            return self.render_line(
                text, size, color=color, outline_color=(10, 12, 20), outline_width=2, direction=direction
            )

    def word_spans(self, text: str, size: int) -> dict:
        """
        Per-word ink x-spans in the SAME coordinate space as render_line's
        output surface (0 = surface left edge, incl. the default pad).

        Words are keyed by their LOGICAL token index (TTS speaks logical
        order) while x spans are VISUAL (HarfBuzz already reordered glyphs),
        so on an RTL line logical word 0 lands at the RIGHT edge. Mark
        glyphs (harakat) inherit their cluster's token.

        Returns:
            {"words": [{"i": int, "x0": int, "x1": int}, ...]  # logical order
             "width": int}                                     # surf width
            {"words": [], "width": 0} for empty/blank text.
        """
        if not text or not text.strip():
            return {"words": [], "width": 0}
        import freetype

        self._load()
        glyphs = self._shape(text, size, "rtl")
        scale = size / self._upem
        face = self._ft_face
        assert face is not None
        face.set_pixel_sizes(0, size)

        # logical char index -> token index
        toks = text.split()
        starts, acc = [], 0
        for t in toks:
            starts.append(acc)
            acc += len(t) + 1

        def tok_of(cp):
            lo, hi = 0, len(starts) - 1
            if cp < starts[0]:
                return None
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if starts[mid] <= cp:
                    lo = mid
                else:
                    hi = mid - 1
            return lo

        spans: dict[int, list[float]] = {}  # token idx -> [min_x, max_x]
        ink_min = 1 << 30
        ink_max = -(1 << 30)
        pen_x = 0.0
        for gid, x_adv, y_adv, x_off, y_off, cluster in glyphs:
            face.load_glyph(gid, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
            bmp = face.glyph.bitmap
            if bmp.buffer is not None and bmp.rows > 0 and bmp.width > 0:
                bx = int(round(pen_x + x_off * scale)) + face.glyph.bitmap_left
                ex = bx + bmp.width
                ti = tok_of(cluster)
                if ti is not None:
                    cur = spans.get(ti)
                    if cur is None:
                        spans[ti] = [bx, ex]
                    else:
                        cur[0] = min(cur[0], bx)
                        cur[1] = max(cur[1], ex)
                ink_min = min(ink_min, bx)
                ink_max = max(ink_max, ex)
            pen_x += x_adv * scale
        if not spans:
            return {"words": [], "width": 0}
        pad = max(2, size // 24)
        origin = ink_min - pad  # render_line canvas left edge
        words = [{"i": ti, "x0": int(v[0] - origin), "x1": int(v[1] - origin)} for ti, v in sorted(spans.items())]
        return {"words": words, "width": int((ink_max - ink_min) + 2 * pad)}


_renderer = ArabicRenderer()


def apply_vertical_gradient(img, top_rgb, bottom_rgb):
    """Recolor an RGBA surface with a vertical top->bottom gradient while
    preserving alpha (premium text look)."""
    a = np.asarray(img).copy()
    h = a.shape[0]
    t = np.linspace(0.0, 1.0, h)[:, None, None]
    top = np.array(top_rgb, dtype=np.float32)[None, None, :]
    bot = np.array(bottom_rgb, dtype=np.float32)[None, None, :]
    a[:, :, :3] = (top * (1.0 - t) + bot * t).astype(np.uint8)
    return Image.fromarray(a)


def render_text(text, size, color=(255, 255, 255), outline_color=(10, 12, 20), outline_width=0):
    """Module-level helper (uses default font)."""
    return _renderer.render_line(text, size, color, outline_color, outline_width)


def measure_text_width(text, size) -> float:
    """Module-level width helper (uses default font)."""
    return _renderer.measure_width(text, size)
