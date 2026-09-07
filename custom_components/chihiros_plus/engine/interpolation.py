"""Interpolation helpers for the Aquarium Light Engine.

Pure math. Knows nothing about Bluetooth, Home Assistant, or Chihiros.
"""
from __future__ import annotations

from collections.abc import Sequence


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolate between a and b for t in [0, 1]."""
    return a + (b - a) * t


def sample_curve(keyframes: Sequence[tuple[float, float]], x: float) -> float:
    """Sample a piecewise-linear curve at x.

    ``keyframes`` is a list of (x, y) sorted ascending by x. Values before the
    first / after the last keyframe clamp to the nearest endpoint. This gives
    smooth ramps (sunrise/sunset) rather than stepped output.
    """
    if not keyframes:
        raise ValueError("no keyframes")
    if x <= keyframes[0][0]:
        return keyframes[0][1]
    if x >= keyframes[-1][0]:
        return keyframes[-1][1]
    for i in range(len(keyframes) - 1):
        x0, y0 = keyframes[i]
        x1, y1 = keyframes[i + 1]
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            return lerp(y0, y1, (x - x0) / (x1 - x0))
    return keyframes[-1][1]  # pragma: no cover - unreachable given clamps
