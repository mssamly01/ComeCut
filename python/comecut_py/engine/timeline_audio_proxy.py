"""Build a continuous audio preview proxy for the whole timeline."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path

from ..core.keyframes import evaluate_keyframes
from ..core.media_probe import probe
from ..core.project import Clip, Keyframe, Project, Track
from .render import render_project_audio_only


_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
_AUDIO_PROXY_RENDER_VERSION = 2
_AUDIO_WINDOW_PROXY_RENDER_VERSION = 1


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    path = Path(base) / "comecut-py" / "timeline-audio-proxies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _source_signature(source: str) -> dict[str, object]:
    path = Path(source)
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)
    try:
        stat = path.stat()
        stat_sig: tuple[int, int] = (int(stat.st_size), int(stat.st_mtime_ns))
    except OSError:
        stat_sig = (0, 0)
    return {"source": resolved, "stat": stat_sig}


def clip_source_has_audio(clip: Clip) -> bool:
    """Best-effort audio stream check that does not touch GUI state."""
    if bool(getattr(clip, "is_text_clip", False)):
        return False
    source = str(getattr(clip, "source", "") or "").strip()
    if not source:
        return False
    path = Path(source)
    if path.suffix.lower() in _AUDIO_EXTS:
        return True
    if not path.exists():
        return False
    try:
        return bool(probe(path).has_audio)
    except Exception:
        return False


def _clip_sig(track: Track, clip: Clip) -> dict[str, object]:
    return {
        "track_kind": track.kind,
        "track_volume": float(getattr(track, "volume", 1.0) or 0.0),
        "track_muted": bool(getattr(track, "muted", False)),
        "track_hidden": bool(getattr(track, "hidden", False)),
        "track_transitions": [
            transition.model_dump(mode="json")
            for transition in getattr(track, "transitions", [])
        ],
        **_source_signature(str(getattr(clip, "source", "") or "")),
        "start": float(getattr(clip, "start", 0.0) or 0.0),
        "in_point": float(getattr(clip, "in_point", 0.0) or 0.0),
        "out_point": (
            None
            if getattr(clip, "out_point", None) is None
            else float(getattr(clip, "out_point"))
        ),
        "speed": float(getattr(clip, "speed", 1.0) or 1.0),
        "reverse": bool(getattr(clip, "reverse", False)),
        "volume": float(getattr(clip, "volume", 1.0) or 0.0),
        "audio_effects": clip.audio_effects.model_dump(mode="json"),
        "volume_keyframes": [
            keyframe.model_dump(mode="json")
            for keyframe in getattr(clip, "volume_keyframes", [])
        ],
    }


def timeline_audio_project(
    project: Project,
    *,
    has_audio: Callable[[Clip], bool] = clip_source_has_audio,
) -> Project:
    """Convert audible video/audio timeline media into audio-only tracks."""
    audio_project = Project(
        name=project.name,
        width=project.width,
        height=project.height,
        fps=project.fps,
        sample_rate=project.sample_rate,
    )

    for source_track in project.tracks:
        if source_track.kind not in {"video", "audio"}:
            continue
        if bool(getattr(source_track, "hidden", False)) or bool(
            getattr(source_track, "muted", False)
        ):
            continue

        source_clips = [
            clip
            for clip in source_track.clips
            if not bool(getattr(clip, "is_text_clip", False))
        ]
        clips = [clip.model_copy(deep=True) for clip in source_clips if has_audio(clip)]
        if not clips:
            continue
        transitions = []
        if len(clips) == len(source_clips):
            transitions = [
                transition.model_copy(deep=True)
                for transition in getattr(source_track, "transitions", [])
            ]

        audio_project.tracks.append(
            Track(
                kind="audio",
                name=source_track.name,
                clips=clips,
                transitions=transitions,
                locked=bool(getattr(source_track, "locked", False)),
                hidden=False,
                muted=False,
                volume=float(getattr(source_track, "volume", 1.0) or 0.0),
                role=getattr(source_track, "role", "other"),
            )
        )

    return audio_project


def _clip_timeline_end(clip: Clip) -> float | None:
    dur = clip.timeline_duration
    if dur is None:
        return None
    return float(clip.start) + max(0.0, float(dur))


def _shift_volume_keyframes_for_window(
    clip: Clip,
    *,
    window_start: float,
    intersection_start: float,
) -> list[Keyframe]:
    source_keyframes = list(getattr(clip, "volume_keyframes", []) or [])
    if not source_keyframes:
        return []

    shifted = [
        Keyframe(time=max(0.0, float(k.time) - window_start), value=float(k.value))
        for k in source_keyframes
        if float(k.time) >= window_start
    ]
    initial_time = max(0.0, intersection_start - window_start)
    initial_value = evaluate_keyframes(
        source_keyframes,
        intersection_start,
        default=float(getattr(clip, "volume", 1.0) or 0.0),
    )
    if not shifted or shifted[0].time > initial_time + 1e-9:
        shifted.insert(0, Keyframe(time=initial_time, value=initial_value))
    return shifted


def timeline_audio_window_project(
    project: Project,
    *,
    start: float,
    duration: float,
    has_audio: Callable[[Clip], bool] = clip_source_has_audio,
) -> Project:
    """Convert audible timeline media intersecting a preview window to audio tracks."""
    window_start = max(0.0, float(start))
    window_duration = max(0.001, float(duration))
    window_end = window_start + window_duration
    audio_project = Project(
        name=project.name,
        width=project.width,
        height=project.height,
        fps=project.fps,
        sample_rate=project.sample_rate,
    )

    for source_track in project.tracks:
        if source_track.kind not in {"video", "audio"}:
            continue
        if bool(getattr(source_track, "hidden", False)) or bool(
            getattr(source_track, "muted", False)
        ):
            continue

        clips: list[Clip] = []
        for source_clip in source_track.clips:
            if bool(getattr(source_clip, "is_text_clip", False)):
                continue
            if not has_audio(source_clip):
                continue
            clip_start = max(0.0, float(getattr(source_clip, "start", 0.0) or 0.0))
            clip_end = _clip_timeline_end(source_clip)
            if clip_end is None:
                clip_end = window_end
            if clip_end <= window_start or clip_start >= window_end:
                continue

            intersection_start = max(clip_start, window_start)
            intersection_end = min(clip_end, window_end)
            if intersection_end <= intersection_start:
                continue

            clip = source_clip.model_copy(deep=True)
            speed = max(1e-9, float(getattr(source_clip, "speed", 1.0) or 1.0))
            source_offset_start = (intersection_start - clip_start) * speed
            source_offset_end = (intersection_end - clip_start) * speed
            clip.in_point = max(0.0, float(source_clip.in_point) + source_offset_start)
            clip.out_point = max(clip.in_point + 0.001, float(source_clip.in_point) + source_offset_end)
            clip.start = max(0.0, intersection_start - window_start)
            clip.volume_keyframes = _shift_volume_keyframes_for_window(
                source_clip,
                window_start=window_start,
                intersection_start=intersection_start,
            )
            clips.append(clip)

        if not clips:
            continue
        audio_project.tracks.append(
            Track(
                kind="audio",
                name=source_track.name,
                clips=clips,
                locked=bool(getattr(source_track, "locked", False)),
                hidden=False,
                muted=False,
                volume=float(getattr(source_track, "volume", 1.0) or 0.0),
                role=getattr(source_track, "role", "other"),
            )
        )

    return audio_project


def timeline_audio_proxy_path(
    project: Project,
    *,
    has_audio: Callable[[Clip], bool] = clip_source_has_audio,
) -> Path:
    payload = {
        "render_version": _AUDIO_PROXY_RENDER_VERSION,
        "sample_rate": int(project.sample_rate),
        "tracks": [
            {
                "name": track.name,
                "clips": [
                    _clip_sig(track, clip)
                    for clip in track.clips
                    if not bool(getattr(clip, "is_text_clip", False)) and has_audio(clip)
                ],
            }
            for track in project.tracks
            if track.kind in {"video", "audio"}
            and not bool(getattr(track, "hidden", False))
            and not bool(getattr(track, "muted", False))
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:24]
    return _cache_dir() / f"{digest}.wav"


def timeline_audio_window_proxy_path(
    project: Project,
    *,
    start: float,
    duration: float,
    has_audio: Callable[[Clip], bool] = clip_source_has_audio,
) -> Path:
    window_project = timeline_audio_window_project(
        project,
        start=start,
        duration=duration,
        has_audio=has_audio,
    )
    payload = {
        "render_version": _AUDIO_WINDOW_PROXY_RENDER_VERSION,
        "sample_rate": int(project.sample_rate),
        "start": round(max(0.0, float(start)), 6),
        "duration": round(max(0.001, float(duration)), 6),
        "tracks": [
            {
                "name": track.name,
                "clips": [_clip_sig(track, clip) for clip in track.clips],
            }
            for track in window_project.tracks
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:24]
    return _cache_dir() / f"win-{digest}.wav"


def make_timeline_audio_proxy(
    project: Project,
    *,
    has_audio: Callable[[Clip], bool] = clip_source_has_audio,
    force: bool = False,
) -> Path:
    out = timeline_audio_proxy_path(project, has_audio=has_audio)
    if not force and out.exists() and out.stat().st_size > 0:
        return out

    audio_project = timeline_audio_project(project, has_audio=has_audio)
    if not audio_project.tracks:
        raise ValueError("Timeline has no audible media.")

    tmp = out.with_name(f"{out.stem}.tmp{out.suffix}")
    if tmp.exists():
        tmp.unlink()
    cmd = render_project_audio_only(audio_project, tmp, audio_format="wav")
    cmd.run()
    tmp.replace(out)
    return out


def make_timeline_audio_window_proxy(
    project: Project,
    *,
    start: float,
    duration: float = 120.0,
    has_audio: Callable[[Clip], bool] = clip_source_has_audio,
    force: bool = False,
) -> Path:
    out = timeline_audio_window_proxy_path(
        project,
        start=start,
        duration=duration,
        has_audio=has_audio,
    )
    if not force and out.exists() and out.stat().st_size > 0:
        return out

    audio_project = timeline_audio_window_project(
        project,
        start=start,
        duration=duration,
        has_audio=has_audio,
    )
    if not audio_project.tracks:
        raise ValueError("Timeline window has no audible media.")

    tmp = out.with_name(f"{out.stem}.tmp{out.suffix}")
    if tmp.exists():
        tmp.unlink()
    cmd = render_project_audio_only(audio_project, tmp, audio_format="wav")
    cmd.run()
    tmp.replace(out)
    return out


__all__ = [
    "clip_source_has_audio",
    "make_timeline_audio_proxy",
    "make_timeline_audio_window_proxy",
    "timeline_audio_project",
    "timeline_audio_proxy_path",
    "timeline_audio_window_project",
    "timeline_audio_window_proxy_path",
]
