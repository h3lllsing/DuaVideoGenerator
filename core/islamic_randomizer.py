"""
Islamic Ultra Pack - Mega Randomizer System
Sab kuch random, sab kuch halal, sab kuch ek saath!

NOTE: All configuration now comes from master_config.py
This file only contains the randomizer logic.
"""

import logging
import random

logger = logging.getLogger(__name__)

# Import EVERYTHING from master config
from core.master_config import (
    EFFECT_MOODS,
    FORBIDDEN_CATEGORIES,
    HALAL_PALETTES,
    ISLAMIC_CATEGORIES,
    MASTER_PALETTES,
    PALETTE_NAMES,
    UltraConfig,
    generate_random_config,
)

__all__ = ["IslamicRandomizer", "IslamicConstraints"]


# ============================================================
# Islamic Constraints - Convenience wrapper
# ============================================================


class IslamicConstraints:
    """Enforce Islamic guidelines - wraps master_config constraints."""

    FORBIDDEN_CATEGORIES = FORBIDDEN_CATEGORIES
    HALAL_PALETTES = HALAL_PALETTES
    ISLAMIC_CATEGORIES = ISLAMIC_CATEGORIES

    @classmethod
    def is_category_allowed(cls, category: str) -> bool:
        """Check if a background category is halal."""
        cat_lower = category.lower()
        return not any(f in cat_lower for f in cls.FORBIDDEN_CATEGORIES)

    @classmethod
    def get_halal_palette(cls, rng: random.Random | None = None) -> dict:
        """Get a random halal color palette."""
        r = rng or random.Random()
        name = r.choice(PALETTE_NAMES)
        return dict(MASTER_PALETTES[name])

    @classmethod
    def validate_content(cls, arabic: str, urdu: str, title: str) -> bool:
        """Validate that content is appropriate."""
        if not arabic or not arabic.strip():
            return False
        if not urdu or not urdu.strip():
            return False
        return True


# ============================================================
# Main Randomizer Class
# ============================================================


class IslamicRandomizer:
    """
    Ultra Pack Randomizer - Sab kuch random, sab kuch halal!

    Usage:
        randomizer = IslamicRandomizer(seed="my_dua_123")
        config = randomizer.generate()
        # Use config to generate video
    """

    def __init__(self, seed: str | None = None, favor: str = "peaceful"):
        self.seed = seed or str(random.randint(100000, 999999))
        self.rng = random.Random(self.seed)
        self.favor = favor if favor in EFFECT_MOODS else "peaceful"

    def generate(self) -> UltraConfig:
        """Generate a complete random configuration."""
        return generate_random_config(
            seed=self.seed,
            favor=self.favor,
        )

    def preview(self) -> str:
        """Preview what config would be generated."""
        config = self.generate()
        return config.summary()
