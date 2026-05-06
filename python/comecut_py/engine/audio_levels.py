"""Local audio level analysis for meters and clipping warnings."""

from __future__ import annotations

import math
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..core.ffmpeg_cmd import ensure_ffmpeg


S16_FULL_SCALE = 32768.0


@dataclass(frozen=True)
class AudioLevelStats:
    peak: float
    peak_dbfs: float
    rms: float
    rms_dbfs: float
    clipped_samples: int
    total_samples: int

    @property
    def clipped_ratio(self) -> float:
        if self.total_samples <= 0:
            return 0.0
        return self.clipped_samples / self.total_samples

    @property
    def has_clipping(self) -> bool:
        return self.clipped_samples > 0


def amplitude_to_dbfs(amplitude: float) -> float:
    amp = max(0.0, float(amplitude))
    if amp <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(amp)


def parse_pcm_s16le_levels(
    raw: bytes,
    *,
    clipping_threshold: float = 0.999,
) -> AudioLevelStats:
    if not raw:
        return AudioLevelStats(
            peak=0.0,
            peak_dbfs=float("-inf"),
            rms=0.0,
            rms_dbfs=float("-inf"),
            clipped_samples=0,
            total_samples=0,
        )

    sample_count = len(raw) // 2
    if sample_count <= 0:
        return AudioLevelStats(
            peak=0.0,
            peak_dbfs=float("-inf"),
            rms=0.0,
            rms_dbfs=float("-inf"),
            clipped_samples=0,
            total_samples=0,
        )

    usable = raw[: sample_count * 2]
    samples = struct.unpack(f"<{sample_count}h", usable)
    peak = 0.0
    sum_squares = 0.0
    clipped = 0
    threshold = max(0.0, min(1.0, float(clipping_threshold)))

    for sample in samples:
        amp = min(1.0, abs(sample) / S16_FULL_SCALE)
        peak = max(peak, amp)
        sum_squares += amp * amp
        if amp >= threshold:
            clipped += 1

    rms = math.sqrt(sum_squares / sample_count)
    return AudioLevelStats(
        peak=peak,
        peak_dbfs=amplitude_to_dbfs(peak),
        rms=rms,
        rms_dbfs=amplitude_to_dbfs(rms),
        clipped_samples=clipped,
        total_samples=sample_count,
    )


def build_audio_level_command(
    src: str | Path,
    *,
    ffmpeg_bin: str = "ffmpeg",
    start: float | None = None,
    duration: float | None = None,
    sample_rate: int = 48000,
) -> list[str]:
    argv = [ffmpeg_bin, "-v", "error"]
    if start is not None:
        argv += ["-ss", str(max(0.0, float(start)))]
    argv += ["-i", str(src)]
    if duration is not None:
        argv += ["-t", str(max(0.0, float(duration)))]
    argv += [
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(max(8000, int(sample_rate))),
        "-f",
        "s16le",
        "-",
    ]
    return argv


def analyze_audio_levels(
    src: str | Path,
    *,
    start: float | None = None,
    duration: float | None = None,
    sample_rate: int = 48000,
    clipping_threshold: float = 0.999,
    timeout: float = 30.0,
) -> AudioLevelStats | None:
    src_path = Path(src)
    if not src_path.exists():
        return None
    try:
        ffmpeg = ensure_ffmpeg()
    except RuntimeError:
        return None

    argv = build_audio_level_command(
        src_path,
        ffmpeg_bin=ffmpeg,
        start=start,
        duration=duration,
        sample_rate=sample_rate,
    )
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return parse_pcm_s16le_levels(
        proc.stdout,
        clipping_threshold=clipping_threshold,
    )


def audio_clipping_warning(
    stats: AudioLevelStats,
    *,
    near_clip_dbfs: float = -0.1,
) -> str | None:
    if stats.has_clipping:
        return (
            f"Audio clipping detected: {stats.clipped_samples} samples "
            f"at or near full scale."
        )
    if stats.peak_dbfs >= near_clip_dbfs:
        return f"Audio peak is very hot: {stats.peak_dbfs:.2f} dBFS."
    return None


__all__ = [
    "AudioLevelStats",
    "amplitude_to_dbfs",
    "analyze_audio_levels",
    "audio_clipping_warning",
    "build_audio_level_command",
    "parse_pcm_s16le_levels",
]
