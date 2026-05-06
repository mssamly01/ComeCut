"""Local JSON presets for libass subtitle styles."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

from .local_presets import (
    LocalPreset,
    list_local_presets,
    load_local_preset,
    save_local_preset,
)
from ..subtitles.style import SubtitleStyle


SUBTITLE_STYLE_SCHEMA = "comecut.subtitle_style.v1"
SUBTITLE_STYLE_FIELDS = tuple(field.name for field in fields(SubtitleStyle))


def _coerce_optional_int(value: Any, *, minimum: int = 0) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected integer, got {value!r}") from exc
    if parsed < minimum:
        raise ValueError(f"Expected integer >= {minimum}, got {parsed}")
    return parsed


def _coerce_optional_float(value: Any, *, minimum: float = 0.0) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected number, got {value!r}") from exc
    if parsed < minimum:
        raise ValueError(f"Expected number >= {minimum}, got {parsed}")
    return parsed


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"Expected boolean, got {value!r}")


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_border_style(value: Any) -> int | None:
    parsed = _coerce_optional_int(value, minimum=1)
    if parsed is None:
        return None
    if parsed not in (1, 3):
        raise ValueError("Subtitle border_style must be 1 or 3")
    return parsed


def _coerce_alignment(value: Any) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        parsed = value
    else:
        text = str(value).strip()
        if text.isdigit():
            parsed = int(text)
        else:
            return text or None
    if not 1 <= parsed <= 9:
        raise ValueError("Subtitle alignment integer must be 1..9")
    return parsed


def subtitle_style_payload_from_style(style: SubtitleStyle) -> dict[str, Any]:
    """Return a JSON-safe payload with only explicitly configured fields."""
    payload: dict[str, Any] = {"schema": SUBTITLE_STYLE_SCHEMA}
    for field_name in SUBTITLE_STYLE_FIELDS:
        value = getattr(style, field_name)
        if value is not None:
            payload[field_name] = value
    return payload


def subtitle_style_from_payload(payload: dict[str, Any]) -> SubtitleStyle:
    if not isinstance(payload, dict):
        raise TypeError("Subtitle style payload must be a JSON object")
    kwargs: dict[str, Any] = {}
    if "font_name" in payload:
        kwargs["font_name"] = _coerce_optional_str(payload.get("font_name"))
    if "font_size" in payload:
        kwargs["font_size"] = _coerce_optional_int(payload.get("font_size"), minimum=1)
    if "primary_colour" in payload:
        kwargs["primary_colour"] = _coerce_optional_str(payload.get("primary_colour"))
    if "outline_colour" in payload:
        kwargs["outline_colour"] = _coerce_optional_str(payload.get("outline_colour"))
    if "back_colour" in payload:
        kwargs["back_colour"] = _coerce_optional_str(payload.get("back_colour"))
    if "bold" in payload:
        kwargs["bold"] = _coerce_optional_bool(payload.get("bold"))
    if "italic" in payload:
        kwargs["italic"] = _coerce_optional_bool(payload.get("italic"))
    if "outline" in payload:
        kwargs["outline"] = _coerce_optional_float(payload.get("outline"), minimum=0.0)
    if "shadow" in payload:
        kwargs["shadow"] = _coerce_optional_float(payload.get("shadow"), minimum=0.0)
    if "border_style" in payload:
        kwargs["border_style"] = _coerce_border_style(payload.get("border_style"))
    if "alignment" in payload:
        kwargs["alignment"] = _coerce_alignment(payload.get("alignment"))
    if "margin_l" in payload:
        kwargs["margin_l"] = _coerce_optional_int(payload.get("margin_l"), minimum=0)
    if "margin_r" in payload:
        kwargs["margin_r"] = _coerce_optional_int(payload.get("margin_r"), minimum=0)
    if "margin_v" in payload:
        kwargs["margin_v"] = _coerce_optional_int(payload.get("margin_v"), minimum=0)

    style = SubtitleStyle(**kwargs)
    # Validate colour/alignment strings eagerly so broken presets fail at load time.
    style.to_force_style()
    return style


def save_subtitle_style_preset(
    name: str,
    style: SubtitleStyle,
    *,
    root: Path | None = None,
) -> Path:
    return save_local_preset("subtitle", name, subtitle_style_payload_from_style(style), root=root)


def load_subtitle_style_preset(name: str, *, root: Path | None = None) -> LocalPreset:
    return load_local_preset("subtitle", name, root=root)


def load_subtitle_style_from_preset(
    name: str,
    *,
    root: Path | None = None,
) -> SubtitleStyle:
    return subtitle_style_from_payload(load_subtitle_style_preset(name, root=root).payload)


def list_subtitle_style_presets(*, root: Path | None = None) -> list[LocalPreset]:
    return list_local_presets("subtitle", root=root)


def merge_subtitle_force_styles(
    *styles: str | SubtitleStyle | None,
) -> str | None:
    parts: list[str] = []
    for style in styles:
        if style is None:
            continue
        if isinstance(style, SubtitleStyle):
            text = style.to_force_style()
        else:
            text = str(style).strip()
        if text:
            parts.append(text)
    return ",".join(parts) or None


__all__ = [
    "SUBTITLE_STYLE_FIELDS",
    "SUBTITLE_STYLE_SCHEMA",
    "list_subtitle_style_presets",
    "load_subtitle_style_from_preset",
    "load_subtitle_style_preset",
    "merge_subtitle_force_styles",
    "save_subtitle_style_preset",
    "subtitle_style_from_payload",
    "subtitle_style_payload_from_style",
]
