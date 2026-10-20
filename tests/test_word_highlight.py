"""
VISUAL Phase 4 tests: WordBoundary-driven word highlighting.

Covers: active-word timing semantics (floor), event normalization,
logical->display token mapping (RTL/bidi, mixed direction, digits,
punctuation), word geometry (ordering, containment, determinism),
line-level fallback (count mismatch, unsupported language, hard-break),
overlay generation, TimelineBuilder scene-relative attachment (no prime
offset), renderer invariance (no events / empty events == legacy frames),
and full-render integration.

Run with: python -m pytest tests/test_word_highlight.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from core.scene_engine import SAFE_RECT, SceneRenderer
from core.timeline_builder import TimelineBuilder
from core.word_highlight import (
    build_word_geometry,
    highlight_targets,
    make_word_overlay,
    normalize_events,
    resolve_active_word,
)

FPS = 24
AR_TEXT = "\u0627\u0644\u0644\u0647\u0645 \u0627\u0646\u064a \u0627\u0633\u0623\u0644\u0643 \u0627\u0644\u0639\u0627\u0641\u064a\u0629 \u0641\u064a \u0627\u0644\u062f\u0646\u064a\u0627 \u0648\u0627\u0644\u0622\u062e\u0631\u0629"
AR3 = "\u0627\u0644\u0644\u0647\u0645 \u0627\u0646\u064a \u0627\u0633\u0623\u0644\u0643"
UR_TEXT = "\u0627\u0644\u0644\u06c1 \u0633\u06d2 \u0639\u0627\u0641\u06cc\u062a \u06a9\u06cc \u062f\u0639\u0627"
MIX_TEXT = "\u0627\u0644\u0644\u0647\u0645 Allah \u0623\u0633\u0623\u0644\u0643 7 \u0639\u0627\u0641\u064a\u0629"


# ----------------------------------------------------------------------
# Timing semantics (pure)
# ----------------------------------------------------------------------
def test_resolve_active_word_empty():
    assert resolve_active_word([], 5.0) is None


def test_resolve_active_word_before_first():
    ev = normalize_events([{"start": 0.5, "end": 1.0}])
    assert resolve_active_word(ev, 0.499) is None


def test_resolve_active_word_floor_semantics():
    ev = normalize_events(
        [
            {"start": 0.1, "end": 0.4, "word": "a"},
            {"start": 0.4, "end": 0.7, "word": "b"},
            {"start": 1.0, "end": 1.3, "word": "c"},
        ]
    )
    # at first start -> that word
    assert resolve_active_word(ev, 0.1) == 0
    # inside word 0 -> stays
    assert resolve_active_word(ev, 0.25) == 0
    # between word 0 and 1 -> previous stays (floor)
    assert resolve_active_word(ev, 0.3999) == 0
    # exactly at word 1 start -> switches
    assert resolve_active_word(ev, 0.4) == 1
    # between 1 and 2 -> previous stays
    assert resolve_active_word(ev, 0.9) == 1
    # at last start -> switches
    assert resolve_active_word(ev, 1.0) == 2
    # after final -> final stays until scene end
    assert resolve_active_word(ev, 99.0) == 2


def test_resolve_active_word_duplicate_starts_deterministic():
    ev = normalize_events(
        [
            {"start": 0.2, "word": "x"},
            {"start": 0.2, "word": "y"},
        ]
    )
    # both start at the same time; the later original entry is active.
    assert resolve_active_word(ev, 0.2) == 1
    assert resolve_active_word(ev, 0.1) is None


def test_normalize_events_filters_invalid():
    raw = [
        {"start": 0.5, "word": "a"},
        {"start": float("nan")},
        {"start": -1.0},
        {"start": "not-a-number"},
        "garbage",
        None,
        {"start": 1.5, "word": "b"},
    ]
    ev = normalize_events(raw)
    assert [e["start"] for e in ev] == [0.5, 1.5]
    assert [e["orig"] for e in ev] == [0, 6]


def test_normalize_events_sorts_and_keeps_orig():
    ev = normalize_events(
        [
            {"start": 1.0, "word": "z"},
            {"start": 0.1, "word": "a"},
        ]
    )
    assert [e["start"] for e in ev] == [0.1, 1.0]
    assert [e["orig"] for e in ev] == [1, 0]
    assert resolve_active_word(ev, 0.5) == 1


def test_normalize_events_empty_and_none():
    assert normalize_events(None) == []
    assert normalize_events([]) == []


# ----------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------
BOX = (200, 300, 880, 380)


def _lines(texts):
    """Fake single/multi-line layout in LOGICAL text order."""
    return [
        {
            "text": t,
            "font_size": 40,
            "x": BOX[0],
            "y": BOX[1],
            "w": BOX[2] - BOX[0],
            "h": BOX[3] - BOX[1],
            "bbox": BOX,
        }
        for t in texts
    ]


def _spans(texts, per_line_x):
    """line_spans aligned with _lines(texts): per line a list of
    (logical_token_index, x0, x1) FRAME-coordinate boxes."""
    out, ti = [], 0
    for _texts_i, xs in zip(texts, per_line_x, strict=False):
        entry = []
        for x0, x1 in xs:
            entry.append((ti, x0, x1))
            ti += 1
        out.append(entry)
    return out


# ----------------------------------------------------------------------
# Word geometry
# ----------------------------------------------------------------------
def test_build_word_geometry_non_ar_ur():
    texts = [AR3]
    geo = build_word_geometry(
        "title",
        AR3,
        _lines(texts),
        3,
        lambda s: 10 * len(s),
        line_spans=_spans(texts, [[(600, 700), (400, 500), (200, 300)]]),
    )
    assert geo["mode"] == "line"
    assert geo["targets"] == {}


def test_build_word_geometry_no_events_or_lines():
    texts = [AR3]
    assert build_word_geometry("ar", AR3, [], 3, lambda s: 10, line_spans=[])["targets"] == {}
    assert (
        build_word_geometry("ar", AR3, _lines(texts), 0, lambda s: 10, line_spans=_spans(texts, [[]]))["targets"] == {}
    )


def test_build_word_geometry_single_line_rtl_order():
    texts = [AR3]
    # Visual placement: logical word 0 at the RIGHT of the RTL line.
    geo = build_word_geometry(
        "ar",
        AR3,
        _lines(texts),
        3,
        lambda s: 10 * len(s),
        line_spans=_spans(texts, [[(600, 700), (400, 500), (200, 300)]]),
    )
    assert geo["mode"] == "word"
    assert set(geo["targets"]) == {0, 1, 2}
    assert geo["targets"][0][0] > geo["targets"][1][0] > geo["targets"][2][0]
    for _k, rect in geo["targets"].items():
        assert rect[0] >= 200 and rect[2] <= 880
        assert rect[1] >= 300 and rect[3] <= 380


def test_build_word_geometry_mixed_direction():
    texts = [MIX_TEXT]
    xs = [(760, 860), (620, 740), (480, 600), (360, 460), (210, 340)]
    geo = build_word_geometry("ur", MIX_TEXT, _lines(texts), 5, lambda s: 10 * len(s), line_spans=_spans(texts, [xs]))
    assert geo["mode"] == "word"
    assert set(geo["targets"]) == {0, 1, 2, 3, 4}
    # Logical word 1 is "Allah" (Latin) but is still mapped by position.
    for _k, rect in geo["targets"].items():
        assert rect[0] >= 200 and rect[2] <= 880


def test_build_word_geometry_with_digits():
    text = "\u0627\u0644\u0644\u0647\u0645 1 \u0648 2 \u0627\u0644\u0639\u0627\u0641\u064a\u0629"
    texts = [text]
    xs = [(700, 800), (600, 680), (500, 580), (400, 480), (220, 380)]
    geo = build_word_geometry("ar", text, _lines(texts), 5, lambda s: 10 * len(s), line_spans=_spans(texts, [xs]))
    assert geo["mode"] == "word"
    assert set(geo["targets"]) == {0, 1, 2, 3, 4}


def test_build_word_geometry_count_mismatch_line_fallback():
    texts = [AR3]
    geo = build_word_geometry(
        "ar",
        AR3,
        _lines(texts),
        5,
        lambda s: 10 * len(s),
        line_spans=_spans(texts, [[(600, 700), (400, 500), (200, 300)]]),
    )
    assert geo["mode"] == "line"
    assert len(geo["targets"]) == 5
    for e in range(5):
        assert geo["targets"][e] == (200, 300, 880, 380)


def test_build_word_geometry_missing_spans_line_fallback():
    texts = [AR3]
    geo = build_word_geometry("ar", AR3, _lines(texts), 3, lambda s: 10 * len(s), line_spans=None)
    assert geo["mode"] == "line"
    assert set(geo["targets"]) == {0, 1, 2}


def test_build_word_geometry_hard_break_fragment_line_fallback():
    # Second line is a hard-break FRAGMENT of token 2 -> cannot be mapped
    # at word level -> whole layer falls back to line boxes.
    texts = ["\u0627\u0644\u0644\u0647\u0645 \u0627\u0646\u064a", "\u0627\u0633\u0623"]
    geo = build_word_geometry(
        "ar", AR3, _lines(texts), 3, lambda s: 10 * len(s), line_spans=[[(0, 700, 850), (1, 400, 600)], [(2, 200, 350)]]
    )
    assert geo["mode"] == "line"


def test_build_word_geometry_span_count_mismatch_line_fallback():
    # One line has fewer spans than tokens -> cannot map word-level.
    texts = [AR3]
    bad = [[(600, 700), (400, 500)]]
    geo = build_word_geometry("ar", AR3, _lines(texts), 3, lambda s: 10 * len(s), line_spans=_spans(texts, bad))
    assert geo["mode"] == "line"


def test_build_word_geometry_unsupported_language_line_mode():
    texts = ["Hello world test"]
    geo = build_word_geometry(
        "title",
        "Hello world test",
        _lines(texts),
        3,
        lambda s: 10 * len(s),
        line_spans=_spans(texts, [[(600, 700), (400, 500), (200, 300)]]),
    )
    assert geo["mode"] == "line"
    assert geo["targets"] == {}


def test_build_word_geometry_deterministic():
    texts = [AR_TEXT]
    xs = [(760 - i * 90, 850 - i * 90) for i in range(7)]
    g1 = build_word_geometry("ar", AR_TEXT, _lines(texts), 7, lambda s: 10 * len(s), line_spans=_spans(texts, [xs]))
    g2 = build_word_geometry("ar", AR_TEXT, _lines(texts), 7, lambda s: 10 * len(s), line_spans=_spans(texts, [xs]))
    assert g1 == g2


def test_real_renderer_word_mode_and_safe_rect():
    """Real renderer wiring: surfaces supply exact spans -> word mode, all
    highlight rects stay inside SAFE_RECT, RTL order holds."""
    r = SceneRenderer(fps=FPS)
    scene = r.build_single_scene("g:s", AR_TEXT, UR_TEXT, "Dua")
    scene.layers = [l for l in scene.layers if (l.text or "").strip()]
    scene.word_events = {
        "arabic": [{"start": i * 0.3} for i in range(len(AR_TEXT.split()))],
        "urdu": [{"start": i * 0.3} for i in range(len(UR_TEXT.split()))],
    }
    layout = r.compute_layout(scene)
    surfaces = r._build_text_surfaces(scene, layout)
    hl = r._build_highlight(scene, layout, surfaces)
    assert hl is not None
    for role in ("arabic", "urdu"):
        info = hl.get(role)
        assert info is not None, role
        geo = info["geometry"]
        assert geo["mode"] == "word", role
        rects = list(geo["targets"].values())
        assert len(rects) == len((AR_TEXT if role == "arabic" else UR_TEXT).split())
        for rect in rects:
            assert rect[0] >= SAFE_RECT[0] and rect[2] <= SAFE_RECT[2]
            assert rect[1] >= SAFE_RECT[1] and rect[3] <= SAFE_RECT[3]
    ar_rects = hl["arabic"]["geometry"]["targets"]
    # Logical word 0 spoken first sits rightmost on the RTL arabic line.
    assert ar_rects[0][0] > ar_rects[len(ar_rects) - 1][0]


def test_real_renderer_without_surfaces_falls_back_to_lines():
    r = SceneRenderer(fps=FPS)
    scene = r.build_single_scene("g:s", AR3, UR_TEXT, "Dua")
    scene.layers = [l for l in scene.layers if (l.text or "").strip()]
    scene.word_events = {"arabic": [{"start": i * 0.3} for i in range(len(AR3.split()))]}
    layout = r.compute_layout(scene)
    hl = r._build_highlight(scene, layout, surfaces=None)
    assert hl is not None
    assert hl["arabic"]["geometry"]["mode"] == "line"


def test_real_renderer_junk_event_does_not_break_word_mode():
    """A raw junk entry (dropped by normalize_events) must not cause a
    spurious word/token count mismatch -> stays word-level."""
    r = SceneRenderer(fps=FPS)
    scene = r.build_single_scene("g:s", AR3, UR_TEXT, "Dua")
    scene.layers = [l for l in scene.layers if (l.text or "").strip()]
    raw = [{"start": i * 0.3} for i in range(len(AR3.split()))]
    raw.insert(1, {"start": "not-a-number"})  # junk -> normalized away
    scene.word_events = {"arabic": raw}
    layout = r.compute_layout(scene)
    surfaces = r._build_text_surfaces(scene, layout)
    hl = r._build_highlight(scene, layout, surfaces)
    assert hl is not None
    geo = hl["arabic"]["geometry"]
    assert geo["mode"] == "word"
    assert set(geo["targets"]) == set(range(len(AR3.split())))


# ----------------------------------------------------------------------
# Overlay
# ----------------------------------------------------------------------
def test_make_word_overlay_size_and_rgba():
    img = make_word_overlay((100, 200, 160, 240), (212, 175, 55))
    assert isinstance(img, Image.Image)
    assert img.mode == "RGBA"
    assert img.size == (60, 40)
    assert img.getpixel((30, 20))[3] > 0


def test_make_word_overlay_deterministic():
    a = make_word_overlay((100, 200, 160, 240), (212, 175, 55))
    b = make_word_overlay((100, 200, 160, 240), (212, 175, 55))
    assert a.tobytes() == b.tobytes()


def test_make_word_overlay_min_size():
    img = make_word_overlay((100, 200, 100, 200), (1, 2, 3))
    assert img.size == (1, 1)


# ----------------------------------------------------------------------
# highlight_targets
# ----------------------------------------------------------------------
def test_highlight_targets():
    events = normalize_events([{"start": 0.1}, {"start": 0.5}])
    texts = [AR3]
    geo = build_word_geometry("ar", AR3, _lines(texts), 2, lambda s: 10 * len(s), line_spans=None)
    assert highlight_targets(events, geo, 0.0) is None
    assert highlight_targets(events, geo, 0.2) is not None
    assert highlight_targets(events, geo, 9.0) is not None


# ----------------------------------------------------------------------
# TimelineBuilder scene-relative attachment (no prime offset)
# ----------------------------------------------------------------------
def _words(count, base=0.1, step=0.3):
    out = []
    for i in range(count):
        out.append(
            {
                "word": f"w{i}",
                "offset": round(base + i * step, 6),
                "duration": 0.2,
                "end": round(base + i * step + 0.2, 6),
            }
        )
    return out


def test_build_attaches_scene_relative_events_no_prime_offset():
    ar_w = _words(4, base=0.100)
    ur_w = _words(3, base=0.300)
    p = TimelineBuilder().build(
        "d",
        AR3,
        UR_TEXT,
        "T",
        arabic_duration=2.0,
        urdu_duration=2.0,
        final_duration=15.0,
        word_events={"arabic": ar_w, "urdu": ur_w},
    )
    assert p["valid"]
    scenes = {
        s2: sc for s2, sc in [(m["role"], s) for m, s in zip(p["scene_metadata"], p["timeline"].scenes, strict=False)]
    }
    ar_scene = scenes["arabic"]
    ur_scene = scenes["urdu"]
    assert ar_scene.word_events["arabic"][0]["start"] == 0.100
    assert ar_scene.word_events["arabic"][1]["start"] == 0.400
    assert ur_scene.word_events["urdu"][0]["start"] == 0.300
    assert ur_scene.word_events["urdu"][1]["start"] == 0.600
    # No prime-offset constant: starts are exactly the sidecar offsets.
    assert [e["start"] for e in ar_scene.word_events["arabic"]] == [0.1, 0.4, 0.7, 1.0]
    assert [e["word"] for e in ar_scene.word_events["arabic"]] == [w["word"] for w in ar_w]


def test_build_without_word_events_no_attachment():
    p = TimelineBuilder().build("d", AR3, UR_TEXT, "T", arabic_duration=2.0, urdu_duration=2.0, final_duration=15.0)
    assert p["valid"]
    for sc in p["timeline"].scenes:
        assert sc.word_events is None


def test_build_empty_word_events_disables_highlight():
    p = TimelineBuilder().build(
        "d",
        AR3,
        UR_TEXT,
        "T",
        arabic_duration=2.0,
        urdu_duration=2.0,
        final_duration=15.0,
        word_events={"arabic": [], "urdu": []},
    )
    assert p["valid"]
    for sc in p["timeline"].scenes:
        assert sc.word_events is None


def test_build_corrupt_word_events_ignored():
    p = TimelineBuilder().build(
        "d",
        AR3,
        UR_TEXT,
        "T",
        arabic_duration=2.0,
        urdu_duration=2.0,
        final_duration=15.0,
        word_events={"arabic": [None, {"word": "x"}, {"offset": "bad", "word": "y"}], "urdu": 123},
    )
    assert p["valid"]
    for sc in p["timeline"].scenes:
        assert sc.word_events is None


# ----------------------------------------------------------------------
# Renderer invariance + integration
# ----------------------------------------------------------------------
def _render_plan(ar_text, ur_text, word_events=None):
    p = TimelineBuilder().build(
        "dua_x",
        ar_text,
        ur_text,
        "Dua",
        arabic_duration=1.0,
        urdu_duration=1.0,
        final_duration=15.0,
        word_events=word_events,
    )
    r = SceneRenderer(fps=FPS)
    return p, r


def test_render_no_events_unchanged_baseline():
    p, r = _render_plan(AR3, UR_TEXT)
    frames_a = r.render(p["timeline"], seed="dua_x")
    # Events that start after every scene ends -> never active -> the frames
    # must be pixel-identical to the no-highlight baseline.
    ar_w = _words(len(AR3.split()), base=100.0, step=0.25)
    p2, r2 = _render_plan(AR3, UR_TEXT, word_events={"arabic": ar_w, "urdu": []})
    frames_b = r2.render(p2["timeline"], seed="dua_x")
    assert len(frames_a) == len(frames_b)
    for fa, fb in zip(frames_a, frames_b, strict=False):
        assert fa.tobytes() == fb.tobytes()


def test_render_with_events_differs_and_is_localized():
    ar_w = _words(len(AR3.split()), base=0.1, step=0.25)
    ur_w = _words(len(UR_TEXT.split()), base=0.1, step=0.25)
    p_base, r_base = _render_plan(AR3, UR_TEXT)
    frames_base = r_base.render(p_base["timeline"], seed="dua_x")

    p_hl, r_hl = _render_plan(AR3, UR_TEXT, word_events={"arabic": ar_w, "urdu": ur_w})
    frames_hl = r_hl.render(p_hl["timeline"], seed="dua_x")

    assert len(frames_hl) == len(frames_base)
    # Highlight must be visible in some frame (timing within audio window).
    any_diff = False
    for fa, fb in zip(frames_base, frames_hl, strict=False):
        if fa.tobytes() != fb.tobytes():
            any_diff = True
            diff = np.asarray(fa).astype(int) - np.asarray(fb).astype(int)
            ys, xs = np.nonzero(diff.sum(axis=2))
            assert len(ys) > 0
            # The changed pixels must be confined to SAFE_RECT.
            assert xs.min() >= SAFE_RECT[0] and xs.max() <= SAFE_RECT[2]
            assert ys.min() >= SAFE_RECT[1] and ys.max() <= SAFE_RECT[3]
            break
    assert any_diff, "highlight produced no visible change on any frame"


def test_render_with_events_deterministic():
    ar_w = _words(len(AR3.split()), base=0.1, step=0.25)
    p1, r1 = _render_plan(AR3, UR_TEXT, word_events={"arabic": ar_w, "urdu": []})
    f1 = r1.render(p1["timeline"], seed="dua_x")
    p2, r2 = _render_plan(AR3, UR_TEXT, word_events={"arabic": ar_w, "urdu": []})
    f2 = r2.render(p2["timeline"], seed="dua_x")
    for a, b in zip(f1, f2, strict=False):
        assert a.tobytes() == b.tobytes()


def test_render_highlight_last_word_stays_until_scene_end():
    ar_w = _words(len(AR3.split()), base=0.1, step=0.25)
    p, r = _render_plan(AR3, UR_TEXT, word_events={"arabic": ar_w, "urdu": []})
    timeline = p["timeline"]
    ar_scene = timeline.scenes[0]
    frames = list(r.render_scene(ar_scene, timeline.frames_for_scene(0), "dua_x", 0))
    assert len(frames) > 0
    # After the final word's start, the last word remains highlighted
    # (floor semantics -> no flicker at the tail).
    assert frames[-1].mode == "RGB"


def test_render_missing_corrupt_sidecar_never_crashes():
    p, r = _render_plan(AR3, UR_TEXT, word_events={"arabic": [None, {"offset": "bad"}], "urdu": None})
    assert p["valid"]
    frames = r.render(p["timeline"], seed="dua_x")
    assert len(frames) == p["final_frames"]
    assert frames[0].mode == "RGB"
