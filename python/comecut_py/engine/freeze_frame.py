"""Freeze a single frame from a video and insert it as a still segment.

Useful for punctuation ("hold this reaction for 2 seconds") and for extending
a clip past its natural end without changing the source.
"""

from __future__ import annotations

from pathlib import Path

from ..core.ffmpeg_cmd import FFmpegCommand


def _layout_name(channels: int | None) -> str:
    """Best-effort ffmpeg channel-layout name for a channel count."""
    if channels == 1:
        return "mono"
    if channels == 2:
        return "stereo"
    if channels == 6:
        return "5.1"
    if channels == 8:
        return "7.1"
    # Fall back to an explicit channel count — ffmpeg accepts e.g. "3c".
    if channels and channels > 0:
        return f"{channels}c"
    return "stereo"


def freeze_frame(
    src: str | Path,
    dst: str | Path,
    *,
    at: float,
    hold: float,
    has_audio: bool | None = None,
    sample_rate: int | None = None,
    channels: int | None = None,
) -> FFmpegCommand:
    """Splice a freeze-frame of ``src`` at time ``at`` for ``hold`` seconds.

    The output is ``[0..at)`` from the source, followed by ``hold`` seconds
    of a still frame captured at ``at``, followed by ``[at..end]`` from the
    source. When the source has audio, a matching ``hold`` seconds of silence
    is concatenated so the sound stays in sync with the frozen image.

    The audio graph normalises every segment with ``aformat=sample_rates=...:
    channel_layouts=...`` so the ``concat`` filter never sees mismatched
    stream parameters — this matters because ``anullsrc`` defaults would
    otherwise collide with a non-48 kHz or non-stereo source.

    Parameters
    ----------
    at, hold : float
        Freeze point and hold length in source seconds. Both must be > 0.
    has_audio : bool or None
        Whether the source has an audio stream. ``None`` (default) triggers
        an ffprobe call; pass an explicit value to skip probing (useful in
        tests or when the caller has already probed).
    sample_rate : int or None
        Target sample rate for the silence and aformat filters. Defaults to
        the probed source sample rate, or 48000 Hz if the probe fails.
    channels : int or None
        Target channel count (1 = mono, 2 = stereo, ...). Defaults to the
        probed source channel count, or 2 if the probe fails.
    """
    if at <= 0:
        raise ValueError(f"at must be > 0 (got {at})")
    if hold <= 0:
        raise ValueError(f"hold must be > 0 (got {hold})")

    # Only probe when the caller hasn't already told us what to expect.
    if has_audio is None or (has_audio and (sample_rate is None or channels is None)):
        try:
            from ..core.media_probe import probe

            info = probe(src)
            if has_audio is None:
                has_audio = info.has_audio
            if has_audio and sample_rate is None:
                sample_rate = info.sample_rate
            if has_audio and channels is None:
                channels = info.channels
        except Exception:
            # If the probe fails, assume the source has audio with sensible
            # defaults — the ffmpeg pass will raise a clear error if the
            # assumption was wrong. Callers who need guaranteed behaviour
            # should pass ``has_audio`` explicitly.
            if has_audio is None:
                has_audio = True

    sr = sample_rate or 48000
    layout = _layout_name(channels)

    cmd = FFmpegCommand()
    cmd.add_input(str(src))  # input #0 — video (+ optional audio)

    filters: list[str] = [
        # Segment A: 0..at
        f"[0:v]trim=start=0:end={at},setpts=PTS-STARTPTS[va]",
        # Segment B: freeze frame at ``at`` held for ``hold`` seconds.
        # Grab a single frame with trim+select, then loop it.
        (
            f"[0:v]trim=start={at}:end={at + 0.04},setpts=PTS-STARTPTS,"
            f"loop=loop=-1:size=1:start=0,"
            f"trim=duration={hold},setpts=PTS-STARTPTS[vb]"
        ),
        # Segment C: at..end
        f"[0:v]trim=start={at},setpts=PTS-STARTPTS[vc]",
    ]

    if has_audio:
        # Force every audio segment to share sample rate + channel layout so
        # the ``concat`` filter doesn't reject mismatched streams. Without
        # the ``aformat`` clauses a non-48 kHz source collides with the
        # anullsrc silence.
        aformat = f"aformat=sample_rates={sr}:channel_layouts={layout}"
        filters.extend(
            [
                f"[0:a]atrim=start=0:end={at},asetpts=PTS-STARTPTS,{aformat}[aa]",
                # Silence of matching length keeps the audio in sync with the hold.
                (
                    f"anullsrc=channel_layout={layout}:sample_rate={sr},"
                    f"atrim=duration={hold},{aformat}[ab]"
                ),
                f"[0:a]atrim=start={at},asetpts=PTS-STARTPTS,{aformat}[ac]",
                # Concatenate A + B + C with matching audio.
                "[va][aa][vb][ab][vc][ac]concat=n=3:v=1:a=1[vo][ao]",
            ]
        )
        cmd.set_filter_complex(";".join(filters))
        cmd.map("[vo]", "[ao]")
    else:
        # Video-only source — skip the audio graph entirely and concat the
        # three video segments only. This is the fix for screen recordings
        # and GIF-to-MP4 conversions that have no audio track.
        filters.append("[va][vb][vc]concat=n=3:v=1:a=0[vo]")
        cmd.set_filter_complex(";".join(filters))
        cmd.map("[vo]")

    cmd.out(str(dst))
    return cmd


__all__ = ["freeze_frame"]
