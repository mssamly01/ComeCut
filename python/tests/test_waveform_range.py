from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from comecut_py.engine import waveform


def test_extract_waveform_peaks_range_uses_ss_t_and_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    src = tmp_path / "voice.mp3"
    src.write_bytes(b"media")

    calls: list[list[str]] = []

    def fake_ensure_ffmpeg() -> str:
        return "ffmpeg"

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        # Four s16le samples: 0, 32767, -32768, 16384.
        return SimpleNamespace(
            returncode=0,
            stdout=b"\x00\x00\xff\x7f\x00\x80\x00\x40",
        )

    monkeypatch.setattr(waveform, "ensure_ffmpeg", fake_ensure_ffmpeg)
    monkeypatch.setattr(waveform.subprocess, "run", fake_run)

    first = waveform.extract_waveform_peaks_range(
        src,
        start=12.5,
        duration=3.25,
        num_peaks=8,
    )
    second = waveform.extract_waveform_peaks_range(
        src,
        start=12.5,
        duration=3.25,
        num_peaks=8,
    )

    assert first == second
    assert len(calls) == 1
    argv = calls[0]
    assert argv[argv.index("-ss") + 1] == "12.500000"
    assert argv[argv.index("-t") + 1] == "3.250000"


def test_extract_waveform_peaks_range_invalidates_when_source_mtime_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    src = tmp_path / "voice.mp3"
    src.write_bytes(b"media")

    calls = 0

    def fake_run(argv, **kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=0, stdout=b"\x00\x00\xff\x7f")

    monkeypatch.setattr(waveform, "ensure_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(waveform.subprocess, "run", fake_run)

    assert waveform.extract_waveform_peaks_range(src, start=0, duration=1) is not None
    src.write_bytes(b"media changed")
    assert waveform.extract_waveform_peaks_range(src, start=0, duration=1) is not None

    assert calls == 2
