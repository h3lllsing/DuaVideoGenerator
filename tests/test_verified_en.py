"""Tests for verified_en reference parsing + the upload EN-caption gate.

These are pure-logic tests (no network): reference strings from duas.json must
map to the correct Quran/hadith source, and English subtitles may never be
attached to YouTube unless the review queue has approved them.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "remotion", "scripts")
sys.path.insert(0, SCRIPTS)

import verified_en as ve  # noqa: E402


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("Surah Al-Baqarah 2:255", [2, 255, 255]),
        ("Al-A'raf 7:126", [7, 126, 126]),
        ("Surah Taha 20:25-26", [20, 25, 26]),
        ("Surah Ibrahim 40", [14, 40, 40]),
        ("Quran Surah Al-Asr 103", [103, None, None]),  # whole surah
    ],
)
def test_quran_reference_parsing(ref, expected):
    assert ve.parse_reference(ref)["quran"] == expected


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("Sahih Muslim 476", [["sahih muslim", 476]]),
        ("Sunan an-Nasa'i 896", [["sunan an-nasa'i", 896]]),
        ("Sahih Bukhari 1234; Sahih Muslim 567", [["sahih bukhari", 1234], ["sahih muslim", 567]]),
    ],
)
def test_hadith_reference_parsing(ref, expected):
    assert ve.parse_reference(ref)["hadith"] == expected


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "Eid Aur Ayyam E Hajj Ki Sunnat",
        "\u06a9\u0648\u0626\u06cc \u0645\u0633\u062a\u0646\u062f \u062d\u062f\u06cc\u062b \u0646\u06c1\u06cc\u06ba",
    ],
)
def test_non_source_reference_is_empty(ref):
    parsed = ve.parse_reference(ref)
    assert parsed["quran"] is None
    assert parsed["hadith"] is None


def test_duas_reference_mapping_snapshot():
    """duas.json refs partition exactly into quran / hadith / other."""
    counts = {"quran": 0, "hadith": 0, "other": 0}
    for dua in ve.load_duas():
        parsed = ve.parse_reference(dua.get("reference") or "")
        if parsed["quran"]:
            counts["quran"] += 1
        elif parsed["hadith"]:
            counts["hadith"] += 1
        else:
            counts["other"] += 1
    # Snapshot numbers track catalog growth (258 duas now); the real
    # invariant is the EXACT partition: every dua lands in one bucket.
    assert counts == {"quran": 82, "hadith": 165, "other": 11}
    assert sum(counts.values()) == len(ve.load_duas())


class TestCaptionGate:
    """upload.en_caption_allowed must default-closed and open only on approve."""

    @pytest.fixture
    def upload(self, tmp_path, monkeypatch):
        import upload

        review = tmp_path / "en_review.json"
        monkeypatch.setattr(upload, "EN_REVIEW_PATH", str(review))
        return upload, review

    def test_missing_file_denies(self, upload):
        mod, _ = upload
        assert mod.en_caption_allowed("dua_a") is False

    def test_pending_denies(self, upload):
        mod, review = upload
        review.write_text(json.dumps({"dua_a": {"status": "pending"}}), encoding="utf-8")
        assert mod.en_caption_allowed("dua_a") is False

    def test_rejected_denies(self, upload):
        mod, review = upload
        review.write_text(json.dumps({"dua_a": {"status": "rejected"}}), encoding="utf-8")
        assert mod.en_caption_allowed("dua_a") is False

    def test_unknown_dua_denies(self, upload):
        mod, review = upload
        review.write_text(json.dumps({"dua_a": {"status": "approved"}}), encoding="utf-8")
        assert mod.en_caption_allowed("dua_b") is False

    def test_approved_allows(self, upload):
        mod, review = upload
        review.write_text(json.dumps({"dua_a": {"status": "approved"}}), encoding="utf-8")
        assert mod.en_caption_allowed("dua_a") is True

    def test_corrupt_file_denies(self, upload):
        mod, review = upload
        review.write_text("{not json", encoding="utf-8")
        assert mod.en_caption_allowed("dua_a") is False


def test_ai_cooldown_keyed_by_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(ve, "COOLDOWN_PATH", str(tmp_path / "cooldown.json"))
    ref = "Sahih Muslim 476"
    assert ve.ai_cooldown_active(ref) is False
    ve._record_ai_failure(ref)
    assert ve.ai_cooldown_active(ref) is True
    # an unrelated reference is NOT cooled down
    assert ve.ai_cooldown_active("Sahih Bukhari 1420") is False
    ve._clear_ai_failure(ref)
    assert ve.ai_cooldown_active(ref) is False


def test_ai_cooldown_survives_reference_spelling(tmp_path, monkeypatch):
    """Same hadith in different casing/punctation shares one cooldown record."""
    monkeypatch.setattr(ve, "COOLDOWN_PATH", str(tmp_path / "cooldown.json"))
    ve._record_ai_failure("Sunan an-Nasa\u02bei 896")
    assert ve.ai_cooldown_active("Sunan an-Nasa'i 896") is True


def test_ai_cooldown_window_is_configurable(tmp_path, monkeypatch):
    monkeypatch.setattr(ve, "COOLDOWN_PATH", str(tmp_path / "cooldown.json"))
    ref = "Sahih Muslim 476"
    ve._record_ai_failure(ref, hours=1)
    # stored window recorded, active under the default 6h check too
    store = json.loads((tmp_path / "cooldown.json").read_text(encoding="utf-8"))
    assert store[ve._cooldown_key(ref)]["window_hours"] == 1
    assert ve.ai_cooldown_active(ref) is True
    # a zero/lapsed window means the attempt is allowed again immediately
    assert ve.ai_cooldown_active(ref, hours=0) is False


def test_ai_cooldown_custom_module_default(tmp_path, monkeypatch):
    """Module-level window constant drives the check when no hours override."""
    monkeypatch.setattr(ve, "COOLDOWN_PATH", str(tmp_path / "cooldown.json"))
    monkeypatch.setattr(ve, "HADITH_AI_COOLDOWN_HOURS", 2)
    ref = "Sahih Muslim 476"
    ve._record_ai_failure(ref)
    assert ve.ai_cooldown_active(ref) is True
    assert ve.ai_cooldown_active(ref, hours=48) is True
    assert ve.ai_cooldown_active(ref, hours=0) is False
