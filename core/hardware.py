"""
Hardware Profile Module (AI Director support).
Detects the machine's CPU/GPU and exposes the best compute backend so the
effect pipeline adapts to the hardware that is actually available.

Backends (auto-selected):
  - "cpu"          : single-core numpy/opencv (fast enough for vectorized fx)
  - "cpu_parallel" : multiprocessing frame-chunk worker (used only when it
                     is clearly beneficial, i.e. very long videos)
  - "opencl_gpu"   : GPU accelerated blur via PyOpenCL (optional; if the
                     package is installed). Falls back silently otherwise.

Nothing here is ever imported from the frozen render modules.
"""

import logging
import multiprocessing as mp
import os
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["detect_cpu_cores", "detect_gpu", "pick_backend", "profile_summary", "gaussian_blur"]


def detect_cpu_cores() -> int:
    try:
        n = mp.cpu_count()
    except Exception:
        logger.debug("mp.cpu_count() failed, defaulting to 1")
        n = 1
    return max(1, int(n or 1))


def detect_gpu() -> dict:
    """
    Best-effort GPU detection. Returns {"name", "vendor", "available"}.
    Tries OpenCL first (works for AMD/Intel), then OpenCV CUDA, then a
    Windows WMI query as a last resort (reporting only).
    """
    info = {"name": "unknown", "vendor": "unknown", "available": False}

    # 1) PyOpenCL (the real GPU compute path for AMD/Intel/NVIDIA).
    try:
        import pyopencl as cl

        platforms = cl.get_platforms()
        if platforms:
            dev = platforms[0].get_devices()
            if dev:
                d = dev[0]
                info["name"] = d.name.strip()
                info["vendor"] = d.vendor.strip()
                info["available"] = True
                return info
    except Exception:
        logger.debug("PyOpenCL not available")
        pass

    # 2) OpenCV CUDA build (very rare on pip wheels, try anyway).
    try:
        import cv2

        if hasattr(cv2, "cuda"):
            n = cv2.cuda.getCudaEnabledDeviceCount()
            if n and n > 0:
                info["name"] = "CUDA device"
                info["vendor"] = "NVIDIA"
                info["available"] = True
                return info
    except Exception:
        logger.debug("OpenCV CUDA not available")
        pass

    # 3) Windows WMI (report only, no compute).
    if os.name == "nt":
        try:
            import subprocess

            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            names = [ln.strip() for ln in out.stdout.splitlines() if ln.strip() and "Name" not in ln]
            if names:
                info["name"] = names[0]
                info["vendor"] = (
                    "AMD"
                    if "AMD" in names[0]
                    else "NVIDIA"
                    if "NVIDIA" in names[0]
                    else "Intel"
                    if "Intel" in names[0]
                    else "GPU"
                )
                # WMI gives us a GPU name but no compute access.
                return info
        except Exception:
            logger.debug("WMI GPU query failed")
            pass
    return info


def pick_backend(frames_total: int = 0) -> str:
    """Choose the best compute backend for the current machine."""
    cores = detect_cpu_cores()

    # GPU compute only if PyOpenCL is actually importable.
    try:
        import pyopencl as cl  # noqa: F401

        return "opencl_gpu"
    except Exception:
        logger.debug("pyopencl import check failed")
        pass

    # CPU parallel only helps for very long, heavy renders.
    if frames_total >= 500 and cores >= 2:
        return "cpu_parallel"
    return "cpu"


def profile_summary(frames_total: int = 0) -> str:
    """Human-readable hardware line for logs/status."""
    cores = detect_cpu_cores()
    gpu = detect_gpu()
    backend = pick_backend(frames_total)
    gpu_txt = gpu.get("name") if gpu.get("name") != "unknown" else "None"
    return f"CPU {cores} cores | GPU: {gpu_txt} | backend: {backend}"


_OCL: dict[str, Any] = {}  # cached OpenCL context/program per (platform, device)

# Small masks are faster on CPU (cv2); GPU wins only above this pixel count.
_GPU_MIN_PIXELS = 250_000


def _ocl_resources():
    """Build (or return cached) OpenCL context + program + kernel."""
    if _OCL:
        return _OCL
    import pyopencl as cl

    plats = cl.get_platforms()
    dev = plats[0].get_devices()[0]
    ctx = cl.Context([dev])
    queue = cl.CommandQueue(ctx)
    prg = cl.Program(
        ctx,
        """
        __kernel void gblur(__global const float* in,
                            __global float* out,
                            int w, int h, int k) {
            int x = get_global_id(0);
            int y = get_global_id(1);
            if (x >= w || y >= h) return;
            float s = 0; int c = 0;
            int r = (k - 1) / 2;
            for (int dy = -r; dy <= r; dy++) {
                for (int dx = -r; dx <= r; dx++) {
                    int nx = x + dx, ny = y + dy;
                    if (nx >= 0 && nx < w && ny >= 0 && ny < h) {
                        s += in[ny * w + nx]; c++;
                    }
                }
            }
            out[y * w + x] = s / c;
        }
    """,
    ).build()
    kernel = cl.Kernel(prg, "gblur")
    _OCL["ctx"], _OCL["queue"], _OCL["prg"], _OCL["kernel"] = ctx, queue, prg, kernel
    return _OCL


def gaussian_blur(mask, sigma: float, kernel=None):
    """
    Hardware-aware Gaussian blur.
      - large masks (>= _GPU_MIN_PIXELS) : GPU box blur via PyOpenCL.
      - small masks                      : OpenCV CPU blur (faster).
      Falls back to CPU automatically on any OpenCL failure.
    """
    import numpy as np

    try:
        if mask.size >= _GPU_MIN_PIXELS:
            import pyopencl as cl

            res = _ocl_resources()
            ctx, queue, kernel = res["ctx"], res["queue"], res["kernel"]
            m = np.ascontiguousarray(mask, dtype=np.float32)
            k = int(max(3, sigma * 2.5))
            if k % 2 == 0:
                k += 1
            h, w = m.shape
            mf = cl.mem_flags
            m_buf = cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=m)
            o_buf = cl.Buffer(ctx, mf.WRITE_ONLY, m.nbytes)
            kernel(queue, (w, h), None, m_buf, o_buf, np.int32(w), np.int32(h), np.int32(k))
            res_arr = np.empty_like(m)
            cl.enqueue_copy(queue, res_arr, o_buf)
            return res_arr.astype(mask.dtype)
    except Exception:
        logger.debug("OpenCL GPU blur failed, falling back to CPU")
        pass
    import cv2

    return cv2.GaussianBlur(mask, (0, 0), sigma)


# ----------------------------------------------------------------------
# Optional CPU-parallel frame processing (used only for very long videos).
# ----------------------------------------------------------------------


def _worker_pool(chunk, worker, params):
    return [worker(f, params) for f in chunk]


def parallel_map(worker, frames, params=None, min_total: int = 500):
    """
    Apply `worker(frame, params)` to every frame.
    Uses a process pool when it is clearly worth it, else serial.
    """
    cores = detect_cpu_cores()
    total = len(frames)
    if total < min_total or cores < 2:
        return [worker(f, params) for f in frames]

    n = min(cores, total)
    chunk = max(1, total // n)
    chunks = [frames[i : i + chunk] for i in range(0, total, chunk)]

    try:
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=n) as pool:
            results = pool.starmap(_worker_pool, [(c, worker, params) for c in chunks])
        out = []
        for r in results:
            out.extend(r)
        return out
    except Exception:
        return [worker(f, params) for f in frames]
