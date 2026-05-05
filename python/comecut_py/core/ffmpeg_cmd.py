"""Thin, type-safe wrapper around building and running ``ffmpeg`` commands.

We deliberately avoid `ffmpeg-python` as a runtime dependency — shelling out to
the ``ffmpeg`` binary keeps things transparent and matches how users expect
pro-video tooling to work.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
import re


class FFmpegNotFoundError(RuntimeError):
    """Raised when the ``ffmpeg`` (or ``ffprobe``) binary cannot be located."""
    pass


def _local_bin_dir() -> Path:
    # Check for bundled ffmpeg in the python directory
    # Adjust to the absolute path where it was found
    p = Path(r"c:\Users\SAMLY\Desktop\ComeCut1\python\ffmpeg")
    return p if p.exists() else Path(__file__).parents[2] / "ffmpeg"


def ensure_ffmpeg() -> str:
    """Return the absolute path to ``ffmpeg`` or raise :class:`FFmpegNotFoundError`."""
    # 1. Try local dir first
    local = _local_bin_dir() / "ffmpeg.exe"
    if local.exists():
        return str(local.resolve())

    # 2. Try PATH
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FFmpegNotFoundError(
            "ffmpeg was not found. Please ensure it is in 'python/ffmpeg' or on PATH."
        )
    return exe


def ensure_ffprobe() -> str:
    # 1. Try local dir first
    local = _local_bin_dir() / "ffprobe.exe"
    if local.exists():
        return str(local.resolve())

    # 2. Try PATH
    exe = shutil.which("ffprobe")
    if not exe:
        raise FFmpegNotFoundError(
            "ffprobe was not found. It ships with ffmpeg; ensure it is in 'python/ffmpeg' or on PATH."
        )
    return exe


@lru_cache(maxsize=1)
def detect_nvenc_available() -> bool:
    """Return True when ffmpeg can encode with NVIDIA NVENC."""
    try:
        ffmpeg = ensure_ffmpeg()
    except RuntimeError:
        return False
    try:
        encoders = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if "h264_nvenc" not in (encoders.stdout or ""):
        return False
    try:
        probe = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x240:d=0.1",
                "-frames:v",
                "1",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return probe.returncode == 0


@lru_cache(maxsize=1)
def detect_cuda_decode_available() -> bool:
    """Return True when ffmpeg advertises CUDA decode acceleration."""
    try:
        ffmpeg = ensure_ffmpeg()
    except RuntimeError:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-hwaccels"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return "cuda" in (result.stdout or "").lower()


@dataclass
class FFmpegCommand:
    """Fluent builder for ``ffmpeg`` command lines.

    Kept small on purpose — exposes just enough for the engine modules. Callers
    who need deeper control can pass raw flags via :meth:`extra` or subclass.
    """

    global_flags: list[str] = field(default_factory=lambda: ["-hide_banner", "-y"])
    inputs: list[tuple[list[str], str]] = field(default_factory=list)
    filter_complex: str | None = None
    maps: list[str] = field(default_factory=list)
    output_flags: list[str] = field(default_factory=list)
    output: str | None = None

    # ---- building ------------------------------------------------------

    def add_input(self, path: str | Path, *flags: str) -> FFmpegCommand:
        self.inputs.append((list(flags), str(path)))
        return self

    def set_filter_complex(self, expr: str) -> FFmpegCommand:
        self.filter_complex = expr
        return self

    def map(self, *labels: str) -> FFmpegCommand:
        self.maps.extend(labels)
        return self

    def out(self, path: str | Path, *flags: str) -> FFmpegCommand:
        self.output = str(path)
        self.output_flags.extend(flags)
        return self

    def extra(self, *flags: str) -> FFmpegCommand:
        self.output_flags.extend(flags)
        return self

    # ---- rendering -----------------------------------------------------

    def build(self, *, ffmpeg_bin: str | None = None) -> list[str]:
        """Return the full argv list (first element is the binary path)."""
        cmd: list[str] = [ffmpeg_bin or "ffmpeg", *self.global_flags]
        for flags, path in self.inputs:
            cmd.extend(flags)
            cmd.extend(["-i", path])
        if self.filter_complex:
            cmd.extend(["-filter_complex", self.filter_complex])
        for m in self.maps:
            cmd.extend(["-map", m])
        cmd.extend(self.output_flags)
        if self.output is None:
            raise ValueError("FFmpegCommand has no output path; call .out(path) first.")
        cmd.append(self.output)
        return cmd

    def run(
        self,
        *,
        ffmpeg_bin: str | None = None,
        check: bool = True,
        capture: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Execute the command and return the :class:`subprocess.CompletedProcess`.

        Requires an installed ``ffmpeg`` binary — raises
        :class:`FFmpegNotFoundError` if missing.
        """
        binary = ffmpeg_bin or ensure_ffmpeg()
        argv = self.build(ffmpeg_bin=binary)
        result = subprocess.run(
            argv,
            check=check,
            capture_output=capture,
            text=True,
        )
        return result


def shell_quote(arg: str) -> str:
    """Best-effort shell quoting for human-readable command echo only."""
    if not arg or any(c in arg for c in " \t\n\"'$`\\"):
        return "'" + arg.replace("'", "'\\''") + "'"
    return arg


def format_argv(argv: Sequence[str]) -> str:
    """Return a human-readable rendering of ``argv`` (for logs / dry-run)."""
    return " ".join(shell_quote(a) for a in argv)


def flatten(*groups: Iterable[str]) -> list[str]:
    out: list[str] = []
    for g in groups:
        out.extend(g)
    return out


def get_video_duration(path: str | Path) -> float:
    """Return the duration of a media file in seconds using ffprobe."""
    def _parse_duration(raw: str) -> float | None:
        if not raw:
            return None
        for line in raw.splitlines():
            token = line.strip()
            if not token or token.upper() == "N/A":
                continue
            try:
                val = float(token)
            except ValueError:
                m = re.search(r"(\d+(?:\.\d+)?)", token)
                if not m:
                    continue
                try:
                    val = float(m.group(1))
                except ValueError:
                    continue
            if val > 0.0:
                return val
        return None

    try:
        probe = ensure_ffprobe()
        probes = [
            [
                probe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            [
                probe,
                "-v", "error",
                "-show_entries", "stream=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
        ]
        for argv in probes:
            res = subprocess.run(argv, capture_output=True, text=True, check=True)
            parsed = _parse_duration(res.stdout or "")
            if parsed is not None:
                return parsed
    except Exception:
        pass
    return 5.0  # Fallback


__all__ = [
    "FFmpegCommand",
    "FFmpegNotFoundError",
    "detect_cuda_decode_available",
    "detect_nvenc_available",
    "ensure_ffmpeg",
    "ensure_ffprobe",
    "flatten",
    "format_argv",
    "get_video_duration",
    "shell_quote",
]
