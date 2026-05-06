"""Cached audio proxies for smooth timeline preview playback."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from ..core.ffmpeg_cmd import ensure_ffmpeg


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    path = Path(base) / "comecut-py" / "audio-proxies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(
    src: str | Path,
    *,
    sample_rate: int,
    channels: int,
    codec: str,
) -> str:
    path = Path(src).resolve()
    try:
        st = path.stat()
        sig = (
            f"{path}:{st.st_size}:{st.st_mtime_ns}:"
            f"sr{sample_rate}:ch{channels}:codec{codec}:v1"
        )
    except OSError:
        sig = f"{path}:sr{sample_rate}:ch{channels}:codec{codec}:v1"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:20]


def audio_proxy_path(
    src: str | Path,
    *,
    sample_rate: int = 44100,
    channels: int = 2,
    codec: str = "pcm_s16le",
) -> Path:
    ext = "wav" if codec == "pcm_s16le" else "m4a"
    key = _cache_key(src, sample_rate=sample_rate, channels=channels, codec=codec)
    return _cache_dir() / f"{key}.{ext}"


def make_audio_proxy(
    src: str | Path,
    *,
    sample_rate: int = 44100,
    channels: int = 2,
    codec: str = "pcm_s16le",
    force: bool = False,
    timeout: float = 300.0,
) -> Path:
    src_path = Path(src)
    if not src_path.exists():
        raise RuntimeError(f"audio source not found: {src_path}")

    out = audio_proxy_path(
        src_path,
        sample_rate=sample_rate,
        channels=channels,
        codec=codec,
    )
    if not force and out.exists() and out.stat().st_size > 0:
        return out

    tmp = out.with_name(f"{out.stem}.tmp{out.suffix}")
    if tmp.exists():
        tmp.unlink()

    ffmpeg = ensure_ffmpeg()
    argv = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(src_path),
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
    ]
    if codec == "pcm_s16le":
        argv.extend(["-c:a", "pcm_s16le", str(tmp)])
    else:
        argv.extend(["-c:a", "aac", "-b:a", "128k", str(tmp)])

    try:
        subprocess.run(argv, check=True, capture_output=True, timeout=timeout)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"audio proxy failed for {src_path}: {exc}") from exc

    tmp.replace(out)
    return out


__all__ = ["audio_proxy_path", "make_audio_proxy"]
