"""
Easing Module (AI Director support).
Professional easing curves so motion feels human and polished instead of
robotic linear motion.

All curves take p in [0,1] and return t in [0,1].

Named after the motion-design industry standard (Apple/Lightroom/GSAP):
  - ease_out        : cubic ease-out (default, universal enter)
  - ease_out_cubic  : alias of ease_out
  - ease_out_quart  : stronger ease-out (big/hero elements)
  - ease_out_quint  : strongest ease-out (dramatic)
  - ease_in         : cubic ease-in (exits from stillness)
  - ease_in_out     : smooth symmetric ease-in-out (camera/crossfade)
  - ease_out_back   : ease-out with a slight overshoot (pop)
  - apple           : Apple-style ease-out bezier (0.16,1,0.3,1)
  - material        : Material Design standard (0.4,0,0.2,1)
  - ease_out_expo   : exponential ease-out (fast start, long tail)
"""

import logging
import math

logger = logging.getLogger(__name__)

__all__ = ["clamp01", "ease_out", "ease_out_cubic", "ease_out_quart", "ease_out_quint"]


def clamp01(p):
    return min(max(float(p), 0.0), 1.0)


def ease_out(p):
    p = clamp01(p)
    return 1 - (1 - p) ** 3


def ease_out_cubic(p):
    return ease_out(p)


def ease_out_quart(p):
    p = clamp01(p)
    return 1 - (1 - p) ** 4


def ease_out_quint(p):
    p = clamp01(p)
    return 1 - (1 - p) ** 5


def ease_out_expo(p):
    p = clamp01(p)
    return 0 if p == 0 else 1 - 2 ** (-10 * p)


def ease_in(p):
    p = clamp01(p)
    return p**3


def ease_in_out(p):
    p = clamp01(p)
    if p < 0.5:
        return 4 * p * p * p
    return 1 - math.pow(-2 * p + 2, 3) / 2


def ease_out_back(p):
    p = clamp01(p)
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


def _bezier(t, x1, y1, x2, y2):
    """Evaluate a cubic-bezier defined by two control points at t."""
    t = clamp01(t)
    # solve x(t) for t so we can evaluate y(x)
    cx = 3.0 * x1
    bx = 3.0 * (x2 - x1) - cx
    ax = 1.0 - cx - bx

    # Newton-Raphson root find for x(t') = t
    t2 = t
    for _ in range(6):
        x = ((ax * t2 + bx) * t2 + cx) * t2
        if abs(x - t) < 1e-6:
            break
        dx = (3 * ax * t2 + 2 * bx) * t2 + cx
        if abs(dx) < 1e-6:
            break
        t2 = t2 - (x - t) / dx
    t2 = clamp01(t2)

    cy = 3.0 * y1
    by = 3.0 * (y2 - y1) - cy
    ay = 1.0 - cy - by
    return ((ay * t2 + by) * t2 + cy) * t2


def apple(p):
    return _bezier(p, 0.16, 1.0, 0.3, 1.0)


def material(p):
    return _bezier(p, 0.4, 0.0, 0.2, 1.0)


# Registry: naami curves jo effect director / scene engine use karti hain.
CURVES = {
    "ease_out": ease_out,
    "ease_out_cubic": ease_out_cubic,
    "ease_out_quart": ease_out_quart,
    "ease_out_quint": ease_out_quint,
    "ease_out_expo": ease_out_expo,
    "ease_in": ease_in,
    "ease_in_out": ease_in_out,
    "ease_out_back": ease_out_back,
    "apple": apple,
    "material": material,
}


def apply(name, p):
    name = name or "ease_out"
    fn = CURVES.get(name, ease_out)
    return fn(clamp01(p))
