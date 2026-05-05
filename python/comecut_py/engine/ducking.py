"""Sidechain-compressor ducking: automatically dip music under voice.

Takes two audio sources — a *voice* (key) track and a *music* (duckee)
track — and returns a mixed track where the music is pulled down in level
whenever the voice is active. Implemented with ffmpeg's
``sidechaincompress`` filter.
"""

from __future__ import annotations

from pathlib import Path

from ..core.ffmpeg_cmd import FFmpegCommand


def duck(
    voice: str | Path,
    music: str | Path,
    dst: str | Path,
    *,
    threshold: float = 0.05,
    ratio: float = 8.0,
    attack: float = 5.0,
    release: float = 250.0,
    makeup: float = 1.0,
    mix: float = 1.0,
) -> FFmpegCommand:
    """Duck ``music`` under ``voice`` and mix both into ``dst``.

    Parameters
    ----------
    threshold : float
        Level above which the sidechain (voice) opens the compressor. Lower
        = more aggressive ducking.
    ratio : float
        Compression ratio applied to music while voice is above threshold.
    attack, release : float
        Attack and release time in milliseconds. ``5`` / ``250`` is a gentle
        podcast-style duck; drop release to ~100 for very quick recovery.
    makeup : float
        Make-up gain applied to the ducked music (1.0 = no boost).
    mix : float
        Dry/wet ratio of the compressor (1.0 = fully processed).
    """
    cmd = FFmpegCommand()
    cmd.add_input(str(voice))  # input 0 — key
    cmd.add_input(str(music))  # input 1 — duckee

    # Duplicate the voice so we can both route it into the compressor as
    # sidechain AND keep it for the final mix.
    filters = [
        "[0:a]asplit=2[voice_out][voice_key]",
        (
            f"[1:a][voice_key]sidechaincompress=threshold={threshold}"
            f":ratio={ratio}:attack={attack}:release={release}"
            f":makeup={makeup}:mix={mix}[ducked]"
        ),
        # ``normalize=0`` is critical — the default ``normalize=1`` divides
        # the sum by the number of active inputs (here 2), halving both
        # voice and ducked music (-6 dB). That defeats the point of
        # sidechain ducking, which is to keep voice at full level.
        "[voice_out][ducked]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]",
    ]
    cmd.set_filter_complex(";".join(filters))
    cmd.map("[aout]")
    cmd.out(str(dst))
    return cmd


__all__ = ["duck"]
