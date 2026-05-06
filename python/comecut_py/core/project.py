"""Project / timeline data model.

A :class:`Project` is the root JSON-serialisable object describing an entire
edit. It contains one or more :class:`Track` s; each track contains
:class:`Clip` s (media references with in/out points and a timeline start).
Tracks may also contain :class:`TextOverlay` s for burn-in titles.

The model intentionally mirrors a subset of the browser app's concepts while
staying small and explicit — we want round-trip JSON I/O, not a pixel-perfect
clone of the original schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, NonNegativeFloat, PositiveInt, field_validator, model_validator

TrackKind = Literal["video", "audio", "text"]
TextDisplayMode = Literal["main", "second", "bilingual"]
AudioRole = Literal["voice", "music", "sfx", "ambience", "other"]

TransitionKind = Literal[
    "fade",
    "fadeblack",
    "fadewhite",
    "wipeleft",
    "wiperight",
    "slideleft",
    "slideright",
    "circleopen",
    "circleclose",
    "dissolve",
    "pixelize",
    "radial",
    "smoothleft",
    "smoothright",
]


class Transition(BaseModel):
    """A crossfade/wipe between two adjacent clips (same track, by index).

    ``from_index`` and ``to_index`` are positions in the owning :class:`Track`'s
    ``clips`` list — the transition overlaps the tail of ``from_index`` with the
    head of ``to_index`` by ``duration`` seconds. ``to_index`` should normally
    be ``from_index + 1``.
    """

    from_index: int = Field(..., ge=0)
    to_index: int = Field(..., ge=0)
    duration: float = Field(..., gt=0.0, description="Overlap duration in seconds.")
    kind: TransitionKind = "fade"

    @field_validator("to_index")
    @classmethod
    def _check_to(cls, v: int, info):
        frm = info.data.get("from_index", 0)
        if v <= frm:
            raise ValueError(f"to_index ({v}) must be greater than from_index ({frm})")
        return v


class CropRect(BaseModel):
    """A rectangular crop region in source pixels, applied before scaling."""

    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)


class ChromaKey(BaseModel):
    """Chroma-key (green/blue screen) parameters for ffmpeg's ``chromakey``.

    ``color`` accepts any ffmpeg colour spec (``0x00FF00``, ``#00ff00``, named
    colours). ``similarity`` widens the matched hue range; ``blend`` softens
    the alpha edge.
    """

    color: str = Field("0x00FF00", description="Key colour (hex or named).")
    similarity: float = Field(0.1, gt=0.0, le=1.0)
    blend: float = Field(0.0, ge=0.0, le=1.0)


class ClipAudioEffects(BaseModel):
    """Per-clip audio post-processing — fade / denoise / normalize / pitch.

    Every field defaults to a no-op so existing projects keep behaving
    identically. Filters are emitted by
    :func:`comecut_py.engine.render._audio_effect_chain` after
    ``volume``/``areverse``/``atempo`` so pitch and level shaping see the
    speed-corrected stream.
    """

    fade_in: float = Field(
        0.0,
        ge=0.0,
        description="Audio fade-in duration in seconds (anchored to clip start).",
    )
    fade_out: float = Field(
        0.0,
        ge=0.0,
        description="Audio fade-out duration in seconds (anchored to clip end).",
    )
    pitch_semitones: float = Field(
        0.0,
        ge=-24.0,
        le=24.0,
        description="Pitch shift in semitones via ffmpeg's ``rubberband`` filter.",
    )
    formant_shift: float = Field(
        0.0,
        ge=-12.0,
        le=12.0,
        description="Formant shift in semitones (rubberband ``formant`` arg). "
                    "Independent from ``pitch_semitones`` so a preset can shift "
                    "pitch up while keeping the timbre natural (e.g. helium = "
                    "pitch+formant up, kid voice = pitch up only).",
    )
    chorus_depth: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Chorus mix depth (0 = off, 1 = max). Rendered via ffmpeg "
                    "``chorus`` with fixed delay/decay. Used by 'Quái thú' / "
                    "'Robot' presets to give a doubled / metallic timbre.",
    )
    voice_preset_id: str = Field(
        "",
        description="Identifier of the active voice changer preset. Empty "
                    "means the user manually tweaked pitch/formant. Special "
                    "value ``'none'`` = explicit Reset. Preset IDs are "
                    "registered in :mod:`comecut_py.core.voice_presets`.",
    )
    denoise: bool = Field(
        False,
        description="Apply per-clip noise reduction. The filter family is "
                    "selected by ``denoise_method`` (default ``afftdn``).",
    )
    denoise_method: Literal["afftdn", "rnnoise"] = Field(
        "afftdn",
        description="Noise-reduction algorithm: ``afftdn`` (FFT-based, "
                    "ships with stock ffmpeg, no model required) or "
                    "``rnnoise`` (RNN-based via ffmpeg's ``arnndn`` filter; "
                    "requires a model file specified by ``denoise_model``).",
    )
    denoise_model: str | None = Field(
        None,
        description="Path to an ``.rnnn`` model file used by the "
                    "``arnndn`` filter when ``denoise_method='rnnoise'``. "
                    "Ignored for ``afftdn``. Models are available from "
                    "https://github.com/GregorR/rnnoise-models.",
    )
    normalize: bool = Field(
        False,
        description="Single-pass ``loudnorm`` (EBU R128) for quick level matching.",
    )


class ClipEffects(BaseModel):
    """Per-clip colour/filter effects applied at render time.

    Every field defaults to a no-op so projects that omit the block behave
    identically to before.
    """

    blur: float = Field(0.0, ge=0.0, description="Gaussian blur sigma (0 = off).")
    brightness: float = Field(
        0.0,
        ge=-1.0,
        le=1.0,
        description="Additive brightness in eq() units (-1..1).",
    )
    contrast: float = Field(
        1.0,
        ge=0.0,
        le=4.0,
        description="Contrast multiplier in eq() units (1 = no change).",
    )
    saturation: float = Field(
        1.0,
        ge=0.0,
        le=3.0,
        description="Saturation multiplier in eq() units (1 = no change).",
    )
    grayscale: bool = Field(False, description="Desaturate the clip entirely.")
    crop: CropRect | None = Field(
        None,
        description="Optional crop applied before scaling.",
    )
    rotate: float = Field(
        0.0,
        ge=-360.0,
        le=360.0,
        description="Rotation in degrees (positive = clockwise).",
    )
    hflip: bool = Field(False, description="Mirror horizontally.")
    vflip: bool = Field(False, description="Mirror vertically.")
    chromakey: ChromaKey | None = Field(
        None,
        description="Green-screen keying: make ``color`` transparent.",
    )


class Keyframe(BaseModel):
    """A single ``(time, value)`` sample on an animated property.

    ``time`` is measured in seconds relative to the project's global clock.
    ``value`` is a plain float; per-property semantics (pixels, opacity,
    gain multipliers, etc.) are documented on the owning field.
    """

    time: NonNegativeFloat
    value: float


def _validate_keyframes(kfs: list[Keyframe]) -> list[Keyframe]:
    """Ensure keyframes are sorted by time and have strictly unique times."""
    if len(kfs) <= 1:
        return kfs
    ordered = sorted(kfs, key=lambda k: k.time)
    for a, b in zip(ordered, ordered[1:], strict=False):
        if a.time == b.time:
            raise ValueError(f"duplicate keyframe time: {a.time}")
    return ordered


class Clip(BaseModel):
    """A single media clip placed on a track."""

    clip_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description="Stable timeline clip ID used for linking and parenting.",
    )
    link_group_id: str | None = Field(
        None,
        description="Clips with the same group can move/delete together.",
    )
    linked_parent_id: str | None = Field(
        None,
        description="Optional parent clip ID for CapCut-like linked children.",
    )
    linked_offset: float = Field(
        0.0,
        description="Child start offset relative to the linked parent start in seconds.",
    )
    clip_type: Literal["media", "text"] = Field(
        "media",
        description="`media` for video/audio/image clips, `text` for timeline subtitle clips.",
    )
    source: str = Field(..., description="Absolute or project-relative path to the media file.")
    proxy: str | None = Field(
        None,
        description=(
            "Optional path to a low-res proxy of ``source``. When the render is invoked "
            "with ``use_proxies=True`` this path is used in place of ``source``."
        ),
    )
    in_point: NonNegativeFloat = Field(0.0, description="Start offset inside the source (s).")
    out_point: NonNegativeFloat | None = Field(
        None,
        description="End offset inside the source (s). ``None`` means 'to the end'.",
    )
    start: NonNegativeFloat = Field(0.0, description="Timeline start position (s).")
    volume: float = Field(1.0, ge=0.0, description="Audio gain multiplier.")
    opacity: float = Field(1.0, ge=0.0, le=1.0, description="Video opacity multiplier.")
    volume_keyframes: list[Keyframe] = Field(
        default_factory=list,
        description="Audio gain keyframes over global timeline time. Empty = use static volume.",
    )
    opacity_keyframes: list[Keyframe] = Field(
        default_factory=list,
        description="Video opacity keyframes over global timeline time. Empty = use static opacity.",
    )
    speed: float = Field(1.0, gt=0.0, description="Playback speed multiplier.")
    reverse: bool = Field(
        False, description="Play the clip backwards (video + audio are both reversed)."
    )
    scale: float | None = Field(
        None,
        gt=0.0,
        le=5.0,
        description=(
            "Picture-in-picture scale factor relative to the project canvas (0..5]. "
            "``None`` means 'fill the canvas' (legacy behaviour)."
        ),
    )
    scale_x: float | None = Field(
        None,
        gt=0.0,
        le=5.0,
        description=(
            "Optional non-uniform horizontal scale factor (0..5]. "
            "When set (or ``scale_y`` is set), non-uniform scaling is enabled."
        ),
    )
    scale_y: float | None = Field(
        None,
        gt=0.0,
        le=5.0,
        description=(
            "Optional non-uniform vertical scale factor (0..5]. "
            "When set (or ``scale_x`` is set), non-uniform scaling is enabled."
        ),
    )
    pos_x: int | None = Field(
        None,
        description="Explicit X position of the scaled clip on the canvas, in pixels.",
    )
    pos_y: int | None = Field(
        None,
        description="Explicit Y position of the scaled clip on the canvas, in pixels.",
    )
    text_main: str = Field(
        "",
        description="Primary text content when `clip_type='text'`.",
    )
    text_second: str = Field(
        "",
        description="Secondary/bilingual text line when `clip_type='text'`.",
    )
    text_display: TextDisplayMode = Field(
        "main",
        description="How to display text clips: main, second, or bilingual.",
    )
    text_font_family: str = "Verdana"
    text_font_size: PositiveInt = 36
    text_color: str = "#ffffff"
    text_second_font_size: PositiveInt = 36
    text_second_color: str = "#ffffff"
    text_stroke_color: str = "#000000"
    text_stroke_width: int = Field(2, ge=0, le=12)
    effects: ClipEffects = Field(default_factory=ClipEffects)
    audio_effects: ClipAudioEffects = Field(default_factory=ClipAudioEffects)

    @field_validator("out_point")
    @classmethod
    def _check_out(cls, v: float | None, info):
        if v is None:
            return v
        in_point = info.data.get("in_point", 0.0)
        if v <= in_point:
            raise ValueError(f"out_point ({v}) must be greater than in_point ({in_point})")
        return v

    @field_validator("volume_keyframes", "opacity_keyframes")
    @classmethod
    def _check_keyframes(cls, v: list[Keyframe]):
        return _validate_keyframes(v)

    @property
    def source_duration(self) -> float | None:
        """Duration consumed from the source (``None`` if open-ended)."""
        if self.out_point is None:
            return None
        return max(0.0, self.out_point - self.in_point)

    @property
    def timeline_duration(self) -> float | None:
        """Duration on the timeline (takes ``speed`` into account)."""
        d = self.source_duration
        if d is None:
            return None
        return d / self.speed

    @property
    def is_text_clip(self) -> bool:
        return self.clip_type == "text"


class TextOverlay(BaseModel):
    """A burn-in text element rendered on top of a video track.

    Animated properties (``opacity_keyframes``, ``x_keyframes``,
    ``y_keyframes``) take precedence over their static counterparts
    (``x``, ``y``) when non-empty. Each list is an ordered sequence of
    :class:`Keyframe` s; the renderer emits a piecewise-linear ffmpeg
    expression that interpolates between consecutive keyframes and clamps
    to the first / last value outside the keyframe range.
    """

    text: str
    start: NonNegativeFloat = 0.0
    end: NonNegativeFloat = Field(..., description="Timeline end time (s).")
    x: str = "(w-text_w)/2"
    y: str = "(h-text_h)-40"
    font_size: PositiveInt = 48
    font_color: str = "white"
    box: bool = True
    box_color: str = "black@0.5"
    opacity_keyframes: list[Keyframe] = Field(
        default_factory=list,
        description="Opacity (0..1) over time. Empty = fully opaque for the whole [start,end] range.",
    )
    x_keyframes: list[Keyframe] = Field(
        default_factory=list,
        description="Horizontal pixel position over time; overrides ``x`` when non-empty.",
    )
    y_keyframes: list[Keyframe] = Field(
        default_factory=list,
        description="Vertical pixel position over time; overrides ``y`` when non-empty.",
    )

    @field_validator("end")
    @classmethod
    def _check_end(cls, v: float, info):
        start = info.data.get("start", 0.0)
        if v <= start:
            raise ValueError(f"end ({v}) must be greater than start ({start})")
        return v

    @field_validator("opacity_keyframes", "x_keyframes", "y_keyframes")
    @classmethod
    def _check_keyframes(cls, v: list[Keyframe]):
        return _validate_keyframes(v)


class ImageOverlay(BaseModel):
    """An image burn-in (watermark, logo, sticker) on top of a video track.

    Unlike :class:`TextOverlay`, the pixel data comes from ``source`` — any
    ffmpeg-decodable image file (PNG with alpha, JPG, etc). The image is
    scaled by ``scale`` (relative to the source size) and placed at
    ``(x, y)`` on the project canvas, visible between ``start`` and ``end``.
    """

    source: str = Field(..., description="Absolute or project-relative path to the image.")
    start: NonNegativeFloat = 0.0
    end: NonNegativeFloat = Field(..., description="Timeline end time (s).")
    x: int = 0
    y: int = 0
    scale: float = Field(1.0, gt=0.0, description="Resize factor for the image.")
    opacity: float = Field(1.0, ge=0.0, le=1.0)

    @field_validator("end")
    @classmethod
    def _check_end(cls, v: float, info):
        start = info.data.get("start", 0.0)
        if v <= start:
            raise ValueError(f"end ({v}) must be greater than start ({start})")
        return v


class Track(BaseModel):
    """A horizontal lane on the timeline — either video or audio."""

    kind: TrackKind = "video"
    name: str = ""
    clips: list[Clip] = Field(default_factory=list)
    overlays: list[TextOverlay] = Field(default_factory=list)
    image_overlays: list[ImageOverlay] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    locked: bool = False
    hidden: bool = False
    muted: bool = False
    volume: float = Field(1.0, ge=0.0, description="Track gain multiplier for mixer/render.")
    role: AudioRole = Field("other", description="Audio mixer role used by ducking/presets.")


class BeatMarker(BaseModel):
    """A local timeline beat/snap marker."""

    time: NonNegativeFloat = Field(..., description="Timeline position in seconds.")
    label: str = Field("Beat", description="User-visible marker label.")
    source: Literal["manual", "detected"] = Field(
        "manual",
        description="Whether the marker was placed by the user or generated locally.",
    )


class LibraryEntry(BaseModel):
    """A library card persisted independently of timeline placement.

    Used by the Media library and Text/Subtitle panels. ``source`` may
    become stale if the user moves files; the resolver re-locates by
    ``name`` + ``size`` (see :mod:`comecut_py.core.library_resolver`).
    ``duration`` is cached at import time so the relink dialog can show
    length even after a file moves.
    """

    source: str = Field(..., description="Absolute path to the file. May be stale.")
    name: str = Field("", description="Basename, used as fingerprint when resolving.")
    size: int = Field(0, ge=0, description="File size in bytes (0 = unknown).")
    mtime: float = Field(0.0, description="Last modified UTC timestamp (0 = unknown).")
    duration: float | None = Field(
        default=None, description="Cached duration in seconds (None = unknown)."
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_str(cls, v):
        # Backward compat: phase B.2 stored bare strings.
        if isinstance(v, str):
            try:
                return {"source": v, "name": Path(v).name, "size": 0, "mtime": 0.0, "duration": None}
            except Exception:
                return {"source": v, "name": "", "size": 0, "mtime": 0.0, "duration": None}
        return v


class Project(BaseModel):
    """Root project object — JSON-serialisable."""

    name: str = "Untitled"
    width: PositiveInt = 1920
    height: PositiveInt = 1080
    fps: float = Field(30.0, gt=0)
    sample_rate: PositiveInt = 48_000
    tracks: list[Track] = Field(default_factory=list)
    beat_markers: list[BeatMarker] = Field(
        default_factory=list,
        description="Local beat markers used as timeline snap anchors.",
    )

    # ---- library --------------------------------------------------------
    # Stored in legacy current.json only; V2 round-trip is informational.
    library_media: list[LibraryEntry] = Field(
        default_factory=list,
        description="Media imported to library (independent of timeline).",
    )
    library_subtitles: list[LibraryEntry] = Field(
        default_factory=list,
        description="Subtitle files imported to text panel.",
    )

    # ---- convenience ----------------------------------------------------

    @property
    def duration(self) -> float:
        """End of the last clip or overlay on any track."""
        end = 0.0
        for t in self.tracks:
            for c in t.clips:
                d = c.timeline_duration
                if d is not None:
                    end = max(end, c.start + d)
            for o in t.overlays:
                end = max(end, o.end)
            for io in t.image_overlays:
                end = max(end, io.end)
        return end

    # ---- I/O ------------------------------------------------------------

    def to_draft_dict(self) -> dict:
        """Serialise to the V2 ``draft_content.json`` shape."""
        from .project_draft_adapter import project_to_v2

        return project_to_v2(self).model_dump(mode="json")

    def to_draft_json(self, path: str | Path, *, indent: int = 2) -> None:
        Path(path).write_text(
            json.dumps(self.to_draft_dict(), indent=indent, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def from_draft_dict(cls, data: dict) -> Project:
        """Load a project from the V2 ``draft_content.json`` shape."""
        from .project_draft_adapter import v2_to_project
        from .project_schema_v2 import ProjectV2

        return v2_to_project(ProjectV2.model_validate(data))

    @classmethod
    def from_json(cls, path: str | Path) -> Project:
        data = json.loads(Path(path).read_text(encoding="utf-8"))

        from .capcut_importer import import_capcut_draft, is_capcut_format

        if is_capcut_format(data):
            return import_capcut_draft(path)

        from .project_draft_adapter import is_v2_format

        if is_v2_format(data):
            return cls.from_draft_dict(data)
        return cls.model_validate(data)

    def to_json(self, path: str | Path, *, indent: int = 2) -> None:
        Path(path).write_text(
            json.dumps(self.model_dump(mode="json"), indent=indent, ensure_ascii=False),
            encoding="utf-8",
        )


__all__ = [
    "ChromaKey",
    "Clip",
    "ClipAudioEffects",
    "ClipEffects",
    "CropRect",
    "ImageOverlay",
    "Keyframe",
    "LibraryEntry",
    "Project",
    "TextOverlay",
    "TextDisplayMode",
    "Track",
    "TrackKind",
    "AudioRole",
    "BeatMarker",
    "Transition",
    "TransitionKind",
]
