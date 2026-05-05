"""Tests for the bilingual subtitle burn engine operation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from comecut_py.engine import burn_bilingual_subtitles
from comecut_py.engine.overlay_text import _subtitles_filter

SAMPLE_SRT = """1
00:00:00,000 --> 00:00:01,000
hello

2
00:00:01,000 --> 00:00:02,000
world
"""


def test_subtitles_filter_escapes_colon():
    f = _subtitles_filter("C:/foo/bar.srt")
    # Windows-style drive colons must be escaped so ffmpeg doesn't confuse
    # them with the filter-arg separator.
    assert r"C\:/foo/bar.srt" in f
    assert f.startswith("subtitles='")


def test_subtitles_filter_includes_force_style():
    f = _subtitles_filter("a.srt", force_style="Alignment=2,Fontsize=22")
    assert "force_style='Alignment=2,Fontsize=22'" in f


def test_bilingual_filter_chain(tmp_path: Path):
    primary = tmp_path / "en.srt"
    secondary = tmp_path / "vi.srt"
    primary.write_text(SAMPLE_SRT)
    secondary.write_text(SAMPLE_SRT)

    cmd = burn_bilingual_subtitles(
        tmp_path / "in.mp4", primary, secondary, tmp_path / "out.mp4"
    )
    argv = cmd.build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # Both subtitle filters must be present, chained via [vp].
    assert fc.count("subtitles='") == 2
    assert "[vp]" in fc
    assert fc.endswith("[v]")
    # Primary gets alignment=2 (bottom-center), secondary alignment=8 (top-center).
    primary_chunk = fc.split(";")[0]
    secondary_chunk = fc.split(";")[1]
    assert "Alignment=2" in primary_chunk
    assert "Alignment=8" in secondary_chunk


def test_bilingual_custom_styles_override_defaults(tmp_path: Path):
    primary = tmp_path / "a.srt"
    secondary = tmp_path / "b.srt"
    primary.write_text(SAMPLE_SRT)
    secondary.write_text(SAMPLE_SRT)

    cmd = burn_bilingual_subtitles(
        tmp_path / "in.mp4",
        primary,
        secondary,
        tmp_path / "out.mp4",
        primary_style="Fontsize=30",
        secondary_style="Fontsize=14",
    )
    fc = cmd.build(ffmpeg_bin="ffmpeg")[cmd.build(ffmpeg_bin="ffmpeg").index("-filter_complex") + 1]
    assert "Fontsize=30" in fc
    assert "Fontsize=14" in fc
    # Defaults must NOT leak through when the caller overrode them.
    assert "Alignment=2" not in fc
    assert "Alignment=8" not in fc


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_bilingual_burn_runs_end_to_end(tmp_path: Path):
    """Build a real tiny video, burn two subtitle tracks, confirm the MP4 is valid."""
    video = tmp_path / "in.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi",
            "-i", "color=c=gray:s=320x180:d=2:r=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(video),
        ],
        check=True, capture_output=True,
    )

    primary = tmp_path / "en.srt"
    secondary = tmp_path / "vi.srt"
    primary.write_text(SAMPLE_SRT)
    secondary.write_text(SAMPLE_SRT)

    out = tmp_path / "out.mp4"
    cmd = burn_bilingual_subtitles(video, primary, secondary, out)
    cmd.run(check=True)
    assert out.exists() and out.stat().st_size > 0

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(out)],
        check=True, capture_output=True, text=True,
    )
    assert '"duration"' in probe.stdout
