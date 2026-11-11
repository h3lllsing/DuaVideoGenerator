"""Tests for core.mega_pack (MegaPackPipeline + MegaPackResult)."""

import os

from core.mega_pack import MegaPackPipeline, MegaPackResult, ultra_pack_preview


def _pipeline(tmp_path):
    return MegaPackPipeline(output_dir=str(tmp_path / "ultra_pack"))


def test_megapack_result_success_str():
    r = MegaPackResult(success=True, video_path="/tmp/x.mp4", config_summary="cfg", generation_time=1.0)
    assert "Video ready" in str(r)


def test_megapack_result_failure_str():
    r = MegaPackResult(success=False, error="boom")
    assert "Failed" in str(r)


def test_megapack_pipeline_init_creates_dir(tmp_path):
    p = _pipeline(tmp_path)
    assert os.path.isdir(str(tmp_path / "ultra_pack"))


def test_megapack_pipeline_generate_invalid_content(tmp_path):
    p = _pipeline(tmp_path)
    res = p.generate(arabic="", urdu="urdu text", title="t", mood="peaceful")
    assert res.success is False
    assert res.error


def test_megapack_preview_config_returns_str(tmp_path):
    p = _pipeline(tmp_path)
    prev = p.preview_config(seed="42", mood="peaceful")
    assert isinstance(prev, str)
    assert len(prev) > 0


def test_megapack_get_available_options(tmp_path):
    p = _pipeline(tmp_path)
    opts = p.get_available_options()
    assert isinstance(opts, dict)
    assert len(opts) > 0


def test_megapack_ultra_pack_preview_returns_str(tmp_path):
    prev = ultra_pack_preview(seed="42", mood="peaceful")
    assert isinstance(prev, str)
    assert len(prev) > 0
