"""Tests for core.asset_registry (VISUAL Phase 1)."""

import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.asset_registry import (
    ALLOWED_LICENSES,
    AssetRegistry,
    normalize_license,
)

TEST_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_asset_registry_tmp")


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _write_manifest(dirpath, assets):
    os.makedirs(dirpath, exist_ok=True)
    manifest_path = os.path.join(dirpath, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 1, "assets": assets}, f)
    return manifest_path


def _write_file(dirpath, name, data):
    with open(os.path.join(dirpath, name), "wb") as f:
        f.write(data)


def _entry(
    asset_id,
    file_name,
    data=b"fake-image-bytes",
    categories=("general",),
    license_name="CC0",
    approved=True,
    checksum=None,
):
    return {
        "id": asset_id,
        "file": file_name,
        "data": data,
        "categories": list(categories),
        "license": license_name,
        "approved": approved,
        "checksum_sha256": checksum,
        "resolution": {"width": 1620, "height": 2880},
        "author": "Test Author",
        "source_url": "https://example.com/test",
    }


def _registry_with(tmp_dir, entries, images=None):
    os.makedirs(tmp_dir, exist_ok=True)
    images = dict(images or {})
    manifest_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            manifest_entries.append(entry)
            continue
        file_name = entry.get("file")
        if entry.get("checksum_sha256") is None:
            content = images.get(file_name, entry.get("data", b""))
            entry["checksum_sha256"] = _sha256(content)
        manifest_entry = dict(entry)
        manifest_entry.pop("data", None)
        manifest_entries.append(manifest_entry)
    for name, data in images.items():
        _write_file(tmp_dir, name, data)
    _write_manifest(tmp_dir, manifest_entries)
    return AssetRegistry(backgrounds_dir=tmp_dir)


def setup_function():
    os.makedirs(TEST_ROOT, exist_ok=True)


def teardown_function():
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


# ----------------------------------------------------------------------
# Manifest parsing
# ----------------------------------------------------------------------
def test_manifest_parse_populates_assets():
    tmp = os.path.join(TEST_ROOT, "parse")
    registry = _registry_with(
        tmp,
        [
            _entry("a", "a.jpg"),
            _entry("b", "b.jpg", categories=("morning",)),
        ],
        images={"a.jpg": b"AAA", "b.jpg": b"BBB"},
    )
    assets = registry.get_assets()
    assert len(assets) == 2
    ids = {a.id for a in assets}
    assert ids == {"a", "b"}
    a = next(x for x in assets if x.id == "a")
    assert a.license == "CC0"
    assert a.approved is True
    assert a.resolution_width == 1620
    assert a.resolution_height == 2880
    assert a.author == "Test Author"
    assert registry.manifest_error is None


def test_manifest_missing_is_not_an_error():
    tmp = os.path.join(TEST_ROOT, "missing")
    os.makedirs(tmp, exist_ok=True)
    registry = AssetRegistry(backgrounds_dir=tmp)
    assert registry.get_assets() == []
    assert registry.manifest_error is not None
    assert registry.get_loadable_assets() == []
    result = registry.select_background("any_dua")
    assert result["kind"] == "procedural"


def test_manifest_malformed_json_is_not_an_error():
    tmp = os.path.join(TEST_ROOT, "malformed")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
        f.write("{ not valid json")
    registry = AssetRegistry(backgrounds_dir=tmp)
    assert registry.get_assets() == []
    assert registry.manifest_error is not None
    result = registry.select_background("any_dua")
    assert result["kind"] == "procedural"


def test_manifest_wrong_root_type_is_not_an_error():
    tmp = os.path.join(TEST_ROOT, "wrong_root")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
        f.write("[]")
    registry = AssetRegistry(backgrounds_dir=tmp)
    assert registry.get_assets() == []
    assert registry.manifest_error is not None


def test_invalid_entries_are_skipped():
    tmp = os.path.join(TEST_ROOT, "skip")
    registry = _registry_with(
        tmp,
        [
            {"id": "no_file"},  # missing file -> skipped
            {"file": "b.jpg"},  # missing id -> skipped
            "not-a-dict",  # non-dict -> skipped
            _entry("ok", "ok.jpg"),
        ],
        images={"ok.jpg": b"OK"},
    )
    assets = registry.get_assets()
    assert [a.id for a in assets] == ["ok"]


def test_normalize_license():
    assert normalize_license("Public Domain") == "PUBLIC DOMAIN"
    assert normalize_license("cc0") == "CC0"
    assert normalize_license("  CC-BY 4.0 ") == "CC-BY 4.0"
    assert normalize_license("") == ""
    assert normalize_license(None) == ""
    assert "CC0" in ALLOWED_LICENSES
    assert "PUBLIC DOMAIN" in ALLOWED_LICENSES
    assert "CC-BY" in ALLOWED_LICENSES


# ----------------------------------------------------------------------
# Approval gate
# ----------------------------------------------------------------------
def test_only_approved_assets_loadable():
    tmp = os.path.join(TEST_ROOT, "approved")
    registry = _registry_with(
        tmp,
        [
            _entry("yes", "yes.jpg", approved=True),
            _entry("no", "no.jpg", approved=False),
        ],
        images={"yes.jpg": b"YES", "no.jpg": b"NO"},
    )
    loadable = {a.id for a in registry.get_loadable_assets()}
    assert loadable == {"yes"}
    assert registry.is_loadable(next(a for a in registry.get_assets() if a.id == "no")) is False


def test_missing_approved_flag_is_rejected():
    tmp = os.path.join(TEST_ROOT, "noflag")
    entry = _entry("x", "x.jpg")
    entry.pop("approved")
    registry = _registry_with(tmp, [entry], images={"x.jpg": b"X"})
    assert registry.get_loadable_assets() == []


def test_license_validation():
    tmp = os.path.join(TEST_ROOT, "license")
    registry = _registry_with(
        tmp,
        [
            _entry("cc0", "cc0.jpg", license_name="CC0"),
            _entry("pd", "pd.jpg", license_name="Public Domain"),
            _entry("by", "by.jpg", license_name="CC-BY 4.0"),
            _entry("bad", "bad.jpg", license_name="All Rights Reserved"),
        ],
        images={n + ".jpg": bytes(n, "ascii") for n in ("cc0", "pd", "by", "bad")},
    )
    loadable = {a.id for a in registry.get_loadable_assets()}
    assert loadable == {"cc0", "pd", "by"}


def test_missing_license_is_rejected():
    tmp = os.path.join(TEST_ROOT, "nolicense")
    entry = _entry("x", "x.jpg")
    entry["license"] = ""
    registry = _registry_with(tmp, [entry], images={"x.jpg": b"X"})
    assert registry.get_loadable_assets() == []


def test_checksum_match_loadable():
    tmp = os.path.join(TEST_ROOT, "checksum_ok")
    registry = _registry_with(
        tmp,
        [
            _entry("a", "a.jpg", data=b"content-A"),
        ],
        images={"a.jpg": b"content-A"},
    )
    loadable = registry.get_loadable_assets()
    assert len(loadable) == 1
    assert registry.verify_checksum(loadable[0]) is True


def test_checksum_mismatch_rejected():
    tmp = os.path.join(TEST_ROOT, "checksum_bad")
    registry = _registry_with(
        tmp,
        [
            _entry("a", "a.jpg", data=b"content-A", checksum=_sha256(b"other-bytes")),
        ],
        images={"a.jpg": b"content-A"},
    )
    assert registry.get_loadable_assets() == []


def test_missing_checksum_rejected():
    tmp = os.path.join(TEST_ROOT, "nochecksum")
    entry = _entry("a", "a.jpg", data=b"content-A")
    entry["checksum_sha256"] = ""
    registry = _registry_with(tmp, [entry], images={"a.jpg": b"content-A"})
    assert registry.get_loadable_assets() == []


def test_checksum_is_case_insensitive_hex():
    tmp = os.path.join(TEST_ROOT, "case_hex")
    entry = _entry("a", "a.jpg", data=b"content-A", checksum=_sha256(b"content-A").upper())
    registry = _registry_with(tmp, [entry], images={"a.jpg": b"content-A"})
    assert len(registry.get_loadable_assets()) == 1


def test_missing_file_rejected():
    tmp = os.path.join(TEST_ROOT, "missing_file")
    registry = _registry_with(
        tmp,
        [
            _entry("a", "ghost.jpg", data=b"content-A"),
        ],
        images={},
    )
    assert registry.get_loadable_assets() == []


# ----------------------------------------------------------------------
# Deterministic category-based selection
# ----------------------------------------------------------------------
def test_selection_is_deterministic_for_same_seed():
    tmp = os.path.join(TEST_ROOT, "deterministic")
    registry = _registry_with(
        tmp,
        [
            _entry("a", "a.jpg", categories=("morning",)),
            _entry("b", "b.jpg", categories=("morning",)),
        ],
        images={"a.jpg": b"A", "b.jpg": b"B"},
    )
    first = registry.select_background("dua_123", "morning", random_mode=False)
    second = registry.select_background("dua_123", "morning", random_mode=False)
    assert first["kind"] == "asset"
    assert first["asset_id"] == second["asset_id"]
    assert first["path"] == second["path"]


def test_selection_deterministic_across_instances():
    tmp = os.path.join(TEST_ROOT, "cross_instance")
    entries = [_entry("a", "a.jpg", categories=("morning",)), _entry("b", "b.jpg", categories=("morning",))]
    images = {"a.jpg": b"A", "b.jpg": b"B"}
    r1 = _registry_with(tmp, entries, images=images)
    r2 = _registry_with(tmp, entries, images=images)
    assert (
        r1.select_background("dua_abc", random_mode=False)["asset_id"]
        == r2.select_background("dua_abc", random_mode=False)["asset_id"]
    )


def test_selection_prefers_category_match():
    tmp = os.path.join(TEST_ROOT, "category_priority")
    registry = _registry_with(
        tmp,
        [
            _entry("specific", "s.jpg", categories=("morning",)),
            _entry("generic", "g.jpg", categories=("general",)),
        ],
        images={"s.jpg": b"S", "g.jpg": b"G"},
    )
    result = registry.select_background("dua_x", "morning")
    assert result["kind"] == "asset"
    assert result["asset_id"] == "specific"


def test_selection_uses_general_fallback_for_any_category():
    tmp = os.path.join(TEST_ROOT, "general_fallback")
    registry = _registry_with(
        tmp,
        [
            _entry("generic", "g.jpg", categories=("general",)),
        ],
        images={"g.jpg": b"G"},
    )
    for cat in ("morning", "bathroom", "evening"):
        result = registry.select_background("dua_y", cat)
        assert result["kind"] == "asset"
        assert result["asset_id"] == "generic"


def test_selection_is_seeded_by_dua_id():
    tmp = os.path.join(TEST_ROOT, "seeded_variety")
    entries = [_entry(f"bg_{i}", f"{i}.jpg", categories=("morning",)) for i in range(6)]
    images = {f"{i}.jpg": bytes([i]) for i in range(6)}
    registry = _registry_with(tmp, entries, images=images)
    picked = {registry.select_background(f"dua_{i}", "morning")["asset_id"] for i in range(40)}
    assert len(picked) > 1  # seed actually influences the choice


def test_selection_excludes_used_assets():
    tmp = os.path.join(TEST_ROOT, "exclude")
    registry = _registry_with(
        tmp,
        [
            _entry("a", "a.jpg", categories=("morning",)),
            _entry("b", "b.jpg", categories=("morning",)),
        ],
        images={"a.jpg": b"A", "b.jpg": b"B"},
    )
    result = registry.select_background("dua_z", "morning", exclude_ids={"a"})
    assert result["kind"] == "asset"
    assert result["asset_id"] == "b"


def test_selection_excluding_everything_falls_back():
    tmp = os.path.join(TEST_ROOT, "exclude_all")
    registry = _registry_with(
        tmp,
        [
            _entry("a", "a.jpg", categories=("morning",)),
        ],
        images={"a.jpg": b"A"},
    )
    result = registry.select_background("dua_z", "morning", exclude_ids={"a"})
    assert result["kind"] == "procedural"
    assert "theme" in result


# ----------------------------------------------------------------------
# Procedural fallback
# ----------------------------------------------------------------------
def test_procedural_fallback_when_no_assets():
    tmp = os.path.join(TEST_ROOT, "empty")
    registry = _registry_with(tmp, [])
    result = registry.select_background("dua_1", "morning")
    assert result["kind"] == "procedural"
    assert result["theme"] in config.THEMES
    assert "reason" in result


def test_procedural_fallback_when_no_approved_assets():
    tmp = os.path.join(TEST_ROOT, "none_approved")
    registry = _registry_with(
        tmp,
        [
            _entry("a", "a.jpg", categories=("morning",), approved=False),
        ],
        images={"a.jpg": b"A"},
    )
    result = registry.select_background("dua_1", "morning")
    assert result["kind"] == "procedural"


def test_procedural_fallback_when_no_category_match():
    tmp = os.path.join(TEST_ROOT, "no_match")
    registry = _registry_with(
        tmp,
        [
            _entry("bath", "b.jpg", categories=("bathroom",)),
        ],
        images={"b.jpg": b"B"},
    )
    result = registry.select_background("dua_2", "prayer")
    assert result["kind"] == "procedural"
    assert result["theme"] in config.THEMES


def test_procedural_theme_is_deterministic():
    tmp = os.path.join(TEST_ROOT, "theme_det")
    registry = _registry_with(tmp, [])
    assert registry.select_background("dua_3")["theme"] == registry.select_background("dua_3")["theme"]


def test_procedural_theme_respects_preference():
    tmp = os.path.join(TEST_ROOT, "theme_pref")
    registry = _registry_with(tmp, [])
    theme = list(config.THEMES)[0]
    result = registry.select_background("dua_4", preferred_theme=theme)
    assert result["theme"] == theme


# ----------------------------------------------------------------------
# Real manifest integration
# ----------------------------------------------------------------------
def test_real_manifest_parses_and_selects_real_asset():
    # Real project manifest (assets/backgrounds). The production library now
    # holds hundreds of approved Pexels assets, so the manifest must parse
    # cleanly and selection must resolve to a real asset (no procedural
    # fallback) when approved assets are available.
    registry = AssetRegistry()
    assert registry.manifest_error is None, registry.manifest_error
    assets = registry.get_assets()
    assert len(assets) > 0
    loadable = registry.get_loadable_assets()
    assert len(loadable) > 0
    # everything loadable is approved (approval gate enforced on real data)
    assert all(a.approved for a in loadable)
    # selecting for a real dua resolves to an actual asset on disk
    result = registry.select_background("dua_real")
    assert result["kind"] == "asset"
    assert result.get("asset_id")
    assert result.get("path")
    assert os.path.exists(result["path"])
