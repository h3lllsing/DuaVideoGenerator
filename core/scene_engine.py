"""
Scene Engine (VISUAL Phase 2).

Deterministic procedural SceneEngine that produces visual variety for
1080x1920 @ 30 FPS dua Shorts WITHOUT requiring any background image
assets. Everything is generated procedurally from a seed (dua_id) so the
same dua always looks the same and different duas can look different.

Architecture (approved):
  - MotionSpec  : deterministic background motion (static / zoom / pan)
  - TextLayer   : a single text element (title, arabic, urdu)
  - Transition  : scene fade-in / fade-out
  - Scene       : a timed segment (palette + motion + decorations + layers)
  - Timeline    : ordered scenes over a total duration (VIDEO-002 final_duration)
  - SceneRenderer: renders a Timeline to the existing List[Image] contract
                   consumed by VideoBuilder.

Content safety (HARD requirement):
  - Formal safe rectangle for critical content (SAFE_RECT).
  - Explicit reserved rectangles for decorative zones (top/bottom bands,
    side strips, watermark area) - decoration NEVER overlaps text.
  - Text is laid out with measured bounding boxes; if content does not fit,
    the cascade is: wrap -> shrink fonts -> reduce spacing -> alternate
    layout. Before rendering, every text bbox is verified to lie inside
    SAFE_RECT and to be disjoint from every reserved rect.

Motion safety: background motion (Ken Burns / pan / zoom) applies to the
BACKGROUND ONLY. Critical text is composited from pre-rendered surfaces at
fixed positions, so it is geometrically stable regardless of motion.

Duration: the renderer fills exactly the caller-supplied final duration
(VIDEO-002). Speech is never stretched, duplicated, or cut.

No packages are installed; no external images are downloaded.
"""

import logging
import os
import random
from typing import Any, cast
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

from core.arabic_renderer import ArabicRenderer, _is_arabic
from core.arabic_renderer import apply_vertical_gradient as _apply_gradient
from core.project_info import PROJECT

# Shared HarfBuzz renderer (proper Arabic/Urdu shaping with harakat).
_AR_RENDERER = ArabicRenderer()

try:
    import config
except Exception:
    config = None  # type: ignore[assignment]

# PERFORMANCE FIX: Import AssetRegistry for Pexels backgrounds
try:
    from core.asset_registry import AssetRegistry, is_video_file

    _ASSET_REGISTRY = AssetRegistry()
    _HAS_ASSET_REGISTRY = True
    logger.info(f"AssetRegistry loaded: {len(_ASSET_REGISTRY.get_loadable_assets())} loadable assets")
except Exception as e:
    _ASSET_REGISTRY = None  # type: ignore[assignment]
    _HAS_ASSET_REGISTRY = False
    logger.debug(f"AssetRegistry not available: {e}")

__all__ = ["MotionSpec", "TextLayer", "Transition", "Scene", "Timeline", "rect_intersect", "rect_within"]


# ----------------------------------------------------------------------
# Canvas + content-safety geometry
# ----------------------------------------------------------------------
CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
DEFAULT_FPS = 30

# Formal content safe rectangle (x0, y0, x1, y1). Critical Arabic/Urdu/title
# text must ALWAYS lie fully inside this rectangle.
SAFE_RECT: tuple[int, int, int, int] = (60, 110, 1020, 1810)

# Explicit reserved rectangles for decorative zones. Decoration lives ONLY
# inside these; text NEVER enters them (enforced before rendering).
RESERVED_RECTS: list[tuple[int, int, int, int]] = [
    (0, 0, 1080, 110),  # top decorative band
    (0, 1810, 1080, 1920),  # bottom decorative band + future watermark area
    (0, 110, 60, 1810),  # left decorative strip
    (1020, 110, 1080, 1810),  # right decorative strip
]

MIN_FONT_SIZE = 26
TEXT_OUTLINE_WIDTH = 4

# Premium look: Arabic lines fade from the layer color into warm gold.
_AR_GRADIENT_BOTTOM = (255, 222, 140)

# Import from master config - SINGLE SOURCE OF TRUTH
from core.master_config import (
    MASTER_PALETTES,
    PALETTE_NAMES,
    TEXT_STYLES,
    MOTION_KINDS,
    CORNER_STYLES,
    HIGHLIGHT_BOX_STYLES,
    BACKGROUND_GRADIENT_KINDS,
)


def _resolve_font_path() -> str:
    candidates = [
        os.path.join(PROJECT.FONTS_DIR, "Amiri-Bold.ttf"),
        os.path.join(PROJECT.FONTS_DIR, "NotoNaskhArabic-Regular.ttf"),
        getattr(config, "ARABIC_FONT", None),
        getattr(config, "ARABIC_FONT_BOLD", None),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    raise FileNotFoundError("No Arabic font found. Checked: " + ", ".join(str(c) for c in candidates))


FONT_PATH = _resolve_font_path()


def rect_intersect(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """True when two axis-aligned rects strictly overlap (touch == no)."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    return ix > 0 and iy > 0


def rect_within(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> bool:
    """True when inner rect is completely inside outer rect."""
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


# ----------------------------------------------------------------------
# Architecture dataclasses
# ----------------------------------------------------------------------
@dataclass
class MotionSpec:
    """Deterministic background motion. Background only - never text."""

    kind: str = "static"
    zoom: float = 0.05  # subtle max zoom delta (5%)
    pan: float = 0.04  # subtle max pan offset (4% of a dimension)

    def crop(self, p: float, width: int, height: int) -> tuple[int, int, int, int]:
        """Return the source crop rect (x0,y0,x1,y1) for progress p in [0,1]."""
        p = max(0.0, min(1.0, p))
        bg_w, bg_h = int(width * 1.12), int(height * 1.12)
        margin = 10

        if self.kind == "static":
            w, h = width, height
            x0, y0 = (bg_w - w) // 2, (bg_h - h) // 2
        elif self.kind in ("zoom_in", "zoom_out"):
            z = self.zoom * (p if self.kind == "zoom_in" else (1 - p))
            w, h = int(width * (1 - z)), int(height * (1 - z))
            x0, y0 = (bg_w - w) // 2, (bg_h - h) // 2
        elif self.kind in ("pan_left", "pan_right"):
            w, h = int(width * 0.94), int(height * 0.94)
            span = (bg_w - w) - 2 * margin
            if self.kind == "pan_left":
                x0 = margin + int(span * (1 - p))
            else:
                x0 = margin + int(span * p)
            y0 = (bg_h - h) // 2
        elif self.kind in ("pan_up", "pan_down"):
            w, h = int(width * 0.94), int(height * 0.94)
            span = (bg_h - h) - 2 * margin
            if self.kind == "pan_up":
                y0 = margin + int(span * (1 - p))
            else:
                y0 = margin + int(span * p)
            x0 = (bg_w - w) // 2
        else:
            w, h, x0, y0 = width, height, (bg_w - width) // 2, (bg_h - height) // 2

        w, h = max(16, w), max(16, h)
        x0 = min(max(0, x0), bg_w - w)
        y0 = min(max(0, y0), bg_h - h)
        return (x0, y0, x0 + w, y0 + h)


@dataclass
class TextLayer:
    """A single critical text element. Text is NEVER altered by the engine."""

    role: str  # "title" | "arabic" | "urdu"
    text: str
    language: str = "title"  # "ar" | "ur" | "title"
    font_size: int = 0  # 0 => auto by role
    color: tuple[int, int, int] = (255, 255, 255)
    outline: bool = False
    outline_color: tuple[int, int, int] = (10, 12, 20)


@dataclass
class Transition:
    """Scene transition (fade through black, or none)."""

    kind: str = "fade"  # "fade" | "none"
    duration: float = 0.4


@dataclass
class Scene:
    """One timed visual segment."""

    duration: float = 15.0
    palette: dict = field(default_factory=dict)
    motion: MotionSpec = field(default_factory=MotionSpec)
    layers: list[TextLayer] = field(default_factory=list)
    particle_count: int = 40
    corner_style: str = "classic"
    text_style: str = "solid"
    transition_in: Transition = field(default_factory=Transition)
    transition_out: Transition = field(default_factory=Transition)
    # VISUAL Phase 4: optional WordBoundary events per role ("arabic"/"urdu"),
    # scene-relative seconds. None => legacy rendering (no highlighting).
    word_events: dict[str, list[dict]] | None = None
    # Highlight style: None/"" = legacy subtle overlay, "gold"/"teal"/"rose" = box style
    highlight_style: str = ""
    # Background gradient kind: "" = default linear, "aurora" = animated shifting gradient
    gradient_kind: str = ""

    def palette_name(self) -> str:
        return cast(str, self.palette.get("name", "midnight"))


@dataclass
class Timeline:
    """Ordered scenes filling a total duration. Frames follow fps exactly."""

    fps: int = DEFAULT_FPS
    scenes: list[Scene] = field(default_factory=list)

    @property
    def total_duration(self) -> float:
        return sum(s.duration for s in self.scenes)

    @property
    def total_frames(self) -> int:
        return int(round(self.total_duration * self.fps))

    def frames_for_scene(self, index: int) -> int:
        """Per-scene frame counts; last scene absorbs rounding to match total."""
        counts = [int(round(s.duration * self.fps)) for s in self.scenes]
        diff = self.total_frames - sum(counts)
        counts[-1] += diff
        return counts[index]


# ----------------------------------------------------------------------
# SceneRenderer
# ----------------------------------------------------------------------
class SceneRenderer:
    """
    Renders a Timeline into the existing List[Image] contract consumed by
    VideoBuilder (unchanged). Fully deterministic from `seed`.

    PERFORMANCE FIX: Added frame caching to avoid redundant redraws.
    """

    def __init__(self, width: int = CANVAS_WIDTH, height: int = CANVAS_HEIGHT, fps: int = DEFAULT_FPS):
        self.width = width
        self.height = height
        self.fps = fps
        self._font_cache: dict[int, ImageFont.FreeTypeFont] = {}
        # PERFORMANCE FIX: Frame caching for static backgrounds
        self._gradient_cache: dict[str, Image.Image] = {}
        self._surface_cache: dict[str, list[dict]] = {}

    def _get_gradient_key(self, palette: dict, bg_w: int, bg_h: int) -> str:
        """Generate cache key for gradient."""
        return f"{palette.get('name', 'default')}_{bg_w}_{bg_h}"

    def _get_surface_key(self, scene: Scene) -> str:
        """Generate cache key for text surfaces."""
        # Cache key based on scene content (text, style, palette)
        return f"{hash(scene.palette.get('name', ''))}_{hash(scene.text_style)}_{len(scene.layers)}"

    # -- fonts / reshaping --------------------------------------------
    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._font_cache:
            self._font_cache[size] = ImageFont.truetype(FONT_PATH, size)
        return self._font_cache[size]

    @staticmethod
    def _text_w(font, text: str) -> int:
        bb = font.getbbox(text)
        assert bb is not None
        return int(bb[2] - bb[0])

    @staticmethod
    def _measure(font, text: str, language: str) -> int:
        """Width of a line/word in px. Arabic-script text is measured through
        the HarfBuzz renderer (logical text, correct shaped width); LTR text
        through the PIL font."""
        if language in ("ar", "ur") and _is_arabic(text):
            return int(round(_AR_RENDERER.measure_width(text, font.size)))
        return SceneRenderer._text_w(font, text)

    def _wrap(self, text: str, font, max_w: int, language: str) -> list[str]:
        """Wrap LOGICAL text (NOT bidi-reordered) so multi-line RTL content
        keeps start->top / end->bottom order. Widths are measured with the
        HarfBuzz shaper for Arabic/Urdu."""
        lines: list[str] = []
        current = ""
        for word in text.split():
            test = (current + " " + word) if current else word
            if self._measure(font, test, language) <= max_w:
                current = test
                continue
            if current:
                lines.append(current)
            current = ""
            # hard-break an over-long unbroken word by measured chunks
            while word and self._measure(font, word, language) > max_w:
                i = 1
                while i < len(word) and self._measure(font, word[:i], language) <= max_w:
                    i += 1
                cut = i - 1 if i > 1 else 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        if current:
            lines.append(current)
        return lines or [text]

    # -- layout --------------------------------------------------------
    def compute_layout(self, scene: Scene) -> dict:
        """
        Lay out all critical text inside SAFE_RECT using measured bounding
        boxes. Fallback cascade: wrap -> shrink fonts -> reduce spacing ->
        alternate layout (tighter gaps). Returns a layout dict with per-line
        pixel bboxes, or raises if content physically cannot fit.
        """
        sx0, sy0, sx1, sy1 = SAFE_RECT
        pad = 24
        wrap_w = (sx1 - sx0) - 2 * pad
        avail_h = (sy1 - sy0) - 2 * pad
        layers = list(scene.layers)

        base_sizes = {"title": 60, "arabic": 72, "urdu": 54}
        sizes = {l.role: (l.font_size or base_sizes.get(l.role, 54)) for l in layers}
        spacing = 1.30
        gap = 26
        fallback = "primary"

        def build_blocks():
            blocks = []
            total = 0
            for layer in layers:
                size = sizes[layer.role]
                font = self._font(size)
                lines = self._wrap(layer.text, font, wrap_w, layer.language)
                line_h = max(int(size * spacing), size + 8)
                block_h = len(lines) * line_h
                blocks.append((layer, lines, size, line_h, block_h))
                total += block_h
            return blocks, total + gap * (len(layers) - 1)

        for _attempt in range(15):
            blocks, total_h = build_blocks()
            if total_h <= avail_h:
                break
            if any(sizes[r] > MIN_FONT_SIZE for r in sizes):
                shrink = avail_h / total_h
                for role in sizes:
                    sizes[role] = max(MIN_FONT_SIZE, int(sizes[role] * shrink))
                fallback = "shrunk"
            elif spacing > 1.10:
                spacing = max(1.10, spacing - 0.05)
                fallback = "spacing"
            elif pad > 12:
                # alternate layout: tighter inter-block gap + padding
                gap = 12
                pad = 12
                wrap_w = (sx1 - sx0) - 2 * pad
                avail_h = (sy1 - sy0) - 2 * pad
                fallback = "alternate"
            else:
                raise ValueError(f"Content cannot fit in SAFE_RECT {SAFE_RECT} (needs {total_h}px, has {avail_h}px).")

        blocks, total_h = build_blocks()
        if total_h > avail_h:
            raise ValueError(f"Content cannot fit in SAFE_RECT {SAFE_RECT} (needs {total_h}px, has {avail_h}px).")

        start_y = sy0 + pad + max(0, (avail_h - total_h) // 2)
        cursor = start_y
        laid: list[dict] = []
        for layer, lines, size, line_h, _bh in blocks:
            font = self._font(size)
            layer_lines = []
            for line in lines:
                w = self._measure(font, line, layer.language) + 2 * TEXT_OUTLINE_WIDTH
                x = sx0 + (wrap_w - w) // 2 + pad
                bbox = (x, cursor, x + w, cursor + line_h)
                layer_lines.append(
                    {
                        "text": line,
                        "font_size": size,
                        "x": x,
                        "y": cursor,
                        "w": w,
                        "h": line_h,
                        "bbox": bbox,
                    }
                )
                cursor += line_h
            laid.append(
                {
                    "role": layer.role,
                    "lines": layer_lines,
                    "block_h": len(lines) * line_h,
                }
            )
            cursor += gap

        return {
            "layers": laid,
            "total_h": total_h,
            "spacing": spacing,
            "gap": gap,
            "font_fallback": fallback,
            "fits": True,
        }

    def verify_layout(self, scene: Scene, layout: dict) -> list[str]:
        """
        Mathematically verify every critical text bbox is inside SAFE_RECT
        and disjoint from every reserved rect. Returns a list of issues
        (empty == clean).
        """
        issues: list[str] = []
        for layer in layout["layers"]:
            for line in layer["lines"]:
                b = line["bbox"]
                if not rect_within(b, SAFE_RECT):
                    issues.append(
                        f"{layer['role']} line '{line['text'][:20]}' bbox {b} not inside SAFE_RECT {SAFE_RECT}"
                    )
                for r in RESERVED_RECTS:
                    if rect_intersect(b, r):
                        issues.append(
                            f"{layer['role']} line '{line['text'][:20]}' bbox {b} intersects reserved rect {r}"
                        )
        return issues

    def _build_text_surfaces(self, scene: Scene, layout: dict) -> list[dict]:
        """Pre-render each text line to an RGBA surface (fixed position)."""
        surfaces = []
        layer_by_role = {l.role: l for l in scene.layers}
        for layer in layout["layers"]:
            spec = layer_by_role[layer["role"]]
            is_ar = layer["role"] in ("arabic", "urdu", "title") and _is_arabic(
                "".join(ln["text"] for ln in layer["lines"])
            )
            for line in layer["lines"]:
                if is_ar:
                    surf = _AR_RENDERER.render_line(
                        line["text"],
                        line["font_size"],
                        color=tuple(spec.color),
                        outline_color=(tuple(spec.outline_color) if spec.outline else None),
                        outline_width=TEXT_OUTLINE_WIDTH if spec.outline else 0,
                    )
                    if layer["role"] == "arabic":
                        surf = _apply_gradient(surf, tuple(spec.color), _AR_GRADIENT_BOTTOM)
                    # Ink-tight surface can exceed the nominal line box
                    # (stacked harakat overflow font metrics). Expand the
                    # canvas instead of cropping, anchored at box center.
                    cw = max(line["w"], surf.width)
                    ch = max(line["h"], surf.height)
                    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                    off_x = (cw - surf.width) // 2
                    img.paste(surf, (off_x, (ch - surf.height) // 2), surf)
                    # Per-word visual x spans (canvas-relative) keyed by
                    # logical token index -> exact word-highlight geometry.
                    spans = _AR_RENDERER.word_spans(line["text"], line["font_size"])
                    words = [(w["i"], off_x + w["x0"], off_x + w["x1"]) for w in spans["words"]]
                    surfaces.append(
                        {
                            "surface": img,
                            "x": max(0, line["x"] - (cw - line["w"]) // 2),
                            "y": max(0, line["y"] - (ch - line["h"]) // 2),
                            "words": words,
                        }
                    )
                    continue
                img = Image.new("RGBA", (line["w"], line["h"]), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                font = self._font(line["font_size"])
                bb = d.textbbox((0, 0), line["text"], font=font, stroke_width=TEXT_OUTLINE_WIDTH)
                dx = -bb[0]
                dy = -bb[1]
                if spec.outline:
                    d.text(
                        (dx, dy),
                        line["text"],
                        font=font,
                        fill=tuple(spec.color) + (255,),
                        stroke_width=TEXT_OUTLINE_WIDTH,
                        stroke_fill=tuple(spec.outline_color) + (255,),
                    )
                else:
                    d.text((dx, dy), line["text"], font=font, fill=tuple(spec.color) + (255,))
                surfaces.append(
                    {
                        "surface": img,
                        "x": line["x"],
                        "y": line["y"],
                    }
                )
        return surfaces

    # -- background / decorations --------------------------------------
    @staticmethod
    def _build_gradient(palette: dict, bg_w: int, bg_h: int) -> Image.Image:
        top = np.array(palette["top"], dtype=np.float64)
        bottom = np.array(palette["bottom"], dtype=np.float64)
        rows = np.linspace(0.0, 1.0, bg_h)[:, None]
        grad = (top * (1 - rows) + bottom * rows).astype(np.uint8)
        img = np.repeat(grad[:, None, :], bg_w, axis=1)
        return Image.fromarray(img)

    @staticmethod
    def _build_aurora_gradient(palette: dict, bg_w: int, bg_h: int, progress: float) -> Image.Image:
        """Animated aurora/northern-lights gradient.

        Shifts 3 soft colour bands vertically over time using sine waves,
        producing a slowly morphing, ethereal background.  The palette's
        ``top`` / ``bottom`` colours define the two main bands; a third
        accent band (from ``accent``) floats between them.

        Args:
            palette:   Standard palette dict with top/bottom/accent.
            bg_w:      Output width (oversized for motion crop).
            bg_h:      Output height.
            progress:  Scene progress 0..1 (drives the animation).

        Returns:
            PIL.Image RGB at (bg_w, bg_h).
        """
        top = np.array(palette["top"], dtype=np.float64)
        bottom = np.array(palette["bottom"], dtype=np.float64)
        accent = np.array(palette.get("accent", (212, 175, 55)), dtype=np.float64)

        ys = np.linspace(0.0, 1.0, bg_h)[:, None]  # (H, 1)

        # Three gaussian-ish bands that drift vertically with progress.
        # Band centres oscillate gently via sine.
        c1 = 0.20 + 0.08 * np.sin(progress * np.pi * 2)  # top band
        c2 = 0.50 + 0.06 * np.cos(progress * np.pi * 2 + 1.0)  # middle (accent)
        c3 = 0.80 + 0.08 * np.sin(progress * np.pi * 2 + 2.5)  # bottom band

        sigma = 0.18  # band width
        w1 = np.exp(-((ys - c1) ** 2) / (2 * sigma**2))
        w2 = np.exp(-((ys - c2) ** 2) / (2 * sigma**2))
        w3 = np.exp(-((ys - c3) ** 2) / (2 * sigma**2))

        # Normalise weights so they sum to ~1 per row.
        wt = w1 + w2 + w3 + 1e-8
        w1, w2, w3 = w1 / wt, w2 / wt, w3 / wt

        # Weighted blend of the three colours per row.
        grad = (w1 * top + w2 * accent + w3 * bottom).astype(np.uint8)
        # Horizontal tiling with subtle horizontal oscillation.
        grad_row = grad[:, None, :]  # (H, 1, 3)
        grad_2d = np.repeat(grad_row, bg_w, axis=1)  # (H, W, 3)
        h_shift = (3 * np.sin(progress * np.pi * 3 + np.linspace(0, np.pi, bg_w))).astype(np.float32)
        # Apply a mild horizontal colour temperature shift.
        r_shift = (h_shift * 0.6).astype(np.int16)
        grad_2d[:, :, 0] = np.clip(grad_2d[:, :, 0].astype(np.int16) + r_shift.T, 0, 255).astype(np.uint8)
        grad_2d[:, :, 2] = np.clip(grad_2d[:, :, 2].astype(np.int16) - r_shift.T, 0, 255).astype(np.uint8)

        return Image.fromarray(grad_2d)

    def _load_pexels_background(self, dua_id: str, category: str, bg_w: int, bg_h: int) -> Image.Image | None:
        """Load Pexels background image/video frame.

        PERFORMANCE FIX: Uses AssetRegistry to load real nature backgrounds
        instead of procedural gradients. Random mode ensures different
        backgrounds each time.

        Returns:
            PIL.Image if successful, None if fallback needed
        """
        if not _HAS_ASSET_REGISTRY or _ASSET_REGISTRY is None:
            return None

        try:
            # Get prefer_video setting from config
            prefer_video = getattr(config, "BACKGROUND_PREFER_VIDEO", True) if config else True

            # Select background from registry (RANDOM MODE)
            result = _ASSET_REGISTRY.select_background(
                dua_id=dua_id,
                category=category,
                prefer_video=prefer_video,
                random_mode=True,  # Random selection each time
            )

            if result.get("kind") != "asset":
                return None

            asset_path = result.get("path", "")
            if not asset_path or not os.path.isfile(asset_path):
                return None

            logger.debug(f"Random background selected: {result.get('asset_id')}")

            # Load based on file type
            if is_video_file(asset_path):
                return self._load_video_frame(asset_path, bg_w, bg_h)
            else:
                return self._load_image_background(asset_path, bg_w, bg_h)

        except Exception as e:
            logger.debug(f"Pexels background load failed: {e}")
            return None

    def _load_image_background(self, path: str, bg_w: int, bg_h: int) -> Image.Image | None:
        """Load and resize Pexels image background."""
        try:
            img: Image.Image = Image.open(path)
            # Convert to RGB if needed
            if img.mode != "RGB":
                img = img.convert("RGB")
            # Resize to fill background (crop if needed)
            img = self._fit_crop(img, bg_w, bg_h)
            return img
        except Exception as e:
            logger.debug(f"Image load failed: {e}")
            return None

    def _load_video_frame(self, path: str, bg_w: int, bg_h: int) -> Image.Image | None:
        """Extract first frame from video as background."""
        try:
            import subprocess
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            # Extract first frame
            cmd = [
                ffmpeg,
                "-i",
                path,
                "-vframes",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "-hide_banner",
                "-loglevel",
                "error",
                "pipe:1",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=10)

            if result.returncode == 0 and result.stdout:
                from io import BytesIO

                img: Image.Image = Image.open(BytesIO(result.stdout))
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img = self._fit_crop(img, bg_w, bg_h)
                return img
        except Exception as e:
            logger.debug(f"Video frame extraction failed: {e}")
        return None

    @staticmethod
    def _fit_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """Crop and resize image to fit target dimensions (cover fit)."""
        src_w, src_h = img.size
        # Calculate scale to cover target
        scale = max(target_w / src_w, target_h / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        # Center crop
        left = (new_w - target_w) // 2
        top_crop = (new_h - target_h) // 2
        img = img.crop((left, top_crop, left + target_w, top_crop + target_h))
        return img

    @staticmethod
    def _draw_particles(frame, particles, frame_i, drift):
        d = ImageDraw.Draw(frame)
        for x, y, r, phase, alpha in particles:
            if drift:
                dx = int(3 * np.sin(2 * np.pi * frame_i * 0.02 + phase))
                dy = int(3 * np.cos(2 * np.pi * frame_i * 0.02 + phase))
            else:
                dx = dy = 0
            d.ellipse([(x + dx - r, y + dy - r), (x + dx + r, y + dy + r)], fill=(255, 245, 210, alpha))

    @staticmethod
    def _draw_decorations(frame, scene, accent, text_style):
        """Draw decorations ONLY inside RESERVED_RECTS."""
        d = ImageDraw.Draw(frame)
        W, H = frame.size
        alpha_line = 170

        # Top band ornament (y in 0..110)
        ty = 55
        d.line([(90, ty), (W - 90, ty)], fill=accent + (alpha_line,), width=2)
        d.line([(90, ty - 8), (W - 90, ty - 8)], fill=accent + (alpha_line // 2,), width=1)
        # center diamond
        d.polygon([(W // 2, ty - 8), (W // 2 + 8, ty), (W // 2, ty + 8), (W // 2 - 8, ty)], fill=accent + (alpha_line,))

        # Bottom band ornament (y in 1810..1920)
        by = H - 55
        d.line([(90, by), (W - 90, by)], fill=accent + (alpha_line,), width=2)
        d.line([(90, by + 8), (W - 90, by + 8)], fill=accent + (alpha_line // 2,), width=1)
        d.polygon([(W // 2, by - 8), (W // 2 + 8, by), (W // 2, by + 8), (W // 2 - 8, by)], fill=accent + (alpha_line,))

        # Side strips (x in 0..60 and 1020..1080, y in 110..1810)
        sx = 30
        d.line([(sx, 150), (sx, H - 150)], fill=accent + (alpha_line // 2,), width=2)
        d.line([(W - sx, 150), (W - sx, H - 150)], fill=accent + (alpha_line // 2,), width=2)

        # Corner brackets (inside reserved corners)
        c = 46
        m = 14
        style = scene.corner_style
        for cx, cy, dx, dy in [(m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)]:
            if style == "double":
                d.line([(cx, cy), (cx + dx * c, cy)], fill=accent + (255,), width=3)
                d.line([(cx, cy), (cx, cy + dy * c)], fill=accent + (255,), width=3)
                d.line([(cx + dx * 12, cy + dy * 4), (cx + dx * c, cy + dy * 4)], fill=accent + (200,), width=2)
                d.line([(cx + dx * 4, cy + dy * 12), (cx + dx * 4, cy + dy * c)], fill=accent + (200,), width=2)
            elif style == "dot":
                d.line([(cx, cy), (cx + dx * c, cy)], fill=accent + (255,), width=3)
                d.line([(cx, cy), (cx, cy + dy * c)], fill=accent + (255,), width=3)
                r = 4
                xa = cx + dx * (c - 2 * r)
                ya = cy + dy * (c - 2 * r)
                xb = cx + dx * c
                yb = cy + dy * c
                d.ellipse([(min(xa, xb), min(ya, yb)), (max(xa, xb), max(ya, yb))], fill=accent + (255,))
            else:  # classic
                d.line([(cx, cy), (cx + dx * c, cy)], fill=accent + (255,), width=3)
                d.line([(cx, cy), (cx, cy + dy * c)], fill=accent + (255,), width=3)

    @staticmethod
    def _apply_transition(frame, scene, frame_i, frame_count, fps):
        d = ImageDraw.Draw(frame)
        tin = min(scene.transition_in.duration, scene.duration / 2) if scene.transition_in.kind == "fade" else 0.0
        tout = min(scene.transition_out.duration, scene.duration / 2) if scene.transition_out.kind == "fade" else 0.0
        n_in = int(round(tin * fps))
        n_out = int(round(tout * fps))
        alpha = 0
        if n_in > 0 and frame_i < n_in:
            t = _smoothstep(frame_i / n_in)
            alpha = int(255 * (1 - t))
        elif n_out > 0 and frame_i >= frame_count - n_out:
            denom = max(1, n_out - 1)
            prog = (frame_i - (frame_count - n_out)) / denom
            alpha = int(255 * _smoothstep(prog))
        if alpha > 0:
            d.rectangle([0, 0, frame.size[0], frame.size[1]], fill=(0, 0, 0, alpha))

    # -- word highlighting (VISUAL Phase 4, additive) ---------------------
    def _build_highlight(self, scene: Scene, layout: dict, surfaces: list[dict] | None = None):
        """
        Build per-role highlight data once per scene: normalized events,
        word geometry, accent. Returns None when there is nothing to draw.
        Missing/corrupt events for a role simply disable that role's
        highlight; the video renders normally.

        ``surfaces`` (from _build_text_surfaces, same layer/line order)
        supplies exact per-word pixel spans; without them the geometry
        falls back to line-level boxes.
        """
        from core.word_highlight import build_word_geometry, normalize_events

        layer_by_role = {l.role: l for l in scene.layers}
        surf_iter = iter(surfaces) if surfaces is not None else None
        hl = {}
        for layer in layout["layers"]:
            role = layer["role"]
            lines = layer["lines"]
            # Consume one surface per line to stay in sync with the flat
            # surfaces list, regardless of early skips below.
            spans_out: list[list[Any]] = []
            spans_ok = True
            for line in lines:
                s = next(surf_iter, None) if surf_iter is not None else None
                ws = s.get("words") if s is not None else None
                if ws:
                    assert s is not None
                    fx = s["x"]
                    spans_out.append([(i, fx + a, fx + b) for (i, a, b) in ws])
                else:
                    spans_ok = False
            line_spans: list[list[Any]] | None = spans_out if spans_ok else None
            events = (scene.word_events or {}).get(role)
            spec = layer_by_role.get(role)
            if not events or lines is None or not lines:
                continue
            if spec is None or spec.language not in ("ar", "ur"):
                continue
            # Geometry and timing MUST see the same event list: normalize
            # first, then count, so a dropped junk entry can't cause a
            # spurious word/token mismatch fallback.
            clean_events = normalize_events(events)
            font = self._font(lines[0]["font_size"])

            def _measure_word(w: str, _f: Any = font) -> int:
                return self._text_w(_f, w)

            geometry = build_word_geometry(
                spec.language,
                spec.text,
                lines,
                len(clean_events),
                _measure_word,
                outline_pad=TEXT_OUTLINE_WIDTH,
                line_spans=(line_spans or None),
            )
            hl[role] = {
                "events": clean_events,
                "geometry": geometry,
                "accent": scene.palette["accent"],
            }
        return hl or None

    def _apply_highlight(self, frame: Image.Image, highlight: dict, t: float, highlight_style: str = ""):
        """Draw the active word's overlay on the frame at scene time ``t``."""
        from core.word_highlight import highlight_targets, make_word_overlay, make_word_highlight_box

        for role, info in highlight.items():
            rect = highlight_targets(info["events"], info["geometry"], t)
            if rect is None:
                continue
            if highlight_style and highlight_style in ("gold", "teal", "rose"):
                overlay = make_word_highlight_box(rect, info["accent"], style=highlight_style)
            else:
                overlay = make_word_overlay(rect, info["accent"])
            frame.paste(
                overlay,
                (
                    int(rect[0]) - max(0, (overlay.width - (rect[2] - rect[0])) // 2),
                    int(rect[1]) - max(0, (overlay.height - (rect[3] - rect[1])) // 2),
                ),
                overlay,
            )

    # -- scene construction ---------------------------------------------
    def build_single_scene(
        self,
        seed: str,
        arabic: str,
        urdu: str,
        title: str = "",
        duration: float | None = None,
        palette: dict | None = None,
        motion: MotionSpec | None = None,
        font_style: str | None = None,
        highlight_style: str = "",
        gradient_kind: str = "",
    ) -> Scene:
        """
        Deterministically build one procedural Scene from content + seed.
        This is NOT TimelineBuilder (Phase 3); it renders a single timed
        segment filling `duration` seconds exactly.
        """
        rng = random.Random(f"{seed}:style")
        if duration is None:
            duration = float(getattr(config, "VIDEO_MIN_DURATION", 15))
        pal_name = palette if isinstance(palette, str) else (palette.get("name") if isinstance(palette, dict) else None)
        if pal_name and pal_name in MASTER_PALETTES:
            pal = dict(MASTER_PALETTES[pal_name])
        else:
            pal = dict(MASTER_PALETTES[rng.choice(PALETTE_NAMES)])
        mot = motion or MotionSpec(kind=rng.choice(list(MOTION_KINDS)))
        density = rng.randint(24, 60)
        corner = rng.choice(list(CORNER_STYLES))
        text_style = rng.choice(list(TEXT_STYLES))

        layers = [
            TextLayer(role="title", text=title, language="title", color=pal["title"]),
        ]
        if text_style == "solid":
            layers.append(TextLayer(role="arabic", text=arabic, language="ar", color=pal["text"]))
            layers.append(TextLayer(role="urdu", text=urdu, language="ur", color=pal["text"]))
        elif text_style == "gold":
            layers.append(
                TextLayer(
                    role="arabic",
                    text=arabic,
                    language="ar",
                    color=pal["accent"],
                    outline=True,
                    outline_color=pal["outline"],
                )
            )
            layers.append(
                TextLayer(
                    role="urdu", text=urdu, language="ur", color=pal["text"], outline=True, outline_color=pal["outline"]
                )
            )
        elif text_style == "glow":
            layers.append(TextLayer(role="arabic", text=arabic, language="ar", color=(255, 255, 255)))
            layers.append(TextLayer(role="urdu", text=urdu, language="ur", color=(255, 255, 255)))
        elif text_style == "gradient":
            layers.append(TextLayer(role="arabic", text=arabic, language="ar", color=(255, 255, 255)))
            layers.append(TextLayer(role="urdu", text=urdu, language="ur", color=pal["text"]))
        elif text_style == "shadow":
            layers.append(
                TextLayer(
                    role="arabic", text=arabic, language="ar", color=pal["text"], outline=True, outline_color=(0, 0, 0)
                )
            )
            layers.append(
                TextLayer(
                    role="urdu", text=urdu, language="ur", color=pal["text"], outline=True, outline_color=(0, 0, 0)
                )
            )
        else:  # outline
            layers.append(
                TextLayer(
                    role="arabic",
                    text=arabic,
                    language="ar",
                    color=pal["text"],
                    outline=True,
                    outline_color=pal["outline"],
                )
            )
            layers.append(
                TextLayer(
                    role="urdu", text=urdu, language="ur", color=pal["text"], outline=True, outline_color=pal["outline"]
                )
            )

        return Scene(
            duration=duration,
            palette=pal,
            motion=mot,
            layers=layers,
            particle_count=density,
            corner_style=corner,
            text_style=text_style,
            highlight_style=highlight_style,
            gradient_kind=gradient_kind,
        )

    # -- rendering -------------------------------------------------------
    def render_scene(
        self,
        scene: Scene,
        frame_count: int,
        seed: str,
        scene_index: int = 0,
        dua_id: str | None = None,
        category: str | None = None,
    ):
        """Render one scene as a generator (memory-efficient streaming).

        PERFORMANCE FIX: Uses cached gradients and surfaces to avoid redundant redraws.
        PRIORITY FIX: Loads Pexels backgrounds when available.
        """
        layout = self.compute_layout(scene)
        issues = self.verify_layout(scene, layout)
        if issues:
            raise RuntimeError("Layout safety verification failed:\n" + "\n".join(issues))

        # PERFORMANCE FIX: Cache text surfaces (same content = same surfaces)
        surface_key = self._get_surface_key(scene)
        if surface_key in self._surface_cache:
            surfaces = self._surface_cache[surface_key]
        else:
            surfaces = self._build_text_surfaces(scene, layout)
            self._surface_cache[surface_key] = surfaces

        highlight = self._build_highlight(scene, layout, surfaces) if scene.word_events else None
        bg_w, bg_h = int(self.width * 1.12), int(self.height * 1.12)

        # PRIORITY FIX: Try loading Pexels background first
        pexels_bg = None
        if dua_id and category:
            pexels_bg = self._load_pexels_background(dua_id, category, bg_w, bg_h)

        if pexels_bg is not None:
            # Use Pexels background
            gradient = pexels_bg
            logger.debug(f"Using Pexels background for {dua_id}")
        else:
            # Fallback to procedural gradient
            gradient_key = self._get_gradient_key(scene.palette, bg_w, bg_h)
            if gradient_key in self._gradient_cache:
                gradient = self._gradient_cache[gradient_key]
            else:
                gradient = self._build_gradient(scene.palette, bg_w, bg_h)
                self._gradient_cache[gradient_key] = gradient

        particle_rng = random.Random(f"{seed}:particles:{scene_index}")
        particles = []
        reserved = RESERVED_RECTS + [SAFE_RECT]  # particles only outside safe
        for _ in range(scene.particle_count):
            rx0, ry0, rx1, ry1 = particle_rng.choice([r for r in reserved if r != SAFE_RECT])
            x = particle_rng.randint(rx0, rx1)
            y = particle_rng.randint(ry0, ry1)
            r = particle_rng.randint(1, 2)
            phase = particle_rng.uniform(0, 2 * np.pi)
            alpha = particle_rng.randint(90, 150)
            particles.append((x, y, r, phase, alpha))

        accent = scene.palette["accent"]
        use_aurora = scene.gradient_kind == "aurora"
        for i in range(frame_count):
            p = 0.0 if frame_count <= 1 else i / (frame_count - 1)
            if use_aurora:
                # Per-frame animated gradient (no caching)
                gradient = self._build_aurora_gradient(scene.palette, bg_w, bg_h, p)
            crop = scene.motion.crop(p, self.width, self.height)
            frame = gradient.crop(crop).resize((self.width, self.height), Image.Resampling.LANCZOS)
            if frame.mode != "RGBA":
                frame = frame.convert("RGBA")
            self._draw_particles(frame, particles, i, scene.motion.kind != "static")
            self._draw_decorations(frame, scene, accent, scene.text_style)
            for surf in surfaces:
                frame.paste(surf["surface"], (surf["x"], surf["y"]), surf["surface"])
            if highlight is not None:
                t = i / self.fps
                self._apply_highlight(frame, highlight, t, scene.highlight_style)
            self._apply_transition(frame, scene, i, frame_count, self.fps)
            yield frame.convert("RGB")

    def render(
        self, timeline: Timeline, seed: str = "default", dua_id: str | None = None, category: str | None = None
    ) -> list[Image.Image]:
        """Render a full Timeline into a list (backward compatible).

        Args:
            timeline: The timeline to render
            seed: Random seed for deterministic rendering
            dua_id: Dua ID for Pexels background selection
            category: Dua category for background selection
        """
        return list(self.render_stream(timeline, seed, dua_id, category))

    def render_stream(
        self, timeline: Timeline, seed: str = "default", dua_id: str | None = None, category: str | None = None
    ):
        """Render a full Timeline as a generator (memory-efficient streaming).

        Args:
            timeline: The timeline to render
            seed: Random seed for deterministic rendering
            dua_id: Dua ID for Pexels background selection
            category: Dua category for background selection
        """
        for idx, scene in enumerate(timeline.scenes):
            yield from self.render_scene(scene, timeline.frames_for_scene(idx), seed, idx, dua_id, category)

    def clear_cache(self):
        """Clear all caches (call when done with a batch of renders)."""
        self._gradient_cache.clear()
        self._surface_cache.clear()
        self._font_cache.clear()
        logger.debug("SceneRenderer caches cleared")
