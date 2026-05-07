"""Build a continuous audio preview proxy for the whole timeline."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path

from ..core.media_probe import probe
from ..core.project import Clip, Project, Track
from .render import render_project_audio_only


_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
_AUDIO_PROXY_RENDER_VERSION = 2


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


__all__ = [
    "clip_source_has_audio",
    "make_timeline_audio_proxy",
    "timeline_audio_project",
    "timeline_audio_proxy_path",
]
