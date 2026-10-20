"""
HW-001 tests: Hardware detection, GPU detection, backend selection,
hardware-aware blur, parallel frame processing, and error fallback paths.

Run with: python -m pytest tests/test_hardware.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from core.hardware import (
    _GPU_MIN_PIXELS,
    detect_cpu_cores,
    detect_gpu,
    gaussian_blur,
    parallel_map,
    pick_backend,
    profile_summary,
)


# ──────────────────────────────────────────────────────────────────
#  Phase 1: CPU Detection
# ──────────────────────────────────────────────────────────────────
class TestDetectCpuCores:
    """detect_cpu_cores() returns valid core count."""

    def test_returns_positive_int(self):
        cores = detect_cpu_cores()
        assert isinstance(cores, int)
        assert cores >= 1

    def test_normal_system(self):
        cores = detect_cpu_cores()
        assert cores >= 1

    def test_mock_none_returns_one(self):
        with patch("core.hardware.mp.cpu_count", return_value=None):
            assert detect_cpu_cores() == 1

    def test_mock_zero_returns_one(self):
        with patch("core.hardware.mp.cpu_count", return_value=0):
            assert detect_cpu_cores() == 1

    def test_mock_sixteen_returns_sixteen(self):
        with patch("core.hardware.mp.cpu_count", return_value=16):
            assert detect_cpu_cores() == 16

    def test_mock_exception_returns_one(self):
        with patch("core.hardware.mp.cpu_count", side_effect=RuntimeError("fail")):
            assert detect_cpu_cores() == 1


# ──────────────────────────────────────────────────────────────────
#  Phase 2: GPU Detection
# ──────────────────────────────────────────────────────────────────
class TestDetectGpu:
    """detect_gpu() three-tier detection."""

    def test_returns_dict_with_required_keys(self):
        gpu = detect_gpu()
        assert isinstance(gpu, dict)
        assert "name" in gpu
        assert "vendor" in gpu
        assert "available" in gpu

    def test_available_is_bool(self):
        gpu = detect_gpu()
        assert isinstance(gpu["available"], bool)

    def test_vendor_is_string(self):
        gpu = detect_gpu()
        assert isinstance(gpu["vendor"], str)

    def test_name_is_string(self):
        gpu = detect_gpu()
        assert isinstance(gpu["name"], str)

    def test_no_opencl_no_cuda_no_wmi(self):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import), patch("core.hardware.os.name", "posix"):
            gpu = detect_gpu()
            assert gpu["available"] is False
            assert gpu["name"] == "unknown"

    def test_opencl_found(self):
        mock_dev = MagicMock()
        mock_dev.name = "RTX 4090"
        mock_dev.vendor = "NVIDIA"

        mock_platform = MagicMock()
        mock_platform.get_devices.return_value = [mock_dev]

        mock_cl = MagicMock()
        mock_cl.get_platforms.return_value = [mock_platform]

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                return mock_cl
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            gpu = detect_gpu()
            assert gpu["available"] is True
            assert gpu["name"] == "RTX 4090"
            assert gpu["vendor"] == "NVIDIA"

    def test_opencl_empty_platforms(self):
        mock_cl = MagicMock()
        mock_cl.get_platforms.return_value = []

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                return mock_cl
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            gpu = detect_gpu()
            assert gpu["available"] is False

    def test_opencl_empty_devices(self):
        mock_platform = MagicMock()
        mock_platform.get_devices.return_value = []

        mock_cl = MagicMock()
        mock_cl.get_platforms.return_value = [mock_platform]

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                return mock_cl
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            gpu = detect_gpu()
            assert gpu["available"] is False

    def test_cuda_found(self):
        mock_cv2 = MagicMock()
        mock_cv2.cuda.getCudaEnabledDeviceCount.return_value = 1

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            if name == "cv2":
                return mock_cv2
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            gpu = detect_gpu()
            assert gpu["available"] is True
            assert gpu["name"] == "CUDA device"
            assert gpu["vendor"] == "NVIDIA"

    def test_cuda_zero_count(self):
        mock_cv2 = MagicMock()
        mock_cv2.cuda.getCudaEnabledDeviceCount.return_value = 0

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            if name == "cv2":
                return mock_cv2
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            gpu = detect_gpu()
            assert gpu["available"] is False

    def test_wmi_amd_gpu(self):
        mock_result = MagicMock()
        mock_result.stdout = "Name\nAMD Radeon RX 7900 XTX\n"

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            if name == "subprocess":
                mock_sub = MagicMock()
                mock_sub.run.return_value = mock_result
                return mock_sub
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import), patch("core.hardware.os.name", "nt"):
            gpu = detect_gpu()
            assert gpu["name"] == "AMD Radeon RX 7900 XTX"
            assert gpu["vendor"] == "AMD"
            assert gpu["available"] is False

    def test_wmi_intel_gpu(self):
        mock_result = MagicMock()
        mock_result.stdout = "Name\nIntel Arc A770\n"

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            if name == "subprocess":
                mock_sub = MagicMock()
                mock_sub.run.return_value = mock_result
                return mock_sub
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import), patch("core.hardware.os.name", "nt"):
            gpu = detect_gpu()
            assert gpu["vendor"] == "Intel"

    def test_wmi_empty_output(self):
        mock_result = MagicMock()
        mock_result.stdout = ""

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            if name == "subprocess":
                mock_sub = MagicMock()
                mock_sub.run.return_value = mock_result
                return mock_sub
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import), patch("core.hardware.os.name", "nt"):
            gpu = detect_gpu()
            assert gpu["available"] is False

    def test_wmi_timeout(self):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            if name == "subprocess":
                mock_sub = MagicMock()
                mock_sub.run.side_effect = TimeoutError("timeout")
                return mock_sub
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import), patch("core.hardware.os.name", "nt"):
            gpu = detect_gpu()
            assert gpu["available"] is False


# ──────────────────────────────────────────────────────────────────
#  Phase 3: Backend Selection
# ──────────────────────────────────────────────────────────────────
class TestPickBackend:
    """pick_backend() selects correct compute backend."""

    def test_returns_valid_string(self):
        b = pick_backend()
        assert b in ("cpu", "cpu_parallel", "opencl_gpu")

    def test_cpu_when_no_gpu(self):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            assert pick_backend(0) == "cpu"

    def test_cpu_parallel_when_many_frames(self):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", side_effect=mock_import),
            patch("core.hardware.detect_cpu_cores", return_value=4),
        ):
            assert pick_backend(500) == "cpu_parallel"

    def test_cpu_when_few_frames(self):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", side_effect=mock_import),
            patch("core.hardware.detect_cpu_cores", return_value=4),
        ):
            assert pick_backend(100) == "cpu"

    def test_cpu_when_single_core(self):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", side_effect=mock_import),
            patch("core.hardware.detect_cpu_cores", return_value=1),
        ):
            assert pick_backend(1000) == "cpu"

    def test_opencl_gpu_when_available(self):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                return MagicMock()
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            assert pick_backend() == "opencl_gpu"

    def test_boundary_499_is_cpu(self):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", side_effect=mock_import),
            patch("core.hardware.detect_cpu_cores", return_value=4),
        ):
            assert pick_backend(499) == "cpu"

    def test_boundary_500_is_parallel(self):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", side_effect=mock_import),
            patch("core.hardware.detect_cpu_cores", return_value=2),
        ):
            assert pick_backend(500) == "cpu_parallel"


# ──────────────────────────────────────────────────────────────────
#  Phase 4: Profile Summary
# ──────────────────────────────────────────────────────────────────
class TestProfileSummary:
    """profile_summary() human-readable hardware line."""

    def test_contains_cpu(self):
        s = profile_summary()
        assert "CPU" in s

    def test_contains_cores(self):
        s = profile_summary()
        assert "cores" in s

    def test_contains_gpu(self):
        s = profile_summary()
        assert "GPU" in s

    def test_contains_backend(self):
        s = profile_summary()
        assert "backend" in s

    def test_format_with_known_cores(self):
        with patch("core.hardware.detect_cpu_cores", return_value=8):
            s = profile_summary()
            assert "CPU 8 cores" in s

    def test_unknown_gpu_shows_none(self):
        with patch(
            "core.hardware.detect_gpu", return_value={"name": "unknown", "vendor": "unknown", "available": False}
        ):
            s = profile_summary()
            assert "GPU: None" in s

    def test_known_gpu_shows_name(self):
        with patch(
            "core.hardware.detect_gpu", return_value={"name": "RTX 4090", "vendor": "NVIDIA", "available": True}
        ):
            s = profile_summary()
            assert "RTX 4090" in s


# ──────────────────────────────────────────────────────────────────
#  Phase 5: Gaussian Blur
# ──────────────────────────────────────────────────────────────────
class TestGaussianBlur:
    """gaussian_blur() hardware-aware blur."""

    def test_small_mask_cpu_path(self):
        m = np.random.rand(64, 64).astype(np.float32)
        out = gaussian_blur(m, 8.0)
        assert out.shape == m.shape
        assert np.isfinite(out).all()

    def test_output_dtype_matches_input(self):
        m = (np.random.rand(64, 64) * 255).astype(np.uint8)
        out = gaussian_blur(m, 3.0)
        assert out.dtype == np.uint8

    def test_float32_dtype_preserved(self):
        m = np.random.rand(64, 64).astype(np.float32)
        out = gaussian_blur(m, 5.0)
        assert out.dtype == np.float32

    def test_blur_reduces_variance(self):
        m = np.random.rand(100, 100).astype(np.float32)
        m[m > 0.5] = 1.0
        m[m <= 0.5] = 0.0
        out = gaussian_blur(m, 10.0)
        assert np.var(out) < np.var(m)

    def test_sigma_zero_works(self):
        m = np.random.rand(64, 64).astype(np.float32)
        out = gaussian_blur(m, 0.1)
        assert out.shape == m.shape
        assert np.isfinite(out).all()

    def test_large_mask_cpu_fallback(self):
        m = np.random.rand(600, 600).astype(np.float32)
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pyopencl":
                raise ImportError("no pyopencl")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            out = gaussian_blur(m, 5.0)
            assert out.shape == m.shape
            assert np.isfinite(out).all()

    def test_kernel_parameter_ignored(self):
        m = np.random.rand(64, 64).astype(np.float32)
        out1 = gaussian_blur(m, 5.0, kernel=None)
        out2 = gaussian_blur(m, 5.0, kernel=7)
        np.testing.assert_array_equal(out1, out2)


# ──────────────────────────────────────────────────────────────────
#  Phase 6: Parallel Map
# ──────────────────────────────────────────────────────────────────
class TestParallelMap:
    """parallel_map() serial/parallel frame processing."""

    def _double(self, frame, params):
        return frame * 2

    def test_serial_small_input(self):
        frames = list(range(10))
        result = parallel_map(self._double, frames)
        assert result == [x * 2 for x in frames]

    def test_result_matches_serial(self):
        frames = list(range(20))
        result = parallel_map(self._double, frames, min_total=500)
        expected = [x * 2 for x in frames]
        assert result == expected

    def test_empty_frames(self):
        result = parallel_map(self._double, [])
        assert result == []

    def test_single_frame(self):
        result = parallel_map(self._double, [42])
        assert result == [84]

    def test_params_passed(self):
        def add_param(frame, params):
            return frame + (params or 0)

        result = parallel_map(add_param, [1, 2, 3], params=10)
        assert result == [11, 12, 13]

    def test_parallel_path_when_many_frames(self):
        frames = list(range(600))
        with patch("core.hardware.detect_cpu_cores", return_value=4):
            result = parallel_map(self._double, frames, min_total=500)
        assert len(result) == 600
        assert result == [x * 2 for x in frames]

    def test_serial_when_single_core(self):
        frames = list(range(600))
        with patch("core.hardware.detect_cpu_cores", return_value=1):
            result = parallel_map(self._double, frames, min_total=500)
        assert result == [x * 2 for x in frames]

    def test_preserves_order(self):
        frames = list(range(100))
        with patch("core.hardware.detect_cpu_cores", return_value=4):
            result = parallel_map(self._double, frames, min_total=50)
        assert result == sorted(result)


# ──────────────────────────────────────────────────────────────────
#  Phase 7: Constants & Module State
# ──────────────────────────────────────────────────────────────────
class TestConstants:
    """Module constants and thresholds."""

    def test_gpu_min_pixels_value(self):
        assert _GPU_MIN_PIXELS == 250_000

    def test_gpu_min_pixels_positive(self):
        assert _GPU_MIN_PIXELS > 0

    def test_gpu_min_pixels_reasonable(self):
        assert 100_000 <= _GPU_MIN_PIXELS <= 1_000_000
