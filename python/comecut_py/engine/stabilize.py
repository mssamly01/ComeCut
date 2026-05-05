"""Two-pass video stabilisation using ``vidstabdetect`` + ``vidstabtransform``.

This is a standalone operation (not part of :func:`render_project`) because
ffmpeg's stabilisation requires a full analysis pass that writes a transforms
file before the smoothing pass can read it.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from ..core.ffmpeg_cmd import ensure_ffmpeg


def stabilize(
    src: str | Path,
    dst: str | Path,
    *,
    shakiness: int = 5,
    smoothing: int = 10,
    zoom: float = 0.0,
    transforms_path: str | Path | None = None,
) -> Path:
    """Stabilise ``src`` into ``dst`` via ffmpeg's two-pass vid.stab filters.

    Parameters
    ----------
    shakiness : int
        Scale for how shaky the source is (1 = mild, 10 = very shaky).
    smoothing : int
        Number of frames on each side used to build the smoothing window.
    zoom : float
        Extra zoom in percent to hide black borders from warping
        (0 = no crop, recommended 1..5 for typical hand-held footage).
    transforms_path : path-like or None
        Where to write the intermediate ``.trf`` file. A temporary file is
        used and cleaned up when ``None``.

    Returns
    -------
    Path
        Absolute path to the stabilised output.

    Raises
    ------
    comecut_py.core.ffmpeg_cmd.FFmpegNotFoundError
        If ``ffmpeg`` is not on ``PATH``.
    RuntimeError
        If either ffmpeg pass fails.
    """
    binary = ensure_ffmpeg()
    src = Path(src)
    dst = Path(dst)

    cleanup = False
    if transforms_path is None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".trf") as tmp:
            trf = Path(tmp.name)
        cleanup = True
    else:
        trf = Path(transforms_path)

    try:
        # Pass 1 — detect motion vectors, write transforms file.
        detect = [
            binary, "-hide_banner", "-y", "-i", str(src),
            "-vf", f"vidstabdetect=shakiness={shakiness}:accuracy=15:result={trf}",
            "-f", "null", "-",
        ]
        r = subprocess.run(detect, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"vidstabdetect failed (exit={r.returncode}):\n{r.stderr.strip()}"
            )

        # Pass 2 — apply the computed transforms, re-encode.
        transform = [
            binary, "-hide_banner", "-y", "-i", str(src),
            "-vf",
            (
                f"vidstabtransform=smoothing={smoothing}:zoom={zoom}:input={trf},"
                "unsharp=5:5:0.8:3:3:0.4"
            ),
            "-c:a", "copy",
            str(dst),
        ]
        r = subprocess.run(transform, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"vidstabtransform failed (exit={r.returncode}):\n{r.stderr.strip()}"
            )
    finally:
        if cleanup and trf.exists():
            trf.unlink()

    return dst.resolve()


__all__ = ["stabilize"]
