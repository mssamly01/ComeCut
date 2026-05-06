"""Local JSON presets for per-clip video effects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .local_presets import (
    LocalPreset,
    list_local_presets,
    load_local_preset,
    save_local_preset,
)
from .project import Clip, ClipEffects


EFFECT_PRESET_SCHEMA = "comecut.effect.v1"
EFFECT_PRESET_FIELDS = (
    "blur",
    "brightness",
    "contrast",
    "saturation",
    "grayscale",
    "crop",
    "rotate",
    "hflip",
    "vflip",
    "chromakey",
)


def _require_media_clip(clip: Clip) -> None:
    if clip.is_text_clip:
        raise ValueError("Effect presets can only be used with media clips")


def effect_payload_from_clip(clip: Clip) -> dict[str, Any]:
    """Return a JSON-safe effects payload without copying media/timing."""
    _require_media_clip(clip)
    effects = clip.effects.model_dump(mode="json")
    return {
        "schema": EFFECT_PRESET_SCHEMA,
        **{field: effects.get(field) for field in EFFECT_PRESET_FIELDS},
    }


def clip_effects_from_payload(payload: dict[str, Any]) -> ClipEffects:
    """Validate an effect preset payload and return a ``ClipEffects`` model."""
    if not isinstance(payload, dict):
        raise TypeError("Effect preset payload must be a JSON object")
    schema = payload.get("schema")
    if schema is not None and schema != EFFECT_PRESET_SCHEMA:
        raise ValueError(f"Unsupported effect preset schema: {schema!r}")
    data = {field: payload[field] for field in EFFECT_PRESET_FIELDS if field in payload}
    try:
        return ClipEffects.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Invalid effect preset payload: {exc}") from exc


def apply_effect_payload(clip: Clip, payload: dict[str, Any]) -> Clip:
    """Apply effects to ``clip`` while preserving source, timing, and audio."""
    _require_media_clip(clip)
    clip.effects = clip_effects_from_payload(payload)
    return clip


def copy_clip_effects(source: Clip, target: Clip) -> Clip:
    """Copy video effects between media clips only."""
    return apply_effect_payload(target, effect_payload_from_clip(source))


def save_effect_preset(
    name: str,
    clip: Clip,
    *,
    root: Path | None = None,
) -> Path:
    return save_local_preset("effect", name, effect_payload_from_clip(clip), root=root)


def load_effect_preset(name: str, *, root: Path | None = None) -> LocalPreset:
    return load_local_preset("effect", name, root=root)


def load_effects_from_preset(name: str, *, root: Path | None = None) -> ClipEffects:
    return clip_effects_from_payload(load_effect_preset(name, root=root).payload)


def list_effect_presets(*, root: Path | None = None) -> list[LocalPreset]:
    return list_local_presets("effect", root=root)


def apply_effect_preset(
    clip: Clip,
    name: str,
    *,
    root: Path | None = None,
) -> LocalPreset:
    preset = load_effect_preset(name, root=root)
    apply_effect_payload(clip, preset.payload)
    return preset


__all__ = [
    "EFFECT_PRESET_FIELDS",
    "EFFECT_PRESET_SCHEMA",
    "apply_effect_payload",
    "apply_effect_preset",
    "clip_effects_from_payload",
    "copy_clip_effects",
    "effect_payload_from_clip",
    "list_effect_presets",
    "load_effect_preset",
    "load_effects_from_preset",
    "save_effect_preset",
]
