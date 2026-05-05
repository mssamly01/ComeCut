"""Tests for filmstrip thumbnail rendering + caching."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from comecut_py.engine.thumbnails import render_filmstrip_png


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """Build a tiny 2-second test video; skip the test if ffmpeg is missing."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg not available")
    out = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v", "error",
            "-f", "lavfi",
            "-i", "color=c=red:s=120x90:d=2:r=12",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out


def test_missing_source_returns_none(tmp_path: Path):
    assert render_filmstrip_png(tmp_path / "no-such.mp4") is None


def test_renders_and_caches(sample_video: Path, tmp_path: Path, monkeypatch):
    # Redirect the cache dir to keep the test hermetic.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    png = render_filmstrip_png(
        sample_video, strip_width=200, strip_height=40, frames=4, duration=2.0
    )
    assert png is not None
    assert png.exists() and png.stat().st_size > 0

    # Second call with the same args hits the cache. Drop mtime to 0 on the
    # cached file and confirm it's reused rather than regenerated.
    os.utime(png, (0, 0))
    png2 = render_filmstrip_png(
        sample_video, strip_width=200, strip_height=40, frames=4, duration=2.0
    )
    assert png2 == png
    assert png2.stat().st_mtime == 0


def test_cache_key_differs_for_different_dimensions(sample_video: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    a = render_filmstrip_png(sample_video, strip_width=200, strip_height=40, frames=4, duration=2.0)
    b = render_filmstrip_png(sample_video, strip_width=320, strip_height=40, frames=4, duration=2.0)
    assert a is not None and b is not None
    assert a != b


def test_strip_width_respects_frames_floor(sample_video: Path, tmp_path: Path, monkeypatch):
    """If strip_width < frames, we must still produce a valid PNG (>=1 px tiles)."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    png = render_filmstrip_png(
        sample_video, strip_width=2, strip_height=20, frames=8, duration=2.0
    )
    assert png is not None
    assert png.exists() and png.stat().st_size > 0
