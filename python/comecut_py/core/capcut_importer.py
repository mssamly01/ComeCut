"""Import CapCut ``draft_content.json`` files into ComeCut.

CapCut draft JSON is a superset of ComeCut's V2 draft shape: it uses the
same materials-pool topology and microsecond timing, but includes many
material categories and segment fields that ComeCut does not understand.
This module reads only the fields ComeCut can use and produces an in-memory
``Project``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .project import Clip, ClipEffects, Project, Track


US_PER_SECOND = 1_000_000
_KNOWN_MIN_VERSION = 100_000

# Matches ``##_draftpath_placeholder_<UUID>_##/rest/of/path``.
_PLACEHOLDER_RE = re.compile(r"^##_draftpath_placeholder_[0-9A-Fa-f-]+_##(.*)$")


def _us_to_seconds(us: Any) -> float:
    if us is None:
        return 0.0
    try:
        return float(us) / US_PER_SECOND
    except (TypeError, ValueError):
        return 0.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def is_capcut_format(data: dict) -> bool:
    """Return ``True`` if *data* looks like a CapCut ``draft_content.json``.

    Detection priority, most-specific first:
    1. ``version`` is an int >= 100000 (CapCut versioning starts at 360000).
    2. ``new_version`` is a non-empty semver-ish string (for example "153.0.0").
    3. ``materials`` contains categories currently treated as CapCut-only.
    """
    if not isinstance(data, dict):
        return False

    version = data.get("version")
    if isinstance(version, int) and version >= _KNOWN_MIN_VERSION:
        return True

    new_version = data.get("new_version")
    if isinstance(new_version, str) and new_version.strip():
        return True

    materials = data.get("materials")
    if isinstance(materials, dict):
        capcut_only = {
            "speeds",
            "beats",
            "vocal_separations",
            "sound_channel_mappings",
            "placeholder_infos",
            "material_animations",
        }
        if any(key in materials for key in capcut_only):
            return True

    return False


def _resolve_path(raw: Any, draft_dir: Path) -> str:
    """Resolve a CapCut path that may contain a draft placeholder."""
    if not raw:
        return ""
    path_text = str(raw)
    match = _PLACEHOLDER_RE.match(path_text)
    if match:
        rel = match.group(1).lstrip("/").lstrip("\\")
        return str((draft_dir / rel).resolve())
    return path_text


def _color_array_to_hex(color: list) -> str | None:
    """Convert an RGB float list in the range 0..1 to ``#rrggbb``."""
    if not isinstance(color, list) or len(color) < 3:
        return None
    try:
        rgb = [int(round(max(0.0, min(1.0, float(c))) * 255)) for c in color[:3]]
    except (TypeError, ValueError):
        return None
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _normalize_hex_color(value: Any, default: str) -> str:
    if not value:
        return default
    text = str(value).strip()
    if not text:
        return default
    if not text.startswith("#"):
        text = f"#{text.lstrip('#')}"
    return text.lower()


def _parse_text_content(content_str: str) -> dict[str, Any]:
    """Parse CapCut's JSON-in-JSON text material ``content`` field."""
    out: dict[str, Any] = {}
    if not content_str:
        return out
    try:
        parsed = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return out

    if isinstance(parsed.get("text"), str):
        out["text"] = parsed["text"]

    styles = parsed.get("styles")
    if isinstance(styles, list) and styles:
        first = styles[0]
        if isinstance(first, dict):
            fill = first.get("fill", {})
            if isinstance(fill, dict):
                solid = (fill.get("content") or {}).get("solid", {})
                if isinstance(solid, dict):
                    color = _color_array_to_hex(solid.get("color"))
                    if color:
                        out["color"] = color

            font = first.get("font")
            if isinstance(font, dict) and font.get("path"):
                out["font_path"] = font["path"]

            size = first.get("size")
            if isinstance(size, (int, float)):
                out["font_size_norm"] = float(size)

    return out


def _video_material(material: dict, draft_dir: Path) -> dict[str, Any]:
    raw_path = material.get("path") or ""
    return {
        "id": material.get("id", ""),
        "path": _resolve_path(raw_path, draft_dir),
        "duration": _safe_int(material.get("duration")),
        "width": _safe_int(material.get("width")),
        "height": _safe_int(material.get("height")),
        "has_audio": bool(material.get("has_audio", True)),
        "name": material.get("material_name") or Path(str(raw_path)).name,
    }


def _audio_material(material: dict, draft_dir: Path) -> dict[str, Any]:
    raw_path = material.get("path") or ""
    return {
        "id": material.get("id", ""),
        "path": _resolve_path(raw_path, draft_dir),
        "duration": _safe_int(material.get("duration")),
        "name": material.get("name") or Path(str(raw_path)).name,
    }


def _text_material(material: dict) -> dict[str, Any]:
    parsed = _parse_text_content(material.get("content", ""))
    text_main = parsed.get("text") or material.get("name") or ""

    color = _normalize_hex_color(
        material.get("text_color") or parsed.get("color"),
        "#ffffff",
    )

    font_size = _safe_int(material.get("text_size"), default=36)
    if font_size <= 0:
        font_size = 36

    border_color = _normalize_hex_color(material.get("border_color"), "#000000")
    border_width_norm = _safe_float(material.get("border_width"), default=0.0)
    border_width_px = int(round(border_width_norm * 100)) if border_width_norm > 0 else 0
    border_width_px = max(0, min(12, border_width_px))

    font_family = "Verdana"
    font_path = material.get("font_path") or parsed.get("font_path", "")
    if font_path:
        font_family = Path(str(font_path)).stem or font_family

    return {
        "id": material.get("id", ""),
        "text_main": text_main,
        "color": color,
        "font_size": font_size,
        "stroke_color": border_color,
        "stroke_width": border_width_px,
        "font_family": font_family,
    }


def _segment_clip_transform(seg: dict) -> dict[str, float | bool]:
    clip = seg.get("clip") or {}
    scale = clip.get("scale") or {}
    transform = clip.get("transform") or {}
    flip = clip.get("flip") or {}
    return {
        "scale_x": _safe_float(scale.get("x"), 1.0),
        "scale_y": _safe_float(scale.get("y"), 1.0),
        "pos_x": _safe_float(transform.get("x"), 0.0),
        "pos_y": _safe_float(transform.get("y"), 0.0),
        "rotation": _safe_float(clip.get("rotation"), 0.0),
        "alpha": _safe_float(clip.get("alpha"), 1.0),
        "hflip": bool(flip.get("horizontal", False)),
        "vflip": bool(flip.get("vertical", False)),
    }


def _apply_tone_modify(clip: Clip, tone_code: int) -> None:
    if not tone_code:
        return
    _REVERSE_MAP = {
        1: "kid_girl", 2: "kid_boy", 3: "robot", 4: "monster",
        5: "elder", 6: "helium", 7: "lofi",
    }
    preset_id = _REVERSE_MAP.get(tone_code)
    if preset_id:
        from .voice_presets import apply_preset
        apply_preset(clip.audio_effects, preset_id)


def _build_video_clip(seg: dict, mat: dict) -> Clip:
    src = seg.get("source_timerange") or {}
    tgt = seg.get("target_timerange") or {}
    speed = _safe_float(seg.get("speed"), 1.0) or 1.0

    in_pt = _us_to_seconds(src.get("start"))
    src_dur = _safe_int(src.get("duration"))
    if src_dur <= 0:
        tgt_dur = _safe_int(tgt.get("duration"))
        src_dur = int(round(tgt_dur * speed))

    out_pt = _us_to_seconds(src.get("start", 0) + src_dur) if src_dur > 0 else None

    tform = _segment_clip_transform(seg)
    eff = ClipEffects(
        rotate=float(tform["rotation"]),
        hflip=bool(tform["hflip"]),
        vflip=bool(tform["vflip"]),
    )

    scale_x = max(0.01, min(5.0, float(tform["scale_x"])))
    scale_y = max(0.01, min(5.0, float(tform["scale_y"])))
    pos_x = int(tform["pos_x"]) if tform["pos_x"] != 0 else None
    pos_y = int(tform["pos_y"]) if tform["pos_y"] != 0 else None
    scale: float | None
    if abs(scale_x - scale_y) <= 1e-9:
        scale = scale_x
        if scale == 1.0 and pos_x is None and pos_y is None:
            scale = None
        scale_x = None
        scale_y = None
    else:
        scale = None

    clip = Clip(
        clip_type="media",
        source=mat["path"],
        in_point=in_pt,
        out_point=out_pt,
        start=_us_to_seconds(tgt.get("start")),
        speed=speed,
        volume=_safe_float(seg.get("volume"), 1.0),
        reverse=bool(seg.get("reverse", False)),
        scale=scale,
        scale_x=scale_x,
        scale_y=scale_y,
        pos_x=pos_x,
        pos_y=pos_y,
        effects=eff,
    )
    tone_code = _safe_int(seg.get("tone_modify"), 0)
    if tone_code:
        _apply_tone_modify(clip, tone_code)
    return clip


def _build_audio_clip(
    seg: dict,
    mat: dict,
    fade_lookup: dict[str, dict[str, Any]] | None = None,
) -> Clip:
    src = seg.get("source_timerange") or {}
    tgt = seg.get("target_timerange") or {}
    speed = _safe_float(seg.get("speed"), 1.0) or 1.0

    in_pt = _us_to_seconds(src.get("start"))
    src_dur = _safe_int(src.get("duration"))
    if src_dur <= 0:
        src_dur = int(round(_safe_int(tgt.get("duration")) * speed))

    out_pt = _us_to_seconds(src.get("start", 0) + src_dur) if src_dur > 0 else None
    clip = Clip(
        clip_type="media",
        source=mat["path"],
        in_point=in_pt,
        out_point=out_pt,
        start=_us_to_seconds(tgt.get("start")),
        speed=speed,
        volume=_safe_float(seg.get("volume"), 1.0),
    )
    tone_code = _safe_int(seg.get("tone_modify"), 0)
    if tone_code:
        _apply_tone_modify(clip, tone_code)
    if fade_lookup:
        for ref_id in (seg.get("extra_material_refs") or []):
            fade_mat = fade_lookup.get(ref_id)
            if not fade_mat:
                continue
            clip.audio_effects.fade_in = _us_to_seconds(fade_mat.get("fade_in_duration", 0))
            clip.audio_effects.fade_out = _us_to_seconds(fade_mat.get("fade_out_duration", 0))
            break
    return clip


def _build_text_clip(seg: dict, mat: dict) -> Clip:
    tgt = seg.get("target_timerange") or {}
    duration_us = _safe_int(tgt.get("duration"))
    duration_s = _us_to_seconds(duration_us) if duration_us > 0 else 0.001
    return Clip(
        clip_type="text",
        source="",
        in_point=0.0,
        out_point=duration_s,
        start=_us_to_seconds(tgt.get("start")),
        text_main=mat.get("text_main", ""),
        text_color=mat.get("color", "#ffffff"),
        text_font_size=mat.get("font_size", 36),
        text_font_family=mat.get("font_family", "Verdana"),
        text_stroke_color=mat.get("stroke_color", "#000000"),
        text_stroke_width=mat.get("stroke_width", 0),
    )


def import_capcut_draft(path: str | Path) -> Project:
    """Read a CapCut ``draft_content.json`` and return a ComeCut ``Project``."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"CapCut draft not found: {path}")

    draft_dir = path.parent
    raw = json.loads(path.read_text(encoding="utf-8"))

    if not is_capcut_format(raw):
        raise ValueError(
            f"{path} does not look like a CapCut draft_content.json "
            f"(expected version >= {_KNOWN_MIN_VERSION})"
        )

    materials = raw.get("materials") or {}

    videos: dict[str, dict[str, Any]] = {}
    for item in materials.get("videos") or []:
        if isinstance(item, dict) and item.get("id"):
            videos[item["id"]] = _video_material(item, draft_dir)

    audios: dict[str, dict[str, Any]] = {}
    for item in materials.get("audios") or []:
        if isinstance(item, dict) and item.get("id"):
            audios[item["id"]] = _audio_material(item, draft_dir)

    texts: dict[str, dict[str, Any]] = {}
    for item in materials.get("texts") or []:
        if isinstance(item, dict) and item.get("id"):
            texts[item["id"]] = _text_material(item)
    fade_lookup: dict[str, dict[str, Any]] = {}
    for item in materials.get("audio_fades") or []:
        if isinstance(item, dict) and item.get("id"):
            fade_lookup[str(item["id"])] = item

    tracks: list[Track] = []
    for raw_track in raw.get("tracks") or []:
        if not isinstance(raw_track, dict):
            continue

        track_type = raw_track.get("type") or "video"
        if track_type not in ("video", "audio", "text"):
            continue

        track = Track(
            kind=track_type,
            name=str(raw_track.get("name") or ""),
            locked=bool(raw_track.get("locked", False)),
            hidden=bool(raw_track.get("hidden", False)),
            muted=bool(raw_track.get("muted", False)),
        )

        for seg in raw_track.get("segments") or []:
            if not isinstance(seg, dict):
                continue

            material_id = seg.get("material_id")
            if not material_id:
                continue

            clip: Clip | None = None
            if track_type == "video" and material_id in videos:
                clip = _build_video_clip(seg, videos[material_id])
            elif track_type == "audio" and material_id in audios:
                clip = _build_audio_clip(seg, audios[material_id], fade_lookup=fade_lookup)
            elif track_type == "text" and material_id in texts:
                clip = _build_text_clip(seg, texts[material_id])

            if clip is not None:
                track.clips.append(clip)

        tracks.append(track)

    canvas = raw.get("canvas_config") or {}
    width = _safe_int(canvas.get("width"), 1920)
    height = _safe_int(canvas.get("height"), 1080)
    name = raw.get("name") or path.stem or "Imported CapCut"

    return Project(
        name=name,
        width=width,
        height=height,
        fps=_safe_float(raw.get("fps"), 30.0),
        sample_rate=48_000,
        tracks=tracks,
    )


__all__ = [
    "import_capcut_draft",
    "is_capcut_format",
]
