"""
Quality Checker Module
Video quality validation for YouTube Shorts
"""

import logging
import os
from typing import Any

import cv2

logger = logging.getLogger(__name__)

try:
    import config as _config
except Exception:
    logger.debug("config not available for quality checker")
    _config = None  # type: ignore[assignment]

__all__ = ["QualityChecker"]


class QualityChecker:
    """
    Video Quality Validation.
    Checks duration, resolution, FPS, and file size.
    """

    # Float tolerance for boundary checks (e.g. 14.99 must fail, 15.00 must pass)
    EPS = 1e-6
    # FPS is written as exactly 30 by the pipeline; this only absorbs binary
    # float representation noise (79.98/80.04 from other tools still FAIL).
    FPS_EPS = 1e-4

    def __init__(self):
        """Initialize quality checker."""
        # VIDEO-002: 15-50 second product window, exactly 30 FPS.
        # Values come from config.py (single source of truth) with safe fallbacks.
        self.min_duration = float(getattr(_config, "VIDEO_MIN_DURATION", 15))
        self.max_duration = float(getattr(_config, "VIDEO_MAX_DURATION", 50))
        self.required_fps = float(getattr(_config, "VIDEO_FPS", 30))
        self.required_width = int(getattr(_config, "VIDEO_WIDTH", 1080))
        self.required_height = int(getattr(_config, "VIDEO_HEIGHT", 1920))
        self.max_file_size_mb = int(getattr(_config, "MAX_FILE_SIZE_MB", 100))

    def check_video(self, video_path: str) -> dict:
        """
        Check video quality.
        
        Args:
            video_path: Path to video file
            
        Returns:
            Quality check results
        """
        results: dict[str, Any] = {
            "valid": True,
            "issues": [],
            "passed": [],
            "video_info": {}
        }

        # Check if file exists
        if not os.path.exists(video_path):
            results["valid"] = False
            results["issues"].append(f"File not found: {video_path}")
            return results

        # Get video info
        cap = None
        try:
            cap = cv2.VideoCapture(video_path)

            if not cap.isOpened():
                results["valid"] = False
                results["issues"].append("Could not open video file")
                return results

            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            duration = frame_count / fps if fps > 0 else 0
            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)

            # Store video info
            results["video_info"] = {
                "duration": duration,
                "width": width,
                "height": height,
                "fps": fps,
                "file_size_mb": file_size_mb
            }

            # Check duration (VIDEO-002: 15-50s, boundary-inclusive)
            if self.min_duration - self.EPS <= duration <= self.max_duration + self.EPS:
                results["passed"].append(f"Duration: {duration:.1f}s (OK)")
            else:
                results["valid"] = False
                results["issues"].append(
                    f"Duration: {duration:.1f}s (FAIL \u2014 expected "
                    f"{int(self.min_duration)}-{int(self.max_duration)}s)"
                )

            # Check resolution
            if width == self.required_width and height == self.required_height:
                results["passed"].append(f"Resolution: {width}x{height} (OK)")
            else:
                results["valid"] = False
                results["issues"].append(
                    f"Resolution: {width}x{height} (must be {self.required_width}x{self.required_height})"
                )

            # Check file size
            if file_size_mb <= self.max_file_size_mb:
                results["passed"].append(f"File size: {file_size_mb:.1f}MB (OK)")
            else:
                results["valid"] = False
                results["issues"].append(
                    f"File size: {file_size_mb:.1f}MB (must be under {self.max_file_size_mb}MB)"
                )

            # Check FPS (VIDEO-002: exactly 30, container-rounding tolerant)
            if abs(fps - self.required_fps) <= self.FPS_EPS:
                results["passed"].append(f"FPS: {fps:.1f} (OK)")
            else:
                results["valid"] = False
                results["issues"].append(
                    f"FPS: {fps:.1f} (FAIL \u2014 expected exactly {self.required_fps:.1f})"
                )

        except Exception as e:
            results["valid"] = False
            results["issues"].append(f"Error checking video: {str(e)}")
        finally:
            if cap is not None:
                cap.release()

        return results

    def validate_duration(self, duration: float) -> bool:
        """
        Validate video duration (VIDEO-002: 15-50s, boundary-inclusive).

        Args:
            duration: Duration in seconds

        Returns:
            True if valid
        """
        return self.min_duration - self.EPS <= duration <= self.max_duration + self.EPS

    def validate_fps(self, fps: float) -> bool:
        """
        Validate video FPS is exactly 30 (VIDEO-002).

        Args:
            fps: Frames per second

        Returns:
            True if valid
        """
        return abs(fps - self.required_fps) <= self.FPS_EPS

    def validate_resolution(self, width: int, height: int) -> bool:
        """
        Validate video resolution.
        
        Args:
            width: Video width
            height: Video height
            
        Returns:
            True if valid
        """
        return width == self.required_width and height == self.required_height


# Test function
if __name__ == "__main__":
    print("Testing Quality Checker...")

    checker = QualityChecker()

    # Test validation functions
    print(f"\nDuration 7.0s valid: {checker.validate_duration(7.0)}")
    print(f"Duration 20.0s valid: {checker.validate_duration(20.0)}")
    print(f"Duration 30.0s valid: {checker.validate_duration(30.0)}")

    print(f"\nResolution 1080x1920 valid: {checker.validate_resolution(1080, 1920)}")
    print(f"Resolution 720x1280 valid: {checker.validate_resolution(720, 1280)}")

    print("\nQuality Checker Test Complete!")
