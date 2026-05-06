from __future__ import annotations

import math
import struct

import pytest

from comecut_py.engine.audio_levels import (
    amplitude_to_dbfs,
    analyze_audio_levels,
    audio_clipping_warning,
    build_audio_level_command,
    parse_pcm_s16le_levels,
)


def _pcm(*samples: int) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def test_amplitude_to_dbfs_handles_silence_and_half_scale():
    assert math.isinf(amplitude_to_dbfs(0.0))
    assert amplitude_to_dbfs(1.0) == pytest.approx(0.0)
    assert amplitude_to_dbfs(0.5) == pytest.approx(-6.020599913, abs=1e-6)


def test_parse_pcm_s16le_levels_detects_peak_rms_and_clipping():
    stats = parse_pcm_s16le_levels(_pcm(0, 16384, -32768, 32767))

    assert stats.total_samples == 4
    assert stats.peak == pytest.approx(1.0)
    assert stats.peak_dbfs == pytest.approx(0.0)
    assert stats.rms == pytest.approx(math.sqrt((0.0 + 0.25 + 1.0 + (32767 / 32768) ** 2) / 4))
    assert stats.clipped_samples == 2
    assert stats.has_clipping is True
    assert stats.clipped_ratio == pytest.approx(0.5)


def test_parse_pcm_s16le_levels_handles_empty_audio():
    stats = parse_pcm_s16le_levels(b"")

    assert stats.total_samples == 0
    assert stats.peak == 0.0
    assert math.isinf(stats.peak_dbfs)
    assert audio_clipping_warning(stats) is None


def test_audio_clipping_warning_reports_clip_and_near_clip():
    clipped = parse_pcm_s16le_levels(_pcm(32767))
    hot = parse_pcm_s16le_levels(_pcm(32000), clipping_threshold=1.0)

    assert "clipping detected" in (audio_clipping_warning(clipped) or "").lower()
    assert "very hot" in (audio_clipping_warning(hot, near_clip_dbfs=-0.3) or "")


def test_build_audio_level_command_supports_window():
    argv = build_audio_level_command(
        "in.mp4",
        ffmpeg_bin="ffmpeg",
        start=1.25,
        duration=2.5,
        sample_rate=16000,
    )

    assert argv[:4] == ["ffmpeg", "-v", "error", "-ss"]
    assert "-t" in argv
    assert argv[argv.index("-t") + 1] == "2.5"
    assert argv[argv.index("-ar") + 1] == "16000"
    assert argv[-2:] == ["s16le", "-"]


def test_analyze_audio_levels_returns_none_for_missing_file(tmp_path):
    assert analyze_audio_levels(tmp_path / "missing.wav") is None
