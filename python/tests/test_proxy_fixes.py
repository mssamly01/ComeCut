"""Regression tests for PR #9 review follow-ups.

Covers two Devin-Review findings:

* `ensure_proxies` must skip audio-only sources (`.mp3` / `.wav`) so a single
  audio clip doesn't break proxy generation for every other clip.
* `_cache_key` must use full-nanosecond mtime so in-place edits that land
  within the same second aren't silently served the stale proxy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from comecut_py.core.project import Clip, Project, Track
from comecut_py.engine.proxy import _source_has_video, ensure_proxies, proxy_path


# ---- _source_has_video ---------------------------------------------------


def _fake_probe(has_video: bool):
    class _Info:
        pass

    info = _Info()
    info.has_video = has_video
    info.has_audio = True
    return info


def test_source_has_video_true_when_probe_says_so(tmp_path: Path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"fake")
    with patch("comecut_py.core.media_probe.probe", return_value=_fake_probe(True)):
        assert _source_has_video(src) is True


def test_source_has_video_false_when_probe_reports_audio_only(tmp_path: Path):
    src = tmp_path / "a.mp3"
    src.write_bytes(b"fake")
    with patch("comecut_py.core.media_probe.probe", return_value=_fake_probe(False)):
        assert _source_has_video(src) is False


def test_source_has_video_false_when_probe_raises(tmp_path: Path):
    src = tmp_path / "missing.mp4"
    with patch("comecut_py.core.media_probe.probe", side_effect=RuntimeError("boom")):
        assert _source_has_video(src) is False


# ---- ensure_proxies: audio-track handling --------------------------------


def test_ensure_proxies_skips_audio_only_sources(tmp_path: Path):
    """Project with mixed video+audio tracks → audio clip is skipped, video one isn't."""
    vid = tmp_path / "v.mp4"
    aud = tmp_path / "a.mp3"
    vid.write_bytes(b"fake-video")
    aud.write_bytes(b"fake-audio")

    project = Project(
        tracks=[
            Track(kind="video", clips=[Clip(source=str(vid), in_point=0, out_point=1)]),
            Track(kind="audio", clips=[Clip(source=str(aud), in_point=0, out_point=1)]),
        ]
    )

    def _probe(path):
        info = _fake_probe(has_video=str(path).endswith(".mp4"))
        return info

    made: list[str] = []

    def _fake_make_proxy(src, **kwargs):
        made.append(str(src))
        # Return a Path that doesn't need to exist for the test.
        return Path(f"{src}.proxy.mp4")

    with patch("comecut_py.core.media_probe.probe", side_effect=_probe):
        with patch("comecut_py.engine.proxy.make_proxy", side_effect=_fake_make_proxy):
            mapping = ensure_proxies(project)

    # Exactly one proxy was generated — for the video source only.
    assert [src for src, _ in mapping] == [str(vid)]
    assert made == [str(vid)]

    # The video clip gained a proxy path; the audio clip did NOT (it should
    # stay None so the render path keeps using the real audio source).
    video_clip = project.tracks[0].clips[0]
    audio_clip = project.tracks[1].clips[0]
    assert video_clip.proxy is not None
    assert audio_clip.proxy is None


def test_ensure_proxies_caches_no_video_decision_across_clips(tmp_path: Path):
    """If the same audio source appears on two clips we probe it exactly once."""
    aud = tmp_path / "a.mp3"
    aud.write_bytes(b"x")
    project = Project(
        tracks=[
            Track(kind="audio", clips=[Clip(source=str(aud), in_point=0, out_point=1)]),
            Track(kind="audio", clips=[Clip(source=str(aud), in_point=0, out_point=1)]),
        ]
    )
    calls = {"n": 0}

    def _probe(_path):
        calls["n"] += 1
        return _fake_probe(has_video=False)

    with patch("comecut_py.core.media_probe.probe", side_effect=_probe):
        mapping = ensure_proxies(project)

    assert mapping == []
    assert calls["n"] == 1  # deduped — probed only on first encounter
    for tr in project.tracks:
        assert tr.clips[0].proxy is None


# ---- cache key: nanosecond mtime ----------------------------------------


def test_cache_key_changes_when_mtime_changes_within_same_second(
    tmp_path: Path, monkeypatch
):
    """Two writes within the same wall-clock second must yield distinct cache keys."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    src = tmp_path / "v.mp4"
    src.write_bytes(b"\x00" * 16)
    # Force st_mtime_ns to the same whole-second but a different nanosecond.
    os.utime(src, ns=(1_700_000_000_000_000_000, 1_700_000_000_111_111_111))
    key_a = proxy_path(src, width=640)
    os.utime(src, ns=(1_700_000_000_000_000_000, 1_700_000_000_888_888_888))
    key_b = proxy_path(src, width=640)
    # Same whole second (1_700_000_000), different nanosecond → must differ.
    assert key_a != key_b


# ---- real-ffmpeg sanity -------------------------------------------------


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
def test_ensure_proxies_end_to_end_with_mixed_sources(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    vid = tmp_path / "v.mp4"
    aud = tmp_path / "a.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x180:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(vid),
        ],
        check=True, capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "libmp3lame", "-b:a", "96k",
            str(aud),
        ],
        check=True, capture_output=True,
    )

    project = Project(
        tracks=[
            Track(kind="video", clips=[Clip(source=str(vid), in_point=0, out_point=1)]),
            Track(kind="audio", clips=[Clip(source=str(aud), in_point=0, out_point=1)]),
        ]
    )
    mapping = ensure_proxies(project, width=160)
    # Real-ffmpeg: only the video source yielded a proxy; the audio track
    # didn't break anything and still has proxy=None on its clip.
    assert len(mapping) == 1
    assert mapping[0][0] == str(vid)
    assert project.tracks[0].clips[0].proxy is not None
    assert project.tracks[1].clips[0].proxy is None
    assert Path(project.tracks[0].clips[0].proxy).exists()
