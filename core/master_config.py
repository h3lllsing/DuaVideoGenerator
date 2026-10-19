"""
Islamic Master Config - SAB KUCH EK JAGAH!

Yeh file single source of truth hai. Sab kuch yahan se import karo.
Koi bhi config yahan define hota hai, baaki sab yahan se padhte hain.

Usage:
    from core.master_config import *

    # Fonts
    font = MASTER_FONTS["amiri_bold"]

    # Effects
    effect = random.choice(MASTER_EFFECTS)

    # Palettes
    palette = random.choice(MASTER_PALETTES)

    # Random video config
    config = generate_random_config(seed="my_seed")
"""

import os
import random
from dataclasses import dataclass, field
from typing import Any, cast

__all__ = [
    # Font system
    "MASTER_FONTS",
    "FONT_COMBOS",
    "FONT_FAMILY",
    # Effect system
    "MASTER_EFFECTS",
    "EFFECT_MOODS",
    "EFFECT_CATEGORIES",
    # Palette system
    "MASTER_PALETTES",
    "PALETTE_NAMES",
    "DARK_PALETTES",
    # Visual system
    "TEXT_STYLES",
    "MOTION_KINDS",
    "CORNER_STYLES",
    # Islamic constraints
    "ISLAMIC_CATEGORIES",
    "FORBIDDEN_CATEGORIES",
    "HALAL_PALETTES",
    # VFX Pattern system
    "VFX_PATTERN_KINDS",
    "VFX_TILE_ZONES",
    "VFX_COLOR_TOKENS",
    "VFX_STYLE_OVERRIDES",
    "MASTER_VFX_PATTERNS",
    "VFX_PATTERN_IDS",
    # VFX Plugin system
    "MASTER_VFX_PLUGINS",
    "VFX_PLUGIN_IDS",
    # VFX Theme system
    "VFX_THEME_DECORS",
    "MASTER_VFX_THEMES",
    "VFX_THEME_IDS",
    # VFX Typography system
    "VFX_TYPOGRAPHY_FAMILIES",
    "MASTER_VFX_TYPOGRAPHY",
    "VFX_TYPOGRAPHY_IDS",
    # VFX Motion system
    "VFX_MOTION_CAMERAS",
    "VFX_MOTION_TEXT_FX",
    "VFX_MOTION_INTRO_FX",
    "MASTER_VFX_MOTION",
    "VFX_MOTION_IDS",
    # VFX Audio system
    "MASTER_VFX_AUDIO",
    "VFX_AUDIO_IDS",
    # Highlight box styles (Reels/TikTok trending)
    "HIGHLIGHT_BOX_STYLES",
    # Background gradient kinds
    "BACKGROUND_GRADIENT_KINDS",
    # Randomizer
    "generate_random_config",
    "UltraConfig",
    # VFX helpers
    "get_random_vfx_pattern",
    "get_random_vfx_plugin",
    "get_random_vfx_theme",
    "get_random_vfx_typography",
    "get_random_vfx_motion",
    "get_random_vfx_audio",
    "get_vfx_stats",
    # Metadata
    "VERSION",
    "PROJECT_NAME",
]

VERSION = "2.0.0"
PROJECT_NAME = "Islamic Ultra Pack"


# ============================================================
# 1. MASTER FONT SYSTEM
# ============================================================

MASTER_FONTS: dict[str, dict[str, Any]] = {
    "amiri_bold": {
        "key": "amiri_bold",
        "name": "Amiri Bold",
        "file": "Amiri-Bold.ttf",
        "weight": "bold",
        "family": "serif",
        "desc": "Classic Naskh - Masjid jaisa",
        "islamic": True,
        "best_for": ["arabic", "title"],
    },
    "amiri_regular": {
        "key": "amiri_regular",
        "name": "Amiri Regular",
        "file": "Amiri-Regular.ttf",
        "weight": "regular",
        "family": "serif",
        "desc": "Light Naskh - Saaf aur clear",
        "islamic": True,
        "best_for": ["arabic", "urdu"],
    },
    "aref_bold": {
        "key": "aref_bold",
        "name": "Aref Ruqaa Bold",
        "file": "ArefRuqaa-Bold.ttf",
        "weight": "bold",
        "family": "ruqaa",
        "desc": "Ruqaa style - Khat jaisa",
        "islamic": True,
        "best_for": ["title", "arabic"],
    },
    "aref_regular": {
        "key": "aref_regular",
        "name": "Aref Ruqaa Regular",
        "file": "ArefRuqaa-Regular.ttf",
        "weight": "regular",
        "family": "ruqaa",
        "desc": "Ruqaa light - Dua ke liye best",
        "islamic": True,
        "best_for": ["urdu", "arabic"],
    },
    "lateef": {
        "key": "lateef",
        "name": "Lateef",
        "file": "Lateef-Regular.ttf",
        "weight": "regular",
        "family": "naskh",
        "desc": "Lateef - Narm aur pyara",
        "islamic": True,
        "best_for": ["urdu"],
    },
    "mada_bold": {
        "key": "mada_bold",
        "name": "Mada Bold",
        "file": "Mada-Bold.ttf",
        "weight": "bold",
        "family": "modern",
        "desc": "Modern Arabic - Aaj kal ka style",
        "islamic": True,
        "best_for": ["title"],
    },
    "noto_bold": {
        "key": "noto_bold",
        "name": "Noto Naskh Arabic Bold",
        "file": "NotoNaskhArabic-Bold.ttf",
        "weight": "bold",
        "family": "naskh",
        "desc": "Google Naskh - Universal",
        "islamic": True,
        "best_for": ["arabic", "title"],
    },
    "noto_regular": {
        "key": "noto_regular",
        "name": "Noto Naskh Arabic Regular",
        "file": "NotoNaskhArabic-Regular.ttf",
        "weight": "regular",
        "family": "naskh",
        "desc": "Google Naskh Light",
        "islamic": True,
        "best_for": ["urdu", "arabic"],
    },
}

FONT_FAMILY = list(set(f["family"] for f in MASTER_FONTS.values()))

FONT_COMBOS = [
    {"arabic": "amiri_bold", "urdu": "noto_regular", "title": "aref_bold", "name": "Classic"},
    {"arabic": "aref_bold", "urdu": "amiri_regular", "title": "noto_bold", "name": "Ruqaa"},
    {"arabic": "noto_bold", "urdu": "lateef", "title": "amiri_bold", "name": "Google"},
    {"arabic": "amiri_regular", "urdu": "noto_regular", "title": "aref_regular", "name": "Light"},
    {"arabic": "aref_regular", "urdu": "amiri_regular", "title": "mada_bold", "name": "Modern"},
    {"arabic": "lateef", "urdu": "noto_regular", "title": "amiri_bold", "name": "Soft"},
    {"arabic": "mada_bold", "urdu": "noto_regular", "title": "aref_bold", "name": "Bold"},
    {"arabic": "noto_regular", "urdu": "lateef", "title": "noto_bold", "name": "Simple"},
]


# ============================================================
# 2. MASTER EFFECT SYSTEM
# ============================================================

MASTER_EFFECTS = {
    # Visual effects (user-facing)
    "neon_glow": {
        "name": "Neon Glow",
        "desc": "Chamakti hui neon roshni",
        "mood": ["peaceful", "mystical"],
        "category": "glow",
        "weight": 0.15,
    },
    "metallic_gold": {
        "name": "Metallic Gold",
        "desc": "Sunehri chandi jaisa",
        "mood": ["powerful", "mystical"],
        "category": "shimmer",
        "weight": 0.12,
    },
    "silver_chrome": {
        "name": "Silver Chrome",
        "desc": "Chandi ka chamak",
        "mood": ["powerful"],
        "category": "shimmer",
        "weight": 0.08,
    },
    "three_d_shadow": {
        "name": "3D Shadow",
        "desc": "Gehri 3D shadow",
        "mood": ["powerful"],
        "category": "depth",
        "weight": 0.08,
    },
    "neon_outline": {
        "name": "Neon Outline",
        "desc": "Neon outline wali text",
        "mood": ["mystical", "energetic"],
        "category": "glow",
        "weight": 0.08,
    },
    "bounce": {
        "name": "Bounce",
        "desc": "Text upar neeche udti hai",
        "mood": ["peaceful", "energetic"],
        "category": "motion",
        "weight": 0.12,
    },
    "wave": {
        "name": "Wave",
        "desc": "Lehron jaisi harkat",
        "mood": ["peaceful"],
        "category": "motion",
        "weight": 0.12,
    },
    "glitch": {
        "name": "Glitch",
        "desc": "Modern glitch effect",
        "mood": ["energetic"],
        "category": "modern",
        "weight": 0.05,
    },
    "fade_in_out": {
        "name": "Fade In/Out",
        "desc": "Aahista se aana aur jaana",
        "mood": ["peaceful"],
        "category": "transition",
        "weight": 0.10,
    },
    "slide_left": {
        "name": "Slide Left",
        "desc": "Baazin se dahini taraf",
        "mood": ["energetic"],
        "category": "motion",
        "weight": 0.06,
    },
    "scale_up": {
        "name": "Scale Up",
        "desc": "Chota se bada hona",
        "mood": ["powerful", "peaceful"],
        "category": "motion",
        "weight": 0.04,
    },
}

EFFECT_CATEGORIES = list(set(e["category"] for e in MASTER_EFFECTS.values()))

EFFECT_MOODS: dict[str, dict[str, Any]] = {
    "peaceful": {
        "name": "Peaceful",
        "desc": "Sukoon aur itminan",
        "effects": ["neon_glow", "wave", "bounce", "fade_in_out", "scale_up"],
        "text_styles": ["solid", "gradient", "glow"],
        "weight": 0.40,
    },
    "powerful": {
        "name": "Powerful",
        "desc": "Taakat aur azmat",
        "effects": ["metallic_gold", "silver_chrome", "three_d_shadow", "bounce", "scale_up"],
        "text_styles": ["outline", "shadow", "gold"],
        "weight": 0.30,
    },
    "mystical": {
        "name": "Mystical",
        "desc": "Roohani aur paak",
        "effects": ["neon_glow", "neon_outline", "metallic_gold", "wave"],
        "text_styles": ["glow", "gradient", "gold"],
        "weight": 0.20,
    },
    "energetic": {
        "name": "Energetic",
        "desc": "Josh aur jazba",
        "effects": ["glitch", "slide_left", "neon_outline", "bounce"],
        "text_styles": ["outline", "shadow"],
        "weight": 0.10,
    },
}


# ============================================================
# 3. MASTER PALETTE SYSTEM
# ============================================================

MASTER_PALETTES: dict[str, dict[str, Any]] = {
    "midnight": {
        "name": "midnight",
        "desc": "Raat ka asman",
        "top": (18, 20, 42),
        "bottom": (9, 11, 27),
        "accent": (212, 175, 55),
        "text": (255, 255, 255),
        "title": (255, 215, 0),
        "outline": (10, 12, 20),
        "dark": True,
    },
    "twilight": {
        "name": "twilight",
        "desc": "Shaam ka waqt",
        "top": (40, 12, 55),
        "bottom": (22, 7, 34),
        "accent": (212, 175, 55),
        "text": (245, 240, 255),
        "title": (255, 215, 0),
        "outline": (16, 6, 24),
        "dark": True,
    },
    "emerald": {
        "name": "emerald",
        "desc": "Sabz pahar",
        "top": (13, 76, 63),
        "bottom": (7, 44, 38),
        "accent": (212, 175, 55),
        "text": (255, 255, 255),
        "title": (255, 215, 0),
        "outline": (4, 22, 18),
        "dark": True,
    },
    "navy": {
        "name": "navy",
        "desc": "Gehra samundar",
        "top": (16, 32, 70),
        "bottom": (8, 17, 43),
        "accent": (203, 172, 96),
        "text": (255, 255, 255),
        "title": (255, 215, 0),
        "outline": (6, 10, 24),
        "dark": True,
    },
    "sage": {
        "name": "sage",
        "desc": "Naram sabzia",
        "top": (42, 58, 48),
        "bottom": (22, 32, 26),
        "accent": (180, 160, 100),
        "text": (245, 245, 240),
        "title": (210, 190, 120),
        "outline": (18, 24, 20),
        "dark": True,
    },
    "dusk": {
        "name": "dusk",
        "desc": "Maghrib ka waqt",
        "top": (55, 35, 65),
        "bottom": (30, 18, 38),
        "accent": (195, 165, 110),
        "text": (248, 245, 252),
        "title": (220, 195, 140),
        "outline": (22, 14, 26),
        "dark": True,
    },
    "stone": {
        "name": "stone",
        "desc": "Patthar ki thandi",
        "top": (60, 55, 50),
        "bottom": (35, 32, 28),
        "accent": (175, 155, 120),
        "text": (245, 242, 238),
        "title": (200, 180, 140),
        "outline": (25, 22, 20),
        "dark": False,
    },
    "forest": {
        "name": "forest",
        "desc": "Jungle ki gehraiyon",
        "top": (25, 50, 35),
        "bottom": (12, 28, 18),
        "accent": (165, 145, 100),
        "text": (240, 245, 238),
        "title": (190, 175, 130),
        "outline": (10, 20, 14),
        "dark": True,
    },
    "sand": {
        "name": "sand",
        "desc": "Registan ki ret",
        "top": (248, 244, 236),
        "bottom": (228, 220, 206),
        "accent": (122, 92, 52),
        "text": (40, 35, 28),
        "title": (122, 92, 52),
        "outline": (255, 255, 255),
        "dark": False,
    },
    "mist": {
        "name": "mist",
        "desc": "Dhuaan aur kohra",
        "top": (236, 237, 246),
        "bottom": (208, 212, 231),
        "accent": (45, 90, 160),
        "text": (28, 33, 58),
        "title": (60, 80, 140),
        "outline": (250, 250, 250),
        "dark": False,
    },
    "royal": {
        "name": "royal",
        "desc": "Badshahi rang",
        "top": (35, 15, 55),
        "bottom": (18, 8, 30),
        "accent": (220, 185, 65),
        "text": (255, 250, 240),
        "title": (255, 215, 0),
        "outline": (15, 5, 25),
        "dark": True,
    },
    "ocean": {
        "name": "ocean",
        "desc": "Samundar ki gehraiyon",
        "top": (10, 40, 70),
        "bottom": (5, 20, 45),
        "accent": (100, 180, 220),
        "text": (240, 250, 255),
        "title": (120, 200, 240),
        "outline": (5, 15, 30),
        "dark": True,
    },
}

PALETTE_NAMES = list(MASTER_PALETTES.keys())
DARK_PALETTES = [k for k, v in MASTER_PALETTES.items() if v.get("dark", True)]
HALAL_PALETTES = list(MASTER_PALETTES.keys())  # All are halal


# ============================================================
# 4. MASTER VISUAL SYSTEM
# ============================================================

TEXT_STYLES = (
    "solid",  # Plain text
    "outline",  # With stroke outline
    "gold",  # Gold metallic
    "glow",  # Neon glow
    "gradient",  # Vertical gradient
    "shadow",  # Drop shadow
)

MOTION_KINDS = (
    "static",  # No motion
    "zoom_in",  # Slow zoom in
    "zoom_out",  # Slow zoom out
    "pan_left",  # Pan left
    "pan_right",  # Pan right
    "pan_up",  # Pan up
    "pan_down",  # Pan down
)

CORNER_STYLES = (
    "classic",  # Simple corners
    "double",  # Double line corners
    "dot",  # Dot at corner
)


# ============================================================
# 4b. HIGHLIGHT BOX STYLES (Reels/TikTok trending captions)
# ============================================================

HIGHLIGHT_BOX_STYLES = (
    "",  # Legacy subtle overlay (default)
    "gold",  # Gold pill with warm glow
    "teal",  # Teal/cyan pill with cool glow
    "rose",  # Rose/pink pill with soft glow
)


# ============================================================
# 4c. BACKGROUND GRADIENT KINDS
# ============================================================

BACKGROUND_GRADIENT_KINDS = (
    "",  # Default static linear gradient
    "aurora",  # Animated shifting aurora/northern-lights gradient
)


# ============================================================
# 5. ISLAMIC CONSTRAINTS
# ============================================================

FORBIDDEN_CATEGORIES = {
    "alcohol",
    "gambling",
    "pork",
    "music_instruments",
    "dancing",
    "nightclub",
    "bar",
    "tattoo",
    "astrology",
    "occult",
    "magic",
    "violence",
    "nudity",
    "weapons",
    "drugs",
}

ISLAMIC_CATEGORIES = [
    "nature",
    "ocean",
    "mountains",
    "sky",
    "stars",
    "sunrise",
    "sunset",
    "clouds",
    "rain",
    "flowers",
    "trees",
    "desert",
    "water",
    "forest",
    "night_sky",
    "moon",
    "river",
    "lake",
    "greenery",
    "hills",
    "mosque",
    "calligraphy",
    "geometric",
    "arabesque",
    "lantern",
    "crescent",
    "star_light",
    "dome",
]


# ============================================================
# 6. MASTER RANDOMIZER
# ============================================================


@dataclass
class UltraConfig:
    """Complete video configuration - sab kuch ek jagah!"""

    # Seed
    seed: str = ""

    # Fonts
    arabic_font: str = "amiri_bold"
    urdu_font: str = "noto_regular"
    title_font: str = "aref_bold"

    # Effects
    text_effect: str = "neon_glow"
    text_style: str = "solid"
    mood: str = "peaceful"

    # Background
    background_category: str = "nature"
    background_type: str = "auto"

    # Visual
    corner_style: str = "classic"
    particle_density: int = 40
    motion_kind: str = "static"
    highlight_style: str = ""  # "" / "gold" / "teal" / "rose"
    gradient_kind: str = ""  # "" / "aurora"

    # Palette
    palette: str = "midnight"

    # VFX (from Remotion VFX Studio)
    vfx_pattern: str = ""
    vfx_plugin: str = ""
    vfx_theme: str = ""
    vfx_typography: str = ""
    vfx_motion: str = ""
    vfx_audio: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "seed": self.seed,
            "arabic_font": self.arabic_font,
            "urdu_font": self.urdu_font,
            "title_font": self.title_font,
            "text_effect": self.text_effect,
            "text_style": self.text_style,
            "mood": self.mood,
            "background_category": self.background_category,
            "background_type": self.background_type,
            "corner_style": self.corner_style,
            "particle_density": self.particle_density,
            "motion_kind": self.motion_kind,
            "highlight_style": self.highlight_style,
            "gradient_kind": self.gradient_kind,
            "palette": self.palette,
            "vfx_pattern": self.vfx_pattern,
            "vfx_plugin": self.vfx_plugin,
            "vfx_theme": self.vfx_theme,
            "vfx_typography": self.vfx_typography,
            "vfx_motion": self.vfx_motion,
            "vfx_audio": self.vfx_audio,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        font_info = MASTER_FONTS.get(self.arabic_font, {})
        effect_info = MASTER_EFFECTS.get(self.text_effect, {})
        palette_info = MASTER_PALETTES.get(self.palette, {})

        vfx_lines = ""
        if self.vfx_pattern:
            pat = MASTER_VFX_PATTERNS.get(self.vfx_pattern, {})
            vfx_lines += f"  VFX PATTERN: {pat.get('label', self.vfx_pattern)} ({pat.get('kind', '?')})\n"
        if self.vfx_theme:
            thm = MASTER_VFX_THEMES.get(self.vfx_theme, {})
            vfx_lines += f"  VFX THEME: {thm.get('label', self.vfx_theme)}\n"
        if self.vfx_motion:
            mot = MASTER_VFX_MOTION.get(self.vfx_motion, {})
            vfx_lines += f"  VFX MOTION: {mot.get('label', self.vfx_motion)}\n"

        return (
            f"{'=' * 40}\n"
            f"  ISLAMIC ULTRA PACK v{VERSION}\n"
            f"{'=' * 40}\n\n"
            f"  MOOD: {self.mood.upper()}\n"
            f"  SEED: {self.seed}\n\n"
            f"  FONTS:\n"
            f"    Arabic: {self.arabic_font}\n"
            f"    Urdu:   {self.urdu_font}\n"
            f"    Title:  {self.title_font}\n\n"
            f"  EFFECT: {self.text_effect}\n"
            f"  STYLE:  {self.text_style}\n\n"
            f"  BACKGROUND: {self.background_category}\n"
            f"  PALETTE: {self.palette}\n"
            f"  CORNER: {self.corner_style}\n"
            f"  MOTION: {self.motion_kind}\n"
            f"  PARTICLES: {self.particle_density}\n"
            f"\n{vfx_lines}"
            f"{'=' * 40}"
        )


def generate_random_config(
    seed: str | None = None,
    favor: str | None = None,
    overrides: dict | None = None,
) -> UltraConfig:
    """
    Generate a fully random video configuration.

    Args:
        seed: Random seed (auto-generated if None)
        favor: Preferred mood (peaceful/powerful/mystical/energetic)
        overrides: Dict of specific values to override

    Returns:
        UltraConfig with all random selections
    """
    seed = seed or str(random.randint(100000, 999999))
    rng = random.Random(seed)

    # 1. Random mood (weighted)
    mood_names = list(EFFECT_MOODS.keys())
    mood_weights: list[float] = [float(EFFECT_MOODS[m]["weight"]) for m in mood_names]

    if favor and favor in EFFECT_MOODS:
        idx = mood_names.index(favor)
        mood_weights[idx] *= 2.0

    total_weight = sum(mood_weights)
    mood_weights = [w / total_weight for w in mood_weights]
    mood = rng.choices(mood_names, weights=mood_weights, k=1)[0]

    # 2. Random fonts (from combos or pure random)
    if rng.random() < 0.7:
        combo = rng.choice(FONT_COMBOS)
        arabic_font = combo["arabic"]
        urdu_font = combo["urdu"]
        title_font = combo["title"]
    else:
        font_keys = list(MASTER_FONTS.keys())
        arabic_font = rng.choice(font_keys)
        urdu_font = rng.choice(font_keys)
        title_font = rng.choice(font_keys)

    # 3. Random effect (mood-based)
    mood_effects: list[str] = EFFECT_MOODS[mood]["effects"]
    text_effect: str = rng.choice(mood_effects)

    # 4. Random style (mood-based)
    mood_styles = EFFECT_MOODS[mood]["text_styles"]
    text_style: str = rng.choice(mood_styles)

    # 5. Random background
    background_category = rng.choice(ISLAMIC_CATEGORIES)
    background_type = rng.choice(["auto", "video", "image", "auto"])

    # 6. Random visual options
    corner_style = rng.choice(CORNER_STYLES)
    particle_density = rng.randint(20, 60)
    motion_kind = rng.choice(MOTION_KINDS)
    highlight_style = rng.choice(HIGHLIGHT_BOX_STYLES)  # "" most of the time
    gradient_kind = rng.choice(BACKGROUND_GRADIENT_KINDS)  # "" most of the time

    # 7. Random palette
    palette = rng.choice(PALETTE_NAMES)

    config = UltraConfig(
        seed=seed,
        arabic_font=arabic_font,
        urdu_font=urdu_font,
        title_font=title_font,
        text_effect=text_effect,
        text_style=text_style,
        mood=mood,
        background_category=background_category,
        background_type=background_type,
        corner_style=corner_style,
        particle_density=particle_density,
        motion_kind=motion_kind,
        highlight_style=highlight_style,
        gradient_kind=gradient_kind,
        palette=palette,
    )

    # 8. Random VFX selections (if data available)
    if VFX_PATTERN_IDS:
        config.vfx_pattern = rng.choice(VFX_PATTERN_IDS)
    if VFX_PLUGIN_IDS:
        config.vfx_plugin = rng.choice(VFX_PLUGIN_IDS)
    if VFX_THEME_IDS:
        config.vfx_theme = rng.choice(VFX_THEME_IDS)
    if VFX_TYPOGRAPHY_IDS:
        config.vfx_typography = rng.choice(VFX_TYPOGRAPHY_IDS)
    if VFX_MOTION_IDS:
        config.vfx_motion = rng.choice(VFX_MOTION_IDS)
    if VFX_AUDIO_IDS:
        config.vfx_audio = rng.choice(VFX_AUDIO_IDS)

    # Apply overrides
    if overrides:
        for key, value in overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)

    return config


# ============================================================
# 7. HELPER FUNCTIONS
# ============================================================


def get_font_path(font_key: str) -> str | None:
    """Get full path to a font file."""
    font = MASTER_FONTS.get(font_key)
    if not font:
        return None

    from core.project_info import PROJECT

    return os.path.join(PROJECT.FONTS_DIR, font["file"])


def get_random_palette(dark_only: bool = False) -> dict:
    """Get a random palette (optionally dark only)."""
    if dark_only:
        names = DARK_PALETTES
    else:
        names = PALETTE_NAMES

    name = random.choice(names)
    return dict(MASTER_PALETTES[name])


def get_random_effect(mood: str | None = None) -> str:
    """Get a random effect, optionally mood-based."""
    if mood and mood in EFFECT_MOODS:
        return cast(str, random.choice(EFFECT_MOODS[mood]["effects"]))
    return random.choice(list(MASTER_EFFECTS.keys()))


def get_random_font_combo() -> dict:
    """Get a random font combination."""
    return random.choice(FONT_COMBOS)


def validate_category(category: str) -> bool:
    """Check if a background category is allowed."""
    cat_lower = category.lower()
    return not any(f in cat_lower for f in FORBIDDEN_CATEGORIES)


# ============================================================
# 8. MASTER VFX PATTERN SYSTEM (from custom_vfx.json)
# ============================================================

VFX_PATTERN_KINDS = (
    "girih-band",
    "girih-corners",
    "arabesque-strip",
    "arabesque-corners",
    "bead-band",
    "starfield-dots",
    "meander-band",
    "geometric-rosette",
)

VFX_TILE_ZONES = ("top", "bottom", "frame", "corners")

VFX_COLOR_TOKENS = ("accent", "glowColor", "particleColor", "solid")

VFX_STYLE_OVERRIDES = (
    "cornerInset",
    "cornerSize",
    "cornerOpacity",
    "frameEnabled",
    "frameOpacity1",
    "frameOpacity2",
    "ornamentScale",
    "ornamentSwayDeg",
    "raysOpacity",
    "orbsOpacity",
    "particlesScale",
    "grainOpacityDark",
    "grainOpacityPaper",
    "vignetteScale",
    "bokehCount",
    "bokehOpacity",
    "chromaticAberration",
    "shimmerStrength",
    "noiseVeilOpacity",
    "raysAngleDeg",
)


def _load_vfx_data():
    """Load VFX data from custom_vfx.json (single read, cached)."""
    vfx_path = os.path.join(os.path.dirname(__file__), "..", "data", "custom_vfx.json")
    vfx_path = os.path.normpath(vfx_path)
    if not os.path.exists(vfx_path):
        return {"patterns": [], "plugins": [], "themes": [], "typography": [], "motion": [], "audio": []}
    import json

    with open(vfx_path, "r", encoding="utf-8") as f:
        return json.load(f)


_vfx_data = _load_vfx_data()

# --- Patterns (164) ---
MASTER_VFX_PATTERNS: dict[str, Any] = {}
for _p in _vfx_data.get("patterns", []):
    pid = _p.get("id", _p.get("label", f"pattern-{len(MASTER_VFX_PATTERNS)}"))
    MASTER_VFX_PATTERNS[pid] = _p

VFX_PATTERN_IDS = list(MASTER_VFX_PATTERNS.keys())

# --- Plugins (69) ---
MASTER_VFX_PLUGINS: dict[str, Any] = {}
for _pl in _vfx_data.get("plugins", []):
    plid = _pl.get("id", f"plugin-{len(MASTER_VFX_PLUGINS)}")
    MASTER_VFX_PLUGINS[plid] = _pl

VFX_PLUGIN_IDS = list(MASTER_VFX_PLUGINS.keys())

# --- Themes (76) ---
VFX_THEME_DECORS = (
    "stars",
    "mosque",
    "sun",
    "paper",
    "pattern",
    "waves",
    "dunes",
    "royal",
    "lanterns",
    "festive",
    "qadr",
)

MASTER_VFX_THEMES: dict[str, Any] = {}
for _t in _vfx_data.get("themes", []):
    tid = _t.get("id", _t.get("label", f"theme-{len(MASTER_VFX_THEMES)}"))
    MASTER_VFX_THEMES[tid] = _t

VFX_THEME_IDS = list(MASTER_VFX_THEMES.keys())

# --- Typography (63) ---
VFX_TYPOGRAPHY_FAMILIES = ("amiri-quran", "noto-nastaliq-urdu", "scheherazade-new")

MASTER_VFX_TYPOGRAPHY: dict[str, Any] = {}
for _ty in _vfx_data.get("typography", []):
    tyid = _ty.get("id", _ty.get("label", f"typo-{len(MASTER_VFX_TYPOGRAPHY)}"))
    MASTER_VFX_TYPOGRAPHY[tyid] = _ty

VFX_TYPOGRAPHY_IDS = list(MASTER_VFX_TYPOGRAPHY.keys())

# --- Motion (63) ---
VFX_MOTION_CAMERAS = ("static", "zoomin", "panx", "kenburns", "driftbreathe")
VFX_MOTION_TEXT_FX = ("glide", "fade", "none", "typewriter", "popwave", "blurin")
VFX_MOTION_INTRO_FX = ("classic", "crescentfade", "patternwipe")

MASTER_VFX_MOTION: dict[str, Any] = {}
for _m in _vfx_data.get("motion", []):
    mid = _m.get("id", _m.get("label", f"motion-{len(MASTER_VFX_MOTION)}"))
    MASTER_VFX_MOTION[mid] = _m

VFX_MOTION_IDS = list(MASTER_VFX_MOTION.keys())

# --- Audio (4) ---
MASTER_VFX_AUDIO: dict[str, Any] = {}
for _a in _vfx_data.get("audio", []):
    aid = _a.get("id", _a.get("label", f"audio-{len(MASTER_VFX_AUDIO)}"))
    MASTER_VFX_AUDIO[aid] = _a

VFX_AUDIO_IDS = list(MASTER_VFX_AUDIO.keys())


# ============================================================
# 9. VFX HELPER FUNCTIONS
# ============================================================


def get_random_vfx_pattern(kind=None, zone=None):
    """Get a random VFX pattern, optionally filtered by kind or zone."""
    patterns = list(MASTER_VFX_PATTERNS.values())
    if kind:
        patterns = [p for p in patterns if p.get("kind") == kind]
    if zone:
        patterns = [p for p in patterns if zone in p.get("zones", [])]
    return random.choice(patterns) if patterns else None


def get_random_vfx_plugin():
    """Get a random VFX plugin."""
    if not MASTER_VFX_PLUGINS:
        return None
    return random.choice(list(MASTER_VFX_PLUGINS.values()))


def get_random_vfx_theme(affinity=None):
    """Get a random VFX theme, optionally filtered by affinity category."""
    themes = list(MASTER_VFX_THEMES.values())
    if affinity:
        matched = [t for t in themes if affinity in t.get("affinity", [])]
        if matched:
            themes = matched
    return random.choice(themes) if themes else None


def get_random_vfx_typography(family=None):
    """Get a random VFX typography preset, optionally filtered by family."""
    typos = list(MASTER_VFX_TYPOGRAPHY.values())
    if family:
        typos = [t for t in typos if t.get("fontFamily") == family]
    return random.choice(typos) if typos else None


def get_random_vfx_motion(camera=None):
    """Get a random VFX motion preset, optionally filtered by camera."""
    motions = list(MASTER_VFX_MOTION.values())
    if camera:
        motions = [m for m in motions if m.get("camera") == camera]
    return random.choice(motions) if motions else None


def get_random_vfx_audio():
    """Get a random VFX audio preset."""
    if not MASTER_VFX_AUDIO:
        return None
    return random.choice(list(MASTER_VFX_AUDIO.values()))


def get_vfx_stats():
    """Get summary stats of all VFX data."""
    return {
        "patterns": len(MASTER_VFX_PATTERNS),
        "plugins": len(MASTER_VFX_PLUGINS),
        "themes": len(MASTER_VFX_THEMES),
        "typography": len(MASTER_VFX_TYPOGRAPHY),
        "motion": len(MASTER_VFX_MOTION),
        "audio": len(MASTER_VFX_AUDIO),
        "total": (
            len(MASTER_VFX_PATTERNS)
            + len(MASTER_VFX_PLUGINS)
            + len(MASTER_VFX_THEMES)
            + len(MASTER_VFX_TYPOGRAPHY)
            + len(MASTER_VFX_MOTION)
            + len(MASTER_VFX_AUDIO)
        ),
    }
