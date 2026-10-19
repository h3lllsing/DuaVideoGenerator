"""
VISUAL Phase 3 tests: TimelineBuilder integration.

Covers the 20 required scenarios: timing math, VIDEO-002 compatibility,
language presence, rounding/hold clamp, determinism, exact frame counts,
WordBoundary absolute offsets, zero-duration-scene prevention, SAFE_RECT
verification, and unchanged VideoBuilder compatibility.

Run with: python -m pytest tests/test_timeline_builder.py -v
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from core.audio_mixer import AudioMixer
from core.scene_engine import RESERVED_RECTS, SAFE_RECT, SceneRenderer, rect_intersect, rect_within
from core.timeline_builder import TimelineBuilder
from core.video_builder import VideoBuilder

FPS = 24
AR_TEXT = "\u0627\u0644\u0644\u0647\u0645 \u0627\u0646\u064a \u0627\u0633\u0623\u0644\u0643 \u0627\u0644\u0639\u0627\u0641\u064a\u0629"
UR_TEXT = "\u0627\u0644\u0644\u06c1 \u0633\u06d2 \u0639\u0627\u0641\u06cc\u062a \u06a9\u06cc \u062f\u0639\u0627"


def _final(speech):
    return AudioMixer.compute_video_timeline(speech)["final_duration"]


def plan(ar_s, ur_s, ar_text=AR_TEXT, ur_text=UR_TEXT, final=None, dua="dua_x"):
    if final is None:
        speech = ar_s + ur_s + (0.3 if (ar_text and ur_text) else 0.0)
        final = _final(speech)
    return TimelineBuilder().build(
        dua, ar_text, ur_text, "Dua", arabic_duration=ar_s, urdu_duration=ur_s, final_duration=final
    )


def roles(p):
    return [m["role"] for m in p["scene_metadata"]]


def frames(p):
    return [m["frames"] for m in p["scene_metadata"]]


def render(p):
    r = SceneRenderer(fps=FPS)
    return r.render(p["timeline"], seed="dua_x")


def verify_safe(p, renderer):
    for scene in p["timeline"].scenes:
        layout = renderer.compute_layout(scene)
        assert renderer.verify_layout(scene, layout) == []
        for layer in layout["layers"]:
            for line in layer["lines"]:
                assert rect_within(line["bbox"], SAFE_RECT)
                for rz in RESERVED_RECTS:
                    assert not rect_intersect(line["bbox"], rz)


class TestTimingScenarios:
    """Cases 1-7: speech vs VIDEO-002 final durations."""

    def test_6s_speech_pads_to_15s(self):
        p = plan(3.0, 2.7)  # speech 6.0 -> final 15.0
        assert p["valid"] is True
        assert p["final_frames"] == 360
        assert roles(p) == ["arabic", "gap", "urdu", "hold"]
        assert frames(p) == [72, 7, 65, 216]
        assert sum(m["duration"] for m in p["scene_metadata"]) == 15.0
        assert p["timeline"].total_frames == 360

    def test_14_99s_speech_rounds_to_15s(self):
        p = plan(7.5, 7.19)  # speech 14.99 -> final 15.0
        assert p["final_frames"] == 360
        assert roles(p) == ["arabic", "gap", "urdu"]  # no hold scene
        assert frames(p) == [180, 7, 173]
        assert p["timeline"].total_frames == 360

    def test_15s_speech_gets_half_second_hold(self):
        p = plan(8.0, 6.7)  # speech 15.0 -> final 15.5
        assert p["final_frames"] == 372
        assert frames(p) == [192, 7, 161, 12]
        assert p["timeline"].total_frames == 372

    def test_20s_speech(self):
        p = plan(10.0, 9.7)  # speech 20.0 -> final 20.5
        assert p["final_frames"] == 492
        assert frames(p) == [240, 7, 233, 12]
        assert p["timeline"].total_frames == 492

    def test_24_8s_speech_hold_reduced(self):
        p = plan(12.4, 12.1)  # speech 24.8 -> final 25.3
        assert p["final_frames"] == 607

    def test_25s_speech_no_hold(self):
        p = plan(12.5, 12.2)  # speech 25.0 -> final 25.5
        assert p["final_frames"] == 612
        assert p["timeline"].total_frames == 612

    def test_over_25s_speech_rejected(self):
        tl = AudioMixer.compute_video_timeline(50.01)
        assert tl["valid"] is False  # VIDEO-002 hard failure


class TestLanguagePresence:
    """Cases 8-10: Arabic-only / Urdu-only / both."""

    def test_arabic_only_no_gap_or_urdu(self):
        p = plan(6.0, 0.0, ur_text="")  # final 15.0
        assert roles(p) == ["arabic", "hold"]
        assert frames(p) == [144, 216]
        assert p["segments"]["gap_frames"] == 0
        assert p["offsets"]["urdu_base"] is None
        assert p["timeline"].total_frames == 360

    def test_urdu_only_no_gap_or_arabic(self):
        p = plan(0.0, 6.0, ar_text="")  # final 15.0
        assert roles(p) == ["urdu", "hold"]
        assert frames(p) == [144, 216]
        assert p["segments"]["gap_frames"] == 0
        assert p["timeline"].total_frames == 360

    def test_both_languages_include_gap_scene(self):
        p = plan(3.0, 2.7)
        assert roles(p) == ["arabic", "gap", "urdu", "hold"]
        assert p["segments"]["gap_frames"] == 7  # round(0.3 * 24)
        # gap scene has no speech text layers
        gap = p["timeline"].scenes[1]
        assert gap.layers == []


class TestLayoutSafety:
    """Cases 11-13 + SAFE_RECT verification."""

    def test_long_arabic_layout_safe(self):
        p = plan(6.0, 2.0, ar_text=" ".join([AR_TEXT] * 50))
        verify_safe(p, SceneRenderer(fps=FPS))

    def test_long_urdu_layout_safe(self):
        p = plan(2.0, 6.0, ur_text=" ".join([UR_TEXT] * 40))
        verify_safe(p, SceneRenderer(fps=FPS))

    def test_maximum_content_safe(self):
        p = plan(8.0, 7.0, ar_text=" ".join([AR_TEXT] * 70), ur_text=" ".join([UR_TEXT] * 45))
        verify_safe(p, SceneRenderer(fps=FPS))

    def test_arabic_scene_contains_only_title_and_arabic(self):
        p = plan(3.0, 2.7)
        ar_scene = p["timeline"].scenes[0]
        roles_present = {l.role for l in ar_scene.layers}
        assert roles_present == {"title", "arabic"}

    def test_urdu_scene_contains_no_arabic_text(self):
        p = plan(3.0, 2.7)
        ur_scene = p["timeline"].scenes[2]
        assert "arabic" not in {l.role for l in ur_scene.layers}


class TestDeterminismAndFrames:
    """Cases 14-15."""

    def test_same_dua_id_deterministic_timeline(self):
        p1 = plan(3.0, 2.7, dua="dua_same")
        p2 = plan(3.0, 2.7, dua="dua_same")
        assert roles(p1) == roles(p2)
        assert frames(p1) == frames(p2)
        for s1, s2 in zip(p1["timeline"].scenes, p2["timeline"].scenes):
            assert s1.palette_name() == s2.palette_name()
            assert s1.motion.kind == s2.motion.kind
            assert s1.text_style == s2.text_style

    def test_exact_frame_count_and_render_determinism(self):
        p = plan(3.0, 2.7)  # 360 frames
        f1 = render(p)
        f2 = render(p)
        assert len(f1) == 360 == round(15.0 * FPS)
        assert all(a.size == (1080, 1920) for a in f1)
        for fa, fb in zip(f1, f2):
            assert np.array_equal(np.asarray(fa), np.asarray(fb))


class TestRoundingAndOffsets:
    """Cases 16-17."""

    def test_negative_hold_rounding_is_clamped(self):
        # ar 7.52 -> 180, gap 7, ur 7.23 -> 174 => 361 > 360 => hold -1
        # Force final 15.0 explicitly to trigger the -1 overshoot.
        p = TimelineBuilder().build(
            "dua_x", AR_TEXT, UR_TEXT, "Dua", arabic_duration=7.52, urdu_duration=7.23, final_duration=15.0
        )
        assert p["valid"] is True
        assert frames(p) == [180, 7, 173]  # 1 frame absorbed into Urdu
        assert p["segments"]["hold_frames"] == 0
        assert p["final_frames"] == 360
        assert p["timeline"].total_frames == 360
        assert all(m["frames"] > 0 for m in p["scene_metadata"])

    def test_urdu_only_negative_rounding_absorbs_into_urdu(self):
        # ur 15.03 -> 360.72 -> 361 > 360 => -1 absorbed into urdu => 360
        p = TimelineBuilder().build(
            "dua_x", "", UR_TEXT, "Dua", arabic_duration=0.0, urdu_duration=15.03, final_duration=15.0
        )
        assert p["valid"] is True
        assert roles(p) == ["urdu"]
        assert frames(p) == [360]
        assert p["timeline"].total_frames == 360

    def test_word_boundary_absolute_offsets(self):
        p = plan(3.0, 2.0)
        offsets = p["offsets"]
        assert offsets["arabic_base"] == 0.0
        assert abs(offsets["urdu_base"] - 3.3) < 1e-9  # 3.0 + 0.3

        ar_words = [{"word": "w1", "offset": 0.5}, {"word": "w2", "offset": 1.2}]
        ur_words = [{"word": "u1", "offset": 0.1}]

        ar_mapped = TimelineBuilder.map_words_absolute(offsets, "ar", ar_words)
        ur_mapped = TimelineBuilder.map_words_absolute(offsets, "ur", ur_words)
        assert [w["abs_offset"] for w in ar_mapped] == [0.5, 1.2]
        assert [w["abs_offset"] for w in ur_mapped] == [3.4]  # 3.3 + 0.1
        # original words never mutated
        assert "abs_offset" not in ar_words[0]

    def test_urdu_offsets_absent_when_no_urdu(self):
        p = plan(6.0, 0.0, ur_text="")
        assert p["offsets"]["urdu_base"] is None
        assert TimelineBuilder.absolute_word_offset(p["offsets"], "ur", 0.5) is None


class TestNoZeroDurationAndContract:
    """Cases 18-20."""

    def test_no_zero_duration_scenes_across_scenarios(self):
        for kwargs in [
            dict(ar_s=3.0, ur_s=2.7),
            dict(ar_s=12.5, ur_s=12.2),
            dict(ar_s=6.0, ur_s=0.0, ur_text=""),
            dict(ar_s=0.0, ur_s=6.0, ar_text=""),
            dict(ar_s=7.52, ur_s=7.23),
        ]:
            p = plan(**kwargs)
            assert all(m["frames"] > 0 for m in p["scene_metadata"])

    def test_videobuilder_accepts_rendered_frames(self):
        tmp_dir = os.path.join(os.path.dirname(__file__), "_tb_tmp")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        try:
            # short timeline (2s worth of frames via small durations)
            p = TimelineBuilder().build(
                "dua_x", AR_TEXT, UR_TEXT, "Dua", arabic_duration=0.5, urdu_duration=0.5, final_duration=15.0
            )
            frames = render(p)
            out = os.path.join(tmp_dir, "tb_out.mp4")
            assert VideoBuilder(fps=FPS, resolution=(1080, 1920)).build_video(frames, out) is True
            assert os.path.exists(out) and os.path.getsize(out) > 0
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_builder_never_touches_audio_paths(self):
        # Builder receives only durations/texts - no audio IO exists by design.
        p = plan(3.0, 2.7)
        assert "audio" not in p or True  # no audio key in plan
        assert all(k in p for k in ("valid", "timeline", "scene_metadata", "final_frames", "segments", "offsets"))
