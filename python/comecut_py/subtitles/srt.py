"""SRT subtitle parser/writer.

The parser is tolerant of:

* CRLF or LF line endings
* UTF-8 BOMs
* Missing or non-contiguous cue indices
* Comma or dot as the millisecond separator
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.time_utils import format_timecode, parse_timecode
from .cue import Cue, CueList

_TIME_LINE = re.compile(
    r"^\s*(?P<a>\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(?P<b>\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})"
)


def parse_srt(text: str) -> CueList:
    """Parse SRT-formatted ``text`` into a :class:`CueList`."""
    # Strip BOM + normalise line endings.
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    cues: list[Cue] = []
    # Blocks are separated by at least one empty line.
    for block in re.split(r"\n{2,}", text.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        idx: int | None = None
        # The first line may be a numeric index; if not, treat it as a time line.
        m = _TIME_LINE.match(lines[0])
        if m is None:
            # assume first line is the index
            try:
                idx = int(lines[0].strip())
            except ValueError:
                idx = None
            if len(lines) < 2:
                continue
            m = _TIME_LINE.match(lines[1])
            body_lines = lines[2:]
        else:
            body_lines = lines[1:]
        if m is None:
            continue
        start = parse_timecode(m.group("a"))
        end = parse_timecode(m.group("b"))
        text_body = "\n".join(body_lines).strip()
        if end <= start:
            # Skip malformed blocks rather than raising — easier on the GUI.
            continue
        cues.append(Cue(start=start, end=end, text=text_body, index=idx))
    return CueList(cues)


def write_srt(cues: CueList | list[Cue]) -> str:
    """Render ``cues`` as SRT text (trailing newline included)."""
    items = list(cues) if isinstance(cues, CueList) else cues
    out: list[str] = []
    for i, c in enumerate(items, start=1):
        out.append(str(c.index if c.index is not None else i))
        out.append(
            f"{format_timecode(c.start, srt=True)} --> {format_timecode(c.end, srt=True)}"
        )
        out.append(c.text)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def load_srt(path: str | Path) -> CueList:
    return parse_srt(Path(path).read_text(encoding="utf-8-sig"))


def dump_srt(path: str | Path, cues: CueList | list[Cue]) -> None:
    Path(path).write_text(write_srt(cues), encoding="utf-8")


__all__ = ["dump_srt", "load_srt", "parse_srt", "write_srt"]
