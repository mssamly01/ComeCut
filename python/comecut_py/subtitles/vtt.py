"""WebVTT subtitle parser/writer (minimal subset, no regions/styles)."""

from __future__ import annotations

import re
from pathlib import Path

from ..core.time_utils import format_timecode, parse_timecode
from .cue import Cue, CueList

_TIME_LINE = re.compile(
    r"^\s*(?P<a>\d{1,2}:\d{2}:\d{2}\.\d{1,3}|\d{2}:\d{2}\.\d{1,3})"
    r"\s*-->\s*"
    r"(?P<b>\d{1,2}:\d{2}:\d{2}\.\d{1,3}|\d{2}:\d{2}\.\d{1,3})"
)


def parse_vtt(text: str) -> CueList:
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    # Drop optional "WEBVTT" header line (and its comment on the same line).
    if lines and lines[0].strip().startswith("WEBVTT"):
        # Skip header block up to the first blank line.
        i = 0
        while i < len(lines) and lines[i].strip() != "":
            i += 1
        lines = lines[i + 1 :]
    body = "\n".join(lines).strip()

    cues: list[Cue] = []
    for block in re.split(r"\n{2,}", body):
        raw = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not raw:
            continue
        # Skip NOTE / STYLE / REGION blocks.
        if raw[0].split(" ", 1)[0] in {"NOTE", "STYLE", "REGION"}:
            continue
        m = _TIME_LINE.match(raw[0])
        body_lines: list[str]
        if m is None and len(raw) >= 2:
            m = _TIME_LINE.match(raw[1])
            body_lines = raw[2:]
        else:
            body_lines = raw[1:]
        if m is None:
            continue
        start = parse_timecode(m.group("a"))
        end = parse_timecode(m.group("b"))
        if end <= start:
            continue
        cues.append(Cue(start=start, end=end, text="\n".join(body_lines).strip()))
    return CueList(cues)


def write_vtt(cues: CueList | list[Cue]) -> str:
    items = list(cues) if isinstance(cues, CueList) else cues
    out: list[str] = ["WEBVTT", ""]
    for c in items:
        out.append(
            f"{format_timecode(c.start, srt=False)} --> {format_timecode(c.end, srt=False)}"
        )
        out.append(c.text)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def load_vtt(path: str | Path) -> CueList:
    return parse_vtt(Path(path).read_text(encoding="utf-8-sig"))


def dump_vtt(path: str | Path, cues: CueList | list[Cue]) -> None:
    Path(path).write_text(write_vtt(cues), encoding="utf-8")


__all__ = ["dump_vtt", "load_vtt", "parse_vtt", "write_vtt"]
