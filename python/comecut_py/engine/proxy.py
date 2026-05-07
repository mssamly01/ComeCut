"""Low-res proxy generation for fast timeline preview.

A proxy is a scaled-down, low-bitrate transcode of the source used during
editing. The full-resolution source is still used at render time — the
:func:`comecut_py.engine.render.render_project` function accepts a
``use_proxies`` flag that swaps ``Clip.source`` for ``Clip.proxy`` when True.

Proxies are cached under the app user cache directory keyed by a hash of
``(source path, size, mtime, target width, target height, video codec)`` so
we don't regenerate them for every preview session.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from ..core.ffmpeg_cmd import (
    detect_cuda_decode_available,
    detect_nvenc_available,
    ensure_ffmpeg,
)
from ..core.media_cache import user_cache_root


def _cache_dir() -> Path:
    d = user_cache_root() / "proxies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(
    src: str | Path,
    *,
    width: int,
    height: int | None,
    vcodec: str,
    crf: int,
    preset: str,
    audio_bitrate: str,
) -> str:
    path = Path(src).resolve()
    params = f"w{width}:h{height}:{vcodec}:crf{crf}:{preset}:ab{audio_bitrate}"
    # Dense keyframes make preview seeking/scrubbing much cheaper.
    params += ":seekg48"
    try:
        st = path.stat()
        # st_mtime_ns preserves full nanosecond precision; truncating to int
        # seconds would let an in-place edit that kept the file size identical
        # and happened within the same second silently reuse the stale proxy.
        sig = f"{path}:{st.st_size}:{st.st_mtime_ns}:{params}"
    except OSError:
        sig = f"{path}:{params}"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


def proxy_path(
    src: str | Path,
    *,
    width: int = 640,
    height: int | None = None,
    vcodec: str = "libx264",
    crf: int = 28,
    preset: str = "veryfast",
    audio_bitrate: str = "96k",
) -> Path:
    """Return the expected proxy path for ``src`` — may or may not exist yet."""
    return _cache_dir() / f"{_cache_key(src, width=width, height=height, vcodec=vcodec, crf=crf, preset=preset, audio_bitrate=audio_bitrate)}.mp4"


def make_proxy(
    src: str | Path,
    *,
    width: int = 640,
    height: int | None = None,
    vcodec: str = "libx264",
    crf: int = 28,
    preset: str = "veryfast",
    audio_bitrate: str = "96k",
    force: bool = False,
    use_gpu: bool | None = None,
) -> Path:
    """Generate (or return a cached) low-res proxy and return its path.

    The output is an MP4 scaled to ``width`` px wide (height auto, preserving
    aspect) unless ``height`` is explicitly provided. Audio is preserved as
    AAC at ``audio_bitrate`` when present. Raises :class:`RuntimeError` if
    the source is missing, ffmpeg is missing, or the transcode fails.
    """
    src_path = Path(src)
    if not src_path.exists():
        raise RuntimeError(f"source not found: {src_path}")

    if use_gpu is None:
        use_gpu = detect_nvenc_available()

    if use_gpu:
        vcodec_actual = "h264_nvenc"
        preset_map = {
            "veryfast": "p1",
            "fast": "p2",
            "medium": "p4",
            "slow": "p6",
            "veryslow": "p7",
        }
        preset_actual = preset_map.get(preset, "p2")
    else:
        vcodec_actual = vcodec
        preset_actual = preset

    out = proxy_path(
        src,
        width=width,
        height=height,
        vcodec=vcodec_actual,
        crf=crf,
        preset=preset_actual,
        audio_bitrate=audio_bitrate,
    )
    if not force and out.exists() and out.stat().st_size > 0:
        return out

    ffmpeg = ensure_ffmpeg()  # may raise RuntimeError

    # Width-only scaling is already aspect-preserving (``-2`` keeps height
    # divisible by 2 so libx264 is happy). ``force_original_aspect_ratio``
    # requires an explicit height so we only pass it when one was provided.
    if height is None:
        scale = f"scale={width}:-2"
    else:
        scale = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"

    hwaccel_args: list[str] = []
    if use_gpu and detect_cuda_decode_available():
        # Keep the regular CPU scale filter for maximum compatibility; ffmpeg
        # downloads frames as needed and NVENC still accelerates the expensive
        # encode step. If this path fails, we retry once with CPU below.
        hwaccel_args = ["-hwaccel", "cuda"]
    quality_args = ["-cq", str(crf), "-rc", "vbr"] if use_gpu else ["-crf", str(crf)]

    argv = [
        ffmpeg, "-v", "error", "-y",
        *hwaccel_args,
        "-i", str(src_path),
        "-vf", scale,
        "-c:v", vcodec_actual,
        "-preset", preset_actual,
        *quality_args,
        "-g", "48",
        "-keyint_min", "24",
        "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        str(out),
    ]
    try:
        subprocess.run(argv, check=True, capture_output=True, timeout=600)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        # Clean up a half-written file so the next call doesn't return junk.
        if out.exists():
            out.unlink()
        if use_gpu:
            return make_proxy(
                src,
                width=width,
                height=height,
                vcodec=vcodec,
                crf=crf,
                preset=preset,
                audio_bitrate=audio_bitrate,
                force=force,
                use_gpu=False,
            )
        raise RuntimeError(f"proxy generation failed for {src_path}: {e}") from e
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"proxy generation produced no output for {src_path}")
    return out


def _source_has_video(src: str | Path) -> bool:
    """Return True if ``src`` is probe-able and contains at least one video stream.

    Used by :func:`ensure_proxies` to skip audio-only sources, which would
    otherwise blow up in ``make_proxy`` because it always applies a video
    ``scale`` filter. Any probe error is treated as "unknown → skip", since
    generating a proxy for an unreachable / unreadable source is pointless.
    """
    from ..core.media_probe import probe

    try:
        info = probe(Path(src))
    except Exception:
        return False
    return bool(getattr(info, "has_video", False))


def ensure_proxies(project, *, width: int = 640, **kwargs) -> list[tuple[str, Path]]:
    """Generate proxies for every unique video source referenced by ``project``.

    Audio-only sources (``.mp3`` / ``.wav`` / etc.) are skipped — they don't
    have a video stream to scale, and the rendering pipeline never reads
    from a proxy for audio-only clips anyway. Each video clip's ``proxy``
    field is written in place so subsequent project saves retain the
    mapping. Returns a ``[(source, proxy_path), …]`` list of newly-generated
    proxies.
    """
    seen: dict[str, Path | None] = {}
    mapping: list[tuple[str, Path]] = []
    for track in project.tracks:
        for clip in track.clips:
            src = str(clip.source)
            if src in seen:
                p = seen[src]
            elif not _source_has_video(src):
                # Remember "no-video" sources so we don't re-probe them for
                # every clip that references them.
                seen[src] = None
                continue
            else:
                p = make_proxy(src, width=width, **kwargs)
                seen[src] = p
                mapping.append((src, p))
            if p is not None:
                clip.proxy = str(p)
    return mapping


__all__ = ["ensure_proxies", "make_proxy", "proxy_path"]
