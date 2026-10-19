"""
Timeline Builder (VISUAL Phase 3).

Converts the immutable audio timing + VIDEO-002 final duration into a
multi-scene visual Timeline for the SceneEngine, without touching audio.

Audio layout (AUDIO-001 / VIDEO-002, immutable):
    [0 ... ar_duration]               Arabic speech
    [ar_duration .. +0.3s]            silence gap (only when both languages)
    [+0.3s .. ur_end]                 Urdu speech
    [ur_end .. final_duration]        trailing visual-hold silence

Visual timeline (segments):
    INTRO+ARABIC  ->  GAP  ->  URDU  ->  HOLD/OUTRO

Intro and outro are visual TREATMENTS (fades anchored to scene boundaries),
never standalone audio-consuming segments, so speech always starts at t=0.

Deterministic: every scene is seeded by "<dua_id>:<role>" so the same dua_id
always produces the same visual result for the same input conditions.

Audio is never stretched, duplicated, cut, or re-normalized here.
WordBoundary absolute-offset mapping is exposed for Phase 4 but not applied.
"""

import logging

logger = logging.getLogger(__name__)
from typing import cast

from core.scene_engine import Scene, SceneRenderer, Timeline, Transition

try:
    import config as _config
except Exception:
    _config = None  # type: ignore[assignment]

__all__ = ["TimelineBuilder"]


class TimelineBuilder:
    """
    Builds a SceneEngine Timeline from audio timing + VIDEO-002 duration.

    All scene durations are expressed as frame_count / fps so that
    Timeline.total_frames == round(final_duration * fps) exactly.
    """

    # Single source of truth is config.py; constants kept as safe fallbacks.
    MIN_DURATION = float(getattr(_config, "VIDEO_MIN_DURATION", 15))
    MAX_DURATION = float(getattr(_config, "VIDEO_MAX_DURATION", 50))

    def __init__(self, fps: int = 24, gap_seconds: float = 0.3, intro_seconds: float = 0.6, outro_seconds: float = 0.6):
        self.fps = int(fps)
        self.gap_seconds = float(gap_seconds)
        self.intro_seconds = float(intro_seconds)
        self.outro_seconds = float(outro_seconds)
        self._renderer = SceneRenderer(fps=self.fps)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build(
        self,
        dua_id: str,
        arabic_text: str,
        urdu_text: str,
        title: str = "",
        arabic_duration: float = 0.0,
        urdu_duration: float = 0.0,
        final_duration: float | None = None,
        category: str | None = None,
        palette: dict | None = None,
        motion=None,
        word_events: dict[str, list] | None = None,
        highlight_style: str = "",
        gradient_kind: str = "",
    ) -> dict:
        """
        Build the visual timeline.

        Args:
            dua_id: Seed base (deterministic per dua).
            arabic_text / urdu_text: Critical speech text (never altered).
            title: Optional title (rendered on the Arabic/first scene).
            arabic_duration / urdu_duration: Measured TTS durations (seconds).
            final_duration: VIDEO-002 final_duration (authoritative).
            category: Unused for styling in Phase 3 (reserved for assets).
            palette / motion: Optional overrides (None => deterministic pick).
            word_events: Optional {"arabic": [...], "urdu": [...]} WordBoundary
                entries (word/offset/duration/end, seconds). Offsets are
                scene-relative (the Arabic scene starts at 0; the Urdu scene
                starts at its own audio start), so they are attached directly
                with NO prime-offset constant. Missing/empty lists disable
                highlighting for that language.

        Returns:
            dict with timeline, scene_metadata, final_frames, segments,
            offsets (word-boundary bases), valid, reason.
        """
        # Defensive VIDEO-002 validation (real gate stays in main.py).
        if final_duration is None:
            return self._invalid("final_duration is required")
        final_duration = float(final_duration)
        eps = 1e-6
        if not (self.MIN_DURATION - eps <= final_duration <= self.MAX_DURATION + eps):
            return self._invalid(
                f"final_duration {final_duration:.2f}s is outside the "
                f"VIDEO-002 window [{self.MIN_DURATION}, {self.MAX_DURATION}]"
            )

        ar_dur = max(0.0, float(arabic_duration))
        ur_dur = max(0.0, float(urdu_duration))

        # ---- Frame math (all scene durations = frames / fps) ---------
        fps = self.fps
        F_total = int(round(final_duration * fps))
        F_ar = int(round(ar_dur * fps))
        F_ur = int(round(ur_dur * fps))

        ar_present = bool((arabic_text or "").strip()) and F_ar > 0
        ur_present = bool((urdu_text or "").strip()) and F_ur > 0
        gap_frames = int(round(self.gap_seconds * fps)) if (ar_present and ur_present) else 0

        # Effective speech frames actually represented by scenes.
        eff_ar = F_ar if ar_present else 0
        eff_ur = F_ur if ur_present else 0

        F_hold = F_total - eff_ar - gap_frames - eff_ur
        if F_hold < 0:
            # Absorb the (<=1 frame) negative rounding into the last speech
            # scene. Audio is never touched.
            if ur_present:
                F_ur += F_hold
            else:
                F_ar += F_hold
            F_hold = 0

        # ---- Build scenes --------------------------------------------
        scenes: list[Scene] = []
        meta: list[dict] = []
        urdu_start = ar_dur + (self.gap_seconds if gap_frames > 0 else 0.0)
        urdu_end = urdu_start + ur_dur

        if ar_present:
            sc = self._build_scene(
                f"{dua_id}:arabic", arabic_text, "", title, F_ar, palette, motion, highlight_style, gradient_kind
            )
            self._attach_events(sc, "arabic", word_events)
            sc.transition_in = Transition("fade", min(self.intro_seconds, sc.duration / 2))
            scenes.append(sc)
            meta.append({"role": "arabic", "frames": F_ar, "start": 0.0, "duration": F_ar / fps})

        if gap_frames > 0:
            sc = self._build_scene(
                f"{dua_id}:gap", "", "", "", gap_frames, palette, motion, highlight_style, gradient_kind
            )
            sc.transition_in = Transition("fade", 0.15)
            sc.transition_out = Transition("fade", 0.15)
            scenes.append(sc)
            meta.append({"role": "gap", "frames": gap_frames, "start": ar_dur, "duration": gap_frames / fps})

        if ur_present:
            sc = self._build_scene(
                f"{dua_id}:urdu",
                "",
                urdu_text,
                "" if ar_present else title,
                F_ur,
                palette,
                motion,
                highlight_style,
                gradient_kind,
            )
            self._attach_events(sc, "urdu", word_events)
            intro = self.intro_seconds if not ar_present else 0.3
            sc.transition_in = Transition("fade", min(intro, sc.duration / 2))
            if F_hold == 0:
                # Fold the outro treatment into the final speech scene.
                sc.transition_out = Transition("fade", min(self.outro_seconds, sc.duration / 2))
            scenes.append(sc)
            meta.append({"role": "urdu", "frames": F_ur, "start": urdu_start, "duration": F_ur / fps})

        if F_hold > 0:
            sc = self._build_scene(
                f"{dua_id}:hold", "", "", "", F_hold, palette, motion, highlight_style, gradient_kind
            )
            sc.transition_out = Transition("fade", min(self.outro_seconds, sc.duration / 2))
            scenes.append(sc)
            meta.append({"role": "hold", "frames": F_hold, "start": urdu_end, "duration": F_hold / fps})

        if not scenes:
            return self._invalid("no scenes could be built (empty input)")

        timeline = Timeline(fps=fps, scenes=scenes)

        # Final assertion: rendered frame count must match exactly.
        if timeline.total_frames != F_total:
            return self._invalid(
                f"timeline frame mismatch: {timeline.total_frames} != "
                f"{F_total} (final_duration {final_duration:.2f}s x {fps})"
            )

        offsets = {
            "arabic_base": 0.0,
            "urdu_base": urdu_start if ur_present else None,
            "gap_seconds": self.gap_seconds if gap_frames > 0 else 0.0,
        }

        return {
            "valid": True,
            "reason": "ok",
            "timeline": timeline,
            "scene_metadata": meta,
            "final_frames": F_total,
            "segments": {
                "arabic_start": 0.0,
                "arabic_end": ar_dur,
                "urdu_start": urdu_start,
                "urdu_end": urdu_end,
                "hold_start": urdu_end,
                "hold_end": final_duration,
                "gap_frames": gap_frames,
                "hold_frames": F_hold,
            },
            "offsets": offsets,
        }

    # ------------------------------------------------------------------
    # WordBoundary absolute-offset mapping (Phase 4 ready, not applied)
    # ------------------------------------------------------------------
    @staticmethod
    def absolute_word_offset(offsets: dict, language: str, word_offset: float) -> float | None:
        """Arabic words: offset; Urdu words: ar_dur + gap + offset."""
        base = offsets["urdu_base"] if language == "ur" else offsets.get("arabic_base", 0.0)
        if base is None:
            return None
        return cast(float, round(base + float(word_offset), 6))

    @staticmethod
    def map_words_absolute(offsets: dict, language: str, words: list[dict]) -> list[dict]:
        """
        Add absolute offsets to parsed WordBoundary entries (Phase 4 uses
        this; Phase 3 only exposes it). Sidecars are never modified.
        """
        result = []
        for w in words:
            copy = dict(w)
            copy["abs_offset"] = TimelineBuilder.absolute_word_offset(
                offsets, language, cast(float, w.get("offset", 0.0))
            )
            result.append(copy)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _attach_events(scene, role: str, word_events: dict[str, list] | None):
        """
        Attach scene-relative WordBoundary events to a scene (additive).

        Raw sidecar offsets are already relative to each language's own audio,
        which is exactly the scene time base (Arabic scene starts at 0; Urdu
        scene starts at its own audio start). They are used directly - NO
        prime-offset constant. Missing/empty/irrelevant entries are ignored.
        """
        entries = (word_events or {}).get(role)
        if not isinstance(entries, (list, tuple)) or not entries:
            return
        clean = []
        for w in entries:
            if not isinstance(w, dict):
                continue
            try:
                raw_start = w.get("offset")
                raw_end = w.get("end")
                if raw_start is None or raw_end is None:
                    continue
                start = round(float(raw_start), 6)
                end = round(float(raw_end), 6)
            except (TypeError, ValueError):
                continue
            clean.append({"start": start, "end": end, "word": w.get("word", "")})
        if clean:
            scene.word_events = {role: clean}

    def _build_scene(
        self,
        seed: str,
        arabic: str,
        urdu: str,
        title: str,
        frames: int,
        palette,
        motion,
        highlight_style: str = "",
        gradient_kind: str = "",
    ) -> Scene:
        duration = frames / self.fps
        scene = self._renderer.build_single_scene(
            seed,
            arabic,
            urdu,
            title,
            duration=duration,
            palette=palette,
            motion=motion,
            highlight_style=highlight_style,
            gradient_kind=gradient_kind,
        )
        # Drop empty-text layers (empty title/arabic/urdu must not waste
        # vertical layout space or produce collision-prone blocks).
        scene.layers = [l for l in scene.layers if (l.text or "").strip()]
        return scene

    @staticmethod
    def _invalid(reason: str) -> dict:
        return {
            "valid": False,
            "reason": reason,
            "timeline": None,
            "scene_metadata": [],
            "final_frames": 0,
            "segments": {},
            "offsets": {},
        }
