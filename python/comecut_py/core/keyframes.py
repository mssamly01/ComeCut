"""Small keyframe evaluation helpers shared by preview, UI, and render code."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def evaluate_keyframes(
    keyframes: Sequence[Any],
    time_seconds: float,
    *,
    default: float = 0.0,
) -> float:
    """Evaluate a sorted keyframe list with linear interpolation."""
    if not keyframes:
        return float(default)
    t = max(0.0, float(time_seconds))
    ordered = sorted(keyframes, key=lambda k: float(k.time))
    if t <= float(ordered[0].time):
        return float(ordered[0].value)
    for left, right in zip(ordered, ordered[1:], strict=False):
        t0 = float(left.time)
        t1 = float(right.time)
        if t <= t1:
            if t1 <= t0:
                return float(right.value)
            ratio = (t - t0) / (t1 - t0)
            return float(left.value) + (float(right.value) - float(left.value)) * ratio
    return float(ordered[-1].value)


def evaluate_clip_keyframes(
    clip: Any,
    property_name: str,
    time_seconds: float,
    *,
    default: float,
) -> float:
    """Evaluate ``<property>_keyframes`` on a clip, falling back to ``default``."""
    keyframes = getattr(clip, f"{property_name}_keyframes", None) or []
    return evaluate_keyframes(keyframes, time_seconds, default=default)


__all__ = ["evaluate_clip_keyframes", "evaluate_keyframes"]
