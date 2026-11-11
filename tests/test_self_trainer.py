"""Tests for core.self_trainer (SelfTrainer AI learning system)."""

import json
import os

from core.self_trainer import SelfTrainer


def _trainer(tmp_path):
    t = SelfTrainer()
    t.learning_dir = str(tmp_path / "learned")
    t.feedback_file = os.path.join(t.learning_dir, "feedback.json")
    t.preferences_file = os.path.join(t.learning_dir, "preferences.json")
    return t


def test_init_creates_learning_dir(tmp_path):
    t = SelfTrainer()
    assert os.path.isdir(t.learning_dir)


def test_save_feedback_persists_and_updates_preferences(tmp_path):
    t = _trainer(tmp_path)
    t.save_feedback({"id": "v1", "effect": "neon_glow", "color": "gold", "duration": 5.0}, rating=5, comments="Great!")
    fb = json.load(open(t.feedback_file, encoding="utf-8"))
    assert len(fb) == 1
    assert fb[0]["rating"] == 5
    prefs = json.load(open(t.preferences_file, encoding="utf-8"))
    assert prefs["effect_ratings"]["neon_glow"] == [5]
    assert prefs["best_effect"] == "neon_glow"


def test_get_recommendation_empty_feedback(tmp_path):
    t = _trainer(tmp_path)
    rec = t.get_recommendation()
    assert isinstance(rec, dict)
    assert rec["total_feedback"] == 0
    assert "best_effect" in rec and "best_color" in rec


def test_calculate_avg_rating_zero_when_no_feedback(tmp_path):
    t = _trainer(tmp_path)
    assert t._calculate_avg_rating() == 0.0


def test_get_learning_stats(tmp_path):
    t = _trainer(tmp_path)
    stats = t.get_learning_stats()
    assert isinstance(stats, dict)
    assert stats["total_feedback"] == 0
    assert "average_rating" in stats
