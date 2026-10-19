# ============================================================
# Dua Video Generator - Configuration File
# Project: H:\DuaVideoGenerator
# Status: PRODUCTION
# ============================================================

import os

# ============================================================
# CONFIG SCHEMA VERSIONING
# ============================================================
# Bump this when config structure changes incompatibly.
# Consumer code can check CONFIG_SCHEMA_VERSION to decide
# whether to migrate old data or reject it.
CONFIG_SCHEMA_VERSION = 2  # v2: added VFX weights, cross-fade, encrypted backups
CONFIG_VERSION_KEY = "config_schema_version"

# ============================================================
# BASE PATHS
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(BASE_DIR, "core")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")
BACKGROUNDS_DIR = os.path.join(ASSETS_DIR, "backgrounds")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")
MUSIC_DIR = os.path.join(ASSETS_DIR, "music")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TESTS_DIR = os.path.join(BASE_DIR, "tests")

# ============================================================
# VIDEO SETTINGS
# ============================================================
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30  # Smooth playback for YouTube Shorts (30fps standard)
BACKGROUND_PREFER_VIDEO = True  # stock video backgrounds over stills jab available hon

# VIDEO-002: Product duration specification for YouTube Shorts.
# 15-50 second window (Shorts supports up to 60s).
VIDEO_MIN_DURATION = 15  # seconds
VIDEO_MAX_DURATION = 50  # seconds
VIDEO_CODEC = "libx264"
VIDEO_QUALITY = 9  # imageio quality (1-10) — max quality

# FFmpeg encoding presets (Phase 2: Video Quality)
FFMPEG_CRF = 15  # Near-lossless (0=lossless, 15=visually transparent)
FFMPEG_PRESET = "slow"  # Better compression at same quality (5% smaller files)
FFMPEG_PROFILE = "high"  # Best compression efficiency (YouTube recommended)
FFMPEG_LEVEL = "4.1"  # Max for 1080p@60fps
FFMPEG_GOP = 60  # 2 seconds at 30fps — standard keyframe interval
FFMPEG_MOVFLAGS = "+faststart"  # moov atom at front for web streaming
FFMPEG_PIX_FMT = "yuv420p"  # Maximum compatibility

# Post-processing filters
FFMPEG_SHARPEN = True  # Unsharp mask for crisp text
FFMPEG_COLOR_GRADE = True  # Slight saturation boost
FFMPEG_LOUDNESS = True  # -14 LUFS (YouTube standard)

# Disk and file size limits
DISK_SPACE_MIN_MB = 500  # Minimum free disk space in MB
MAX_FILE_SIZE_MB = 100  # Maximum output file size in MB

# ============================================================
# AUDIO SETTINGS (edge-tts)
# ============================================================
# Arabic Voices (Microsoft)
VOICE_ARABIC_MALE = "ar-SA-HamedNeural"
VOICE_ARABIC_FEMALE = "ar-SA-ZariyahNeural"

# Urdu Voices (Microsoft)
VOICE_URDU_MALE = "ur-PK-AsadNeural"
VOICE_URDU_FEMALE = "ur-PK-UzmaNeural"

# Default Voices
DEFAULT_VOICE_ARABIC = VOICE_ARABIC_MALE
DEFAULT_VOICE_URDU = VOICE_URDU_MALE

# Audio Settings (AUDIO-001: 48 kHz lossless intermediates, AAC 192k final)
AUDIO_VOLUME = 1.0
AUDIO_BITRATE = "192k"
AUDIO_SAMPLE_RATE = 48000

# ============================================================
# TEXT SETTINGS
# ============================================================
# Arabic Font
ARABIC_FONT = os.path.join(FONTS_DIR, "NotoNaskhArabic-Regular.ttf")
ARABIC_FONT_BOLD = os.path.join(FONTS_DIR, "Amiri-Bold.ttf")

# Urdu Font (using Naskh for compatibility)
URDU_FONT = os.path.join(FONTS_DIR, "NotoNaskhArabic-Regular.ttf")

# Text Sizes
TITLE_SIZE = 36
ARABIC_SIZE = 48
URDU_SIZE = 42
LABEL_SIZE = 32
INFO_SIZE = 28
WATERMARK_SIZE = 20
EMOJI_SIZE = 50

# Text Colors (RGB)
TEXT_COLOR_WHITE = (255, 255, 255)
TEXT_COLOR_LIGHT = (220, 220, 220)
TEXT_COLOR_GOLD = (180, 140, 80)
TEXT_COLOR_DARK = (30, 30, 30)
TEXT_COLOR_GRAY = (100, 100, 100)

# Text Positions
TEXT_CENTER = "center"
TEXT_LEFT = "left"
TEXT_RIGHT = "right"

# ============================================================
# THEME SETTINGS
# ============================================================
THEMES = {
    "dark": {
        "name": "Dark Theme",
        "bg_color_top": (40, 12, 55),
        "bg_color_bottom": (55, 27, 75),
        "accent_color": (180, 140, 80),
        "text_color": (255, 255, 255),
        "label_color": (180, 140, 80),
    },
    "light": {
        "name": "Light Theme",
        "bg_color_top": (245, 245, 250),
        "bg_color_bottom": (230, 230, 240),
        "accent_color": (45, 90, 160),
        "text_color": (30, 30, 30),
        "label_color": (45, 90, 160),
    },
    "islamic": {
        "name": "Islamic Theme",
        "bg_color_top": (13, 76, 63),
        "bg_color_bottom": (20, 100, 80),
        "accent_color": (212, 175, 55),
        "text_color": (255, 255, 255),
        "label_color": (212, 175, 55),
    },
    "minimal": {
        "name": "Minimal Theme",
        "bg_color_top": (20, 20, 20),
        "bg_color_bottom": (30, 30, 30),
        "accent_color": (255, 255, 255),
        "text_color": (255, 255, 255),
        "label_color": (200, 200, 200),
    },
}

DEFAULT_THEME = "dark"

# ============================================================
# DUA DATABASE SETTINGS
# ============================================================
DUA_DATABASE = os.path.join(DATA_DIR, "duas.json")
CATEGORIES_DATABASE = os.path.join(DATA_DIR, "categories.json")

# Dua Categories
CATEGORIES = ["bathroom", "prayer", "sleep", "food", "travel", "morning", "evening", "general"]

# ============================================================
# WATERMARK SETTINGS
# ============================================================
WATERMARK = {
    "enabled": True,
    "text": "@bushranasir1075",
    "position": "bottom_left",
    "color": (100, 100, 100),
    "size": 20,
}

# ============================================================
# OUTPUT SETTINGS
# ============================================================
OUTPUT_FORMAT = "mp4"
OUTPUT_RESOLUTION = f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}"
OUTPUT_NAMING = "{category}_{dua_id}_{timestamp}.mp4"

# ============================================================
# LOGGING SETTINGS
# ============================================================
LOG_LEVEL = "INFO"
LOG_FILE = os.path.join(LOGS_DIR, "app.log")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# ============================================================
# PERFORMANCE SETTINGS
# ============================================================
MAX_WORKERS = 4  # Parallel processing threads
FRAME_BATCH_SIZE = 50  # Frames to process at once
TEMP_FILE_CLEANUP = True  # Auto-delete temp files

# ============================================================
# INTERNET SETTINGS (for TTS)
# ============================================================
TTS_ONLINE = True  # edge-tts requires internet
TTS_TIMEOUT = 30  # seconds
TTS_RETRY = 3  # retry attempts

# ============================================================
# FEATURE FLAGS
# ============================================================
FEATURES = {
    "background_music": False,  # User requested no music
    "thumbnail_generation": True,
    "batch_processing": True,
    "custom_templates": True,
    "multiple_voices": True,
}

# ============================================================
# VERSION INFO
# ============================================================
VERSION = "0.10.0"
APP_NAME = "Dua Video Generator"
APP_AUTHOR = "bushranasir1075"
