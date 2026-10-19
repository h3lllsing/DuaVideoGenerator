"""
VIDEO-001 regression tests: generated videos must be exactly 1080x1920.
"""

import os
import shutil
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
from PIL import Image

from core.quality_checker import QualityChecker
from core.video_builder import VideoBuilder


class TestVideoResolution:
    """Regression tests for the 1088x1920 macro-block upscale bug (VIDEO-001)"""

    def setup_method(self):
        self.tmp_dir = os.path.join(os.path.dirname(__file__), "_video_tmp")
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)
        os.makedirs(self.tmp_dir)
        self.builder = VideoBuilder(fps=120, resolution=(1080, 1920))
        self.frame = Image.new("RGB", (1080, 1920), (20, 25, 35))

    def teardown_method(self):
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)

    def test_output_is_exact_1080x1920(self):
        frames = [self.frame] * 120  # 1 second at 120fps
        output_path = os.path.join(self.tmp_dir, "test_1080.mp4")

        assert self.builder.build_video(frames, output_path) is True
        assert os.path.exists(output_path)

        cap = cv2.VideoCapture(output_path)
        assert cap.isOpened()
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        ret, _ = cap.read()
        cap.release()

        assert ret is True, "Video must be decodable/playable"
        assert width == 1080, f"Expected width 1080, got {width}"
        assert height == 1920, f"Expected height 1920, got {height}"
        assert fps == 120, f"Expected fps 120, got {fps}"
        assert frame_count == 120, f"Expected 120 frames, got {frame_count}"

    def test_quality_checker_resolution_valid(self):
        frames = [self.frame] * 120
        output_path = os.path.join(self.tmp_dir, "test_1080_qc.mp4")

        assert self.builder.build_video(frames, output_path) is True

        results = QualityChecker().check_video(output_path)
        info = results["video_info"]
        assert info["width"] == 1080
        assert info["height"] == 1920
        assert "Resolution: 1080x1920 (OK)" in results["passed"]
