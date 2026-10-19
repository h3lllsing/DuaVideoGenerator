"""
Word Highlight (VISUAL Phase 4).


Deterministic, additive WordBoundary-driven visual highlighting.

Locked design:
  - Events are scene-relative seconds, already attached to the correct
    language scene by TimelineBuilder. Scene time is t = frame_index / fps.
  - Active word = last event whose start <= t (floor semantics; no flicker,
    no randomness). Before the first word -> no highlight; at a start -> that
    word; between words -> previous stays; after the final word -> final
    stays until scene end.
  - Timing is authoritative: NO prime-offset constant. WordBoundary offsets
    from the sidecar are used directly.
  - Word rectangles come from the renderer itself: SceneRenderer pre-computes
    per-line ``line_spans`` (logical token index + visual x span) through the
    HarfBuzz shaper's cluster values, so mapping is exact by POSITION - no
    arabic_reshaper/bidi replication, no string matching.
  - When reliable word-level geometry cannot be established (token-count
    mismatch, missing spans, wrapping hard-break), a deterministic
    LINE-LEVEL fallback is used for the affected layer.
  - The overlay never alters text, layout, wrapping, frame count, or audio.

This module contains no audio, layout, or renderer logic.
"""

import logging
from collections.abc import Callable
from typing import cast

from PIL import Image

logger = logging.getLogger(__name__)

__all__ = [
    "normalize_events",
    "resolve_active_word",
    "build_word_geometry",
    "highlight_targets",
    "make_word_overlay",
    "HIGHLIGHT_BOX_STYLES",
    "make_word_highlight_box",
]


Rect = tuple[int, int, int, int]


# ----------------------------------------------------------------------
# Event normalization + active-word resolution (pure timing)
# ----------------------------------------------------------------------
def normalize_events(events: list[dict] | None) -> list[dict]:
    """
    Return a stable, start-sorted copy of WordBoundary events.

    Invalid entries (non-dict, non-finite / negative start) are dropped.
    Entries with an identical start keep their original relative order.
    Each output entry carries the original list index as ``orig``.
    """
    if not events:
        return []
    cleaned = []
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        raw_start = ev.get("start")
        if raw_start is None:
            continue
        try:
            start = float(raw_start)
        except (TypeError, ValueError):
            continue
        if start != start:  # NaN
            continue
        if start < 0.0:  # negative is never a valid scene-relative time
            continue
        cleaned.append((start, i, dict(ev)))
    cleaned.sort(key=lambda t: (t[0], t[1]))
    return [{"start": start, "orig": orig, **rest} for (start, orig, rest) in cleaned]


def resolve_active_word(events: list[dict], t: float) -> int | None:
    """
    Return the ``orig`` index of the active event at scene time ``t``.

    Floor semantics: the last event with start <= t is active. Events are
    assumed normalized (sorted ascending by start). ``t`` is in seconds.
    Returns None before the first event (no highlight).
    """
    if not events:
        return None
    lo, hi = 0, len(events)
    while lo < hi:
        mid = (lo + hi) // 2
        if events[mid]["start"] <= t:
            lo = mid + 1
        else:
            hi = mid
    return events[lo - 1]["orig"] if lo > 0 else None


# ----------------------------------------------------------------------
# Word geometry
# ----------------------------------------------------------------------
def build_word_geometry(
    language: str,
    logical_text: str,
    display_lines: list[dict],
    n_events: int,
    measure: Callable[[str], int],
    outline_pad: int = 4,
    line_spans: list[list[tuple[int, int, int]]] | None = None,
) -> dict:
    """
    Map each word event to a deterministic highlight rectangle.

    Args:
        language: "ar" / "ur" (highlight only applies to these).
        logical_text: The source text exactly as sent to TTS (never altered).
        display_lines: Per-line layout dicts (``text``, ``bbox``, ...) exactly
            as produced by SceneRenderer.compute_layout for this layer.
        n_events: Number of WordBoundary events for this layer.
        measure: str -> pixel width (unused when line_spans are provided;
            kept for API compatibility).
        outline_pad: Horizontal text-outline inset (unused; kept for API
            compatibility - spans already account for ink positions).
        line_spans: Per-line word boxes from the renderer, aligned with
            ``display_lines``. Each entry is a list of ``(idx, x0, x1)``
            in FRAME pixel coordinates, where the j-th span belongs to that
            line's j-th logical token (``idx`` is line-local/informational).
            None or malformed -> line-level fallback.

    Returns:
        dict with:
          mode       "word" | "line"  (informational)
          targets    {event_index: rect}  rect = (x0, y0, x1, y1) in pixels
          line_boxes [rect, ...]  per display line, in order
    """
    line_boxes: list[Rect] = [
        (int(ln["bbox"][0]), int(ln["bbox"][1]), int(ln["bbox"][2]), int(ln["bbox"][3])) for ln in display_lines
    ]

    def line_fallback() -> dict:
        targets: dict[int, Rect] = {}
        n_lines = len(line_boxes)
        if n_lines and n_events:
            for e in range(n_events):
                k = min(n_lines - 1, (e * n_lines) // n_events)
                targets[e] = line_boxes[k]
        return {"mode": "line", "targets": targets, "line_boxes": line_boxes}

    if language not in ("ar", "ur") or n_events <= 0 or not display_lines:
        return {"mode": "line", "targets": {}, "line_boxes": line_boxes}

    ltoks = logical_text.split()
    if not ltoks or n_events != len(ltoks):
        return line_fallback()

    if line_spans is None or len(line_spans) != len(display_lines):
        return line_fallback()

    # Walk lines in order; tokens must appear contiguously and match the
    # wrapped line text exactly (wrap preserves logical order). Spans are
    # consumed by POSITION: the j-th span of a line belongs to that line's
    # j-th logical token (span idx values are line-local and informational).
    # Any count mismatch or hard-break fragment -> fallback.
    targets: dict[int, Rect] = {}
    ti = 0
    for li, ln in enumerate(display_lines):
        toks = ln["text"].split()
        spans = line_spans[li]
        b = line_boxes[li]
        if not toks or len(spans) != len(toks):
            return line_fallback()
        if ltoks[ti : ti + len(toks)] != toks:
            return line_fallback()
        for j, span in enumerate(spans):
            _idx, x0, x1 = span
            targets[ti + j] = (int(x0), b[1] + 1, int(x1), b[3] - 1)
        ti += len(toks)

    if ti != len(ltoks) or not targets:
        return line_fallback()

    return {"mode": "word", "targets": targets, "line_boxes": line_boxes}


def highlight_targets(events: list[dict], geometry: dict, t: float) -> Rect | None:
    """Rect (or None) for the active event at scene time ``t`` seconds."""
    active = resolve_active_word(events, t)
    if active is None:
        return None
    return cast("Rect | None", geometry["targets"].get(active))


# ----------------------------------------------------------------------
# Overlay generation
# ----------------------------------------------------------------------
def make_word_overlay(rect: Rect, accent_rgb: tuple[int, int, int], fill_alpha: int = 46, outline_alpha: int = 165):
    """
    Build a deterministic RGBA overlay sized to ``rect``: a subtle rounded
    translucent accent fill with a thin accent outline. The overlay is drawn
    ON TOP of the already-pasted text surface and never re-renders it.
    """
    from PIL import Image, ImageDraw

    x0, y0, x1, y1 = (int(v) for v in rect)
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)
    r, g, b = accent_rgb
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = min(8, h // 2)
    d.rounded_rectangle(
        [0, 0, w - 1, h - 1], radius=radius, fill=(r, g, b, fill_alpha), outline=(r, g, b, outline_alpha), width=2
    )
    return img


# ----------------------------------------------------------------------
# Highlight Box styles (Reels/TikTok trending caption look)
# ----------------------------------------------------------------------
HIGHLIGHT_BOX_STYLES: dict[str, dict] = {
    "gold": {
        "fill": (212, 175, 55, 70),
        "outline": (255, 215, 0, 200),
        "glow": (255, 215, 0, 40),
        "radius_ratio": 0.45,
        "padding_x": 14,
        "padding_y": 6,
        "width": 3,
    },
    "teal": {
        "fill": (0, 180, 180, 65),
        "outline": (0, 220, 220, 190),
        "glow": (0, 220, 220, 35),
        "radius_ratio": 0.45,
        "padding_x": 14,
        "padding_y": 6,
        "width": 3,
    },
    "rose": {
        "fill": (180, 50, 80, 65),
        "outline": (220, 80, 110, 190),
        "glow": (220, 80, 110, 35),
        "radius_ratio": 0.45,
        "padding_x": 14,
        "padding_y": 6,
        "width": 3,
    },
}


def make_word_highlight_box(
    rect: Rect,
    accent_rgb: tuple[int, int, int],
    style: str = "gold",
) -> "Image.Image":
    """
    Build a Reels/TikTok-style rounded pill highlight behind the active word.

    Creates a semi-transparent filled box with a glowing outline, padded
    slightly beyond the word's ink bounds.  The overlay is composited on top
    of already-pasted text and never re-renders it.

    Args:
        rect:        (x0, y0, x1, y1) bounding box of the active word.
        accent_rgb:  Fallback accent colour (unused when ``style`` matches
                     a preset in HIGHLIGHT_BOX_STYLES).
        style:       Key into HIGHLIGHT_BOX_STYLES ("gold" / "teal" / "rose").

    Returns:
        RGBA PIL.Image sized to the padded box, ready for paste().
    """
    from PIL import Image, ImageDraw, ImageFilter

    preset = HIGHLIGHT_BOX_STYLES.get(style, HIGHLIGHT_BOX_STYLES["gold"])
    fill_rgba = tuple(preset["fill"])
    outline_rgba = tuple(preset["outline"])
    glow_rgba = tuple(preset["glow"])
    radius_ratio = float(preset["radius_ratio"])
    pad_x = int(preset["padding_x"])
    pad_y = int(preset["padding_y"])
    border_w = int(preset["width"])

    x0, y0, x1, y1 = (int(v) for v in rect)
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)

    # Padded canvas
    cw = w + 2 * pad_x
    ch = h + 2 * pad_y

    # Glow layer (soft blur behind the box)
    glow_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.rounded_rectangle(
        [0, 0, cw - 1, ch - 1],
        radius=max(4, int(ch * radius_ratio)),
        fill=glow_rgba,
    )
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=8))

    # Main box
    box_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    bd = ImageDraw.Draw(box_layer)
    bd.rounded_rectangle(
        [0, 0, cw - 1, ch - 1],
        radius=max(4, int(ch * radius_ratio)),
        fill=fill_rgba,
        outline=outline_rgba,
        width=border_w,
    )

    # Composite: glow behind, box on top
    result = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    result = Image.alpha_composite(result, glow_layer)
    result = Image.alpha_composite(result, box_layer)

    return result
