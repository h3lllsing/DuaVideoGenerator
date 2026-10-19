"""
Islamic Ultra Pack - Mega Pipeline
Sab kuch ek saath: Random fonts + effects + styles + backgrounds + Islamic constraints

All configuration comes from master_config.py
This file contains the pipeline logic only.

Usage:
    from core.mega_pack import MegaPackPipeline

    mega = MegaPackPipeline()
    result = mega.generate(
        arabic="بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ",
        urdu="اللہ کے نام سے شروع",
        title="Bismillah",
        mood="peaceful"  # optional - will be random if not specified
    )
"""

import logging
import os
from typing import Any
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Import from master config
from core.master_config import (
    MASTER_FONTS,
    MASTER_EFFECTS,
    MASTER_PALETTES,
    EFFECT_MOODS,
    TEXT_STYLES,
    MOTION_KINDS,
    CORNER_STYLES,
    ISLAMIC_CATEGORIES,
    generate_random_config,
    UltraConfig,
)

__all__ = ["MegaPackPipeline", "MegaPackResult"]


@dataclass
class MegaPackResult:
    """Result of a Mega Pack video generation."""

    success: bool
    video_path: str = ""
    config_summary: str = ""
    generation_time: float = 0.0
    error: str = ""

    def __str__(self):
        if self.success:
            return f"✅ Video ready: {self.video_path}\n⏱️ Time: {self.generation_time:.1f}s\n{self.config_summary}"
        return f"❌ Failed: {self.error}"


class MegaPackPipeline:
    """
    Islamic Ultra Pack Pipeline - Everything combined!

    Features:
    - 8 Arabic fonts (Amiri, Aref, Lateef, Mada, Noto)
    - 11 visual effects
    - 6 text styles
    - 854 Pexels backgrounds (halal only)
    - 4 mood presets
    - Islamic content validation
    - RTL/LTR mixed text support
    - All random, all halal
    """

    def __init__(self, output_dir: str | None = None):
        """Initialize Mega Pack pipeline."""
        from core.project_info import PROJECT

        self.output_dir = output_dir or os.path.join(PROJECT.OUTPUT_DIR, "ultra_pack")
        os.makedirs(self.output_dir, exist_ok=True)

        self._pipeline: Any = None
        self._randomizer: Any = None

        logger.info("MegaPackPipeline initialized")

    def _get_pipeline(self):
        """Lazy load the main pipeline."""
        if self._pipeline is None:
            from main import DuaVideoPipeline

            self._pipeline = DuaVideoPipeline()
        return self._pipeline

    def generate(
        self, arabic: str, urdu: str, title: str = "", mood: str | None = None, seed: str | None = None, **kwargs
    ) -> MegaPackResult:
        """
        Generate a video with full randomization.

        Args:
            arabic: Arabic dua text
            urdu: Urdu translation
            title: Video title (optional)
            mood: Preferred mood (peaceful/powerful/mystical/energetic)
            seed: Random seed (optional, auto-generated if None)
            **kwargs: Override any config option

        Returns:
            MegaPackResult with video path and details
        """
        start_time = time.time()

        try:
            # 1. Import and initialize randomizer
            from core.islamic_randomizer import IslamicRandomizer, IslamicConstraints

            # 2. Validate content
            if not IslamicConstraints.validate_content(arabic, urdu, title):
                return MegaPackResult(success=False, error="Content validation failed - check Arabic/Urdu text")

            # 3. Generate random config
            self._randomizer = IslamicRandomizer(seed=seed, favor=mood or "peaceful")
            config = self._randomizer.generate()

            # 4. Apply any overrides
            for key, value in kwargs.items():
                if hasattr(config, key):
                    setattr(config, key, value)

            logger.info(f"Mega Pack generating with {config.mood} mood...")
            logger.debug(f"Config:\n{config.summary()}")

            # 5. Load fonts and create renderer
            from core.arabic_renderer import ArabicRenderer
            from core.effects_engine import EffectsEngine
            from core.scene_engine import SceneRenderer, Scene, TextLayer, MotionSpec

            # Create Arabic renderer with selected font
            arabic_renderer = ArabicRenderer(font_key=config.arabic_font)

            # 6. Create scene with random settings
            scene_renderer = SceneRenderer()

            # Build scene
            scene = scene_renderer.build_single_scene(
                seed=config.seed,
                arabic=arabic,
                urdu=urdu,
                title=title,
                palette=config.palette,
                motion=MotionSpec(kind=config.motion_kind),
            )

            # Override corner and text style
            scene.corner_style = config.corner_style
            scene.text_style = config.text_style

            # 7. Generate video using main pipeline
            pipeline = self._get_pipeline()

            # Prepare pipeline parameters
            output_path = os.path.join(self.output_dir, f"ultra_{int(time.time())}.mp4")

            # Use the existing pipeline with our random config
            # The pipeline handles TTS, scene rendering, and video building
            result = pipeline.generate_video(
                arabic=arabic,
                urdu=urdu,
                title=title,
                output_path=output_path,
                scene=scene,
                dua_id=config.seed,
                category=config.background_category,
            )

            generation_time = time.time() - start_time

            if result.get("success", False):
                return MegaPackResult(
                    success=True,
                    video_path=result.get("video_path", output_path),
                    config_summary=config.summary(),
                    generation_time=generation_time,
                )
            else:
                return MegaPackResult(
                    success=False,
                    error=result.get("error", "Unknown error"),
                    config_summary=config.summary(),
                    generation_time=generation_time,
                )

        except Exception as e:
            logger.error(f"Mega Pack generation failed: {e}", exc_info=True)
            return MegaPackResult(
                success=False,
                error=str(e),
                generation_time=time.time() - start_time,
            )

    def preview_config(self, seed: str | None = None, mood: str | None = None) -> str:
        """Preview what config would be generated without actually making a video."""
        config = generate_random_config(seed=seed, favor=mood or "peaceful")
        return config.summary()

    def get_available_options(self) -> dict:
        """Get all available options for the UI."""
        return {
            "fonts": {k: v["desc"] for k, v in MASTER_FONTS.items()},
            "effects": list(MASTER_EFFECTS.keys()),
            "text_styles": list(TEXT_STYLES),
            "moods": {k: f"Weight: {v['weight']}" for k, v in EFFECT_MOODS.items()},
            "palettes": list(MASTER_PALETTES.keys()),
            "corners": list(CORNER_STYLES),
            "motions": list(MOTION_KINDS),
        }


# ============================================================
# Quick access functions for frontend
# ============================================================


def ultra_pack_generate(arabic: str, urdu: str, title: str = "", mood: str | None = None, **kwargs) -> MegaPackResult:
    """Quick function for frontend to generate Ultra Pack video."""
    mega = MegaPackPipeline()
    return mega.generate(arabic=arabic, urdu=urdu, title=title, mood=mood, **kwargs)


def ultra_pack_preview(seed: str | None = None, mood: str | None = None) -> str:
    """Quick function for frontend to preview config."""
    mega = MegaPackPipeline()
    return mega.preview_config(seed=seed, mood=mood)
