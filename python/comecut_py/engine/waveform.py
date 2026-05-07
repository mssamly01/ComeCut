"""Render a monochrome PNG waveform thumbnail for an audio/video file.

Uses ffmpeg's ``showwavespic`` filter. The result is cached on disk under the
platform-appropriate user cache directory so subsequent refreshes of the
timeline panel don't re-invoke ffmpeg.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path

from ..core.ffmpeg_cmd import ensure_ffmpeg


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    d = Path(base) / "comecut-py" / "waveforms"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(src: str | Path, width: int, height: int) -> str:
    path = Path(src).resolve()
    try:
        st = path.stat()
        sig = f"{path}:{st.st_size}:{int(st.st_mtime)}:{width}x{height}"
    except OSError:
        sig = f"{path}:{width}x{height}"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


def render_waveform_png(
    src: str | Path,
    *,
    width: int = 400,
    height: int = 48,
    color: str = "0x2BB67355",
) -> Path | None:
    """Render a PNG waveform thumbnail and return the file path.

    Returns ``None`` if ``src`` does not exist or ffmpeg is missing. Requested
    sizes below 1 pixel are silently clamped.
    """
    width = max(1, int(width))
    height = max(1, int(height))
    src_path = Path(src)
    if not src_path.exists():
        return None

    out = _cache_dir() / f"{_cache_key(src, width, height)}.png"
    if out.exists() and out.stat().st_size > 0:
        return out

    try:
        ffmpeg = ensure_ffmpeg()
    except RuntimeError:
        return None

    filt = f"showwavespic=s={width}x{height}:colors={color}:split_channels=0"
    argv = [
        ffmpeg,
        "-v", "error",
        "-y",
        "-i", str(src_path),
        "-filter_complex", filt,
        "-frames:v", "1",
        str(out),
    ]
    try:
        subprocess.run(argv, check=True, capture_output=True, timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return out if out.exists() else None


def _peaks_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    d = Path(base) / "comecut-py" / "waveform-peaks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _peaks_cache_key(src: str | Path, num_peaks: int) -> str:
    path = Path(src).resolve()
    try:
        st = path.stat()
        sig = f"{path}:{st.st_size}:{int(st.st_mtime)}:n{num_peaks}"
    except OSError:
        sig = f"{path}:n{num_peaks}"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


def _range_peaks_cache_key(
    src: str | Path,
    *,
    start: float,
    duration: float,
    num_peaks: int,
) -> str:
    path = Path(src).resolve()
    start_ms = int(round(max(0.0, float(start)) * 1000.0))
    duration_ms = int(round(max(0.0, float(duration)) * 1000.0))
    try:
        st = path.stat()
        sig = (
            f"{path}:{st.st_size}:{st.st_mtime_ns}:"
            f"s{start_ms}:d{duration_ms}:n{num_peaks}:range-v1"
        )
    except OSError:
        sig = f"{path}:s{start_ms}:d{duration_ms}:n{num_peaks}:range-v1"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:20]


def _peaks_from_s16le(raw: bytes, *, num_peaks: int) -> list[float] | None:
    n_samples = len(raw) // 2
    if n_samples <= 0:
        return None

    bucket = max(1, n_samples // num_peaks)
    peaks: list[float] = []
    fmt_cache: dict[int, str] = {}
    for i in range(num_peaks):
        s_start = i * bucket
        s_end = min(s_start + bucket, n_samples)
        if s_end <= s_start:
            peaks.append(0.0)
            continue
        chunk = raw[s_start * 2 : s_end * 2]
        n = len(chunk) // 2
        fmt = fmt_cache.get(n) or fmt_cache.setdefault(n, f"<{n}h")
        try:
            samples = struct.unpack(fmt, chunk)
        except struct.error:
            peaks.append(0.0)
            continue
        peak = max((abs(s) for s in samples), default=0)
        peaks.append(min(1.0, peak / 32768.0))
    return peaks


def extract_waveform_peaks(
    src: str | Path,
    *,
    num_peaks: int = 256,
) -> list[float] | None:
    """Extract normalized [0..1] peaks for capcut-style waveform bars."""
    num_peaks = max(8, int(num_peaks))
    src_path = Path(src)
    if not src_path.exists():
        return None

    cache = _peaks_cache_dir() / f"{_peaks_cache_key(src, num_peaks)}.json"
    if cache.exists() and cache.stat().st_size > 0:
        try:
            data = json.loads(cache.read_text("utf-8"))
            if isinstance(data, list) and all(isinstance(x, (int, float)) for x in data):
                return [float(x) for x in data]
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass

    try:
        ffmpeg = ensure_ffmpeg()
    except RuntimeError:
        return None

    argv = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(src_path),
        "-ac",
        "1",
        "-ar",
        "8000",
        "-f",
        "s16le",
        "-",
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if proc.returncode != 0 or not proc.stdout:
        return None

    peaks = _peaks_from_s16le(proc.stdout, num_peaks=num_peaks)
    if peaks is None:
        return None

    try:
        cache.write_text(json.dumps(peaks), "utf-8")
    except OSError:
        pass
    return peaks


def extract_waveform_peaks_range(
    src: str | Path,
    *,
    start: float,
    duration: float,
    num_peaks: int = 256,
) -> list[float] | None:
    """Extract normalized peaks for a bounded source range.

    This is intended for long timeline clips: the UI can draw the visible
    portion without decoding a multi-hour audio stream. ``start`` and
    ``duration`` are source seconds.
    """
    num_peaks = max(8, int(num_peaks))
    start = max(0.0, float(start))
    duration = max(0.001, float(duration))
    src_path = Path(src)
    if not src_path.exists():
        return None

    cache = _peaks_cache_dir() / (
        f"{_range_peaks_cache_key(src_path, start=start, duration=duration, num_peaks=num_peaks)}.json"
    )
    if cache.exists() and cache.stat().st_size > 0:
        try:
            data = json.loads(cache.read_text("utf-8"))
            if isinstance(data, list) and all(isinstance(x, (int, float)) for x in data):
                return [float(x) for x in data]
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass

    try:
        ffmpeg = ensure_ffmpeg()
    except RuntimeError:
        return None

    argv = [
        ffmpeg,
        "-v",
        "error",
        "-ss",
        f"{start:.6f}",
        "-t",
        f"{duration:.6f}",
        "-i",
        str(src_path),
        "-ac",
        "1",
        "-ar",
        "8000",
        "-f",
        "s16le",
        "-",
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if proc.returncode != 0 or not proc.stdout:
        return None

    peaks = _peaks_from_s16le(proc.stdout, num_peaks=num_peaks)
    if peaks is None:
        return None

    try:
        cache.write_text(json.dumps(peaks), "utf-8")
    except OSError:
        pass
    return peaks


__all__ = ["render_waveform_png", "extract_waveform_peaks", "extract_waveform_peaks_range"]
