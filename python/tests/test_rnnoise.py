"""Tests for the rnnoise (``arnndn``) denoise option.

Covers the new ``denoise_method`` / ``denoise_model`` fields on
:class:`ClipAudioEffects`, the audio-effect chain emitted by
``_audio_effect_chain``, and the CLI plumbing for ``apply-effects``
with ``--denoise-method=rnnoise``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from comecut_py.cli import app
from comecut_py.core.project import (
    Clip,
    ClipAudioEffects,
    Project,
    Track,
)
from comecut_py.engine import render_project
from comecut_py.engine.render import _audio_effect_chain


def test_default_denoise_method_is_afftdn():
    """Existing projects continue to emit ``afftdn`` with no extra config."""
    afx = ClipAudioEffects(denoise=True)
    assert afx.denoise_method == "afftdn"
    assert afx.denoise_model is None
    clip = Clip(source="in.mp4", in_point=0, out_point=5, audio_effects=afx)
    chain = _audio_effect_chain(clip).split(",")
    assert "afftdn" in chain
    assert not any(p.startswith("arnndn") for p in chain)


def test_rnnoise_emits_arnndn_with_model_path():
    afx = ClipAudioEffects(
        denoise=True,
        denoise_method="rnnoise",
        denoise_model="/opt/models/voice.rnnn",
    )
    clip = Clip(source="in.mp4", in_point=0, out_point=5, audio_effects=afx)
    chain = _audio_effect_chain(clip).split(",")
    assert any(p.startswith("arnndn=m=") for p in chain), chain
    assert "afftdn" not in chain
    arnndn_part = next(p for p in chain if p.startswith("arnndn=m="))
    assert "voice.rnnn" in arnndn_part


def test_rnnoise_escapes_colon_in_path_for_filter_complex():
    """ffmpeg filter_complex needs ``:`` in paths escaped (e.g. Windows
    drive letters or URL-style paths)."""
    afx = ClipAudioEffects(
        denoise=True,
        denoise_method="rnnoise",
        denoise_model=r"C:\models\voice.rnnn",
    )
    clip = Clip(source="in.mp4", in_point=0, out_point=5, audio_effects=afx)
    chain = _audio_effect_chain(clip).split(",")
    arnndn_part = next(p for p in chain if p.startswith("arnndn=m="))
    # Colon in 'C:\' must be escaped so libavfilter's parser doesn't treat
    # it as an option separator.
    assert r"C\:" in arnndn_part


def test_rnnoise_without_model_raises_clear_error():
    afx = ClipAudioEffects(
        denoise=True,
        denoise_method="rnnoise",
        denoise_model=None,
    )
    clip = Clip(source="in.mp4", in_point=0, out_point=5, audio_effects=afx)
    with pytest.raises(ValueError, match=r"rnnoise.*denoise_model"):
        _audio_effect_chain(clip)


def test_invalid_denoise_method_rejected_by_pydantic():
    """Pydantic enforces the Literal — typos fail validation early."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ClipAudioEffects(denoise=True, denoise_method="nope")  # type: ignore[arg-type]


def test_denoise_off_ignores_method_and_model():
    """When ``denoise=False`` the method/model fields are inert."""
    afx = ClipAudioEffects(
        denoise=False,
        denoise_method="rnnoise",
        denoise_model=None,
    )
    clip = Clip(source="in.mp4", in_point=0, out_point=5, audio_effects=afx)
    chain = _audio_effect_chain(clip).split(",")
    assert "afftdn" not in chain
    assert not any(p.startswith("arnndn") for p in chain)


def test_rnnoise_runs_before_pitch_and_normalize():
    afx = ClipAudioEffects(
        denoise=True,
        denoise_method="rnnoise",
        denoise_model="/m.rnnn",
        pitch_semitones=2.0,
        normalize=True,
    )
    clip = Clip(source="in.mp4", in_point=0, out_point=5, audio_effects=afx)
    chain = _audio_effect_chain(clip).split(",")
    i_arnndn = next(i for i, p in enumerate(chain) if p.startswith("arnndn"))
    i_rubber = chain.index("rubberband=pitch=" + str(2.0 ** (2.0 / 12.0)))
    i_loud = chain.index("loudnorm")
    assert i_arnndn < i_rubber < i_loud


def test_rnnoise_roundtrip_through_render_project_filter_complex(tmp_path: Path):
    """End-to-end: a project with rnnoise is wired into ffmpeg's
    -filter_complex argv with the model path embedded."""
    p = Project(width=320, height=180)
    p.tracks.append(Track(kind="audio", clips=[
        Clip(
            source="in.mp4", in_point=0, out_point=5,
            audio_effects=ClipAudioEffects(
                denoise=True,
                denoise_method="rnnoise",
                denoise_model="/data/std.rnnn",
            ),
        ),
    ]))
    argv = render_project(p, str(tmp_path / "out.mp4")).build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "arnndn=m=" in fc
    assert "std.rnnn" in fc
    assert "afftdn" not in fc


def test_rnnoise_roundtrip_through_project_json():
    p = Project(width=320, height=180)
    p.tracks.append(Track(kind="audio", clips=[
        Clip(
            source="in.mp4", in_point=0, out_point=5,
            audio_effects=ClipAudioEffects(
                denoise=True,
                denoise_method="rnnoise",
                denoise_model="/m.rnnn",
            ),
        ),
    ]))
    data = p.model_dump_json()
    p2 = Project.model_validate_json(data)
    afx = p2.tracks[0].clips[0].audio_effects
    assert afx.denoise is True
    assert afx.denoise_method == "rnnoise"
    assert afx.denoise_model == "/m.rnnn"


# ---- CLI plumbing -------------------------------------------------------


class _FakeCmd:
    def build(self, *, ffmpeg_bin: str = "ffmpeg") -> list[str]:
        return [ffmpeg_bin, "-y", "-i", "fake", "out.mp4"]

    def run(self, *, ffmpeg_bin: str = "ffmpeg", check: bool = True) -> None:
        return None


def test_cli_apply_effects_rnnoise_flag_routes_to_arnndn(
    tmp_path: Path, monkeypatch,
):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake-mp4")
    model = tmp_path / "model.rnnn"
    model.write_bytes(b"fake-rnnn")
    dst = tmp_path / "out.mp4"

    captured: dict[str, Project] = {}

    def _fake_render(project, out, **kw):
        captured["project"] = project
        return _FakeCmd()

    fake_info = MagicMock(duration=5.0, has_audio=True)
    runner = CliRunner()
    with patch("comecut_py.cli.render_project", side_effect=_fake_render), \
         patch("comecut_py.cli.probe_media", return_value=fake_info):
        r = runner.invoke(app, [
            "apply-effects", str(src), str(dst),
            "--denoise",
            "--denoise-method", "rnnoise",
            "--denoise-model", str(model),
        ])

    assert r.exit_code == 0, r.output
    project = captured["project"]
    audio_track = next(t for t in project.tracks if t.kind == "audio")
    afx = audio_track.clips[0].audio_effects
    assert afx.denoise is True
    assert afx.denoise_method == "rnnoise"
    assert afx.denoise_model == str(model)


def test_cli_apply_effects_rnnoise_without_model_errors(
    tmp_path: Path, monkeypatch,
):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake-mp4")
    dst = tmp_path / "out.mp4"

    fake_info = MagicMock(duration=5.0, has_audio=True)
    runner = CliRunner()
    with patch("comecut_py.cli.render_project", return_value=_FakeCmd()), \
         patch("comecut_py.cli.probe_media", return_value=fake_info):
        r = runner.invoke(app, [
            "apply-effects", str(src), str(dst),
            "--denoise",
            "--denoise-method", "rnnoise",
        ])

    assert r.exit_code == 2
    assert "rnnoise" in r.output and "denoise-model" in r.output


def test_cli_apply_effects_unknown_denoise_method_errors(tmp_path: Path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake-mp4")
    dst = tmp_path / "out.mp4"

    fake_info = MagicMock(duration=5.0, has_audio=True)
    runner = CliRunner()
    with patch("comecut_py.cli.render_project", return_value=_FakeCmd()), \
         patch("comecut_py.cli.probe_media", return_value=fake_info):
        r = runner.invoke(app, [
            "apply-effects", str(src), str(dst),
            "--denoise",
            "--denoise-method", "magicmagic",
        ])

    assert r.exit_code == 2
    assert "magicmagic" in r.output or "denoise-method" in r.output


def test_cli_apply_effects_default_denoise_still_emits_afftdn(tmp_path: Path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake-mp4")
    dst = tmp_path / "out.mp4"

    captured: dict[str, Project] = {}

    def _fake_render(project, out, **kw):
        captured["project"] = project
        return _FakeCmd()

    fake_info = MagicMock(duration=5.0, has_audio=True)
    runner = CliRunner()
    with patch("comecut_py.cli.render_project", side_effect=_fake_render), \
         patch("comecut_py.cli.probe_media", return_value=fake_info):
        r = runner.invoke(app, [
            "apply-effects", str(src), str(dst),
            "--denoise",  # no method specified → default afftdn
        ])
    assert r.exit_code == 0, r.output
    project = captured["project"]
    audio_track = next(t for t in project.tracks if t.kind == "audio")
    afx = audio_track.clips[0].audio_effects
    assert afx.denoise is True
    assert afx.denoise_method == "afftdn"
    assert afx.denoise_model is None
