"""Tests for the typed styling flags on `burn-subs`.

The CLI builds a :class:`SubtitleStyle` from individual flags
(`--font-name`, `--color`, `--alignment`, ...) and threads it through
:func:`burn_subtitles` as the libass ``force_style`` string. Any raw
``--force-style`` argument is appended after the typed style so it
overrides on conflict (libass keeps the last value).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from comecut_py.cli import app


def _make_subs(tmp_path: Path) -> Path:
    subs = tmp_path / "subs.srt"
    subs.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8",
    )
    return subs


def _capture_burn(args):
    """Invoke the CLI and return the FFmpegCommand that would run."""
    captured = {}

    def fake_burn(src, subs, dst, *, force_style=None):
        captured["force_style"] = force_style

        class _Cmd:
            filter_complex = None

            def build(self, ffmpeg_bin="ffmpeg"):
                return [ffmpeg_bin]

            def run(self, check=True):
                return 0

        return _Cmd()

    runner = CliRunner()
    with patch("comecut_py.cli.burn_subtitles", side_effect=fake_burn):
        result = runner.invoke(app, args)
    return result, captured


def test_burn_subs_typed_style_renders_libass_string(tmp_path: Path):
    subs = _make_subs(tmp_path)
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    result, captured = _capture_burn([
        "burn-subs", str(src), str(subs), str(dst),
        "--font-name", "Arial",
        "--font-size", "32",
        "--color", "#FFFF00",
        "--outline-color", "#000000",
        "--bold",
        "--italic",
        "--outline", "1.5",
        "--shadow", "0",
        "--border-style", "1",
        "--alignment", "bottom-center",
        "--margin-l", "20", "--margin-r", "20", "--margin-v", "40",
    ])
    assert result.exit_code == 0, result.output
    fs = captured["force_style"] or ""
    for needle in [
        "FontName=Arial",
        "Fontsize=32",
        "PrimaryColour=&H0000FFFF",  # CSS #FFFF00 → libass &H0000FFFF
        "OutlineColour=&H00000000",
        "Bold=1",
        "Italic=1",
        "Outline=1.5",
        "Shadow=0",
        "BorderStyle=1",
        "Alignment=2",
        "MarginL=20",
        "MarginR=20",
        "MarginV=40",
    ]:
        assert needle in fs, f"missing {needle} in {fs}"


def test_burn_subs_alignment_accepts_numpad_int(tmp_path: Path):
    subs = _make_subs(tmp_path)
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    result, captured = _capture_burn([
        "burn-subs", str(src), str(subs), str(dst),
        "--alignment", "8",
    ])
    assert result.exit_code == 0, result.output
    assert "Alignment=8" in (captured["force_style"] or "")


def test_burn_subs_force_style_overrides_typed_flags(tmp_path: Path):
    subs = _make_subs(tmp_path)
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    result, captured = _capture_burn([
        "burn-subs", str(src), str(subs), str(dst),
        "--font-size", "20",
        "--force-style", "Fontsize=48",
    ])
    assert result.exit_code == 0, result.output
    fs = captured["force_style"] or ""
    # The raw --force-style is appended after the typed flags so it wins
    # in libass (last value for the same key).
    assert fs.endswith("Fontsize=48")
    assert fs.index("Fontsize=20") < fs.index("Fontsize=48")


def test_burn_subs_no_flags_passes_none_force_style(tmp_path: Path):
    subs = _make_subs(tmp_path)
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    result, captured = _capture_burn([
        "burn-subs", str(src), str(subs), str(dst),
    ])
    assert result.exit_code == 0, result.output
    assert captured["force_style"] is None


def test_burn_subs_only_force_style_passes_through(tmp_path: Path):
    subs = _make_subs(tmp_path)
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    result, captured = _capture_burn([
        "burn-subs", str(src), str(subs), str(dst),
        "--force-style", "Fontsize=24",
    ])
    assert result.exit_code == 0, result.output
    assert captured["force_style"] == "Fontsize=24"


def test_burn_subs_rejects_invalid_border_style(tmp_path: Path):
    subs = _make_subs(tmp_path)
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    result, _ = _capture_burn([
        "burn-subs", str(src), str(subs), str(dst),
        "--border-style", "2",
    ])
    assert result.exit_code != 0
    assert "border-style" in result.output


def test_burn_subs_rejects_invalid_alignment_int(tmp_path: Path):
    subs = _make_subs(tmp_path)
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    dst = tmp_path / "out.mp4"

    result, _ = _capture_burn([
        "burn-subs", str(src), str(subs), str(dst),
        "--alignment", "12",
    ])
    assert result.exit_code != 0
