"""Cut out ``[start, end]`` from a single input file (accurate, re-encoded)."""

from __future__ import annotations

from pathlib import Path

from ..core.ffmpeg_cmd import FFmpegCommand
from ..core.time_utils import TimeLike, format_timecode, parse_timecode


def cut(
    src: str | Path,
    dst: str | Path,
    start: TimeLike,
    end: TimeLike,
    *,
    copy: bool = False,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    crf: int = 20,
    preset: str = "medium",
) -> FFmpegCommand:
    """Cut ``src[start:end]`` → ``dst``.

    When ``copy=True`` we stream-copy (fast, but only accurate to keyframes).
    Otherwise we re-encode with the given codec settings for frame-accurate cuts.
    """
    s = parse_timecode(start)
    e = parse_timecode(end)
    if e <= s:
        raise ValueError(f"end ({e}) must be > start ({s})")
    duration = e - s

    cmd = FFmpegCommand()
    # ``-ss`` before ``-i`` is much faster but less accurate for re-encode paths;
    # for copy mode we prefer it, for re-encode we place it after for accuracy.
    if copy:
        cmd.add_input(src, "-ss", format_timecode(s, srt=False), "-t", format_timecode(duration))
        cmd.extra("-c", "copy")
    else:
        cmd.add_input(src)
        cmd.extra(
            "-ss",
            format_timecode(s, srt=False),
            "-t",
            format_timecode(duration),
            "-c:v",
            video_codec,
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-c:a",
            audio_codec,
            "-movflags",
            "+faststart",
        )
    cmd.out(dst)
    return cmd


__all__ = ["cut"]
