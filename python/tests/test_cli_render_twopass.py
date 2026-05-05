"""Regression test for PR #15 review finding: ``render --two-pass`` on a
CRF-only preset without ``--video-bitrate`` must error cleanly instead
of raising a bare ``ValueError`` through to the user.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from comecut_py.cli import app


def _minimal_project(p: Path) -> Path:
    p.write_text(
        '{"width":1920,"height":1080,"fps":30,"tracks":[{"kind":"video",'
        '"clips":[{"source":"/nonexistent.mp4","in_point":0,"out_point":2}]}]}',
        encoding="utf-8",
    )
    return p


def test_two_pass_without_bitrate_errors_cleanly(tmp_path: Path):
    proj = _minimal_project(tmp_path / "proj.json")
    runner = CliRunner()
    # ``youtube-1080p`` is CRF-only by default; ``--two-pass`` needs a
    # video_bitrate grafted on via ``--video-bitrate``.
    result = runner.invoke(
        app, ["render", str(proj), str(tmp_path / "out.mp4"),
              "--preset", "youtube-1080p", "--two-pass", "--dry-run"],
    )
    assert result.exit_code == 2
    assert "video_bitrate" in result.output or "video-bitrate" in result.output


def test_two_pass_without_preset_errors_cleanly(tmp_path: Path):
    proj = _minimal_project(tmp_path / "proj.json")
    runner = CliRunner()
    result = runner.invoke(
        app, ["render", str(proj), str(tmp_path / "out.mp4"),
              "--two-pass", "--dry-run"],
    )
    assert result.exit_code == 2
    assert "--preset" in result.output


def test_two_pass_with_bitrate_override_succeeds(tmp_path: Path):
    proj = _minimal_project(tmp_path / "proj.json")
    runner = CliRunner()
    # Dry-run so we don't actually shell out to ffmpeg.
    result = runner.invoke(
        app, ["render", str(proj), str(tmp_path / "out.mp4"),
              "--preset", "youtube-1080p",
              "--two-pass", "--video-bitrate", "8M",
              "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    # Both passes should be rendered in the dry-run output.
    assert "pass" in result.output.lower() or "-pass" in result.output
