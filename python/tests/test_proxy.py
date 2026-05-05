"""Tests for the proxy workflow (low-res preview, full-res render)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from comecut_py.core.project import Clip, Project, Track
from comecut_py.engine.proxy import ensure_proxies, make_proxy, proxy_path
from comecut_py.engine.render import _clip_input_path, render_project


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


# ---- model ---------------------------------------------------------------


def test_clip_proxy_field_defaults_to_none():
    c = Clip(source="/a/b.mp4")
    assert c.proxy is None


def test_clip_proxy_roundtrip(tmp_path: Path):
    p = Project(
        tracks=[Track(kind="video", clips=[Clip(source="/a/b.mp4", proxy="/cache/b_proxy.mp4")])]
    )
    f = tmp_path / "p.json"
    p.to_json(f)
    parsed = Project.from_json(f)
    assert parsed.tracks[0].clips[0].proxy == "/cache/b_proxy.mp4"


# ---- _clip_input_path -----------------------------------------------------


def test_clip_input_path_prefers_proxy_when_enabled(tmp_path: Path):
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"fake")
    c = Clip(source="/a/full.mp4", proxy=str(proxy))
    assert _clip_input_path(c, use_proxies=True) == str(proxy)
    # With use_proxies=False we always fall back to the full-res source.
    assert _clip_input_path(c, use_proxies=False) == "/a/full.mp4"


def test_clip_input_path_falls_back_when_proxy_missing(tmp_path: Path):
    c = Clip(source="/a/full.mp4", proxy=str(tmp_path / "does_not_exist.mp4"))
    assert _clip_input_path(c, use_proxies=True) == "/a/full.mp4"


def test_clip_input_path_uses_source_when_no_proxy_field():
    c = Clip(source="/a/full.mp4")
    assert _clip_input_path(c, use_proxies=True) == "/a/full.mp4"


# ---- proxy_path / cache key ----------------------------------------------


def test_proxy_path_stable_for_same_inputs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    src = tmp_path / "v.mp4"
    src.write_bytes(b"\x00" * 32)
    a = proxy_path(src, width=640)
    b = proxy_path(src, width=640)
    assert a == b
    # Different width → different cache key.
    c = proxy_path(src, width=320)
    assert c != a


def test_proxy_path_includes_encoding_params_in_cache_key(tmp_path: Path, monkeypatch):
    """Changing crf / preset / audio_bitrate must change the cache path — otherwise a
    user running --crf 28 then --crf 18 would silently get the stale low-quality file.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    src = tmp_path / "v.mp4"
    src.write_bytes(b"\x00" * 32)
    base = proxy_path(src, width=640, crf=28, preset="veryfast", audio_bitrate="96k")
    assert proxy_path(src, width=640, crf=18) != base
    assert proxy_path(src, width=640, preset="medium") != base
    assert proxy_path(src, width=640, audio_bitrate="192k") != base
    assert proxy_path(src, width=640, vcodec="libx265") != base


# ---- render_project use_proxies plumbing ---------------------------------


def test_render_project_use_proxies_swaps_input_paths(tmp_path: Path):
    """When use_proxies=True the ffmpeg argv lists the proxy, not the source."""
    src = tmp_path / "full.mp4"
    proxy = tmp_path / "proxy.mp4"
    src.write_bytes(b"F")
    proxy.write_bytes(b"P")

    project = Project(
        width=320, height=180, fps=24,
        tracks=[
            Track(
                kind="video",
                clips=[Clip(source=str(src), proxy=str(proxy), in_point=0.0, out_point=1.0)],
            ),
        ],
    )

    argv_proxy = render_project(project, tmp_path / "out.mp4", use_proxies=True).build(
        ffmpeg_bin="ffmpeg"
    )
    argv_full = render_project(project, tmp_path / "out.mp4", use_proxies=False).build(
        ffmpeg_bin="ffmpeg"
    )
    assert str(proxy) in argv_proxy
    assert str(src) not in argv_proxy
    assert str(src) in argv_full
    assert str(proxy) not in argv_full


# ---- ensure_proxies (needs real ffmpeg) ----------------------------------


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
def test_make_proxy_generates_and_caches(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    src = tmp_path / "big.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(src),
        ],
        check=True, capture_output=True,
    )

    out1 = make_proxy(src, width=320, crf=30)
    assert out1.exists() and out1.stat().st_size > 0
    # Cached: second invocation returns the same file with unchanged mtime.
    import os as _os
    _os.utime(out1, (0, 0))
    out2 = make_proxy(src, width=320, crf=30)
    assert out2 == out1
    assert out2.stat().st_mtime == 0

    # --force regenerates.
    out3 = make_proxy(src, width=320, crf=30, force=True)
    assert out3 == out1
    assert out3.stat().st_mtime > 0


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
def test_ensure_proxies_attaches_paths_to_clips(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    src = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x180:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(src),
        ],
        check=True, capture_output=True,
    )

    project = Project(
        tracks=[
            Track(kind="video", clips=[Clip(source=str(src), in_point=0, out_point=1)]),
            # Second clip references the same source — dedupe, only one proxy generated.
            Track(kind="video", clips=[Clip(source=str(src), in_point=0, out_point=1)]),
        ]
    )
    mapping = ensure_proxies(project, width=160)
    assert len(mapping) == 1  # deduped
    for tr in project.tracks:
        assert tr.clips[0].proxy is not None
        assert Path(tr.clips[0].proxy).exists()


def test_make_proxy_raises_on_missing_source(tmp_path: Path):
    with pytest.raises(RuntimeError, match="source not found"):
        make_proxy(tmp_path / "nope.mp4")
