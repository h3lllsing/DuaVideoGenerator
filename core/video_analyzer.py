"""
Video Analyzer Module
Scans sample videos to learn visual styles
"""

import json
import logging
import os
from collections import Counter
from typing import Any, cast

import cv2
import numpy as np

logger = logging.getLogger(__name__)

__all__ = ["VideoAnalyzer"]


class VideoAnalyzer:
    """
    Analyzes sample videos to learn visual styles.
    Extracts colors, text positions, effects, and timing patterns.
    """

    def __init__(self):
        """Initialize video analyzer."""
        self.samples_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
        self.learned_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "learned_styles"
        )

        # Create directories if not exist
        os.makedirs(self.samples_dir, exist_ok=True)
        os.makedirs(self.learned_dir, exist_ok=True)

    def scan_all_samples(self) -> list[dict]:
        """
        Scan all sample videos in the samples directory.

        Returns:
            List of learned styles from all samples
        """
        # Get all video files
        video_files = self._get_video_files()

        if not video_files:
            logger.info("No sample videos found!")
            logger.info("Place your videos in: %s", self.samples_dir)
            return []

        logger.info("Found %d sample videos:", len(video_files))
        for idx, video_file in enumerate(video_files, 1):
            logger.info("  %d. %s", idx, video_file)

        logger.info("Scanning videos...")

        learned_styles = []

        for idx, video_file in enumerate(video_files, 1):
            video_path = os.path.join(self.samples_dir, video_file)

            logger.info("[%d/%d] Scanning %s...", idx, len(video_files), video_file)

            style = self.analyze_video(video_path)

            if style:
                style["source_file"] = video_file
                learned_styles.append(style)

                # Save individual style
                style_name = os.path.splitext(video_file)[0]
                self.save_style(style_name, style)

                logger.info("  - Colors: %s", style["colors"]["primary"])
                logger.info("  - Effects: %s", style["effects"])
                logger.info("  - Timing: %.1fs", style["timing"]["duration"])
                logger.info("  - Style saved!")

        # Create master patterns
        if learned_styles:
            master_patterns = self.create_master_patterns(learned_styles)
            self.save_master_patterns(master_patterns)
            logger.info("Master patterns created!")
            logger.info("Total styles learned: %d", len(learned_styles))

        return learned_styles

    def analyze_video(self, video_path: str) -> dict[str, Any] | None:
        """
        Analyze a single video file.

        Args:
            video_path: Path to video file

        Returns:
            Learned style dictionary
        """
        # Check if file exists
        if not os.path.exists(video_path):
            logger.error("Video file not found: %s", video_path)
            return None

        # Open video
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            logger.error("Could not open video: %s", video_path)
            return None

        try:
            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            duration = frame_count / fps if fps > 0 else 0

            logger.info("  - Duration: %.1fs", duration)
            logger.info("  - Resolution: %dx%d", width, height)
            logger.info("  - FPS: %.1f", fps)

            # Extract frames (1 per second)
            frames = self._extract_frames(cap, fps, frame_count)
        finally:
            cap.release()

        if not frames:
            logger.error("Could not extract frames")
            return None

        # Analyze frames
        colors = self._analyze_colors(frames)
        text_positions = self._detect_text_positions(frames)
        effects = self._identify_effects(frames)
        timing = self._analyze_timing(frames, fps)

        # Create style dictionary
        style = {
            "colors": colors,
            "text_positions": text_positions,
            "effects": effects,
            "timing": timing,
            "resolution": {"width": width, "height": height},
            "fps": fps,
        }

        return style

    def _get_video_files(self) -> list[str]:
        """Get all video files from samples directory."""
        video_extensions = [".mp4", ".avi", ".mov", ".mkv", ".webm"]

        video_files = []

        if os.path.exists(self.samples_dir):
            for file in os.listdir(self.samples_dir):
                if any(file.lower().endswith(ext) for ext in video_extensions):
                    video_files.append(file)

        return sorted(video_files)

    def _extract_frames(self, cap, fps: float, frame_count: int) -> list[np.ndarray]:
        """
        Extract frames from video (1 per second).

        Args:
            cap: Video capture object
            fps: Frames per second
            frame_count: Total number of frames

        Returns:
            List of extracted frames
        """
        frames = []

        # Calculate frame interval (1 frame per second)
        frame_interval = int(fps) if fps > 0 else 30

        # Extract frames
        frame_idx = 0
        while True:
            ret, frame = cap.read()

            if not ret:
                break

            # Save frame at intervals
            if frame_idx % frame_interval == 0:
                frames.append(frame)

            frame_idx += 1

            # Limit to 30 frames (30 seconds max)
            if len(frames) >= 30:
                break

        return frames

    def _analyze_colors(self, frames: list[np.ndarray]) -> dict:
        """
        Analyze dominant colors in frames.

        Args:
            frames: List of video frames

        Returns:
            Color analysis dictionary
        """
        # Collect all pixels
        all_pixels = []

        for frame in frames:
            # Resize frame for faster processing
            small_frame = cv2.resize(frame, (100, 100))
            # Convert to RGB
            rgb_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            # Reshape to list of pixels
            pixels = rgb_frame.reshape(-1, 3)
            all_pixels.append(pixels)

        # Combine all pixels
        all_pixels = cast(Any, np.vstack(all_pixels))

        # Get dominant colors using k-means
        from sklearn.cluster import KMeans

        # Use 5 clusters for dominant colors
        n_colors = 5

        try:
            kmeans = KMeans(n_clusters=n_colors, random_state=42, n_init=10)
            kmeans.fit(all_pixels)

            # Get color counts
            colors = kmeans.cluster_centers_.astype(int)
            labels = kmeans.labels_
            label_counts = Counter(labels)

            # Sort by count
            sorted_colors = sorted(
                zip(colors, [label_counts[i] for i in range(n_colors)]), key=lambda x: x[1], reverse=True
            )

            # Extract primary and secondary colors
            primary_color = sorted_colors[0][0].tolist()
            secondary_color = sorted_colors[1][0].tolist() if len(sorted_colors) > 1 else [255, 255, 255]

            # Get background color (usually the most common)
            background_color = sorted_colors[-1][0].tolist()

            return {
                "primary": primary_color,
                "secondary": secondary_color,
                "background": background_color,
                "palette": [c[0].tolist() for c in sorted_colors],
            }

        except Exception as e:
            logger.warning("Color analysis failed: %s", e)
            # Return default colors
            return {
                "primary": [255, 215, 0],
                "secondary": [210, 210, 210],
                "background": [15, 20, 30],
                "palette": [[255, 215, 0], [210, 210, 210], [15, 20, 30]],
            }

    def _detect_text_positions(self, frames: list[np.ndarray]) -> dict:
        """
        Detect text positions in frames.

        Args:
            frames: List of video frames

        Returns:
            Text position dictionary
        """
        # Simple approach: detect bright regions (likely text)
        # This is a basic heuristic - could be improved with OCR

        positions = {"arabic": {"x": 0, "y": 300}, "urdu": {"x": 0, "y": 800}, "title": {"x": 0, "y": 50}}

        # Analyze first frame
        if frames:
            frame = frames[0]
            height, width = frame.shape[:2]

            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Threshold to find bright regions
            _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

            # Find contours
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # Get bounding boxes
            bboxes = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w > 50 and h > 20:  # Filter small contours
                    bboxes.append((x, y, w, h))

            # Sort by y position
            bboxes.sort(key=lambda b: b[1])

            # Assign positions based on vertical order
            if len(bboxes) >= 1:
                positions["title"] = {"x": bboxes[0][0], "y": bboxes[0][1]}
            if len(bboxes) >= 2:
                positions["arabic"] = {"x": bboxes[1][0], "y": bboxes[1][1]}
            if len(bboxes) >= 3:
                positions["urdu"] = {"x": bboxes[2][0], "y": bboxes[2][1]}

        return positions

    def _identify_effects(self, frames: list[np.ndarray]) -> list[str]:
        """
        Identify visual effects in frames.

        Args:
            frames: List of video frames

        Returns:
            List of identified effects
        """
        effects = []

        if len(frames) < 2:
            return ["fade_in"]  # Default effect

        # Check for fade-in (brightness change)
        first_frame = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
        mid_frame = cv2.cvtColor(frames[len(frames) // 2], cv2.COLOR_BGR2GRAY)

        first_brightness = np.mean(first_frame)
        mid_brightness = np.mean(mid_frame)

        # If brightness increases significantly, it's likely fade-in
        if mid_brightness > first_brightness * 1.5:
            effects.append("fade_in")

        # Check for motion (potential bounce or wave)
        diff = cv2.absdiff(frames[0], frames[-1])
        motion = np.mean(diff)

        if motion > 30:
            # High motion - could be bounce or wave
            effects.append("bounce")

        # Default effects if none detected
        if not effects:
            effects = ["fade_in", "glow"]

        return effects

    def _analyze_timing(self, frames: list[np.ndarray], fps: float) -> dict:
        """
        Analyze timing patterns.

        Args:
            frames: List of video frames
            fps: Frames per second

        Returns:
            Timing dictionary
        """
        # Calculate duration
        duration = len(frames) / fps if fps > 0 else 0

        # Detect text appearance timing
        text_appearances = []

        if len(frames) >= 3:
            # Check brightness changes between frames
            for i in range(1, len(frames)):
                prev_gray = cv2.cvtColor(frames[i - 1], cv2.COLOR_BGR2GRAY)
                curr_gray = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)

                diff = np.mean(np.abs(curr_gray.astype(float) - prev_gray.astype(float)))

                # If significant change, text likely appeared
                if diff > 20:
                    text_appearances.append(i / fps)

        # Calculate text delay (first text appearance)
        text_delay = text_appearances[0] if text_appearances else 1.0

        return {"duration": duration, "text_delay": text_delay, "fps": fps}

    def save_style(self, style_name: str, style: dict):
        """
        Save learned style to file.

        Args:
            style_name: Name of the style
            style: Style dictionary
        """
        file_path = os.path.join(self.learned_dir, f"{style_name}_style.json")

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(style, f, indent=2, ensure_ascii=False)

    def create_master_patterns(self, styles: list[dict]) -> dict:
        """
        Create master patterns from multiple styles.

        Args:
            styles: List of style dictionaries

        Returns:
            Master patterns dictionary
        """
        if not styles:
            return {}

        # Average colors
        all_primary = [s["colors"]["primary"] for s in styles]
        all_secondary = [s["colors"]["secondary"] for s in styles]
        all_background = [s["colors"]["background"] for s in styles]

        avg_primary = [int(np.mean([c[i] for c in all_primary])) for i in range(3)]
        avg_secondary = [int(np.mean([c[i] for c in all_secondary])) for i in range(3)]
        avg_background = [int(np.mean([c[i] for c in all_background])) for i in range(3)]

        # Collect all effects
        all_effects = []
        for s in styles:
            all_effects.extend(s["effects"])

        # Get most common effects
        effect_counts = Counter(all_effects)
        common_effects = [e for e, _ in effect_counts.most_common(3)]

        # Average timing
        durations = [s["timing"]["duration"] for s in styles]
        avg_duration = np.mean(durations) if durations else 7.0

        return {
            "colors": {"primary": avg_primary, "secondary": avg_secondary, "background": avg_background},
            "effects": common_effects,
            "timing": {"duration": avg_duration, "text_delay": 1.0},
            "total_samples": len(styles),
        }

    def save_master_patterns(self, patterns: dict):
        """Save master patterns to file."""
        file_path = os.path.join(self.learned_dir, "master_patterns.json")

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2, ensure_ascii=False)


# Test function
if __name__ == "__main__":
    print("Testing Video Analyzer...")

    analyzer = VideoAnalyzer()

    # Show samples directory
    print(f"\nSamples directory: {analyzer.samples_dir}")
    print(f"Learned styles directory: {analyzer.learned_dir}")

    # Check for videos
    video_files = analyzer._get_video_files()

    if video_files:
        print(f"\nFound {len(video_files)} videos:")
        for video in video_files:
            print(f"  - {video}")

        # Scan all videos
        print("\nScanning videos...")
        styles = analyzer.scan_all_samples()

        print("\nScanning complete!")
        print(f"Total styles learned: {len(styles)}")
    else:
        print("\nNo sample videos found!")
        print("Place your videos in the samples directory.")
        print(f"Directory: {analyzer.samples_dir}")

    print("\nVideo Analyzer Test Complete!")
