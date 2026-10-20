"""
Effects Engine Module
6 Professional Visual Effects for Dua Videos
"""

import logging
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

from core.project_info import PROJECT

__all__ = ["EffectsEngine"]


class EffectsEngine:
    """
    6 Professional Visual Effects:
    1. Neon Glow - Glowing text effect
    2. Metallic Gold - Shiny gold metallic text
    3. Typewriter - Character by character reveal
    4. Bounce - Text bounces in
    5. Wave - Wave animation
    6. Glitch - Modern glitch effect
    """

    def __init__(self, width: int | None = None, height: int | None = None):
        """Initialize effects engine."""
        self.width = width or PROJECT.VIDEO_WIDTH
        self.height = height or PROJECT.VIDEO_HEIGHT
        self.effects = {
            "neon_glow": self.neon_glow,
            "metallic_gold": self.metallic_gold,
            "silver_chrome": self.silver_chrome,
            "three_d_shadow": self.three_d_shadow,
            "neon_outline": self.neon_outline,
            "bounce": self.bounce,
            "wave": self.wave,
            "glitch": self.glitch,
            "fade_in_out": self.fade_in_out,
            "slide_left": self.slide_left,
            "scale_up": self.scale_up,
        }
        self._summary_cache: dict[Any, Any] = {}
        self._buffers: dict[str, Image.Image] = {}
        self._vignette_mask: Any = None

    def apply_effect(self, effect_name: str, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Apply specified effect to text image.

        Args:
            effect_name: Name of the effect
            text_img: Text image to apply effect
            frame_num: Current frame number
            total_frames: Total number of frames

        Returns:
            Processed image with effect
        """
        if effect_name in self.effects:
            return self.effects[effect_name](text_img, frame_num, total_frames)
        else:
            # Default: return original with fade-in
            return self._default_fade(text_img, frame_num, total_frames)

    def _default_fade(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """Default fade-in effect."""
        alpha = int(255 * min(1.0, (frame_num / total_frames) * 2))

        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        r, g, b, a = text_img.split()
        a = a.point(lambda p: int(p * (alpha / 255.0)))

        return Image.merge("RGBA", (r, g, b, a))

    def neon_glow(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Neon Glow Effect - Glowing text with animated intensity.

        Args:
            text_img: Text image
            frame_num: Current frame
            total_frames: Total frames

        Returns:
            Image with neon glow effect
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        # Calculate glow intensity (pulsing)
        progress = frame_num / total_frames
        glow_intensity = 0.5 + 0.5 * np.sin(progress * np.pi * 4)

        # Create glow layer
        glow = text_img.copy()
        glow = glow.filter(ImageFilter.GaussianBlur(radius=5))
        enhancer = ImageEnhance.Brightness(glow)
        glow = enhancer.enhance(1.5 + glow_intensity)

        # Apply alpha based on fade-in — split directly, no copy needed
        alpha = int(255 * min(1.0, progress * 2))
        r, g, b, a = text_img.split()
        a = a.point(lambda p: int(p * (alpha / 255.0)))
        main_text = Image.merge("RGBA", (r, g, b, a))

        # Combine glow and main text
        result = Image.new("RGBA", text_img.size, (0, 0, 0, 0))
        result = Image.alpha_composite(result, glow)
        result = Image.alpha_composite(result, main_text)

        return result

    def metallic_gold(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Metallic Gold Effect - Shiny gold metallic text.

        Args:
            text_img: Text image
            frame_num: Current frame
            total_frames: Total frames

        Returns:
            Image with metallic gold effect
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames
        W, H = text_img.size

        # Create gold gradient effect using numpy (vectorized)
        gold_layer = np.zeros((H, W, 4), dtype=np.uint8)
        ys = np.arange(H).reshape(-1, 1)
        gold_intensity = (255 * (1 - ys / H)).astype(np.uint8)
        shimmer = (20 * np.sin(progress * np.pi * 4 + ys * 0.1)).astype(np.int16)
        r = np.clip(gold_intensity + shimmer, 0, 255).astype(np.uint8)
        g = np.clip(gold_intensity + shimmer - 40, 0, 255).astype(np.uint8)
        b = np.zeros_like(r)
        gold_layer[:, :, 0] = r
        gold_layer[:, :, 1] = g
        gold_layer[:, :, 2] = b
        gold_layer[:, :, 3] = 128
        gold_layer_img = Image.fromarray(gold_layer)

        # Apply fade-in
        alpha = int(255 * min(1.0, progress * 2))
        r, g, b, a = text_img.split()
        a = a.point(lambda p: int(p * (alpha / 255.0)))
        text_faded = Image.merge("RGBA", (r, g, b, a))

        # Combine gold gradient with text
        result = Image.new("RGBA", text_img.size, (0, 0, 0, 0))
        result = Image.alpha_composite(result, gold_layer_img)
        result = Image.alpha_composite(result, text_faded)

        return result

    def silver_chrome(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Silver Chrome Effect - Shiny silver metallic text with cold shimmer.
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames
        W, H = text_img.size

        silver_layer = np.zeros((H, W, 4), dtype=np.uint8)
        ys = np.arange(H).reshape(-1, 1)
        silver_intensity = (220 * (1 - ys / H)).astype(np.uint8)
        shimmer = (15 * np.sin(progress * np.pi * 5 + ys * 0.08)).astype(np.int16)
        r = np.clip(silver_intensity + shimmer, 0, 255).astype(np.uint8)
        g = np.clip(silver_intensity + shimmer + 5, 0, 255).astype(np.uint8)
        b = np.clip(silver_intensity + shimmer + 10, 0, 255).astype(np.uint8)
        silver_layer[:, :, 0] = r
        silver_layer[:, :, 1] = g
        silver_layer[:, :, 2] = b
        silver_layer[:, :, 3] = 128
        silver_layer_img = Image.fromarray(silver_layer)

        alpha = int(255 * min(1.0, progress * 2))
        r, g, b, a = text_img.split()
        a = a.point(lambda p: int(p * (alpha / 255.0)))
        text_faded = Image.merge("RGBA", (r, g, b, a))

        result = Image.new("RGBA", text_img.size, (0, 0, 0, 0))
        result = Image.alpha_composite(result, silver_layer_img)
        result = Image.alpha_composite(result, text_faded)

        return result

    def three_d_shadow(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        3D Shadow Effect - Text with depth shadow and perspective.
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames
        W, H = text_img.size

        result = Image.new("RGBA", (W + 20, H + 20), (0, 0, 0, 0))

        alpha = int(255 * min(1.0, progress * 2))
        r, g, b, a = text_img.split()
        a = a.point(lambda p: int(p * (alpha / 255.0)))
        text_faded = Image.merge("RGBA", (r, g, b, a))

        shadow = Image.new("RGBA", text_faded.size, (0, 0, 0, 0))
        shadow_alpha = Image.new("L", shadow.size, 0)
        alpha_draw = ImageDraw.Draw(shadow_alpha)
        W_s, H_s = shadow.size
        for i in range(8, 0, -1):
            alpha_draw.rectangle([(0, 0), (W_s, H_s)], fill=int(40 * i / 8))
            shadow.putalpha(shadow_alpha)
            offset_x = int(i * 1.5)
            offset_y = int(i * 2)
            result.paste(shadow, (offset_x, offset_y), shadow)

        result.paste(text_faded, (0, 0), text_faded)

        return result.crop((0, 0, W, H))

    def neon_outline(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Neon Outline Effect - Glowing outline text with animated color.
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames
        W, H = text_img.size

        glow_color = (
            int(127 + 128 * np.sin(progress * np.pi * 2)),
            int(127 + 128 * np.sin(progress * np.pi * 2 + 2)),
            255,
        )

        outline_mask = text_img.split()[3].point(lambda p: 255 if p > 0 else 0)
        outline_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(outline_layer).rectangle([(0, 0), (W, H)], fill=glow_color + (100,))
        outline_layer.putalpha(outline_mask)

        glow = outline_layer.filter(ImageFilter.GaussianBlur(radius=6))
        enhancer = ImageEnhance.Brightness(glow)
        glow = enhancer.enhance(1.5)

        result = Image.new("RGBA", text_img.size, (0, 0, 0, 0))
        result = Image.alpha_composite(result, glow)
        result = Image.alpha_composite(result, text_img)

        return result

    def fade_in_out(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Fade In/Out Effect - Smooth fade in then fade out.
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames
        if progress < 0.3:
            alpha = int(255 * (progress / 0.3))
        elif progress < 0.7:
            alpha = 255
        else:
            alpha = int(255 * (1 - (progress - 0.7) / 0.3))

        alpha = max(0, min(255, alpha))
        r, g, b, a = text_img.split()
        a = a.point(lambda p: int(p * (alpha / 255.0)))

        return Image.merge("RGBA", (r, g, b, a))

    def slide_left(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Slide Left Effect - Text slides in from the right.
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames
        W, H = text_img.size

        if progress < 0.4:
            slide_progress = progress / 0.4
            offset_x = int(W * (1 - slide_progress))
        else:
            offset_x = 0

        alpha = int(255 * min(1.0, progress * 2))
        r, g, b, a = text_img.split()
        a = a.point(lambda p: int(p * (alpha / 255.0)))
        text_faded = Image.merge("RGBA", (r, g, b, a))

        result = Image.new("RGBA", text_img.size, (0, 0, 0, 0))
        result.paste(text_faded, (max(0, offset_x), 0), text_faded)

        return result

    def scale_up(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Scale Up Effect - Text scales up from small to full size.
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames
        W, H = text_img.size

        scale = 0.3 + 0.7 * (progress / 0.3) if progress < 0.3 else 1.0

        new_w = int(W * scale)
        new_h = int(H * scale)
        if new_w < 1 or new_h < 1:
            new_w, new_h = max(1, new_w), max(1, new_h)

        scaled = text_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        result = Image.new("RGBA", text_img.size, (0, 0, 0, 0))
        paste_x = (W - new_w) // 2
        paste_y = (H - new_h) // 2
        result.paste(scaled, (paste_x, paste_y), scaled)

        return result

    def typewriter(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Typewriter Effect - Character by character reveal.

        Args:
            text_img: Text image
            frame_num: Current frame
            total_frames: Total frames

        Returns:
            Image with typewriter effect
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames

        # Calculate visible width
        visible_width = int(text_img.size[0] * min(1.0, progress * 2))

        # Create mask for visible portion (reuse buffer across frames)
        mask = self._buffers.get("typewriter_mask")
        if mask is None or mask.size != text_img.size:
            mask = Image.new("L", text_img.size, 0)
            self._buffers["typewriter_mask"] = mask
        else:
            mask.paste(0)  # Clear to black
        draw = ImageDraw.Draw(mask)
        draw.rectangle([(0, 0), (visible_width, text_img.size[1])], fill=255)

        # Apply mask to text
        result = Image.new("RGBA", text_img.size, (0, 0, 0, 0))
        result.paste(text_img, (0, 0), mask)

        return result

    def bounce(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Bounce Effect - Text bounces in from top.

        Args:
            text_img: Text image
            frame_num: Current frame
            total_frames: Total frames

        Returns:
            Image with bounce effect
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames

        # Calculate bounce position
        if progress < 0.5:
            # Bounce down
            bounce_progress = progress * 2
            offset_y = int(-200 * (1 - bounce_progress))
        else:
            # Bounce up slightly
            bounce_progress = (progress - 0.5) * 2
            offset_y = int(-20 * bounce_progress)

        # Apply fade-in
        alpha = int(255 * min(1.0, progress * 2))
        r, g, b, a = text_img.split()
        a = a.point(lambda p: int(p * (alpha / 255.0)))
        text_faded = Image.merge("RGBA", (r, g, b, a))

        # Create result with offset (clamped to canvas)
        result = Image.new("RGBA", text_img.size, (0, 0, 0, 0))
        paste_y = max(0, offset_y)  # Clamp to prevent off-screen clipping
        result.paste(text_faded, (0, paste_y), text_faded)

        return result

    def wave(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Wave Effect - Wave animation.

        Args:
            text_img: Text image
            frame_num: Current frame
            total_frames: Total frames

        Returns:
            Image with wave effect
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames

        # Apply fade-in
        alpha = int(255 * min(1.0, progress * 2))
        r, g, b, a = text_img.split()
        a = a.point(lambda p: int(p * (alpha / 255.0)))
        text_faded = Image.merge("RGBA", (r, g, b, a))

        # Vectorized wave distortion using numpy advanced indexing
        arr = np.array(text_faded)
        H, W = arr.shape[:2]
        ys = np.arange(H).reshape(-1, 1)
        wave_offsets = (10 * np.sin(progress * np.pi * 4 + ys * 0.05)).astype(np.int32)
        cols = np.arange(W).reshape(1, -1)
        shifted_cols = (cols + wave_offsets) % W
        arr = arr[ys, shifted_cols]
        result = Image.fromarray(arr)

        return result

    def glitch(self, text_img: Image.Image, frame_num: int, total_frames: int) -> Image.Image:
        """
        Glitch Effect - Modern glitch with color separation.

        Args:
            text_img: Text image
            frame_num: Current frame
            total_frames: Total frames

        Returns:
            Image with glitch effect
        """
        if text_img.mode != "RGBA":
            text_img = text_img.convert("RGBA")

        progress = frame_num / total_frames

        # Apply fade-in
        alpha = int(255 * min(1.0, progress * 2))
        r, g, b, a = text_img.split()
        a = a.point(lambda p: int(p * (alpha / 255.0)))
        text_faded = Image.merge("RGBA", (r, g, b, a))

        # Deterministic glitch offset
        glitch_offset = int(5 * np.sin(progress * np.pi * 10))

        # Create color channels with offset
        result = Image.new("RGBA", text_img.size, (0, 0, 0, 0))

        # Red channel
        r, g, b, a = text_faded.split()
        gray = Image.new("L", r.size, 128)
        red_channel = Image.merge("RGBA", (r, gray, gray, a))
        result.paste(red_channel, (glitch_offset, 0), red_channel)

        # Green channel
        green_channel = Image.merge("RGBA", (gray, g, gray, a))
        result.paste(green_channel, (0, 0), green_channel)

        # Blue channel
        blue_channel = Image.merge("RGBA", (gray, gray, b, a))
        result.paste(blue_channel, (-glitch_offset, 0), blue_channel)

        return result

    def apply_to_frames(self, frames: list[Image.Image], effect_name: str = "neon_glow") -> list[Image.Image]:
        """
        Apply a frame-level effect to a whole list of frames.
        'none'/'empty' returns the frames untouched.
        """
        if not frames or effect_name in (None, "", "none"):
            return frames
        total = len(frames)
        out = []
        for i, frame in enumerate(frames):
            try:
                if frame.mode != "RGBA":
                    frame = frame.convert("RGBA")
                res = self.apply_effect(effect_name, frame, i, total)
                out.append(res.convert("RGB"))
            except Exception as e:
                logger.warning("Effect '%s' failed on frame %d: %s", effect_name, i, e)
                # Return original frame on failure
                out.append(frame.convert("RGB") if frame.mode != "RGB" else frame)
        return out

    # ------------------------------------------------------------------
    # NEW: AI Director effects (whole-frame, numpy/opencv, high-end look)
    # ------------------------------------------------------------------

    _FX = {
        "bloom_glow": "_fx_bloom_glow",
        "gold_shimmer": "_fx_gold_shimmer",
        "breathing": "_fx_breathing",
        "vignette": "_fx_vignette",
        "grain": "_fx_grain",
        "rtl_reveal": "_fx_rtl_reveal",
        "glitch_v2": "_fx_glitch_v2",
        "word_pulse": "_fx_word_pulse",
        "aurora": "_fx_aurora",
        "title_hook": "_fx_title_hook",
        "summary_card": "_fx_summary_card",
    }

    def _to_np(self, img):
        return np.asarray(img.convert("RGB"), dtype=np.uint8)

    def _from_np(self, arr):
        return Image.fromarray(arr)

    def apply_plan(self, frames, frame_plan):
        """
        Apply an AI Director frame plan to a list of frames.
        frame_plan[frame_index] = [ {effect, params, seed}, ... ]
        Returns the processed list of RGB PIL frames.
        """
        if not frames:
            return frames
        if not frame_plan or len(frame_plan) != len(frames):
            return frames

        out = []
        active_pulses = []  # (remaining_frames, params)

        for i, (frame, specs) in enumerate(zip(frames, frame_plan, strict=False)):
            arr = self._to_np(frame)

            # collect new word pulses for THIS frame
            for spec in specs:
                if spec.get("effect") == "word_pulse":
                    active_pulses.append((int(spec.get("params", {}).get("decay", 8)), spec))

            # decaying pulses
            if active_pulses:
                kept = []
                for rem, spec in active_pulses:
                    params = spec.get("params", {})
                    strength = float(params.get("strength", 0.16))
                    fade = rem / float(params.get("decay", 8))
                    arr = self._fx_word_pulse(
                        arr,
                        strength=strength * fade,
                        tint=params.get("tint", (212, 175, 55)),
                        seed=spec.get("seed", i),
                    )
                    rem -= 1
                    if rem > 0:
                        kept.append((rem, spec))
                active_pulses = kept

            # ordered effect stack
            for spec in specs:
                eff = spec.get("effect")
                if eff == "word_pulse":
                    continue
                method = self._FX.get(eff)
                if method:
                    params = spec.get("params", {}) or {}
                    arr = getattr(self, method)(arr, params, spec.get("seed", i), i, len(frames))

            out.append(self._from_np(arr))

        return out

    # ---- individual effects (all operate on uint8 HxWx3 numpy arrays) ----

    def _fx_vignette(self, arr, params, seed, frame, total):
        strength = float(params.get("strength", 0.35))
        m = self._get_vignette_mask(strength)
        # scale=1/255: dst = saturate(arr * m / 255) — proper multiply.
        return cv2.multiply(arr, m, scale=1 / 255.0, dtype=cv2.CV_8U)

    def _get_vignette_mask(self, strength=0.35):
        """Cached full-res vignette multiply mask (H, W, 1) uint8 (thread-safe)."""
        key = (self.width, self.height, strength)
        if getattr(self, "_vignette_key", None) == key:
            return self._vignette_mask
        h, w = self.height, self.width
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = w / 2.0, h / 2.0
        r = np.sqrt(((xx - cx) / (w * 0.62)) ** 2 + ((yy - cy) / (h * 0.62)) ** 2)
        f = np.clip(r, 0.5, 1.3)
        f = 1.0 - strength * (f - 0.5)
        f = np.clip(f, 0.55, 1.0)
        mask = (f * 255).astype(np.uint8)
        mask = np.repeat(mask[:, :, None], 3, axis=2)
        self._vignette_mask = mask
        self._vignette_key = key
        return mask

    def _fx_grain(self, arr, params, seed, frame, total):
        strength = float(params.get("strength", 0.06))
        if strength <= 0:
            return arr
        h, w = arr.shape[:2]
        rng = np.random.default_rng((int(seed) + frame) & 0xFFFFFF)
        amp = max(1, int(strength * 60))
        n = rng.integers(0, amp + 1, (h // 4, w // 4, 1), dtype=np.uint8)
        n = np.repeat(n, 3, axis=2)
        n = cv2.resize(n, (w, h), interpolation=cv2.INTER_NEAREST)
        # signed grain: darken on even frames, brighten on odd (neutral tint)
        if frame % 2 == 0:
            return cv2.subtract(arr, n)
        return cv2.add(arr, n)

    def _fx_bloom_glow(self, arr, params, seed, frame, total):
        tint = params.get("tint", (212, 175, 55))
        intensity = float(params.get("intensity", 0.6))
        threshold = int(params.get("threshold", 110))
        h, w = arr.shape[:2]
        sw, sh = max(2, w // 8), max(2, h // 8)
        small = cv2.resize(arr, (sw, sh), interpolation=cv2.INTER_AREA)
        gray = small.mean(axis=2)
        mask = (gray > threshold).astype(np.float32)
        try:
            from core.hardware import gaussian_blur

            m = gaussian_blur(mask, 8.0)
        except Exception:
            logger.debug("gaussian_blur import failed, using cv2 fallback")
            m = cv2.GaussianBlur(mask, (0, 0), 8)
        glow = np.stack([m * (tint[0] * intensity), m * (tint[1] * intensity), m * (tint[2] * intensity)], axis=2)
        glow = np.clip(glow, 0, 255).astype(np.uint8)
        glow = cv2.resize(glow, (w, h), interpolation=cv2.INTER_LINEAR)
        return cv2.add(arr, glow)

    def _fx_gold_shimmer(self, arr, params, seed, frame, total):
        tint = params.get("tint", (212, 175, 55))
        phase = float(params.get("phase", 0.0))
        intensity = float(params.get("intensity", 0.30))
        h, w = arr.shape[:2]
        sw, sh = max(2, w // 8), max(2, h // 8)
        xc = sw * (0.5 + 0.82 * np.sin(phase * 2 * np.pi))
        x = np.arange(sw).astype(np.float32)
        off = (np.arange(sh).astype(np.float32)[:, None] / sh - 0.5) * sw * 0.35
        xcoord = x[None, :] - off
        band = np.exp(-(((xcoord - xc) / (sw * 0.14)) ** 2))
        gold = np.stack(
            [band * (tint[0] * intensity), band * (tint[1] * intensity), band * (tint[2] * intensity)], axis=2
        )
        gold = np.clip(gold, 0, 255).astype(np.uint8)
        gold = cv2.resize(gold, (w, h), interpolation=cv2.INTER_LINEAR)
        return cv2.add(arr, gold)

    def _fx_breathing(self, arr, params, seed, frame, total):
        phase = float(params.get("phase", 0.0))
        freq = float(params.get("freq", 1.5))
        amp = float(params.get("amp", 0.05))
        factor = 1.0 + amp * np.sin(phase * 2 * np.pi * freq)
        return cv2.convertScaleAbs(arr, alpha=factor, beta=0)

    def _fx_rtl_reveal(self, arr, params, seed, frame, total):
        fraction = float(params.get("fraction", 0.0))
        fraction = min(max(fraction, 0.0), 1.0)
        h, w = arr.shape[:2]
        half_w = w // 2
        small = cv2.resize(arr, (half_w, h), interpolation=cv2.INTER_AREA)
        left, right = int(half_w * 0.06), int(half_w * 0.94)
        bound = int(right - (right - left) * fraction)
        col = np.ones(half_w, dtype=np.float32)
        col[:bound] = 0.35
        col[bound : bound + 2] = np.linspace(0.35, 1.0, 2)
        small = (small.astype(np.float32) * col[None, :, None]).astype(np.uint8)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)

    def _fx_glitch_v2(self, arr, params, seed, frame, total):
        strength = float(params.get("strength", 0.5))
        h, w = arr.shape[:2]
        rng = np.random.default_rng((int(seed) + frame) & 0xFFFFFF)
        out = arr.copy()
        top, bot = int(h * 0.15), int(h * 0.88)
        n_slices = int(2 + strength * 3)
        for _ in range(n_slices):
            ys = rng.integers(top, bot)
            ye = min(bot, ys + rng.integers(int(h * 0.02), int(h * 0.09)))
            xshift = int(rng.integers(-int(14 * strength), int(14 * strength) + 1))
            if xshift == 0:
                xshift = 1
            band = out[ys:ye, :, :].copy()
            band = np.roll(band, xshift, axis=1)
            out[ys:ye, :, :] = band
        # subtle RGB split on the text block
        r_off = int(3 * strength)
        if r_off:
            block = out[top:bot, :, :]
            out[top:bot, :, 0] = np.roll(block[:, :, 0], -r_off, axis=1)
            out[top:bot, :, 2] = np.roll(block[:, :, 2], r_off, axis=1)
        return out

    def _fx_word_pulse(self, arr, strength, tint, seed):
        if strength <= 0:
            return arr
        h, w = arr.shape[:2]
        sw, sh = max(2, w // 8), max(2, h // 8)
        cx, cy = sw / 2.0, sh * 0.40
        yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
        r = np.sqrt((xx - cx) ** 2 + ((yy - cy) / 1.2) ** 2)
        r0 = sh * 0.42
        m = np.exp(-((r / r0) ** 2))
        m = np.clip(m * (strength * 1.4), 0, 1)
        glow = np.stack([m * tint[0], m * tint[1], m * tint[2]], axis=2)
        glow = np.clip(glow, 0, 255).astype(np.uint8)
        glow = cv2.resize(glow, (w, h), interpolation=cv2.INTER_LINEAR)
        return cv2.add(arr, glow)

    def _fx_aurora(self, arr, params, seed, frame, total):
        """Animated soft light-leak washes in the background (top/bottom)."""
        tint = params.get("tint", (120, 160, 255))
        intensity = float(params.get("intensity", 0.10))
        phase = float(params.get("phase", 0.0))
        h, w = arr.shape[:2]
        sw, sh = max(2, w // 4), max(2, h // 4)
        yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
        acc = np.zeros((sh, sw), np.float32)
        for k, (cx0, cy0, rx, ry) in enumerate([(0.22, 0.10, 0.32, 0.16), (0.78, 0.92, 0.32, 0.16)]):
            cx = sw * (cx0 + 0.07 * np.sin(phase * 2 * np.pi + k * 2.0))
            cy = sh * (cy0 + 0.05 * np.cos(phase * 2 * np.pi + k * 1.3))
            r = np.sqrt(((xx - cx) / (sw * rx)) ** 2 + ((yy - cy) / (sh * ry)) ** 2)
            acc += np.exp(-(r**2))
        m = np.clip(acc, 0, 1) * intensity
        glow = np.stack([m * tint[0], m * tint[1], m * tint[2]], axis=2)
        glow = np.clip(glow, 0, 255).astype(np.uint8)
        glow = cv2.resize(glow, (w, h), interpolation=cv2.INTER_LINEAR)
        return cv2.add(arr, glow)

    def _fx_title_hook(self, arr, params, seed, frame, total):
        """
        Premium opening hook: camera push-in (Ken Burns zoom) + a fading
        golden bloom flash on the title area. Runs during the first ~25% of
        the arabic scene (the "first-frame 10x" hook).
        """
        phase = float(params.get("phase", 0.0))
        tint = params.get("tint", (212, 175, 55))
        h, w = arr.shape[:2]

        if phase < 1.0:
            zoom = 1.0 + 0.045 * (1.0 - phase)
            cw, ch = int(w / zoom), int(h / zoom)
            x0, y0 = (w - cw) // 2, (h - ch) // 2
            out = cv2.resize(arr[y0 : y0 + ch, x0 : x0 + cw], (w, h), interpolation=cv2.INTER_LINEAR)
            flash = 0.45 * (1.0 - phase)
            if flash > 0:
                sw, sh = max(2, w // 8), max(2, h // 8)
                cx, cy = sw / 2.0, sh * 0.13
                yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
                r = np.sqrt((xx - cx) ** 2 + ((yy - cy) / 1.1) ** 2)
                m = np.exp(-((r / (sh * 0.35)) ** 2))
                m = np.clip(m * flash, 0, 1)
                glow = np.stack([m * tint[0], m * tint[1], m * tint[2]], axis=2)
                glow = np.clip(glow, 0, 255).astype(np.uint8)
                glow = cv2.resize(glow, (w, h), interpolation=cv2.INTER_LINEAR)
                out = cv2.add(out, glow)
            return out
        return arr

    def _fx_summary_card(self, arr, params, seed, frame, total):
        """
        Outro summary card for the hold scene: shows BOTH the Arabic dua and
        its Urdu translation (plus the title) on a dark rounded card, so the
        end of the video is meaningful instead of an empty background.
        Rendered once and cached; blended per frame with a fade-in.
        """
        arabic = str(params.get("arabic", ""))
        urdu = str(params.get("urdu", ""))
        title = str(params.get("title", ""))
        tint = params.get("tint", (212, 175, 55))
        fade_lp = float(params.get("lp", 1.0))
        if not (arabic or urdu):
            return arr

        key = ("sc", arabic, urdu, title, tuple(tint), self.width, self.height)
        card = self._summary_cache.get(key)
        if card is None:
            card = self._build_summary_card(arabic, urdu, title, tint)
            if len(self._summary_cache) > 8:
                self._summary_cache.clear()
            self._summary_cache[key] = card
        card_img, card_alpha = card  # RGB uint8, alpha float 0..1

        alpha = min(1.0, max(0.0, fade_lp / 0.12))
        if alpha <= 0:
            return arr
        f = alpha
        out = (
            arr.astype(np.float32) * (1.0 - card_alpha * f)[:, :, None]
            + card_img.astype(np.float32) * (card_alpha * f)[:, :, None]
        )
        return np.clip(out, 0, 255).astype(np.uint8)

    def _build_summary_card(self, arabic: str, urdu: str, title: str, tint=(212, 175, 55)):
        """Build the cached outro card as (RGB uint8 HxWx3, alpha float HxW).

        Modern glass style: soft drop shadow, translucent panel with top
        sheen, gold gradient border, gradient-gold Arabic, clean Urdu.
        """
        from core.arabic_renderer import ArabicRenderer, _is_arabic, apply_vertical_gradient

        ar = ArabicRenderer()
        W, H = self.width, self.height
        card_w, card_h = int(W * 0.86), int(H * 0.58)
        x0 = (W - card_w) // 2
        y0 = int(H * 0.27)
        pad = int(card_w * 0.05)
        inner_w = card_w - 2 * pad
        radius = 30

        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

        # 1) soft drop shadow
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            [x0, y0 + 12, x0 + card_w, y0 + card_h + 12], radius=radius, fill=(0, 0, 0, 150)
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        canvas = Image.alpha_composite(canvas, shadow)

        # 2) glass panel with subtle top sheen
        panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(panel).rounded_rectangle(
            [x0, y0, x0 + card_w, y0 + card_h], radius=radius, fill=(12, 15, 32, 226)
        )
        sheen = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sheen)
        sheen_h = int(card_h * 0.16)
        for i in range(sheen_h):
            a = int(30 * (1 - i / sheen_h))
            sd.line([(x0 + radius, y0 + i), (x0 + card_w - radius, y0 + i)], fill=(255, 255, 255, a))
        panel = Image.alpha_composite(panel, sheen)
        canvas = Image.alpha_composite(canvas, panel)

        # 3) gold gradient border ring
        ring = Image.new("L", (W, H), 0)
        ImageDraw.Draw(ring).rounded_rectangle([x0, y0, x0 + card_w, y0 + card_h], radius=radius, outline=255, width=4)
        rows = np.linspace(0.0, 1.0, H)[:, None]
        g_top, g_bot = np.array([255, 233, 168]), np.array([186, 146, 58])
        grad = np.zeros((H, W, 4), dtype=np.uint8)
        grad[:, :, :3] = (g_top * (1 - rows) + g_bot * rows).astype(np.uint8)[:, None, :]
        grad[:, :, 3] = 255
        border = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        border.paste(Image.fromarray(grad), (0, 0), ring)
        canvas = Image.alpha_composite(canvas, border)
        d = ImageDraw.Draw(canvas)

        def wrap_ar(text, size):
            lines = []
            cur = ""
            for word in text.split():
                test = (cur + " " + word) if cur else word
                if ar.measure_width(test, size) <= inner_w:
                    cur = test
                    continue
                if cur:
                    lines.append(cur)
                cur = word
            if cur:
                lines.append(cur)
            return lines or [text]

        cy = y0 + pad + 10
        # title (centered)
        if title:
            if _is_arabic(title):
                t_img = ar.render_line(title, 36, color=tuple(tint), outline_color=(10, 12, 20), outline_width=2)
                canvas.paste(t_img, ((W - t_img.width) // 2, cy), t_img)
            else:
                tmp = Image.new("RGBA", (inner_w, 60), (0, 0, 0, 0))
                td = ImageDraw.Draw(tmp)
                tfont = ImageFont.truetype(ar.font_path, 36)
                bb = td.textbbox((0, 0), title, font=tfont)
                td.text((-bb[0], -bb[1]), title, font=tfont, fill=tuple(tint) + (255,))
                t_img = tmp.crop((max(0, bb[0]), max(0, bb[1]), min(inner_w, bb[2]), min(60, bb[3])))
                canvas.paste(t_img, ((W - t_img.width) // 2, cy), t_img)
            cy += 72

        # divider with center diamond ornament
        dy = cy
        d.line([(x0 + int(card_w * 0.15), dy), (x0 + int(card_w * 0.46), dy)], fill=tuple(tint) + (200,), width=2)
        d.line([(x0 + int(card_w * 0.54), dy), (x0 + int(card_w * 0.85), dy)], fill=tuple(tint) + (200,), width=2)
        r = 7
        d.polygon([(W // 2, dy - r), (W // 2 + r, dy), (W // 2, dy + r), (W // 2 - r, dy)], fill=tuple(tint) + (255,))
        cy += 26

        def paste_block(text, size, color, cy_in, line_gap, grad=None):
            lines = wrap_ar(text, size)
            for ln in lines:
                surf = ar.render_line(ln, size, color=color, outline_color=(10, 12, 20), outline_width=2)
                if grad:
                    surf = apply_vertical_gradient(surf, grad[0], grad[1])
                slot = int(size * line_gap)
                canvas.paste(surf, ((W - surf.width) // 2, cy_in + max(0, (slot - surf.height) // 2)), surf)
                cy_in += slot
            return cy_in

        # arabic: gradient gold
        cy = paste_block(arabic, 56, (255, 215, 0), cy, 1.45, grad=((255, 240, 185), (216, 178, 80)))
        cy += 22
        # urdu: soft white
        cy = paste_block(urdu, 44, (244, 247, 255), cy, 1.45)

        arr_rgba = np.array(canvas)
        card_alpha = arr_rgba[:, :, 3].astype(np.float32) / 255.0
        card_img = arr_rgba[:, :, :3]
        return card_img, card_alpha


# Test function
if __name__ == "__main__":
    print("Testing Effects Engine...")

    engine = EffectsEngine()

    # Create test image
    test_img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(test_img)
    draw.text((50, 80), "Test Text", fill=(255, 215, 0, 255))

    # Test each effect
    effects = ["neon_glow", "metallic_gold", "typewriter", "bounce", "wave", "glitch"]

    for effect_name in effects:
        print(f"\nTesting effect: {effect_name}")

        # Apply effect at different frames
        for frame in [0, 30, 60, 90]:
            result = engine.apply_effect(effect_name, test_img, frame, 100)
            print(f"  Frame {frame}: Applied successfully")

    print("\nEffects Engine Test Complete!")
