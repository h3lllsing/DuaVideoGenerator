"""
Effect Preview Module
Generates a short cached preview video for each visual effect so the user can
see what the effect looks like before generating a real video.

Uses the exact same Phase 3 visual pipeline (TimelineBuilder + SceneRenderer
+ EffectsEngine.apply_to_frames + VideoBuilder) but on a short sample dua and
at a reduced fps, with no audio, so it renders quickly.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.effect_director import EffectDirector, premium_palette
from core.effects_engine import EffectsEngine
from core.project_info import PROJECT
from core.scene_engine import SceneRenderer
from core.timeline_builder import TimelineBuilder
from core.video_builder import VideoBuilder

PREVIEW_FPS = 12
PREVIEW_DURATION = 15.0
AR_DURATION = 4.0
UR_DURATION = 3.5

SAMPLE_TITLE = "\u0627\u0644\u0644\u06c1 \u06a9\u06d2 \u0646\u0627\u0645 \u0633\u06d2"
SAMPLE_ARABIC = "\u0628\u0650\u0633\u0652\u0645\u0650 \u0627\u0644\u0644\u0651\u064e\u0647\u0650 \u0627\u0644\u0631\u0651\u064e\u062d\u0652\u0645\u064e\u0670\u0646\u0650 \u0627\u0644\u0631\u0651\u064e\u062d\u0650\u064a\u0645\u0650"
SAMPLE_URDU = "\u0627\u0644\u0644\u06c1 \u06a9\u06d2 \u0646\u0627\u0645 \u0633\u06d2 \u062c\u0648 \u0628\u06c1\u062a \u0645\u06c1\u0631\u0628\u0627\u0646 \u0631\u062d\u0645\u062a \u0648\u0627\u0644\u0627 \u06c1\u06d2\u06d4"

# Generate EFFECT_INFO dynamically from master config
from core.master_config import MASTER_EFFECTS

EFFECT_INFO = {
    "auto": (
        "AI Director: dua ki category, text aur hardware dekh kar khud best "
        "effect, word-sync pulse aur cinematic polish (vignette+grain) "
        "lagaata hai - har video consistent aur premium."
    ),
    "none": "Koi extra effect nahi - simple aur clean.",
}
EFFECT_INFO.update({key: info["desc"] for key, info in MASTER_EFFECTS.items()})

PREVIEW_DIR = os.path.join(PROJECT.TEMP_DIR, "previews")


def preview_path(effect: str) -> str:
    return os.path.join(PREVIEW_DIR, f"{(effect or 'none')}.mp4")


def preview_exists(effect: str) -> bool:
    return os.path.exists(preview_path(effect))


def build_effect_preview(effect: str, force: bool = False) -> str:
    """
    Build (and cache) a short preview MP4 for the given effect.
    Returns the preview file path. Raises RuntimeError on failure.
    """
    effect = effect or "none"
    out = preview_path(effect)
    if os.path.exists(out) and not force:
        return out
    os.makedirs(PREVIEW_DIR, exist_ok=True)

    plan = TimelineBuilder(fps=PREVIEW_FPS).build(
        dua_id="preview",
        arabic_text=SAMPLE_ARABIC,
        urdu_text=SAMPLE_URDU,
        title=SAMPLE_TITLE,
        arabic_duration=AR_DURATION,
        urdu_duration=UR_DURATION,
        final_duration=PREVIEW_DURATION,
        category="general",
        palette=premium_palette("preview"),
    )
    if not plan["valid"]:
        raise RuntimeError(f"TimelineBuilder failed: {plan['reason']}")

    frames = SceneRenderer(fps=PREVIEW_FPS).render(plan["timeline"], seed="preview")
    if effect == "auto":
        dua = {
            "id": "preview",
            "category": "general",
            "arabic": SAMPLE_ARABIC,
            "urdu": SAMPLE_URDU,
            "title": SAMPLE_TITLE,
        }
        fxplan = EffectDirector(fps=PREVIEW_FPS).plan(dua, plan, {}, effect_request="auto", dua_id="preview")
        frames = EffectsEngine().apply_plan(frames, fxplan["frame_plan"])
    elif effect != "none":
        frames = EffectsEngine().apply_to_frames(frames, effect)

    ok = VideoBuilder(fps=PREVIEW_FPS).build_video(frames, out, audio_path=None)
    if not ok or not os.path.exists(out):
        raise RuntimeError("Preview video build failed.")
    return out
