"""Timeline helpers used by preview playback selection/sync."""

from __future__ import annotations

from bisect import bisect_right

from ..core.audio_mixer import audible_audio_tracks
from ..core.project import Clip, Track

_EPS = 1e-3


class _ClipIntervalIndex:
    """Per-track interval lookup for preview ticks.

    The old preview picker walked every clip on every playhead tick. With long
    voice tracks that can mean 1,000+ checks dozens of times per second. This
    index keeps track priority unchanged while making the common lookup a
    binary search inside each audible/visible track.
    """

    def __init__(self) -> None:
        self._track_intervals: list[
            tuple[list[float], list[tuple[float, float, Clip]], list[float]]
        ] = []

    def clear(self) -> None:
        self._track_intervals.clear()

    def rebuild(self, tracks: list[Track]) -> None:
        rebuilt: list[tuple[list[float], list[tuple[float, float, Clip]], list[float]]] = []
        for track in tracks:
            intervals: list[tuple[float, float, Clip]] = []
            for clip in track.clips:
                start = float(clip.start)
                end = clip_end_seconds(clip)
                if end <= start:
                    continue
                intervals.append((start, end, clip))
            if not intervals:
                continue
            intervals.sort(key=lambda item: item[0])
            starts = [item[0] for item in intervals]
            max_ends: list[float] = []
            max_end = 0.0
            for _, end, _clip in intervals:
                max_end = max(max_end, end)
                max_ends.append(max_end)
            rebuilt.append((starts, intervals, max_ends))
        self._track_intervals = rebuilt

    def find(self, seconds: float) -> Clip | None:
        s = max(0.0, float(seconds))
        for starts, intervals, max_ends in self._track_intervals:
            idx = bisect_right(starts, s) - 1
            while idx >= 0 and max_ends[idx] > s:
                start, end, clip = intervals[idx]
                if start <= s < end:
                    return clip
                idx -= 1
        return None


def clip_end_seconds(clip: Clip) -> float:
    dur = clip.timeline_duration or 0.0
    return float(clip.start) + max(0.0, float(dur))


def clip_contains_time(clip: Clip, seconds: float) -> bool:
    start = float(clip.start)
    return start <= float(seconds) < clip_end_seconds(clip)


def clip_fade_multiplier_at_local_time(
    clip: Clip,
    local_seconds: float,
    *,
    duration_seconds: float | None = None,
) -> float:
    dur = (
        float(duration_seconds)
        if duration_seconds is not None
        else float(clip.timeline_duration or 0.0)
    )
    if dur <= 1e-6:
        return 1.0

    afx = clip.audio_effects
    fade_in = max(0.0, float(getattr(afx, "fade_in", 0.0) or 0.0))
    fade_out = max(0.0, float(getattr(afx, "fade_out", 0.0) or 0.0))
    max_fade = dur * 0.5
    fade_in = min(fade_in, max_fade)
    fade_out = min(fade_out, max_fade)

    local_t = max(0.0, float(local_seconds))
    mult = 1.0
    if fade_in > 0.0:
        mult *= max(0.0, min(1.0, local_t / fade_in))
    if fade_out > 0.0:
        remain = max(0.0, dur - local_t)
        mult *= max(0.0, min(1.0, remain / fade_out))
    return mult


def clip_fade_multiplier(clip: Clip, timeline_seconds: float) -> float:
    local_t = max(0.0, float(timeline_seconds) - float(clip.start))
    return clip_fade_multiplier_at_local_time(clip, local_t)


def visible_audio_tracks(tracks: list[Track]) -> list[Track]:
    return audible_audio_tracks(tracks)


def pick_timeline_audio_clip(
    tracks: list[Track],
    seconds: float,
    *,
    fallback_to_first: bool = False,
    index: _ClipIntervalIndex | None = None,
) -> Clip | None:
    s = max(0.0, float(seconds))
    audio_tracks = visible_audio_tracks(tracks)
    if index is not None:
        clip = index.find(s)
        if clip is not None:
            return clip
    for track in audio_tracks:
        for clip in track.clips:
            if clip_contains_time(clip, s):
                return clip
    if fallback_to_first and audio_tracks:
        return audio_tracks[0].clips[0]
    return None


def next_playable_time_after(tracks: list[Track], seconds: float) -> float | None:
    after = max(0.0, float(seconds)) + _EPS
    best: float | None = None
    for track in tracks:
        if track.kind not in {"video", "audio"} or bool(getattr(track, "hidden", False)):
            continue
        if track.kind == "audio" and bool(getattr(track, "muted", False)):
            continue
        for clip in track.clips:
            end = clip_end_seconds(clip)
            if end <= after:
                continue
            start = float(clip.start)
            candidate = start if start >= after else after
            if candidate < end and (best is None or candidate < best):
                best = candidate
    return best
