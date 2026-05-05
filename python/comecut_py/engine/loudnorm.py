"""Two-pass EBU R128 loudness normalisation.

Single-pass ``loudnorm`` can introduce audible pumping on content with wide
dynamic range. FFmpeg's recommended workflow is:

1. **Analyse** — run ``loudnorm`` with ``print_format=json`` and parse the
   measured ``input_i``, ``input_tp``, ``input_lra``, ``input_thresh``,
   and ``target_offset`` values.
2. **Apply** — run ``loudnorm`` again with those measurements as
   ``measured_*`` parameters plus ``linear=true``, which switches the
   filter from dynamic to linear (gain-only) normalisation.

The output is guaranteed to hit the requested LUFS target without the
dynamic mode's compressor artefacts.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ..core.ffmpeg_cmd import ensure_ffmpeg


def _parse_loudnorm_json(stderr: str) -> dict[str, str]:
    """Pick the JSON block that ``loudnorm`` appends to ffmpeg's stderr."""
    # ffmpeg prints the JSON after the final "[Parsed_loudnorm_...] " line —
    # use a regex that finds the last ``{...}`` block to avoid parsing any
    # earlier noise.
    matches = list(re.finditer(r"\{[^{}]*\}", stderr, re.DOTALL))
    if not matches:
        raise RuntimeError(
            "Could not locate loudnorm JSON output in ffmpeg stderr:\n" + stderr
        )
    for m in reversed(matches):
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if "input_i" in data:
            return data
    raise RuntimeError("loudnorm stderr had no input_i field:\n" + stderr)


def loudnorm_twopass(
    src: str | Path,
    dst: str | Path,
    *,
    integrated_lufs: float = -16.0,
    true_peak_dbtp: float = -1.5,
    lra: float = 11.0,
) -> Path:
    """Measure + apply EBU R128 loudnorm in two passes.

    Parameters
    ----------
    integrated_lufs : float
        Target integrated loudness. ``-16`` is a good default for
        YouTube/podcasts; ``-14`` for Spotify; ``-23`` for broadcast (EBU).
    true_peak_dbtp : float
        Maximum true peak in dBTP. ``-1.5`` leaves safe headroom for lossy
        encoders.
    lra : float
        Target loudness range (dynamic spread).
    """
    binary = ensure_ffmpeg()
    src = Path(src)
    dst = Path(dst)

    # Pass 1 — analyse. Output is discarded (``-f null``) since we only care
    # about the JSON measurement.
    analyse = [
        binary, "-hide_banner", "-y", "-i", str(src),
        "-af",
        (
            f"loudnorm=I={integrated_lufs}:TP={true_peak_dbtp}:LRA={lra}"
            ":print_format=json"
        ),
        "-f", "null", "-",
    ]
    r = subprocess.run(analyse, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"loudnorm analyse pass failed (exit={r.returncode}):\n{r.stderr.strip()}"
        )
    m = _parse_loudnorm_json(r.stderr)

    # Pass 2 — apply with measured_* and linear=true so the gain is
    # applied uniformly, producing a clean, artefact-free normalisation.
    apply = [
        binary, "-hide_banner", "-y", "-i", str(src),
        "-af",
        (
            f"loudnorm=I={integrated_lufs}:TP={true_peak_dbtp}:LRA={lra}"
            f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
            f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
            f":offset={m['target_offset']}:linear=true:print_format=summary"
        ),
        "-c:v", "copy",
        str(dst),
    ]
    r = subprocess.run(apply, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"loudnorm apply pass failed (exit={r.returncode}):\n{r.stderr.strip()}"
        )
    return dst.resolve()


__all__ = ["loudnorm_twopass"]
