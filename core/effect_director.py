"""
Effect Director Module (the "AI brain").

A small deterministic intelligence layer that decides HOW the visuals should
behave for every dua video. It is NOT a neural network - it is a content
analysis + scoring engine that behaves like modern AI editors:

  1. ANALYZE   - reads the dua content (category, word counts, density).
  2. PLAN      - picks a scene-aware stack of effects (arabic / urdu / hold)
                 tuned to that content and to the hardware.
  3. SYNC      - drives a word-sync pulse from the real WordBoundary sidecars
                 (karaoke rhythm, the #1 2026 short-video trend).
  4. CONSISTENT- everything is seeded from dua_id, so the same dua always
                 renders the same way (deterministic, no surprises).

Frame plan contract (consumed by EffectsEngine.apply_plan):
  frame_plan[frame_index] = [ {effect, params, seed}, ... ]   (ordered stack)
"""

import logging
import math
import random
import zlib

logger = logging.getLogger(__name__)

from core import easing  # noqa: E402

__all__ = ["EffectDirector", "analyze_dua", "premium_palette", "scene_frame_ranges", "word_pulse_events"]

# ----------------------------------------------------------------------
# Content analysis
# ----------------------------------------------------------------------


def analyze_dua(dua_data: dict) -> dict:
    """Compute lightweight content metrics used for effect scoring."""
    arabic = str(dua_data.get("arabic", ""))
    urdu = str(dua_data.get("urdu", ""))
    title = str(dua_data.get("title", ""))
    category = str(dua_data.get("category", "general"))

    ar_words = [w for w in arabic.split() if w.strip()]
    ur_words = [w for w in urdu.split() if w.strip()]
    total_chars = len(arabic) + len(urdu)

    density = 1.0
    if total_chars > 300:
        density = 0.6
    elif total_chars > 180:
        density = 0.8

    return {
        "category": category,
        "arabic_word_count": len(ar_words),
        "urdu_word_count": len(ur_words),
        "title": title,
        "text_density": density,
    }


def _seed_int(dua_id: str) -> int:
    if isinstance(dua_id, int):
        return dua_id
    return zlib.crc32(str(dua_id or "dua").encode("utf-8")) & 0x7FFFFFFF


# Premium look: only the DARK palettes are eligible so every Short keeps
# the dark-gold cinematic grade. Import from master config.
from core.master_config import DARK_PALETTES


def premium_palette(dua_id: str) -> dict:
    """Deterministically pick a premium dark palette for a dua.

    Same dua -> same palette (consistency); different duas -> subtle variety
    across the dark family. Pass the result as TimelineBuilder.build(palette=).
    """
    from core.master_config import MASTER_PALETTES

    dark = [dict(MASTER_PALETTES[name]) for name in DARK_PALETTES]
    return dark[_seed_int(dua_id) % len(dark)]


# ----------------------------------------------------------------------
# Category mood model
# ----------------------------------------------------------------------

MOODS = {
    "prayer": {"tint": (212, 175, 55), "bold": 0.55, "sweep": True},
    "morning": {"tint": (255, 210, 90), "bold": 0.50, "sweep": True},
    "evening": {"tint": (150, 170, 255), "bold": 0.45, "sweep": False},
    "general": {"tint": (212, 175, 55), "bold": 0.70, "sweep": True},
    "sleep": {"tint": (140, 165, 255), "bold": 0.35, "sweep": False},
    "bathroom": {"tint": (150, 200, 230), "bold": 0.35, "sweep": False},
    "food": {"tint": (235, 190, 120), "bold": 0.40, "sweep": True},
    "travel": {"tint": (120, 200, 170), "bold": 0.45, "sweep": True},
}

DEFAULT_MOOD = MOODS["general"]


def _mood(category: str) -> dict:
    return MOODS.get(category, DEFAULT_MOOD)


def _score_effects(metrics: dict, mood: dict, rng) -> list:
    """
    Score candidate hero effects for a dua. Higher = better fit.
    Deterministic tie-break via rng.

    Balanced so most videos get the premium text-following glow (bloom),
    bold/captivating categories get the gold shimmer, and the RTL reveal is
    a rare accent (mostly very short duas) instead of the default look.
    """
    cat = metrics["category"]
    bold = mood["bold"]
    density = metrics["text_density"]
    n_words = metrics["arabic_word_count"]
    scores = []

    shimmer = 0.50 + 0.45 * bold + (0.15 if mood["sweep"] else 0.0)
    shimmer *= 1.25 - density * 0.35
    scores.append(("gold_shimmer", round(shimmer, 3)))

    bloom = 0.85
    if cat in ("evening", "sleep"):
        bloom += 0.10
    scores.append(("bloom_glow", round(bloom, 3)))

    reveal = 0.90 if n_words <= 6 else 0.45
    scores.append(("rtl_reveal", round(reveal, 3)))

    glitch = 0.15 + 0.55 * bold
    if cat in ("prayer", "morning", "evening", "sleep"):
        glitch *= 0.35
    scores.append(("glitch_v2", round(glitch, 3)))

    scores.sort(key=lambda kv: (-kv[1], rng.random()))
    return scores


# ----------------------------------------------------------------------
# Scene frame mapping
# ----------------------------------------------------------------------


def scene_frame_ranges(scene_metadata, fps: int, total_frames: int = 0):
    """Convert scene metadata into absolute frame ranges (clamped to video)."""
    ranges = []
    for i, sc in enumerate(scene_metadata or []):
        start_f = int(round(float(sc.get("start", 0.0)) * fps))
        dur_f = int(round(float(sc.get("duration", 0.0)) * fps))
        end_f = start_f + max(1, dur_f)
        if total_frames > 0:
            start_f = min(start_f, total_frames - 1)
            end_f = min(end_f, total_frames)
        ranges.append(
            {
                "index": i,
                "role": sc.get("role", "hold"),
                "start": max(0, start_f),
                "end": max(1, end_f),
                "start_sec": float(sc.get("start", 0.0)),
                "duration": float(sc.get("duration", 0.0)),
            }
        )
    return ranges


def word_pulse_events(word_events, offsets, fps: int, language: str = "arabic", max_words: int = 20):
    """
    Convert WordBoundary sidecars into pulse events at absolute frame
    indices (karaoke rhythm). Limited anchors so the video stays calm.
    """
    words = (word_events or {}).get(language) or []
    if not words:
        return []
    base = offsets.get("urdu_base") if language == "urdu" else 0.0
    if base is None:
        return []
    events = []
    step = max(1, len(words) // max_words) if len(words) > max_words else 1
    for w in words[::step]:
        try:
            off = float(w.get("offset", 0.0))
            dur = float(w.get("duration", 0.3))
        except (TypeError, ValueError):
            continue
        frame = int(round((base + off) * fps))
        frames_dur = max(4, int(round(dur * fps)))
        events.append({"frame": frame, "decay": max(6, frames_dur), "word": w.get("word", "")})
    return events


# ----------------------------------------------------------------------
# The director
# ----------------------------------------------------------------------


class EffectDirector:
    """Small deterministic brain that plans effects per video."""

    def __init__(self, fps: int | None = None, canvas=(1080, 1920)):
        if fps is None:
            from core.project_info import PROJECT

            fps = PROJECT.FPS
        self.fps = int(fps)
        self.width, self.height = canvas

    # ------------------------------------------------------------------
    def plan(
        self, dua_data, timeline_plan, word_events, effect_request: str = "auto", dua_id: str | None = None
    ) -> dict:
        """
        Build the per-frame effect stack.

        Returns {"frame_plan": list[list[dict]], "summary": str,
                 "hero": str|None, "hardware": str}
        """
        dua_id = dua_id or dua_data.get("id", "dua")
        seed = _seed_int(dua_id)
        rng = random.Random(seed)

        fps = self.fps
        metrics = analyze_dua(dua_data)
        mood = _mood(metrics["category"])
        total = int(timeline_plan.get("final_frames", 0))
        scenes = scene_frame_ranges(timeline_plan.get("scene_metadata", []), fps, total_frames=total)
        offsets = timeline_plan.get("offsets", {}) or {}

        role_by_frame = {}
        for sc in scenes:
            for f in range(sc["start"], sc["end"]):
                role_by_frame[f] = sc["role"]

        def role_of(frame):
            return role_by_frame.get(frame, "hold")

        pulses = word_pulse_events(word_events, offsets, fps, "arabic")

        # ---- hero effect selection ----
        if effect_request in (None, "", "none"):
            hero = None
        elif effect_request == "auto":
            scored = _score_effects(metrics, mood, rng)
            hero = scored[0][0]
        else:
            hero = effect_request

        ar_scene = next((s for s in scenes if s["role"] == "arabic"), None)
        ur_scene = next((s for s in scenes if s["role"] == "urdu"), None)
        hold_scene = next((s for s in scenes if s["role"] == "hold"), None)

        def local_progress(scene, frame):
            if not scene or scene["start"] == scene["end"]:
                return 0.0
            return (frame - scene["start"]) / (scene["end"] - scene["start"])

        # ---- build the per-frame plan ----
        plan: list[list[dict]] = [[] for _ in range(total)]

        for f in range(total):
            plan[f].append({"effect": "vignette", "params": {"strength": 0.35}, "seed": seed})
            plan[f].append({"effect": "grain", "params": {"strength": 0.06}, "seed": seed + f})

        if hero is not None:
            # word-sync karaoke pulses (arabic scene only)
            for p in pulses:
                frame = p["frame"]
                if 0 <= frame < total and role_of(frame) in ("arabic", "urdu"):
                    plan[frame].append(
                        {
                            "effect": "word_pulse",
                            "params": {
                                "strength": 0.16,
                                "tint": mood["tint"],
                                "decay": p["decay"],
                            },
                            "seed": seed + frame,
                        }
                    )

            # Phase C premium layers (auto mode only):
            #  - aurora light-leaks across the whole video (subtle, background)
            #  - title hook (zoom + gold flash) on the opening of arabic scene
            if effect_request == "auto":
                for f in range(total):
                    plan[f].append(
                        {
                            "effect": "aurora",
                            "params": {
                                "phase": f / max(1, total - 1),
                                "tint": mood["tint"],
                                "intensity": 0.08,
                            },
                            "seed": seed + f,
                        }
                    )
                if ar_scene:
                    hook_end = ar_scene["start"] + int((ar_scene["end"] - ar_scene["start"]) * 0.25)
                    for f in range(ar_scene["start"], min(hook_end, total)):
                        lp = (f - ar_scene["start"]) / max(1, hook_end - ar_scene["start"])
                        plan[f].append(
                            {
                                "effect": "title_hook",
                                "params": {"phase": lp, "tint": mood["tint"]},
                                "seed": seed + f,
                            }
                        )

            # hero effect on arabic + urdu scenes
            for sc in (ar_scene, ur_scene):
                if not sc:
                    continue
                for f in range(sc["start"], sc["end"]):
                    lp = local_progress(sc, f)
                    if hero == "rtl_reveal":
                        if lp < 0.4:
                            plan[f].append(
                                {
                                    "effect": "rtl_reveal",
                                    "params": {
                                        "fraction": easing.apply("ease_out", lp / 0.4),
                                    },
                                    "seed": seed,
                                }
                            )
                    elif hero == "gold_shimmer":
                        plan[f].append(
                            {
                                "effect": "gold_shimmer",
                                "params": {
                                    "phase": (f - sc["start"]) / max(1, sc["end"] - sc["start"]),
                                    "tint": mood["tint"],
                                    "intensity": 0.30 + 0.15 * (1 - metrics["text_density"]),
                                },
                                "seed": seed,
                            }
                        )
                    elif hero == "glitch_v2":
                        amp = 0.5 + 0.5 * abs(math.sin(lp * math.pi * 3))
                        if amp > 0.35:
                            plan[f].append(
                                {
                                    "effect": "glitch_v2",
                                    "params": {"strength": amp, "tint": mood["tint"]},
                                    "seed": seed + f,
                                }
                            )
                    else:
                        plan[f].append(
                            {
                                "effect": "bloom_glow",
                                "params": {
                                    "tint": mood["tint"],
                                    "intensity": 0.55 + 0.2 * mood["bold"],
                                    "threshold": 110,
                                },
                                "seed": seed,
                            }
                        )

            # calm breathing on the hold scene
            if hold_scene:
                for f in range(hold_scene["start"], hold_scene["end"]):
                    lp = local_progress(hold_scene, f)
                    plan[f].append(
                        {
                            "effect": "breathing",
                            "params": {"phase": lp, "freq": 1.5, "amp": 0.05},
                            "seed": seed,
                        }
                    )
                    # outro summary card: both Arabic + translation + title
                    if hero is not None:
                        plan[f].append(
                            {
                                "effect": "summary_card",
                                "params": {
                                    "arabic": str(dua_data.get("arabic", "")),
                                    "urdu": str(dua_data.get("urdu", "")),
                                    "title": str(dua_data.get("title", "")),
                                    "tint": mood["tint"],
                                    "lp": lp,
                                },
                                "seed": seed,
                            }
                        )

            summary = "AI Director: %s | word-sync %d | %s" % (hero, len(pulses), self._hardware())
        else:
            summary = "Effects off (none)"

        return {
            "frame_plan": plan,
            "summary": summary,
            "hero": hero,
            "hardware": self._hardware(),
        }

    def _hardware(self):
        try:
            from core.hardware import profile_summary

            return profile_summary()
        except Exception:
            return "cpu"
