"""
Self-Trainer Module
AI learns from user feedback and sample videos
"""

import json
import logging
import os
from typing import Any, cast
from datetime import datetime

logger = logging.getLogger(__name__)

__all__ = ["SelfTrainer"]


class SelfTrainer:
    """
    AI Self-Learning System.
    Learns from user feedback and sample videos.
    """

    def __init__(self):
        """Initialize self-trainer."""
        self.learning_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "learned_styles"
        )

        self.feedback_file = os.path.join(self.learning_dir, "feedback.json")
        self.preferences_file = os.path.join(self.learning_dir, "preferences.json")

        # Create directory if not exists
        os.makedirs(self.learning_dir, exist_ok=True)

    def save_feedback(self, video_data: dict, rating: int, comments: str = ""):
        """
        Save user feedback for learning.

        Args:
            video_data: Video metadata
            rating: User rating (1-5 stars)
            comments: Optional comments
        """
        feedback = self._load_feedback()

        entry = {
            "timestamp": datetime.now().isoformat(),
            "video_id": video_data.get("id"),
            "effect": video_data.get("effect"),
            "color": video_data.get("color"),
            "duration": video_data.get("duration"),
            "rating": rating,
            "comments": comments,
        }

        feedback.append(entry)
        self._save_feedback(feedback)

        # Update preferences
        self._update_preferences(entry)

        logger.info("Feedback saved! Rating: %d/5", rating)

    def _update_preferences(self, entry: dict):
        """Update user preferences based on feedback."""
        prefs = self._load_preferences()

        effect = entry.get("effect")
        rating = entry.get("rating", 0)

        # Track effect ratings
        if "effect_ratings" not in prefs:
            prefs["effect_ratings"] = {}

        if effect not in prefs["effect_ratings"]:
            prefs["effect_ratings"][effect] = []

        prefs["effect_ratings"][effect].append(rating)

        # Calculate average rating per effect
        prefs["effect_averages"] = {}
        for eff, ratings in prefs["effect_ratings"].items():
            if ratings:
                prefs["effect_averages"][eff] = sum(ratings) / len(ratings)

        # Find best effect
        if prefs["effect_averages"]:
            prefs["best_effect"] = max(prefs["effect_averages"], key=prefs["effect_averages"].get)

        # Track color ratings
        color = entry.get("color")
        if color:
            if "color_ratings" not in prefs:
                prefs["color_ratings"] = {}

            if color not in prefs["color_ratings"]:
                prefs["color_ratings"][color] = []

            prefs["color_ratings"][color].append(rating)

        # Calculate average rating per color
        prefs["color_averages"] = {}
        for col, ratings in prefs.get("color_ratings", {}).items():
            if ratings:
                prefs["color_averages"][col] = sum(ratings) / len(ratings)

        # Find best color
        if prefs.get("color_averages"):
            prefs["best_color"] = max(prefs["color_averages"], key=prefs["color_averages"].get)

        self._save_preferences(prefs)

    def get_recommendation(self) -> dict:
        """
        Get AI recommendation based on learning.

        Returns:
            Recommendation dictionary
        """
        prefs = self._load_preferences()
        feedback = self._load_feedback()

        # Get master patterns from video analysis
        master_patterns = self._load_master_patterns()

        recommendation = {
            "best_effect": prefs.get("best_effect", "neon_glow"),
            "best_color": prefs.get("best_color", "gold"),
            "effect_averages": prefs.get("effect_averages", {}),
            "color_averages": prefs.get("color_averages", {}),
            "total_feedback": len(feedback),
            "average_rating": self._calculate_avg_rating(),
        }

        # Merge with video analysis patterns
        if master_patterns:
            recommendation["learned_colors"] = master_patterns.get("colors", {})
            recommendation["learned_effects"] = master_patterns.get("effects", [])
            recommendation["learned_timing"] = master_patterns.get("timing", {})

        return recommendation

    def _calculate_avg_rating(self) -> float:
        """Calculate overall average rating."""
        feedback = self._load_feedback()

        if not feedback:
            return 0.0

        ratings = [f.get("rating", 0) for f in feedback]
        return sum(ratings) / len(ratings) if ratings else 0.0

    def _load_feedback(self) -> list[Any]:
        """Load feedback from file."""
        if not os.path.exists(self.feedback_file):
            return []

        try:
            with open(self.feedback_file, encoding="utf-8") as f:
                return cast(list[Any], json.load(f))
        except Exception:
            return []

    def _save_feedback(self, feedback: list):
        """Save feedback to file with atomic write."""
        import tempfile

        dir_name = os.path.dirname(self.feedback_file)
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(feedback, f, indent=2, ensure_ascii=False)
            import shutil

            shutil.move(tmp_path, self.feedback_file)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def _load_preferences(self) -> dict[str, Any]:
        """Load preferences from file."""
        if not os.path.exists(self.preferences_file):
            return {}

        try:
            with open(self.preferences_file, encoding="utf-8") as f:
                return cast(dict[str, Any], json.load(f))
        except Exception:
            return {}

    def _save_preferences(self, prefs: dict):
        """Save preferences to file."""
        with open(self.preferences_file, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2, ensure_ascii=False)

    def _load_master_patterns(self) -> dict[str, Any] | None:
        """Load master patterns from video analysis."""
        master_patterns_file = os.path.join(self.learning_dir, "master_patterns.json")

        if not os.path.exists(master_patterns_file):
            return None

        try:
            with open(master_patterns_file, encoding="utf-8") as f:
                return cast(dict[str, Any], json.load(f))
        except Exception:
            return None

    def get_learning_stats(self) -> dict:
        """Get learning statistics."""
        feedback = self._load_feedback()
        prefs = self._load_preferences()

        return {
            "total_feedback": len(feedback),
            "average_rating": self._calculate_avg_rating(),
            "best_effect": prefs.get("best_effect", "N/A"),
            "best_color": prefs.get("best_color", "N/A"),
            "effect_averages": prefs.get("effect_averages", {}),
            "color_averages": prefs.get("color_averages", {}),
        }


# Test function
if __name__ == "__main__":
    print("Testing Self-Trainer...")

    trainer = SelfTrainer()

    # Test feedback
    test_video_data = {"id": "test_video_001", "effect": "neon_glow", "color": "gold", "duration": 7.5}

    # Save feedback
    trainer.save_feedback(test_video_data, rating=5, comments="Great video!")

    # Get recommendation
    recommendation = trainer.get_recommendation()
    print(f"\nRecommendation: {recommendation}")

    # Get stats
    stats = trainer.get_learning_stats()
    print(f"\nLearning Stats: {stats}")

    print("\nSelf-Trainer Test Complete!")
