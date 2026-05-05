"""CapCut-inspired V2 project schema for ``draft_content.json``.

The editor still works with the legacy in-memory Project model. This schema is
only the on-disk draft shape: microsecond timing, tracks with segments, and a
materials pool referenced by ``material_id``.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, NonNegativeFloat, NonNegativeInt, PositiveInt


DRAFT_CONTENT_VERSION: int = 1
APP_VERSION: str = "1.0.0"
US_PER_SECOND: int = 1_000_000


def seconds_to_us(seconds: float | None) -> int:
    if seconds is None:
        return 0
    return int(round(float(seconds) * US_PER_SECOND))


def us_to_seconds(us: int | None) -> float:
    if us is None:
        return 0.0
    return float(us) / US_PER_SECOND


def new_id() -> str:
    return str(uuid.uuid4()).upper()


class TimeRange(BaseModel):
    start: NonNegativeInt = 0
    duration: NonNegativeInt = 0


class Vec2(BaseModel):
    x: float = 0.0
    y: float = 0.0


class Scale2(BaseModel):
    x: float = 1.0
    y: float = 1.0


class Flip(BaseModel):
    horizontal: bool = False
    vertical: bool = False


class ClipTransform(BaseModel):
    scale: Scale2 = Field(default_factory=Scale2)
    transform: Vec2 = Field(default_factory=Vec2)
    rotation: float = 0.0
    alpha: float = Field(1.0, ge=0.0, le=1.0)
    flip: Flip = Field(default_factory=Flip)


class CanvasConfig(BaseModel):
    width: PositiveInt = 1920
    height: PositiveInt = 1080
    ratio: str = "16:9"
    background: str | None = None


class VideoMaterial(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["video"] = "video"
    path: str = ""
    proxy_path: str | None = None
    duration: NonNegativeInt = 0
    width: NonNegativeInt = 0
    height: NonNegativeInt = 0
    has_audio: bool = True
    name: str = ""


class AudioMaterial(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["audio"] = "audio"
    path: str = ""
    duration: NonNegativeInt = 0
    name: str = ""


class TextMaterial(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["text"] = "text"
    text_main: str = ""
    text_second: str = ""
    text_display: Literal["main", "second", "bilingual"] = "main"
    font_family: str = "Verdana"
    font_size: PositiveInt = 36
    color: str = "#ffffff"
    second_font_size: PositiveInt = 36
    second_color: str = "#ffffff"
    stroke_color: str = "#000000"
    stroke_width: NonNegativeInt = 2


class ImageMaterial(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["image"] = "image"
    path: str = ""
    name: str = ""


class EffectMaterial(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["effect"] = "effect"
    blur: float = 0.0
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    grayscale: bool = False
    rotate: float = 0.0
    hflip: bool = False
    vflip: bool = False


class AudioEffectMaterial(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["audio_effect"] = "audio_effect"
    fade_in: float = 0.0
    fade_out: float = 0.0
    pitch_semitones: float = 0.0
    formant_shift: float = 0.0
    chorus_depth: float = 0.0
    voice_preset_id: str = ""
    denoise: bool = False
    denoise_method: Literal["afftdn", "rnnoise"] = "afftdn"
    denoise_model: str | None = None
    normalize: bool = False


class CropMaterial(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["crop"] = "crop"
    x: NonNegativeInt = 0
    y: NonNegativeInt = 0
    width: PositiveInt = 1
    height: PositiveInt = 1


class ChromaMaterial(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["chroma"] = "chroma"
    color: str = "0x00FF00"
    similarity: float = 0.1
    blend: float = 0.0


class TransitionMaterial(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["transition"] = "transition"
    kind: str = "fade"
    duration: NonNegativeInt = 1_000_000
    from_segment_id: str = ""
    to_segment_id: str = ""


class Materials(BaseModel):
    videos: list[VideoMaterial] = Field(default_factory=list)
    audios: list[AudioMaterial] = Field(default_factory=list)
    texts: list[TextMaterial] = Field(default_factory=list)
    images: list[ImageMaterial] = Field(default_factory=list)
    effects: list[EffectMaterial] = Field(default_factory=list)
    audio_effects: list[AudioEffectMaterial] = Field(default_factory=list)
    crops: list[CropMaterial] = Field(default_factory=list)
    chromas: list[ChromaMaterial] = Field(default_factory=list)
    transitions: list[TransitionMaterial] = Field(default_factory=list)


class KeyframeV2(BaseModel):
    time: NonNegativeInt = 0
    value: float = 0.0


class KeyframeGroup(BaseModel):
    id: str = Field(default_factory=new_id)
    property_name: str = ""
    keyframes: list[KeyframeV2] = Field(default_factory=list)


class Segment(BaseModel):
    id: str = Field(default_factory=new_id)
    material_id: str
    source_timerange: TimeRange | None = None
    target_timerange: TimeRange = Field(default_factory=TimeRange)
    speed: float = Field(1.0, gt=0.0)
    volume: NonNegativeFloat = 1.0
    reverse: bool = False
    visible: bool = True
    clip: ClipTransform = Field(default_factory=ClipTransform)
    extra_material_refs: list[str] = Field(default_factory=list)
    pip_scale: float | None = None
    pip_pos_x: int | None = None
    pip_pos_y: int | None = None
    opacity_keyframes: list[KeyframeV2] = Field(default_factory=list)
    x_keyframes: list[KeyframeV2] = Field(default_factory=list)
    y_keyframes: list[KeyframeV2] = Field(default_factory=list)
    voice_preset_id: str = ""


class TrackV2(BaseModel):
    id: str = Field(default_factory=new_id)
    type: Literal["video", "audio", "text", "image"] = "video"
    name: str = ""
    locked: bool = False
    hidden: bool = False
    muted: bool = False
    segments: list[Segment] = Field(default_factory=list)


class ProjectV2(BaseModel):
    id: str = Field(default_factory=new_id)
    version: int = DRAFT_CONTENT_VERSION
    app_version: str = APP_VERSION
    name: str = "Untitled"
    duration: NonNegativeInt = 0
    fps: float = Field(30.0, gt=0.0)
    sample_rate: PositiveInt = 48_000
    create_time: NonNegativeInt = 0
    update_time: NonNegativeInt = 0
    canvas_config: CanvasConfig = Field(default_factory=CanvasConfig)
    tracks: list[TrackV2] = Field(default_factory=list)
    materials: Materials = Field(default_factory=Materials)
    keyframes: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "APP_VERSION",
    "DRAFT_CONTENT_VERSION",
    "US_PER_SECOND",
    "AudioEffectMaterial",
    "AudioMaterial",
    "CanvasConfig",
    "ChromaMaterial",
    "ClipTransform",
    "CropMaterial",
    "EffectMaterial",
    "Flip",
    "ImageMaterial",
    "KeyframeGroup",
    "KeyframeV2",
    "Materials",
    "ProjectV2",
    "Scale2",
    "Segment",
    "TextMaterial",
    "TimeRange",
    "TrackV2",
    "TransitionMaterial",
    "Vec2",
    "VideoMaterial",
    "new_id",
    "seconds_to_us",
    "us_to_seconds",
]
