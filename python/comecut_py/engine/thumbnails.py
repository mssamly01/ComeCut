"""Render a horizontal filmstrip thumbnail of a video for timeline display.

Uses ffmpeg's ``fps``/``scale``/``tile`` filter chain to sample ``N`` evenly
spaced frames from the source and tile them into one PNG. The result is
cached on disk so repeated timeline refreshes don't re-invoke ffmpeg.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from ..core.ffmpeg_cmd import detect_cuda_decode_available, ensure_ffmpeg

TILES_PER_CHUNK = 60
DEFAULT_TILE_WIDTH = 80
DEFAULT_TILE_HEIGHT = 48
THUMB_COVER_MODE_VERSION = "cover-v1"


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    d = Path(base) / "comecut-py" / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(
    src: str | Path,
    *,
    strip_width: int,
    strip_height: int,
    frames: int,
    duration: float | None,
) -> str:
    path = Path(src).resolve()
    try:
        st = path.stat()
        sig = (
            f"{path}:{st.st_size}:{int(st.st_mtime)}:{strip_width}x{strip_height}"
            f":n{frames}:d{duration}:m{THUMB_COVER_MODE_VERSION}"
        )
    except OSError:
        sig = f"{path}:{strip_width}x{strip_height}:n{frames}:d{duration}:m{THUMB_COVER_MODE_VERSION}"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


def _chunk_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    d = Path(base) / "comecut-py" / "filmstrip-chunks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chunk_cache_key(
    src: str | Path,
    *,
    tile_width: int,
    tile_height: int,
    tiles_per_chunk: int,
) -> str:
    path = Path(src).resolve()
    try:
        st = path.stat()
        sig = (
            f"{path}:{st.st_size}:{int(st.st_mtime)}:"
            f"{tile_width}x{tile_height}:tpc{tiles_per_chunk}:m{THUMB_COVER_MODE_VERSION}"
        )
    except OSError:
        sig = f"{path}:{tile_width}x{tile_height}:tpc{tiles_per_chunk}:m{THUMB_COVER_MODE_VERSION}"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


def chunk_path(
    src: str | Path,
    chunk_idx: int,
    *,
    tile_width: int = DEFAULT_TILE_WIDTH,
    tile_height: int = DEFAULT_TILE_HEIGHT,
    tiles_per_chunk: int = TILES_PER_CHUNK,
) -> Path:
    """Return the cache path for one per-second filmstrip chunk."""
    key = _chunk_cache_key(
        src,
        tile_width=tile_width,
        tile_height=tile_height,
        tiles_per_chunk=tiles_per_chunk,
    )
    return _chunk_cache_dir() / key / f"c{int(chunk_idx):05d}.jpg"


def render_filmstrip_png(
    src: str | Path,
    *,
    strip_width: int = 400,
    strip_height: int = 48,
    frames: int = 8,
    duration: float | None = None,
) -> Path | None:
    """Render a horizontal filmstrip PNG and return the cached file path.

    ``frames`` controls how many thumbnails make up the strip. Each thumbnail
    is ``strip_width / frames`` pixels wide. If ``duration`` is provided, the
    ffmpeg sampling rate is chosen so the requested number of frames is hit
    regardless of the source's fps. Returns ``None`` if the source is missing
    or ffmpeg fails.
    """
    frames = max(1, int(frames))
    strip_width = max(frames, int(strip_width))
    strip_height = max(1, int(strip_height))
    src_path = Path(src)
    if not src_path.exists():
        return None

    out = _cache_dir() / f"{_cache_key(src, strip_width=strip_width, strip_height=strip_height, frames=frames, duration=duration)}.png"
    if out.exists() and out.stat().st_size > 0:
        return out

    try:
        ffmpeg = ensure_ffmpeg()
    except RuntimeError:
        return None

    hwaccel_args: list[str] = []
    try:
        if detect_cuda_decode_available():
            hwaccel_args = ["-hwaccel", "cuda"]
    except Exception:
        hwaccel_args = []

    tile_w = max(1, strip_width // frames)
    tile_h = strip_height

    # When we know the clip duration we can evenly spread `frames` samples
    # across it; otherwise fall back to a fixed 1-frame-per-second rate.
    if duration is not None and duration > 0:
        sample_rate = max(0.01, frames / float(duration))
        fps_filter = f"fps={sample_rate:.4f}"
    else:
        fps_filter = "fps=1"

    filt = (
        f"{fps_filter},"
        f"scale={tile_w}:{tile_h}:force_original_aspect_ratio=increase,"
        f"crop={tile_w}:{tile_h},"
        f"tile={frames}x1"
    )
    argv = [
        ffmpeg,
        "-v", "error",
        "-y",
        *hwaccel_args,
        "-i", str(src_path),
        "-vf", filt,
        "-frames:v", "1",
        str(out),
    ]
    try:
        subprocess.run(argv, check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return out if out.exists() else None


def extract_filmstrip_chunk(
    src: str | Path,
    chunk_idx: int,
    *,
    tile_width: int = DEFAULT_TILE_WIDTH,
    tile_height: int = DEFAULT_TILE_HEIGHT,
    tiles_per_chunk: int = TILES_PER_CHUNK,
) -> Path | None:
    """Extract a cache chunk containing one thumbnail per source second.

    The output is one horizontal JPG with ``tiles_per_chunk`` tiles. It is
    zoom-independent, so the timeline can draw only the source-second tiles it
    needs instead of stretching one fixed filmstrip across the whole clip.
    """
    tile_width = max(1, int(tile_width))
    tile_height = max(1, int(tile_height))
    tiles_per_chunk = max(1, int(tiles_per_chunk))
    chunk_idx = max(0, int(chunk_idx))

    src_path = Path(src)
    if not src_path.exists():
        return None

    out = chunk_path(
        src_path,
        chunk_idx,
        tile_width=tile_width,
        tile_height=tile_height,
        tiles_per_chunk=tiles_per_chunk,
    )
    if out.exists() and out.stat().st_size > 0:
        return out

    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        ffmpeg = ensure_ffmpeg()
    except RuntimeError:
        return None

    hwaccel_args: list[str] = []
    try:
        if detect_cuda_decode_available():
            hwaccel_args = ["-hwaccel", "cuda"]
    except Exception:
        hwaccel_args = []

    start_seconds = chunk_idx * tiles_per_chunk
    filt = (
        "fps=1,"
        f"scale={tile_width}:{tile_height}:force_original_aspect_ratio=increase,"
        f"crop={tile_width}:{tile_height},"
        f"tile={tiles_per_chunk}x1"
    )
    argv = [
        ffmpeg,
        "-v",
        "error",
        "-y",
        *hwaccel_args,
        "-ss",
        str(start_seconds),
        "-t",
        str(tiles_per_chunk),
        "-i",
        str(src_path),
        "-vf",
        filt,
        "-frames:v",
        "1",
        "-q:v",
        "5",
        str(out),
    ]
    try:
        subprocess.run(argv, check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        if out.exists():
            try:
                out.unlink()
            except OSError:
                pass
        return None
    return out if out.exists() and out.stat().st_size > 0 else None


__all__ = [
    "render_filmstrip_png",
    "extract_filmstrip_chunk",
    "chunk_path",
    "TILES_PER_CHUNK",
    "DEFAULT_TILE_WIDTH",
    "DEFAULT_TILE_HEIGHT",
]
