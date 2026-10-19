import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ["ProjectInfo"]


@dataclass
class ProjectInfo:
    """
    Centralized metadata and configuration for the Dua Video Generator.
    Loads settings from config.py if available, otherwise uses defaults.
    """

    # Core Metadata
    PROJECT_NAME: str = "Dua Video Generator"
    VERSION: str = "0.10.0"
    CHANNEL_NAME: str = "@bushranasir1075"
    AUTHOR: str = "MASOOD NASIR"

    # Video Standards
    VIDEO_WIDTH: int = 1080
    VIDEO_HEIGHT: int = 1920
    FPS: int = 30

    # Folder Paths (Relative to project root)
    PROJECT_ROOT: str = ""
    OUTPUT_DIR: str = "output"
    TEMP_DIR: str = "temp"
    ASSETS_DIR: str = "assets"
    DATA_DIR: str = "data"
    FONTS_DIR: str = "assets/fonts"
    LOGS_DIR: str = "logs"

    # TTS Voices
    VOICE_AR: str = "ar-SA-HamedNeural"
    VOICE_UR: str = "ur-PK-AsadNeural"

    def __post_init__(self):
        """Auto-calculate absolute paths relative to project root."""
        # F-22: single source of truth = root config.py (agar importable ho).
        # Aaj dono layers ke values same hain to behavior change zero hai,
        # lekin future config.py change ab PROJECT.* me bhi propagate hoga.
        try:
            import config as _cfg

            if self.PROJECT_NAME == ProjectInfo.PROJECT_NAME:
                self.PROJECT_NAME = getattr(_cfg, "APP_NAME", self.PROJECT_NAME)
            if self.VERSION == ProjectInfo.VERSION:
                self.VERSION = str(getattr(_cfg, "VERSION", self.VERSION))
            if self.VIDEO_WIDTH == ProjectInfo.VIDEO_WIDTH:
                self.VIDEO_WIDTH = int(getattr(_cfg, "VIDEO_WIDTH", self.VIDEO_WIDTH))
            if self.VIDEO_HEIGHT == ProjectInfo.VIDEO_HEIGHT:
                self.VIDEO_HEIGHT = int(getattr(_cfg, "VIDEO_HEIGHT", self.VIDEO_HEIGHT))
            if self.FPS == ProjectInfo.FPS:
                self.FPS = int(getattr(_cfg, "VIDEO_FPS", self.FPS))
            if self.VOICE_AR == ProjectInfo.VOICE_AR:
                self.VOICE_AR = str(getattr(_cfg, "DEFAULT_VOICE_ARABIC", self.VOICE_AR))
            if self.VOICE_UR == ProjectInfo.VOICE_UR:
                self.VOICE_UR = str(getattr(_cfg, "DEFAULT_VOICE_URDU", self.VOICE_UR))
            logger.debug(
                "project_info: config.py se sync ho gaya (%sx%s@%s)",
                self.VIDEO_WIDTH,
                self.VIDEO_HEIGHT,
                self.FPS,
            )
        except Exception:
            logger.debug("project_info: config.py import nahi hua, defaults istemal")

        if not self.PROJECT_ROOT:
            # Get the directory where this file is located (core folder), then go up one level
            self.PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Convert relative paths to absolute
        self.OUTPUT_DIR = self._abs_path(self.OUTPUT_DIR)
        self.TEMP_DIR = self._abs_path(self.TEMP_DIR)
        self.ASSETS_DIR = self._abs_path(self.ASSETS_DIR)
        self.DATA_DIR = self._abs_path(self.DATA_DIR)
        self.FONTS_DIR = self._abs_path(self.FONTS_DIR)
        self.LOGS_DIR = self._abs_path(self.LOGS_DIR)

        # Create all directories if they don't exist
        for dir_path in [self.OUTPUT_DIR, self.TEMP_DIR, self.ASSETS_DIR, self.DATA_DIR, self.FONTS_DIR, self.LOGS_DIR]:
            os.makedirs(dir_path, exist_ok=True)

    def _abs_path(self, relative_path: str) -> str:
        """Convert a relative path to absolute based on PROJECT_ROOT."""
        if os.path.isabs(relative_path):
            return relative_path
        return os.path.join(self.PROJECT_ROOT, relative_path)

    def get_summary(self) -> str:
        """Return a human-readable summary of the project settings."""
        lines = [
            "=" * 50,
            f"Project   : {self.PROJECT_NAME}",
            f"Version   : {self.VERSION}",
            f"Channel   : {self.CHANNEL_NAME}",
            f"Author    : {self.AUTHOR}",
            f"Video     : {self.VIDEO_WIDTH}x{self.VIDEO_HEIGHT} @ {self.FPS}fps",
            f"Voices    : Arabic({self.VOICE_AR}), Urdu({self.VOICE_UR})",
            f"Root      : {self.PROJECT_ROOT}",
            f"Output    : {self.OUTPUT_DIR}",
            f"Temp      : {self.TEMP_DIR}",
            "=" * 50,
        ]
        return "\n".join(lines)


# Create a singleton instance for easy import
PROJECT = ProjectInfo()
