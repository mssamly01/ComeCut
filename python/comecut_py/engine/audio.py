"""Audio-only operations: extract, adjust volume."""

from __future__ import annotations

from pathlib import Path

from ..core.ffmpeg_cmd import FFmpegCommand


def extract_audio(
    src: str | Path,
    dst: str | Path,
    *,
    codec: str = "libmp3lame",
    bitrate: str = "192k",
) -> FFmpegCommand:
    """Extract the audio track from ``src`` into ``dst``."""
    cmd = FFmpegCommand().add_input(src)
    cmd.extra("-vn", "-c:a", codec, "-b:a", bitrate)
    cmd.out(dst)
    return cmd


def adjust_volume(
    src: str | Path,
    dst: str | Path,
    gain: float,
) -> FFmpegCommand:
    """Multiply audio by ``gain`` (``1.0`` = unchanged, ``0.5`` = half, ``2.0`` = double)."""
    if gain < 0:
        raise ValueError("gain must be non-negative")
    cmd = FFmpegCommand().add_input(src)
    cmd.extra("-filter:a", f"volume={gain}", "-c:v", "copy")
    cmd.out(dst)
    return cmd


__all__ = ["adjust_volume", "extract_audio"]
