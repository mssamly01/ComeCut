"""Audio track mixer helpers shared by preview, timeline, and render."""

from __future__ import annotations

from typing import Iterable

from .project import AudioRole, Track


AUDIO_ROLE_LABELS: dict[AudioRole, str] = {
    "voice": "Voice",
    "music": "Music",
    "sfx": "SFX",
    "ambience": "Ambience",
    "other": "Other",
}


def clamp_track_volume(value: object) -> float:
    try:
        volume = float(value)
    except (TypeError, ValueError):
        volume = 1.0
    return max(0.0, volume)


def track_output_gain(track: Track | None) -> float:
    if track is None:
        return 1.0
    return clamp_track_volume(getattr(track, "volume", 1.0))


def is_audio_track_enabled(track: Track, *, require_clips: bool = True) -> bool:
    if track.kind != "audio":
        return False
    if require_clips and not track.clips:
        return False
    if bool(getattr(track, "hidden", False)) or bool(getattr(track, "muted", False)):
        return False
    return track_output_gain(track) > 0.0


def audible_audio_tracks(
    tracks: Iterable[Track],
    *,
    require_clips: bool = True,
) -> list[Track]:
    return [
        track
        for track in tracks
        if is_audio_track_enabled(track, require_clips=require_clips)
    ]


def set_track_volume(track: Track, value: object) -> float:
    track.volume = clamp_track_volume(value)
    return track.volume


def set_track_role(track: Track, role: object) -> AudioRole:
    role_id = str(role or "other").strip().lower()
    if role_id not in AUDIO_ROLE_LABELS:
        role_id = "other"
    track.role = role_id  # type: ignore[assignment]
    return track.role


__all__ = [
    "AUDIO_ROLE_LABELS",
    "audible_audio_tracks",
    "clamp_track_volume",
    "is_audio_track_enabled",
    "set_track_role",
    "set_track_volume",
    "track_output_gain",
]
