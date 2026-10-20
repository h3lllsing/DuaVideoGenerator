"""
5D-001 tests: MetadataGenerator - title, description, tags, hashtags, save/load, edge cases.

Run with: python -m pytest tests/test_metadata_generator.py -v
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.metadata_generator import MetadataGenerator


# Phase 1: Instantiation
class TestInstantiation:
    def test_creates_instance(self):
        g = MetadataGenerator()
        assert g is not None

    def test_has_titles_dict(self):
        g = MetadataGenerator()
        assert isinstance(g.titles, dict)
        assert len(g.titles) == 8

    def test_has_category_tags_dict(self):
        g = MetadataGenerator()
        assert isinstance(g.category_tags, dict)
        assert len(g.category_tags) == 8

    def test_has_base_tags_list(self):
        g = MetadataGenerator()
        assert isinstance(g.base_tags, list)
        assert len(g.base_tags) == 8

    def test_all_categories_match(self):
        g = MetadataGenerator()
        assert set(g.titles.keys()) == set(g.category_tags.keys())

    def test_base_tags_contain_islamic_dua(self):
        g = MetadataGenerator()
        assert "Islamic Dua" in g.base_tags

    def test_multiple_instances_independent(self):
        g1 = MetadataGenerator()
        g2 = MetadataGenerator()
        g1.base_tags.append("TEST_POLLUTION")
        assert "TEST_POLLUTION" not in g2.base_tags


# Phase 2: Title Generation
class TestGenerateTitle:
    def test_bathroom(self):
        g = MetadataGenerator()
        assert g.generate_title("bathroom") == "Bathroom Exit Dua | Islamic Prayer"

    def test_sleep(self):
        g = MetadataGenerator()
        assert g.generate_title("sleep") == "Sleep Dua | Bedtime Prayer"

    def test_food(self):
        g = MetadataGenerator()
        assert g.generate_title("food") == "Food Dua | Eating Prayer"

    def test_travel(self):
        g = MetadataGenerator()
        assert g.generate_title("travel") == "Travel Dua | Journey Prayer"

    def test_morning(self):
        g = MetadataGenerator()
        assert g.generate_title("morning") == "Morning Dua | Daily Prayer"

    def test_evening(self):
        g = MetadataGenerator()
        assert g.generate_title("evening") == "Evening Dua | Daily Prayer"

    def test_prayer(self):
        g = MetadataGenerator()
        assert g.generate_title("prayer") == "Prayer Dua | Salah Prayer"

    def test_general(self):
        g = MetadataGenerator()
        assert g.generate_title("general") == "Islamic Dua | Daily Prayer"

    def test_unknown_category_fallback(self):
        g = MetadataGenerator()
        assert g.generate_title("xyz_unknown") == "Islamic Dua | Prayer"

    def test_returns_string(self):
        g = MetadataGenerator()
        assert isinstance(g.generate_title("food"), str)

    def test_all_titles_contain_pipe(self):
        g = MetadataGenerator()
        for cat in g.titles:
            assert "|" in g.generate_title(cat)


# Phase 3: Description Generation
class TestGenerateDescription:
    def test_contains_arabic_text(self):
        g = MetadataGenerator()
        desc = g.generate_description("arabic_text", "urdu", "food")
        assert "arabic_text" in desc

    def test_contains_urdu_text(self):
        g = MetadataGenerator()
        desc = g.generate_description("a", "urdu_text", "food")
        assert "urdu_text" in desc

    def test_contains_category_title(self):
        g = MetadataGenerator()
        desc = g.generate_description("a", "u", "food")
        assert "Food" in desc

    def test_contains_subscribe(self):
        g = MetadataGenerator()
        desc = g.generate_description("a", "u", "food")
        assert "Subscribe" in desc

    def test_contains_like_share(self):
        g = MetadataGenerator()
        desc = g.generate_description("a", "u", "food")
        assert "Like & Share" in desc

    def test_contains_base_hashtags(self):
        g = MetadataGenerator()
        desc = g.generate_description("a", "u", "food")
        assert "#IslamicDua" in desc
        assert "#Muslim" in desc

    def test_returns_string(self):
        g = MetadataGenerator()
        assert isinstance(g.generate_description("a", "u", "food"), str)

    def test_description_is_stripped(self):
        g = MetadataGenerator()
        desc = g.generate_description("a", "u", "food")
        assert desc == desc.strip()

    def test_empty_arabic(self):
        g = MetadataGenerator()
        desc = g.generate_description("", "urdu", "food")
        assert "Arabic: " in desc
        assert "urdu" in desc

    def test_empty_urdu(self):
        g = MetadataGenerator()
        desc = g.generate_description("arabic", "", "food")
        assert "Urdu: " in desc
        assert "arabic" in desc

    def test_empty_category(self):
        g = MetadataGenerator()
        desc = g.generate_description("a", "u", "")
        assert "Category: " in desc

    def test_category_is_titlecased(self):
        g = MetadataGenerator()
        desc = g.generate_description("a", "u", "morning")
        assert "Morning" in desc

    def test_all_categories_work(self):
        g = MetadataGenerator()
        for cat in ["bathroom", "sleep", "food", "travel", "morning", "evening", "prayer", "general"]:
            desc = g.generate_description("a", "u", cat)
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_description_length(self):
        g = MetadataGenerator()
        desc = g.generate_description("test_arabic", "test_urdu", "food")
        assert len(desc) > 100


# Phase 4: Tags Generation
class TestGenerateTags:
    def test_returns_list(self):
        g = MetadataGenerator()
        tags = g.generate_tags("food")
        assert isinstance(tags, list)

    def test_base_tags_included(self):
        g = MetadataGenerator()
        tags = g.generate_tags("food")
        for bt in g.base_tags:
            assert bt in tags

    def test_bathroom_category_tags(self):
        g = MetadataGenerator()
        tags = g.generate_tags("bathroom")
        assert "Bathroom Dua" in tags
        assert "Wudu Dua" in tags
        assert "Islamic Hygiene" in tags

    def test_sleep_category_tags(self):
        g = MetadataGenerator()
        tags = g.generate_tags("sleep")
        assert "Sleep Dua" in tags
        assert "Bedtime Dua" in tags

    def test_food_category_tags(self):
        g = MetadataGenerator()
        tags = g.generate_tags("food")
        assert "Food Dua" in tags
        assert "Bismillah" in tags

    def test_travel_category_tags(self):
        g = MetadataGenerator()
        tags = g.generate_tags("travel")
        assert "Travel Dua" in tags

    def test_morning_category_tags(self):
        g = MetadataGenerator()
        tags = g.generate_tags("morning")
        assert "Morning Dua" in tags

    def test_evening_category_tags(self):
        g = MetadataGenerator()
        tags = g.generate_tags("evening")
        assert "Evening Dua" in tags

    def test_prayer_category_tags(self):
        g = MetadataGenerator()
        tags = g.generate_tags("prayer")
        assert "Prayer Dua" in tags
        assert "Salah Dua" in tags

    def test_general_category_tags(self):
        g = MetadataGenerator()
        tags = g.generate_tags("general")
        assert "General Dua" in tags

    def test_unknown_category_no_category_tags(self):
        g = MetadataGenerator()
        tags = g.generate_tags("xyz_unknown")
        assert tags == g.base_tags

    def test_tag_count_bathroom(self):
        g = MetadataGenerator()
        tags = g.generate_tags("bathroom")
        assert len(tags) == 11

    def test_tag_count_unknown(self):
        g = MetadataGenerator()
        tags = g.generate_tags("unknown")
        assert len(tags) == 8

    def test_no_duplicates_within_category(self):
        g = MetadataGenerator()
        for cat in g.category_tags:
            tags = g.generate_tags(cat)
            assert len(tags) == len(set(tags))

    def test_tags_are_strings(self):
        g = MetadataGenerator()
        for tag in g.generate_tags("food"):
            assert isinstance(tag, str)


# Phase 5: Hashtags Generation
class TestGenerateHashtags:
    def test_returns_string(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("food")
        assert isinstance(h, str)

    def test_contains_base_hashtags(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("food")
        assert "#IslamicDua" in h
        assert "#UrduDua" in h
        assert "#ArabicDua" in h
        assert "#Prayer" in h
        assert "#Muslim" in h

    def test_bathroom_specific(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("bathroom")
        assert "#BathroomDua" in h
        assert "#Wudu" in h

    def test_sleep_specific(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("sleep")
        assert "#SleepDua" in h
        assert "#BedtimePrayer" in h

    def test_food_specific(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("food")
        assert "#FoodDua" in h
        assert "#Bismillah" in h

    def test_travel_specific(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("travel")
        assert "#TravelDua" in h
        assert "#SafetyPrayer" in h

    def test_morning_specific(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("morning")
        assert "#MorningDua" in h
        assert "#DailyPrayer" in h

    def test_evening_specific(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("evening")
        assert "#EveningDua" in h
        assert "#DailyPrayer" in h

    def test_prayer_specific(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("prayer")
        assert "#PrayerDua" in h
        assert "#Salah" in h

    def test_general_specific(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("general")
        assert "#DailyDua" in h
        assert "#IslamicPrayer" in h

    def test_unknown_category_base_only(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("unknown")
        base = "#IslamicDua #UrduDua #ArabicDua #Prayer #Muslim"
        assert h == base

    def test_all_hashtags_start_with_hash(self):
        g = MetadataGenerator()
        for cat in g.titles:
            h = g.generate_hashtags(cat)
            for tag in h.split():
                assert tag.startswith("#")

    def test_hashtags_are_space_separated(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("food")
        assert "  " not in h


# Phase 6: Full Generate Pipeline
class TestGenerate:
    def test_returns_dict_with_all_keys(self):
        g = MetadataGenerator()
        m = g.generate("arabic", "urdu", "food")
        assert isinstance(m, dict)
        assert "title" in m
        assert "description" in m
        assert "tags" in m
        assert "hashtags" in m

    def test_title_matches_direct_call(self):
        g = MetadataGenerator()
        m = g.generate("a", "u", "food")
        assert m["title"] == g.generate_title("food")

    def test_tags_matches_direct_call(self):
        g = MetadataGenerator()
        m = g.generate("a", "u", "sleep")
        assert m["tags"] == g.generate_tags("sleep")

    def test_hashtags_matches_direct_call(self):
        g = MetadataGenerator()
        m = g.generate("a", "u", "morning")
        assert m["hashtags"] == g.generate_hashtags("morning")

    def test_description_contains_input(self):
        g = MetadataGenerator()
        m = g.generate("ar_text", "ur_text", "food")
        assert "ar_text" in m["description"]
        assert "ur_text" in m["description"]

    def test_all_categories_produce_valid_metadata(self):
        g = MetadataGenerator()
        for cat in ["bathroom", "sleep", "food", "travel", "morning", "evening", "prayer", "general"]:
            m = g.generate("a", "u", cat)
            assert len(m["title"]) > 0
            assert len(m["description"]) > 0
            assert len(m["tags"]) > 0
            assert len(m["hashtags"]) > 0

    def test_unknown_category_still_works(self):
        g = MetadataGenerator()
        m = g.generate("a", "u", "unknown_cat")
        assert m["title"] == "Islamic Dua | Prayer"
        assert len(m["tags"]) == 8

    def test_unicode_arabic_urdu(self):
        g = MetadataGenerator()
        m = g.generate(
            "\u0628\u0650\u0633\u0652\u0645\u0650 \u0627\u0644\u0644\u0651\u064e\u0647\u0650",
            "\u0627\u0644\u0644\u0647 \u06a9\u06d2 \u0646\u0627\u0645",
            "food",
        )
        assert "\u0627\u0644\u0644\u0647" in m["description"]
        assert len(m["title"]) > 0

    def test_metadata_values_are_correct_types(self):
        g = MetadataGenerator()
        m = g.generate("a", "u", "prayer")
        assert isinstance(m["title"], str)
        assert isinstance(m["description"], str)
        assert isinstance(m["tags"], list)
        assert isinstance(m["hashtags"], str)


# Phase 7: Save & Load
class TestSaveLoad:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_creates_file(self):
        g = MetadataGenerator()
        m = g.generate("a", "u", "food")
        path = os.path.join(self.tmpdir, "meta.json")
        g.save_metadata(m, path)
        assert os.path.exists(path)

    def test_save_load_roundtrip(self):
        g = MetadataGenerator()
        m = g.generate("ar", "ur", "food")
        path = os.path.join(self.tmpdir, "meta.json")
        g.save_metadata(m, path)
        loaded = g.load_metadata(path)
        assert loaded == m

    def test_load_nonexistent_returns_none(self):
        g = MetadataGenerator()
        result = g.load_metadata(os.path.join(self.tmpdir, "nope.json"))
        assert result is None

    def test_save_unicode_content(self):
        g = MetadataGenerator()
        m = g.generate("arabic_unicode", "urdu_unicode", "sleep")
        path = os.path.join(self.tmpdir, "meta.json")
        g.save_metadata(m, path)
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        assert raw["title"] == m["title"]

    def test_save_ensure_ascii_false(self):
        g = MetadataGenerator()
        path = os.path.join(self.tmpdir, "meta.json")
        g.save_metadata({"arabic": "\u0628\u0633\u0645"}, path)
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        assert "\u0628\u0633\u0645" in raw
        assert "\\u0628" not in raw

    def test_load_valid_json(self):
        path = os.path.join(self.tmpdir, "valid.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"title": "test", "tags": ["a"]}, f)
        g = MetadataGenerator()
        loaded = g.load_metadata(path)
        assert loaded["title"] == "test"
        assert loaded["tags"] == ["a"]

    def test_load_invalid_json_raises(self):
        path = os.path.join(self.tmpdir, "bad.json")
        with open(path, "w") as f:
            f.write("NOT JSON {{{")
        g = MetadataGenerator()
        try:
            g.load_metadata(path)
            raise AssertionError("Should have raised")
        except json.JSONDecodeError:
            pass

    def test_overwrite_existing_file(self):
        g = MetadataGenerator()
        path = os.path.join(self.tmpdir, "meta.json")
        m1 = g.generate("a", "u", "food")
        g.save_metadata(m1, path)
        m2 = g.generate("b", "v", "sleep")
        g.save_metadata(m2, path)
        loaded = g.load_metadata(path)
        assert loaded["title"] == m2["title"]


# Phase 8: Edge Cases
class TestEdgeCases:
    def test_empty_string_arabic(self):
        g = MetadataGenerator()
        m = g.generate("", "", "food")
        assert m["title"] == "Food Dua | Eating Prayer"
        assert len(m["tags"]) > 0

    def test_empty_string_category(self):
        g = MetadataGenerator()
        m = g.generate("a", "u", "")
        assert "Islamic Dua | Prayer" in m["title"]

    def test_special_chars_in_text(self):
        g = MetadataGenerator()
        m = g.generate("<script>alert(1)</script>", "test", "food")
        assert "<script>" in m["description"]

    def test_very_long_arabic_text(self):
        g = MetadataGenerator()
        long_text = "test " * 1000
        m = g.generate(long_text, "u", "food")
        assert len(m["description"]) > 4000

    def test_newlines_in_text(self):
        g = MetadataGenerator()
        m = g.generate("line1\nline2", "line3\nline4", "food")
        assert "line1\nline2" in m["description"]

    def test_numbers_in_text(self):
        g = MetadataGenerator()
        m = g.generate("12345", "67890", "food")
        assert "12345" in m["description"]

    def test_case_sensitivity_title(self):
        g = MetadataGenerator()
        assert g.generate_title("FOOD") == "Islamic Dua | Prayer"
        assert g.generate_title("Food") == "Islamic Dua | Prayer"

    def test_case_sensitivity_tags(self):
        g = MetadataGenerator()
        tags = g.generate_tags("FOOD")
        assert tags == g.base_tags

    def test_case_sensitivity_hashtags(self):
        g = MetadataGenerator()
        h = g.generate_hashtags("FOOD")
        base = "#IslamicDua #UrduDua #ArabicDua #Prayer #Muslim"
        assert h == base

    def test_all_seven_categories_covered(self):
        g = MetadataGenerator()
        cats = ["bathroom", "sleep", "food", "travel", "morning", "evening", "prayer", "general"]
        for cat in cats:
            m = g.generate("a", "u", cat)
            assert m["title"] != "Islamic Dua | Prayer" or cat == "general"
