"""Subtitle format auto-detection and cross-format conversion."""

from __future__ import annotations

from pathlib import Path

from .ass import parse_ass, write_ass
from .cue import CueList
from .lrc import parse_lrc, write_lrc
from .srt import parse_srt, write_srt
from .vtt import parse_vtt, write_vtt

_EXT_MAP = {
    ".srt": "srt",
    ".vtt": "vtt",
    ".webvtt": "vtt",
    ".lrc": "lrc",
    ".ass": "ass",
    ".ssa": "ass",
}


def detect_format(path: str | Path, text: str) -> str:
    """Return the subtitle format code (``"srt"`` / ``"vtt"`` / ``"lrc"`` / ``"ass"``)."""
    ext = Path(path).suffix.lower()
    if ext in _EXT_MAP:
        return _EXT_MAP[ext]
    head = text.lstrip()
    if head.startswith("WEBVTT"):
        return "vtt"
    # ASS headers start with ``[Script Info]``; LRC lines start with e.g.
    # ``[00:12.34]``. Disambiguate on the section name.
    if head.startswith("[Script Info]") or head.lower().startswith("[script info]"):
        return "ass"
    if head.startswith("["):
        return "lrc"
    return "srt"


# Backwards-compatible private alias.
_detect_format = detect_format


def convert(src: str | Path, dst: str | Path) -> None:
    """Read a subtitle file at ``src`` and write it in the format implied by ``dst``."""
    src_path = Path(src)
    dst_path = Path(dst)
    src_text = src_path.read_text(encoding="utf-8-sig")
    src_fmt = detect_format(src_path, src_text)
    dst_fmt = _EXT_MAP.get(dst_path.suffix.lower())
    if dst_fmt is None:
        raise ValueError(f"Unknown destination subtitle format: {dst_path.suffix!r}")

    cues: CueList
    if src_fmt == "srt":
        cues = parse_srt(src_text)
    elif src_fmt == "vtt":
        cues = parse_vtt(src_text)
    elif src_fmt == "ass":
        cues = parse_ass(src_text)
    else:
        cues, _ = parse_lrc(src_text)

    if dst_fmt == "srt":
        dst_path.write_text(write_srt(cues), encoding="utf-8")
    elif dst_fmt == "vtt":
        dst_path.write_text(write_vtt(cues), encoding="utf-8")
    elif dst_fmt == "ass":
        dst_path.write_text(write_ass(cues), encoding="utf-8")
    else:
        dst_path.write_text(write_lrc(cues), encoding="utf-8")


__all__ = ["convert", "detect_format"]
