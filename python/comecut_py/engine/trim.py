"""Trim N seconds off the head and/or tail of a file.

``head`` is handled with ``-ss`` (fast and universally supported).
``tail`` is handled via ``-sseof`` in a second pass, but because combining
``-ss`` with ``-sseof`` in one invocation is brittle, we require a prior
:func:`comecut_py.core.media_probe.probe` call when both are non-zero. The
caller passes the total ``duration`` of the source so we can compute an
explicit end timestamp.
"""

from __future__ import annotations

from pathlib import Path

from ..core.ffmpeg_cmd import FFmpegCommand
from ..core.time_utils import TimeLike, format_timecode, parse_timecode


def trim(
    src: str | Path,
    dst: str | Path,
    *,
    head: TimeLike = 0.0,
    tail: TimeLike = 0.0,
    duration: TimeLike | None = None,
    copy: bool = False,
) -> FFmpegCommand:
    """Remove ``head`` seconds from the start and ``tail`` seconds from the end.

    If ``tail > 0`` the caller MUST also pass ``duration`` (total length of the
    source in seconds). Otherwise the operation is ambiguous.
    """
    h = parse_timecode(head)
    t = parse_timecode(tail)
    if h < 0 or t < 0:
        raise ValueError("head/tail must be non-negative")

    cmd = FFmpegCommand()
    input_flags: list[str] = ["-ss", format_timecode(h, srt=False)]
    if t > 0:
        if duration is None:
            raise ValueError(
                "Non-zero tail trim requires the source duration. "
                "Probe it first with comecut_py.core.media_probe.probe()."
            )
        total = parse_timecode(duration)
        end = total - t
        if end <= h:
            raise ValueError(f"Empty trim: head={h}, tail={t}, duration={total}")
        input_flags.extend(["-to", format_timecode(end, srt=False)])
    cmd.add_input(src, *input_flags)
    if copy:
        cmd.extra("-c", "copy")
    else:
        cmd.extra(
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        )
    cmd.out(dst)
    return cmd


__all__ = ["trim"]
