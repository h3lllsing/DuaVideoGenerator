"""
Effect Director tests: deterministic planning, scene-frame clamping, plan
shape, frame round-trip through apply_plan, and hardware backend detection.

Run with: python -m pytest tests/test_effect_director.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from core.effect_director import EffectDirector, scene_frame_ranges
from core.effects_engine import EffectsEngine
from core.hardware import pick_backend, profile_summary

W, H = 1080, 1920
FPS = 24


def _timeline(total=360):
    meta = [
        {"role": "arabic", "frames": 96, "start": 0.0, "duration": 96 / FPS},
        {"role": "urdu", "frames": 95, "start": 4.0, "duration": 95 / FPS},
        {"role": "hold", "frames": total - 191, "start": 7.95, "duration": (total - 191) / FPS},
    ]
    return {
        "valid": True,
        "final_frames": total,
        "offsets": {"urdu_base": 4.0},
        "scene_metadata": meta,
    }


def _dua(category="prayer", dua_id="t1"):
    return {"id": dua_id, "category": category, "arabic": "a" * 40, "urdu": "u" * 40, "title": "Test"}


def _words(n=8):
    return {"arabic": [{"word": "x", "offset": i * 0.3, "duration": 0.4} for i in range(n)]}


class TestEffectDirector:
    def test_plan_shape_matches_total_frames(self):
        plan = _timeline()
        d = EffectDirector(fps=FPS, canvas=(W, H)).plan(_dua(), plan, _words(), effect_request="auto", dua_id="t1")
        assert len(d["frame_plan"]) == plan["final_frames"]
        assert d["hero"] in ("bloom_glow", "gold_shimmer", "rtl_reveal", "glitch_v2")

    def test_none_request_yields_base_plan_only(self):
        d = EffectDirector(fps=FPS, canvas=(W, H)).plan(
            _dua(), _timeline(), _words(), effect_request="none", dua_id="t1"
        )
        assert d["hero"] is None
        # only the universal cinematic base (vignette+grain) is applied
        for specs in d["frame_plan"]:
            assert all(s["effect"] in ("vignette", "grain") for s in specs)

    def test_same_dua_is_deterministic(self):
        args = (_dua(dua_id="d9"), _timeline(), _words())
        a = EffectDirector(fps=FPS, canvas=(W, H)).plan(*args, effect_request="auto", dua_id="d9")
        b = EffectDirector(fps=FPS, canvas=(W, H)).plan(*args, effect_request="auto", dua_id="d9")
        assert a["hero"] == b["hero"]
        assert a["frame_plan"] == b["frame_plan"]

    def test_scene_end_clamped_to_video_length(self):
        meta = [
            {"role": "arabic", "frames": 96, "start": 0.0, "duration": 96 / FPS},
            {"role": "hold", "frames": 300, "start": 4.0, "duration": 300 / FPS},
        ]
        ranges = scene_frame_ranges(meta, FPS, total_frames=360)
        assert all(r["end"] <= 360 for r in ranges)
        # hold scene overflows past 360 -> clamped, must not crash plan()
        tplan = {"valid": True, "final_frames": 360, "offsets": {"urdu_base": 4.0}, "scene_metadata": meta}
        d = EffectDirector(fps=FPS, canvas=(W, H)).plan(
            _dua(dua_id="x9"), tplan, _words(), effect_request="auto", dua_id="x9"
        )
        assert len(d["frame_plan"]) == 360

    def test_apply_plan_roundtrip(self):
        frames = [Image.fromarray(np.random.randint(20, 60, (H, W, 3), dtype=np.uint8)) for _ in range(24)]
        d = EffectDirector(fps=FPS, canvas=(W, H)).plan(
            _dua(), _timeline(total=24), _words(), effect_request="auto", dua_id="rt"
        )
        # fix the small timeline for a 24-frame plan
        tplan = _timeline(total=24)
        d = EffectDirector(fps=FPS, canvas=(W, H)).plan(_dua(), tplan, _words(), effect_request="auto", dua_id="rt")
        out = EffectsEngine(width=W, height=H).apply_plan(frames, d["frame_plan"])
        assert len(out) == 24
        assert all(f.mode == "RGB" for f in out)

    def test_apply_plan_ignores_mismatched_plan(self):
        frames = [Image.fromarray(np.random.randint(20, 60, (10, 10, 3), dtype=np.uint8))]
        out = EffectsEngine().apply_plan(frames, [])
        assert out is frames

    def test_vignette_never_whitewashes_dark_frame(self):
        """Regression: cv2.multiply without scale=1/255 blew every frame to
        pure white (mean 255). A dark base must stay dark after vignette."""
        eng = EffectsEngine(width=360, height=640)
        base = np.random.randint(15, 60, (640, 360, 3), dtype=np.uint8)
        base[230:430, 120:260] = 235  # bright text block
        out = eng._fx_vignette(base, {"strength": 0.35}, 1, 0, 10)
        assert out.mean() < 120, "vignette whitewashed the frame (mean {:.0f})".format(out.mean())
        assert out.max() >= 200, "bright text lost after vignette"

    def test_full_auto_plan_keeps_dark_background(self):
        """End-to-end guard: a full auto plan on a dark synthetic frame must
        not saturate the whole frame to white (the earlier vignette bug)."""
        base = np.random.randint(15, 60, (640, 360, 3), dtype=np.uint8)
        base[230:430, 120:260] = 235
        frames = [Image.fromarray(base) for _ in range(12)]
        tplan = _timeline(total=12)
        d = EffectDirector(fps=FPS, canvas=(360, 640)).plan(
            _dua(dua_id="ww"), tplan, _words(), effect_request="auto", dua_id="ww"
        )
        out = EffectsEngine(width=360, height=640).apply_plan(frames, d["frame_plan"])
        means = [np.asarray(f).mean() for f in out]
        assert max(means) < 150, "auto plan whitewashed frames (max mean {:.0f})".format(max(means))


class TestHardware:
    def test_profile_and_backend_report(self):
        summary = profile_summary()
        assert "CPU" in summary and "GPU" in summary and "backend" in summary
        assert pick_backend() in ("cpu", "cpu_parallel", "opencl_gpu")

    def test_gaussian_blur_falls_back_to_cpu(self):
        from core.hardware import gaussian_blur

        m = (np.random.rand(64, 64) > 0.5).astype(np.float32)
        out = gaussian_blur(m, 8.0)
        assert out.shape == m.shape and np.isfinite(out).all()


# ----------------------------------------------------------------------
# Rendering-fix regressions (HarfBuzz renderer, logical line order,
# hold-scene summary card, premium dark palette).
# ----------------------------------------------------------------------
RABBANA = "رَبَّنَا آتِنَا فِي الدُّنْيَا حَسَنَةً وَفِي الْآخِرَةِ حَسَنَةً وَقِنَا عَذَابَ النَّارِ"
BISMILLAH = "بِسْمِ اللَّهِ"


class TestRenderingFixes:
    def test_harakat_rendered_above_and_below(self):
        """Diacritics (fatha/shadda above, kasra below) must produce pixels in
        BOTH halves of the rendered line."""
        from core.arabic_renderer import ArabicRenderer

        img = ArabicRenderer().render_line(BISMILLAH, 72, color=(255, 255, 255))
        rows = np.array(img)[:, :, 3] > 0
        h = rows.shape[0]
        assert rows[: h // 2].sum() > 100, "no pixels above midline (fatha/shadda)"
        assert rows[h // 2 :].sum() > 100, "no pixels below midline (kasra)"

    def test_arabic_render_is_clip_free(self):
        """Two-pass ink-bbox renderer must be pad-invariant: identical ink
        whether drawn on a tight or oversized canvas (stacked harakat used
        to overflow the font-metric box and get silently cropped)."""
        from core.arabic_renderer import ArabicRenderer

        def trim(img):
            a = np.array(img)[:, :, 3]
            ys, xs = np.nonzero(a > 0)
            return a[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]

        ar = ArabicRenderer()
        for txt in (BISMILLAH, RABBANA):
            tight = trim(ar.render_line(txt, 64))
            loose = trim(ar.render_line(txt, 64, pad=60))
            assert tight.shape == loose.shape, "ink extent depends on canvas size -> clipped"
            assert np.array_equal(tight, loose), "ink content differs between canvas sizes -> clipped"

    def test_wrap_keeps_logical_line_order(self):
        """Multi-line Arabic must stay start->top / end->bottom (previously
        the bidi-reordered string was wrapped, reversing the content)."""
        from core.scene_engine import SceneRenderer

        sr = SceneRenderer(fps=FPS)
        font = sr._font(72)
        lines = sr._wrap(RABBANA, font, 1000, "ar")
        assert len(lines) >= 2, "multi-line dua should wrap to 2+ lines"
        assert lines[0].startswith("رَبَّنَا"), "first (top) line must start with the LOGICAL start"
        assert lines[-1].rstrip().endswith("النَّارِ"), "last (bottom) line must end with the LOGICAL end"

    def test_summary_card_appears_on_hold(self):
        """The hold scene must show the outro card (Arabic + translation) so
        the end of the video is not an empty background."""
        dua = {
            "id": "sc1",
            "category": "prayer",
            "arabic": RABBANA,
            "urdu": "اے ہمارے رب ہمیں دنیا اور آخرت میں بھلائی عطا فرما",
            "title": "Test",
        }
        tplan = _timeline(total=240)
        d = EffectDirector(fps=FPS, canvas=(360, 640)).plan(dua, tplan, {}, effect_request="auto", dua_id="sc1")
        hold = next(s for s in tplan["scene_metadata"] if s["role"] == "hold")
        specs = d["frame_plan"][int(hold["start"] * FPS) + 5]
        assert any(s["effect"] == "summary_card" for s in specs)

        base = np.random.randint(15, 60, (640, 360, 3), dtype=np.uint8)
        frames = [Image.fromarray(base) for _ in range(240)]
        out = EffectsEngine(width=360, height=640).apply_plan(frames, d["frame_plan"])
        hf = np.asarray(out[int(hold["start"] * FPS) + 10].convert("RGB")).mean(axis=2)
        card = hf[640 // 3 : 2 * 640 // 3, 360 // 4 : 3 * 360 // 4]
        assert (card > 150).sum() > 200, "summary card text missing on hold"

    def test_premium_palette_never_light(self):
        from core.effect_director import premium_palette
        from core.master_config import DARK_PALETTES

        for dua_id in ("x", "y", "z", "rabbana_hasanah", "bathroom_exit"):
            pal = premium_palette(dua_id)
            assert pal["name"] in DARK_PALETTES
            assert max(pal["top"]) < 120, "light palette leaked through"
