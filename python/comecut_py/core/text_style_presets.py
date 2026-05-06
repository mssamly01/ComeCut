"""Text style preset helpers built on top of local JSON presets."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from .local_presets import (
    LocalPreset,
    list_local_presets,
    load_local_preset,
    save_local_preset,
)
from .project import Clip, TextDisplayMode


TEXT_STYLE_SCHEMA = "comecut.text_style.v1"
TEXT_STYLE_FIELDS = (
    "text_display",
    "text_font_family",
    "text_font_size",
    "text_color",
    "text_second_font_size",
    "text_second_color",
    "text_stroke_color",
    "text_stroke_width",
)
_DISPLAY_MODES = {"main", "second", "bilingual"}


def _require_text_clip(clip: Clip) -> None:
    if not clip.is_text_clip:
        raise ValueError("Text style presets can only be used with text clips")


def _coerce_display(value: Any) -> TextDisplayMode:
    mode = str(value or "main").strip().lower()
    if mode not in _DISPLAY_MODES:
        return "main"
    return cast(TextDisplayMode, mode)


def _coerce_positive_int(value: Any, default: int, *, minimum: int = 8) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _coerce_stroke_width(value: Any, default: int = 2) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(12, parsed))


def _coerce_color(value: Any, default: str) -> str:
    color = str(value or "").strip()
    if len(color) == 7 and color.startswith("#"):
        return color.lower()
    return default


def text_style_payload_from_clip(clip: Clip) -> dict[str, Any]:
    """Return a JSON-safe style payload without copying text content."""
    _require_text_clip(clip)
    return {
        "schema": TEXT_STYLE_SCHEMA,
        "text_display": clip.text_display,
        "text_font_family": (clip.text_font_family or "Verdana").strip() or "Verdana",
        "text_font_size": int(clip.text_font_size),
        "text_color": _coerce_color(clip.text_color, "#ffffff"),
        "text_second_font_size": int(clip.text_second_font_size),
        "text_second_color": _coerce_color(clip.text_second_color, "#ffffff"),
        "text_stroke_color": _coerce_color(clip.text_stroke_color, "#000000"),
        "text_stroke_width": int(clip.text_stroke_width),
    }


def apply_text_style_payload(clip: Clip, payload: dict[str, Any]) -> Clip:
    """Apply a text style payload to ``clip`` while preserving content/timing."""
    _require_text_clip(clip)
    if not isinstance(payload, dict):
        raise TypeError("Text style payload must be a JSON object")

    clip.text_display = _coerce_display(payload.get("text_display", clip.text_display))
    clip.text_font_family = (
        str(payload.get("text_font_family", clip.text_font_family) or "").strip()
        or "Verdana"
    )
    clip.text_font_size = _coerce_positive_int(
        payload.get("text_font_size", clip.text_font_size),
        int(clip.text_font_size),
    )
    clip.text_color = _coerce_color(payload.get("text_color", clip.text_color), clip.text_color)
    clip.text_second_font_size = _coerce_positive_int(
        payload.get("text_second_font_size", clip.text_second_font_size),
        int(clip.text_second_font_size),
    )
    clip.text_second_color = _coerce_color(
        payload.get("text_second_color", clip.text_second_color),
        clip.text_second_color,
    )
    clip.text_stroke_color = _coerce_color(
        payload.get("text_stroke_color", clip.text_stroke_color),
        clip.text_stroke_color,
    )
    clip.text_stroke_width = _coerce_stroke_width(
        payload.get("text_stroke_width", clip.text_stroke_width),
        int(clip.text_stroke_width),
    )
    return clip


def copy_text_style(source: Clip, target: Clip) -> Clip:
    """Copy style/display between text clips without changing their content."""
    return apply_text_style_payload(target, text_style_payload_from_clip(source))


def save_text_style_preset(
    name: str,
    clip: Clip,
    *,
    root: Path | None = None,
) -> Path:
    return save_local_preset("text", name, text_style_payload_from_clip(clip), root=root)


def load_text_style_preset(name: str, *, root: Path | None = None) -> LocalPreset:
    return load_local_preset("text", name, root=root)


def list_text_style_presets(*, root: Path | None = None) -> list[LocalPreset]:
    return list_local_presets("text", root=root)


def apply_text_style_preset(
    clip: Clip,
    name: str,
    *,
    root: Path | None = None,
) -> LocalPreset:
    preset = load_text_style_preset(name, root=root)
    apply_text_style_payload(clip, preset.payload)
    return preset


__all__ = [
    "TEXT_STYLE_FIELDS",
    "TEXT_STYLE_SCHEMA",
    "apply_text_style_payload",
    "apply_text_style_preset",
    "copy_text_style",
    "list_text_style_presets",
    "load_text_style_preset",
    "save_text_style_preset",
    "text_style_payload_from_clip",
]
