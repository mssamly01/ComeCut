"""``ffprobe``-backed media inspection."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg_cmd import ensure_ffprobe


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration: float | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None
    has_video: bool
    has_audio: bool


def _parse_fps(rate: str | None) -> float | None:
    if not rate or rate in {"0/0", "0/1"}:
        return None
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            n, d = float(num), float(den)
            return n / d if d else None
        except ValueError:
            return None
    try:
        return float(rate)
    except ValueError:
        return None


def probe(path: str | Path, *, timeout: float = 15.0) -> MediaInfo:
    """Probe a media file using ``ffprobe``. Requires the ``ffprobe`` binary."""
    ffprobe = ensure_ffprobe()
    argv = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(
        argv,
        check=True,
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout)),
    )
    data = json.loads(result.stdout or "{}")
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = fmt.get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except ValueError:
        duration = None

    return MediaInfo(
        path=str(path),
        duration=duration,
        width=int(video["width"]) if video and "width" in video else None,
        height=int(video["height"]) if video and "height" in video else None,
        fps=_parse_fps(video.get("r_frame_rate") if video else None),
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        sample_rate=int(audio["sample_rate"]) if audio and "sample_rate" in audio else None,
        channels=int(audio["channels"]) if audio and "channels" in audio else None,
        has_video=video is not None,
        has_audio=audio is not None,
    )


__all__ = ["MediaInfo", "probe"]
