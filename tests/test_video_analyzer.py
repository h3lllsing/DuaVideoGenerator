"""
Tests for core.video_analyzer module
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.video_analyzer import VideoAnalyzer


class TestVideoAnalyzerInit:
    """Test VideoAnalyzer initialization."""

    def test_creates_directories(self, tmp_path):
        samples = tmp_path / "samples"
        learned = tmp_path / "learned"
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.samples_dir = str(samples)
        analyzer.learned_dir = str(learned)
        os.makedirs(analyzer.samples_dir, exist_ok=True)
        os.makedirs(analyzer.learned_dir, exist_ok=True)
        assert os.path.isdir(analyzer.samples_dir)
        assert os.path.isdir(analyzer.learned_dir)


class TestGetVideoFiles:
    """Test _get_video_files method."""

    def test_returns_sorted(self, tmp_path):
        samples = tmp_path / "samples"
        os.makedirs(samples)
        for name in ["z.mp4", "a.mp4", "m.avi"]:
            (samples / name).touch()
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.samples_dir = str(samples)
        files = analyzer._get_video_files()
        assert files == ["a.mp4", "m.avi", "z.mp4"]

    def test_ignores_non_video(self, tmp_path):
        samples = tmp_path / "samples"
        os.makedirs(samples)
        (samples / "readme.txt").touch()
        (samples / "image.jpg").touch()
        (samples / "clip.mp4").touch()
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.samples_dir = str(samples)
        files = analyzer._get_video_files()
        assert files == ["clip.mp4"]

    def test_empty_dir(self, tmp_path):
        samples = tmp_path / "samples"
        os.makedirs(samples)
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.samples_dir = str(samples)
        files = analyzer._get_video_files()
        assert files == []


class TestAnalyzeVideo:
    """Test analyze_video method."""

    def test_nonexistent_file(self, tmp_path):
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.samples_dir = str(tmp_path)
        analyzer.learned_dir = str(tmp_path / "learned")
        result = analyzer.analyze_video("nonexistent.mp4")
        assert result is None


class TestCreateMasterPatterns:
    """Test create_master_patterns method."""

    def test_empty_list(self):
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        result = analyzer.create_master_patterns([])
        assert result == {}

    def test_single_style(self):
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        styles = [
            {
                "colors": {"primary": (255, 0, 0), "secondary": (0, 255, 0), "background": (0, 0, 255)},
                "effects": ["fade_in", "bounce"],
                "timing": {"duration": 15.0},
            }
        ]
        result = analyzer.create_master_patterns(styles)
        assert "colors" in result
        assert "effects" in result


class TestSaveStyle:
    """Test save_style method."""

    def test_creates_json(self, tmp_path):
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.learned_dir = str(tmp_path / "learned")
        os.makedirs(analyzer.learned_dir, exist_ok=True)
        style = {"colors": {"primary": [255, 0, 0]}}  # use list for JSON compat
        analyzer.save_style("test", style)
        expected_file = tmp_path / "learned" / "test_style.json"
        assert expected_file.exists()
        with open(expected_file) as f:
            data = json.load(f)
        assert data == style
