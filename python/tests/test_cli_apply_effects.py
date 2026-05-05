"""Regression tests for the `apply-effects` CLI.

Specifically verifies that the command builds a Project with *both* a video
and an audio track so that `--speed` / `--reverse` / volume propagate to the
audio render path (otherwise the output would be silent — see PR #4 review).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from comecut_py.cli import app


class _FakeProbe:
    def __init__(self, *, duration=2.5, has_audio=True):
        self.duration = duration
        self.has_audio = has_audio
        self.width = 1920
        self.height = 1080
        self.fps = 30.0


def _run_apply_effects(args, *, has_audio=True):
    """Invoke `apply-effects` and return the Project that would have been rendered."""
    captured = {}

    class _FakeCmd:
        def build(self, ffmpeg_bin="ffmpeg"):
            return [ffmpeg_bin, "-v", "error"]

        def run(self, check=True):
            return 0

    def fake_render_project(project, dst):
        captured["project"] = project
        captured["dst"] = dst
        return _FakeCmd()

    runner = CliRunner()
    with patch("comecut_py.cli.probe_media", return_value=_FakeProbe(has_audio=has_audio)):
        with patch("comecut_py.cli.render_project", side_effect=fake_render_project):
            result = runner.invoke(app, args)
    return result, captured


def test_apply_effects_includes_audio_track_by_default(tmp_path: Path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    result, captured = _run_apply_effects(
        ["apply-effects", str(src), str(dst), "--speed", "2.0"]
    )
    assert result.exit_code == 0, result.output
    project = captured["project"]
    kinds = sorted(t.kind for t in project.tracks)
    assert kinds == ["audio", "video"], f"expected both tracks, got {kinds}"

    # Both tracks must reference the same source and propagate speed+reverse
    # so the audio render path actually applies the time stretch.
    video_clip = next(t.clips[0] for t in project.tracks if t.kind == "video")
    audio_clip = next(t.clips[0] for t in project.tracks if t.kind == "audio")
    assert video_clip.source == audio_clip.source == str(src)
    assert video_clip.speed == audio_clip.speed == 2.0
    assert video_clip.reverse is False and audio_clip.reverse is False


def test_apply_effects_omits_audio_when_source_has_no_audio(tmp_path: Path):
    src = tmp_path / "silent.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    result, captured = _run_apply_effects(
        ["apply-effects", str(src), str(dst)], has_audio=False
    )
    assert result.exit_code == 0, result.output
    project = captured["project"]
    assert [t.kind for t in project.tracks] == ["video"]


def test_apply_effects_propagates_reverse_to_audio(tmp_path: Path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    result, captured = _run_apply_effects(
        ["apply-effects", str(src), str(dst), "--reverse"]
    )
    assert result.exit_code == 0, result.output
    project = captured["project"]
    audio_clip = next(t.clips[0] for t in project.tracks if t.kind == "audio")
    assert audio_clip.reverse is True


def test_apply_effects_video_effects_not_copied_onto_audio(tmp_path: Path):
    """Colour effects only belong on the video clip; the audio clip stays clean."""
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    _, captured = _run_apply_effects(
        [
            "apply-effects", str(src), str(dst),
            "--brightness", "0.2",
            "--contrast", "1.5",
            "--grayscale",
        ]
    )
    project = captured["project"]
    video_clip = next(t.clips[0] for t in project.tracks if t.kind == "video")
    audio_clip = next(t.clips[0] for t in project.tracks if t.kind == "audio")
    assert video_clip.effects.brightness == 0.2
    assert video_clip.effects.grayscale is True
    # Audio clip uses default (no-op) effects — brightness/grayscale are video-only knobs.
    assert audio_clip.effects.brightness == 0.0
    assert audio_clip.effects.grayscale is False
