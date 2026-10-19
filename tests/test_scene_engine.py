"""
VISUAL Phase 2 tests: SceneEngine determinism, motion, safe-area geometry,
collision prevention, layout fallback, long content, and VideoBuilder
regression compatibility.

Run with: python -m pytest tests/test_scene_engine.py -v
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from core.scene_engine import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    MOTION_KINDS,
    RESERVED_RECTS,
    SAFE_RECT,
    MotionSpec,
    SceneRenderer,
    Timeline,
    Transition,
    rect_intersect,
    rect_within,
)
from core.video_builder import VideoBuilder

FPS = 24

SHORT_AR = "\u0627\u0644\u0644\u0647\u0645 \u0627\u0646\u064a \u0627\u0633\u0623\u0644\u0643 \u0627\u0644\u0639\u0627\u0641\u064a\u0629"
SHORT_UR = "\u0627\u0644\u0644\u06c1 \u0633\u06d2 \u0639\u0627\u0641\u06cc\u062a \u06a9\u06cc \u062f\u0639\u0627"

# Long synthetic content for layout stress tests (never touches real dua text)
LONG_AR = " ".join([SHORT_AR] * 50)  # ~1300 chars
LONG_UR = " ".join([SHORT_UR] * 35)  # ~700 chars
MAX_AR = " ".join([SHORT_AR] * 70)  # ~1820 chars
MAX_UR = " ".join([SHORT_UR] * 45)  # ~900 chars
ABSURD_AR = " ".join([SHORT_AR] * 200)  # ~5200 chars (cannot fit)


def _renderer(fps=FPS):
    return SceneRenderer(width=CANVAS_WIDTH, height=CANVAS_HEIGHT, fps=fps)


def _scene(seed="test_seed", arabic=SHORT_AR, urdu=SHORT_UR, title="Dua", duration=1.0, palette=None, motion=None):
    r = _renderer()
    return r.build_single_scene(seed, arabic, urdu, title, duration=duration, palette=palette, motion=motion)


def _no_fade(scene):
    scene.transition_in = Transition("none")
    scene.transition_out = Transition("none")
    return scene


def _render(seed, scene, fps=FPS):
    r = _renderer(fps)
    return r.render(Timeline(fps=fps, scenes=[scene]), seed=seed), r


def _as_np(img):
    return np.asarray(img)


class TestOutputAndTiming:
    def test_output_resolution_1080x1920(self):
        scene = _scene()
        frames, _ = _render("seed_a", scene)
        for f in frames[:3]:
            assert f.size == (1080, 1920)
        assert frames[0].mode == "RGB"

    def test_frame_count_matches_duration_fps(self):
        scene = _scene(duration=2.0)
        frames, _ = _render("seed_a", scene)
        assert len(frames) == int(round(2.0 * FPS))

    def test_frame_count_for_15s(self):
        scene = _scene(duration=15.0)
        frames, _ = _render("seed_a", scene)
        assert len(frames) == 360

    def test_timeline_frame_distribution_matches_total(self):
        scenes = [_scene(duration=2.0), _scene(duration=1.0)]
        tl = Timeline(fps=FPS, scenes=scenes)
        assert tl.total_frames == 72
        assert tl.frames_for_scene(0) == 48
        assert tl.frames_for_scene(1) == 24
        assert sum(tl.frames_for_scene(i) for i in range(2)) == tl.total_frames

    def test_all_motion_kinds_render_same_resolution(self):
        for kind in MOTION_KINDS:
            scene = _scene(motion=MotionSpec(kind=kind))
            frames, _ = _render(f"seed_{kind}", scene)
            assert len(frames) == FPS
            assert frames[-1].size == (1080, 1920)


class TestMotion:
    def test_static_background_frames_identical(self):
        scene = _no_fade(_scene(motion=MotionSpec(kind="static")))
        frames, _ = _render("seed_static", scene)
        first = _as_np(frames[0])
        assert all(np.array_equal(first, _as_np(f)) for f in frames[1:])

    def test_zoom_in_changes_over_time(self):
        scene = _no_fade(_scene(motion=MotionSpec(kind="zoom_in"), duration=2.0))
        frames, _ = _render("seed_zi", scene)
        assert not np.array_equal(_as_np(frames[0]), _as_np(frames[-1]))

    def test_zoom_out_changes_over_time(self):
        scene = _no_fade(_scene(motion=MotionSpec(kind="zoom_out"), duration=2.0))
        frames, _ = _render("seed_zo", scene)
        assert not np.array_equal(_as_np(frames[0]), _as_np(frames[-1]))

    def test_pan_motions_change_over_time(self):
        for kind in ("pan_left", "pan_right", "pan_up", "pan_down"):
            scene = _no_fade(_scene(motion=MotionSpec(kind=kind), duration=2.0))
            frames, _ = _render(f"seed_{kind}", scene)
            assert not np.array_equal(_as_np(frames[0]), _as_np(frames[-1]))

    def test_zoom_differs_from_static(self):
        static = _no_fade(_scene(motion=MotionSpec("static")))
        zoom = _no_fade(_scene(motion=MotionSpec("zoom_in")))
        frames_static, _ = _render("seed_s", static)
        frames_zoom, _ = _render("seed_z", zoom)
        mid = FPS // 2  # middle frame (fade-free, clearly zoomed)
        assert not np.array_equal(_as_np(frames_static[mid]), _as_np(frames_zoom[mid]))


class TestTransitions:
    def test_fade_transition_darkens_start_and_end(self):
        scene = _scene(duration=2.0, motion=MotionSpec("static"))
        frames, _ = _render("seed_fade", scene)
        # start frame has black overlay (fade from black)
        start_mean = _as_np(frames[0]).mean()
        middle_mean = _as_np(frames[FPS // 2]).mean()
        end_mean = _as_np(frames[-1]).mean()
        assert start_mean < middle_mean
        assert end_mean < middle_mean

    def test_frames_never_fully_black_in_middle(self):
        scene = _scene(duration=2.0, motion=MotionSpec("static"))
        frames, _ = _render("seed_fade2", scene)
        mid = _as_np(frames[FPS // 2])
        assert mid.mean() > 10  # visible content, not a black frame


class TestDeterminism:
    def test_same_seed_same_frames(self):
        scene = _scene(duration=2.0)
        a, _ = _render("deterministic_seed", scene)
        b, _ = _render("deterministic_seed", scene)
        assert len(a) == len(b)
        for fa, fb in zip(a, b):
            assert np.array_equal(_as_np(fa), _as_np(fb))

    def test_same_seed_across_renderer_instances(self):
        s1 = _scene(duration=1.0)
        s2 = _scene(duration=1.0)
        f1, _ = _render("cross_instance", s1)
        f2, _ = _render("cross_instance", s2)
        assert np.array_equal(_as_np(f1[0]), _as_np(f2[0]))

    def test_same_dua_id_same_scene_style(self):
        a = _scene("dua_abc", duration=1.0)
        b = _scene("dua_abc", duration=1.0)
        assert a.palette_name() == b.palette_name()
        assert a.motion.kind == b.motion.kind
        assert a.text_style == b.text_style
        assert a.particle_count == b.particle_count

    def test_different_seeds_produce_variety(self):
        styles = []
        for i in range(24):
            s = _scene(f"seed_{i}", duration=1.0)
            styles.append((s.palette_name(), s.motion.kind, s.text_style, s.particle_count, s.corner_style))
        assert len({x[0] for x in styles}) >= 2  # palette variety
        assert len({x[1] for x in styles}) >= 2  # motion variety
        assert len({x[2] for x in styles}) >= 2  # text-style variety

    def test_different_seeds_can_render_differently(self):
        seeds = []
        for i in range(12):
            s = _scene(f"seed_{i}", duration=1.0)
            seeds.append((i, s))
        # pick two seeds with different style
        pair = None
        for i in range(len(seeds)):
            for j in range(i + 1, len(seeds)):
                si, sj = seeds[i][1], seeds[j][1]
                if (si.palette_name(), si.motion.kind) != (sj.palette_name(), sj.motion.kind):
                    pair = (seeds[i][0], seeds[j][0])
                    break
            if pair:
                break
        assert pair is not None
        fa, _ = _render(f"seed_{pair[0]}", seeds[pair[0]][1])
        fb, _ = _render(f"seed_{pair[1]}", seeds[pair[1]][1])
        mid = FPS // 2  # middle frames are fade-free and fully visible
        assert not np.array_equal(_as_np(fa[mid]), _as_np(fb[mid]))


class TestSafeAreaGeometry:
    def test_all_line_bboxes_inside_safe_rect(self):
        scene = _scene(duration=1.0)
        layout = _renderer().compute_layout(scene)
        for layer in layout["layers"]:
            for line in layer["lines"]:
                assert rect_within(line["bbox"], SAFE_RECT), line["bbox"]

    def test_no_line_intersects_reserved_rects(self):
        scene = _scene(duration=1.0)
        layout = _renderer().compute_layout(scene)
        for layer in layout["layers"]:
            for line in layer["lines"]:
                for r in RESERVED_RECTS:
                    assert not rect_intersect(line["bbox"], r), (line["bbox"], r)

    def test_safe_rect_disjoint_from_reserved(self):
        for r in RESERVED_RECTS:
            assert not rect_intersect(SAFE_RECT, r)

    def test_verify_layout_flags_outside_bbox(self):
        layout = {
            "layers": [
                {
                    "role": "arabic",
                    "lines": [{"text": "x", "bbox": (0, 0, 400, 50)}],
                }
            ],
        }
        issues = _renderer().verify_layout(_scene(), layout)
        assert len(issues) >= 1

    def test_verify_layout_flags_colliding_bbox(self):
        # bbox inside top reserved band (0,0,1080,110)
        layout = {
            "layers": [
                {
                    "role": "title",
                    "lines": [{"text": "x", "bbox": (100, 20, 900, 90)}],
                }
            ],
        }
        issues = _renderer().verify_layout(_scene(), layout)
        assert len(issues) >= 1

    def test_text_positions_stable_with_motion(self):
        # Layout is independent of background motion by construction
        base = _scene(duration=1.0)
        static = _scene(duration=1.0, motion=MotionSpec("static"))
        pan = _scene(duration=1.0, motion=MotionSpec("pan_left"))
        static.layers = base.layers
        pan.layers = base.layers
        r = _renderer()
        lay_s = r.compute_layout(static)
        lay_p = r.compute_layout(pan)
        bs_s = [l["bbox"] for l in lay_s["layers"] for l in l["lines"]]
        bs_p = [l["bbox"] for l in lay_p["layers"] for l in l["lines"]]
        assert bs_s == bs_p


class TestContentFitFallback:
    def test_long_arabic_fits(self):
        scene = _scene(arabic=LONG_AR, duration=1.0)
        r = _renderer()
        layout = r.compute_layout(scene)
        assert r.verify_layout(scene, layout) == []
        assert layout["fits"] is True

    def test_long_urdu_fits(self):
        scene = _scene(urdu=LONG_UR, duration=1.0)
        r = _renderer()
        layout = r.compute_layout(scene)
        assert r.verify_layout(scene, layout) == []

    def test_long_combined_fits(self):
        scene = _scene(arabic=LONG_AR, urdu=LONG_UR, duration=1.0)
        r = _renderer()
        layout = r.compute_layout(scene)
        assert r.verify_layout(scene, layout) == []

    def test_max_combined_content_fits(self):
        scene = _scene(arabic=MAX_AR, urdu=MAX_UR, duration=1.0)
        r = _renderer()
        layout = r.compute_layout(scene)
        assert r.verify_layout(scene, layout) == []
        assert layout["font_fallback"] != "primary"
        # every line must still be inside the safe rectangle
        for layer in layout["layers"]:
            for line in layer["lines"]:
                assert rect_within(line["bbox"], SAFE_RECT)

    def test_font_fallback_engaged_for_long_content(self):
        scene = _scene(arabic=LONG_AR, urdu=LONG_UR, duration=1.0)
        layout = _renderer().compute_layout(scene)
        assert layout["font_fallback"] != "primary"
        assert layout["font_fallback"] in ("shrunk", "spacing", "alternate")

    def test_long_content_renders(self):
        scene = _scene(arabic=LONG_AR, urdu=LONG_UR, duration=1.0)
        frames, _ = _render("seed_long", scene)
        assert len(frames) == FPS
        assert frames[-1].size == (1080, 1920)

    def test_unfittable_content_raises(self):
        # ~5k+ characters cannot fit in the safe area even at minimum font.
        scene = _scene(arabic=ABSURD_AR, urdu=LONG_UR, duration=1.0)
        r = _renderer()
        try:
            r.compute_layout(scene)
        except ValueError:
            return
        raise AssertionError("compute_layout should refuse unfittable content")


class TestTextIntegrity:
    def test_source_dua_text_never_modified(self):
        ar = SHORT_AR
        ur = SHORT_UR
        scene = _scene(arabic=ar, urdu=ur, title="Dua", duration=1.0)
        r = _renderer()
        r.compute_layout(scene)
        frames, _ = _render("seed_txt", scene)
        assert len(frames) == FPS
        roles = {l.role: l for l in scene.layers}
        assert roles["arabic"].text == ar
        assert roles["urdu"].text == ur
        assert roles["title"].text == "Dua"

    def test_no_shaping_of_title(self):
        scene = _scene(title="Bathroom Dua", duration=1.0)
        # title text must pass through untouched (no reshaping/bidi anywhere)
        assert scene.layers[0].text == "Bathroom Dua"
        frames, _ = _render("seed_title_plain", scene)
        assert len(frames) == FPS


class TestProceduralFallback:
    def test_render_needs_no_image_assets(self):
        # backgrounds dir contains only manifest.json (no images) - render must work
        from core.project_info import PROJECT

        bg_dir = os.path.join(PROJECT.ASSETS_DIR, "backgrounds")
        assert os.path.exists(os.path.join(bg_dir, "manifest.json"))
        scene = _scene(duration=1.0)
        frames, _ = _render("seed_proc", scene)
        assert len(frames) == FPS

    def test_all_frames_have_content(self):
        scene = _scene(duration=1.0)
        frames, _ = _render("seed_content", scene)
        assert _as_np(frames[FPS // 2]).mean() > 5


class TestVideoBuilderCompatibility:
    def test_frames_match_videobuilder_contract(self):
        scene = _scene(duration=1.0)
        frames, _ = _render("seed_vb", scene)
        assert all(isinstance(f, Image.Image) for f in frames)
        assert all(f.size == (1080, 1920) for f in frames)

    def test_videobuilder_accepts_scene_engine_frames(self):
        tmp_dir = os.path.join(os.path.dirname(__file__), "_scene_tmp")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        try:
            scene = _scene(duration=1.0)
            frames, _ = _render("seed_vb2", scene)
            out = os.path.join(tmp_dir, "out.mp4")
            assert VideoBuilder(fps=FPS, resolution=(1080, 1920)).build_video(frames, out) is True
            assert os.path.exists(out) and os.path.getsize(out) > 0
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
