"""Generate volume-keyframe based auto ducking for local projects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .project import Clip, Keyframe, Track


@dataclass(frozen=True)
class AutoDuckingConfig:
    duck_volume: float = 0.35
    attack: float = 0.12
    release: float = 0.25
    voice_roles: tuple[str, ...] = ("voice",)
    duck_roles: tuple[str, ...] = ("music",)


def _clip_end(clip: Clip) -> float:
    return float(clip.start) + max(0.0, float(clip.timeline_duration or 0.0))


def collect_role_intervals(
    tracks: Iterable[Track],
    roles: Iterable[str],
) -> list[tuple[float, float]]:
    role_set = {str(role).strip().lower() for role in roles}
    intervals: list[tuple[float, float]] = []
    for track in tracks:
        if track.kind != "audio":
            continue
        if str(getattr(track, "role", "other") or "other").strip().lower() not in role_set:
            continue
        if bool(getattr(track, "hidden", False)) or bool(getattr(track, "muted", False)):
            continue
        for clip in track.clips:
            start = float(clip.start)
            end = _clip_end(clip)
            if end > start:
                intervals.append((start, end))
    return sorted(intervals)


def merge_ducking_intervals(
    intervals: Iterable[tuple[float, float]],
    *,
    gap: float = 0.25,
) -> list[tuple[float, float]]:
    ordered = sorted((float(a), float(b)) for a, b in intervals if b > a)
    if not ordered:
        return []
    merged: list[tuple[float, float]] = []
    cur_start, cur_end = ordered[0]
    max_gap = max(0.0, float(gap))
    for start, end in ordered[1:]:
        if start <= cur_end + max_gap:
            cur_end = max(cur_end, end)
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = start, end
    merged.append((cur_start, cur_end))
    return merged


def build_ducking_keyframes_for_clip(
    clip: Clip,
    voice_intervals: Iterable[tuple[float, float]],
    *,
    duck_volume: float = 0.35,
    attack: float = 0.12,
    release: float = 0.25,
) -> list[Keyframe]:
    clip_start = float(clip.start)
    clip_end = _clip_end(clip)
    if clip_end <= clip_start:
        return []

    duck = max(0.0, min(1.0, float(duck_volume)))
    attack_s = max(0.0, float(attack))
    release_s = max(0.0, float(release))
    points: dict[float, float] = {}

    def add(time_s: float, value: float) -> None:
        if time_s < clip_start - 1e-6 or time_s > clip_end + 1e-6:
            return
        t = round(max(clip_start, min(clip_end, time_s)), 6)
        v = max(0.0, float(value))
        points[t] = min(points[t], v) if t in points else v

    intervals = merge_ducking_intervals(voice_intervals, gap=release_s)
    for voice_start, voice_end in intervals:
        overlap_start = max(clip_start, float(voice_start))
        overlap_end = min(clip_end, float(voice_end))
        if overlap_end <= overlap_start:
            continue

        if voice_start > clip_start:
            add(overlap_start - attack_s, 1.0)
        add(overlap_start, duck)
        add(overlap_end, duck)
        if voice_end < clip_end:
            add(overlap_end + release_s, 1.0)

    return [Keyframe(time=t, value=points[t]) for t in sorted(points)]


def merge_volume_keyframes(
    existing: Iterable[Keyframe],
    generated: Iterable[Keyframe],
) -> list[Keyframe]:
    points: dict[float, float] = {}
    for keyframe in existing:
        points[round(float(keyframe.time), 6)] = float(keyframe.value)
    for keyframe in generated:
        t = round(float(keyframe.time), 6)
        v = float(keyframe.value)
        points[t] = min(points[t], v) if t in points else v
    return [Keyframe(time=t, value=points[t]) for t in sorted(points)]


def apply_auto_ducking_to_tracks(
    tracks: list[Track],
    *,
    config: AutoDuckingConfig | None = None,
    replace_existing: bool = True,
) -> int:
    cfg = config or AutoDuckingConfig()
    voice_intervals = collect_role_intervals(tracks, cfg.voice_roles)
    if not voice_intervals:
        return 0

    changed = 0
    duck_roles = {str(role).strip().lower() for role in cfg.duck_roles}
    for track in tracks:
        if track.kind != "audio":
            continue
        role = str(getattr(track, "role", "other") or "other").strip().lower()
        if role not in duck_roles:
            continue
        if bool(getattr(track, "hidden", False)) or bool(getattr(track, "muted", False)):
            continue
        for clip in track.clips:
            generated = build_ducking_keyframes_for_clip(
                clip,
                voice_intervals,
                duck_volume=cfg.duck_volume,
                attack=cfg.attack,
                release=cfg.release,
            )
            if not generated:
                continue
            new_keyframes = (
                generated
                if replace_existing
                else merge_volume_keyframes(clip.volume_keyframes, generated)
            )
            if [
                (round(float(k.time), 6), round(float(k.value), 6))
                for k in clip.volume_keyframes
            ] == [
                (round(float(k.time), 6), round(float(k.value), 6))
                for k in new_keyframes
            ]:
                continue
            clip.volume_keyframes = new_keyframes
            changed += 1
    return changed


__all__ = [
    "AutoDuckingConfig",
    "apply_auto_ducking_to_tracks",
    "build_ducking_keyframes_for_clip",
    "collect_role_intervals",
    "merge_ducking_intervals",
    "merge_volume_keyframes",
]
