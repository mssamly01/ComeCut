"""Concatenate several input files into one output."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..core.ffmpeg_cmd import FFmpegCommand


def concat(
    srcs: Iterable[str | Path],
    dst: str | Path,
    *,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    crf: int = 20,
    preset: str = "medium",
) -> FFmpegCommand:
    """Concat files using the ``concat`` filter (re-encodes — safe across codecs).

    For inputs that all share the exact same codec + parameters, the
    ``-f concat`` demuxer is faster; we prefer the filter path here for
    correctness.
    """
    inputs = [str(s) for s in srcs]
    if len(inputs) < 2:
        raise ValueError("concat requires at least 2 inputs")
    cmd = FFmpegCommand()
    for p in inputs:
        cmd.add_input(p)
    # Inputs are assumed to all have audio; callers with silent sources should
    # pre-process them to add an empty audio track (``-f lavfi -i anullsrc``).
    parts = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(len(inputs)))
    cmd.set_filter_complex(
        f"{parts}concat=n={len(inputs)}:v=1:a=1[outv][outa]"
    )
    cmd.map("[outv]").map("[outa]")
    cmd.extra(
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


__all__ = ["concat"]
