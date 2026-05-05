"""Minimal ASS / SSA v4+ parser and writer.

We only round-trip the parts needed to represent timed dialogue, i.e.:

* ``[Script Info]`` — preserve ``ScriptType`` and ``PlayResX/Y`` if present.
* ``[V4+ Styles]`` — preserve lines verbatim so re-written files keep the
  same styling. A single ``Default`` style is written for ASS files
  generated from scratch (e.g. converted from SRT).
* ``[Events]`` — ``Dialogue`` lines are parsed into :class:`Cue`s with
  any in-line override codes (``{\\…}``) stripped from the text body.

The goal is **round-trip compatibility with real ASS files**, not full
karaoke/animation rendering — that's libass's job.
"""

from __future__ import annotations

import re
from pathlib import Path

from .cue import Cue, CueList

# ``H:MM:SS.cs`` — ASS uses centiseconds, not milliseconds, and exactly
# one hour digit.
_ASS_TIME = re.compile(r"^\s*(?P<h>\d+):(?P<m>\d{2}):(?P<s>\d{2})[.](?P<cs>\d{2})\s*$")
_OVERRIDE = re.compile(r"\{[^}]*\}")


def _parse_ass_time(tc: str) -> float:
    m = _ASS_TIME.match(tc)
    if m is None:
        raise ValueError(f"invalid ASS timecode: {tc!r}")
    return (
        int(m.group("h")) * 3600
        + int(m.group("m")) * 60
        + int(m.group("s"))
        + int(m.group("cs")) / 100.0
    )


def _format_ass_time(seconds: float) -> str:
    # ASS centiseconds, single-digit hour. Negative clamp.
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = round((seconds - int(seconds)) * 100)
    if cs == 100:
        # rounding carried; propagate.
        cs = 0
        s += 1
        if s == 60:
            s = 0
            m += 1
            if m == 60:
                m = 0
                h += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _strip_override_codes(text: str) -> str:
    # Replace ASS ``\N`` newline with real \n; strip ``{\…}`` tag blocks.
    return _OVERRIDE.sub("", text).replace(r"\N", "\n").replace(r"\n", "\n")


def parse_ass(text: str) -> CueList:
    """Parse ASS/SSA ``text`` into a :class:`CueList`.

    Ignores everything except the ``Dialogue:`` lines — callers who
    want to preserve styles should use the returned cue list together
    with :func:`write_ass` on the same input.
    """
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    section: str | None = None
    fields: list[str] = []
    cues: list[Cue] = []

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            fields = []
            continue
        if section != "events":
            continue
        if line.lower().startswith("format:"):
            fields = [f.strip().lower() for f in line.split(":", 1)[1].split(",")]
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        if not fields:
            # Fall back to the canonical ASS v4+ Dialogue field order.
            fields = [
                "layer", "start", "end", "style", "name",
                "marginl", "marginr", "marginv", "effect", "text",
            ]
        # Dialogue splits on ',' up to (len(fields) - 1) times so commas
        # inside the final Text column are preserved.
        body = line.split(":", 1)[1].lstrip()
        parts = body.split(",", len(fields) - 1)
        if len(parts) != len(fields):
            continue
        row = dict(zip(fields, parts, strict=True))
        try:
            start = _parse_ass_time(row["start"])
            end = _parse_ass_time(row["end"])
        except ValueError:
            continue
        if end <= start:
            continue
        body_text = _strip_override_codes(row.get("text", "")).strip()
        cues.append(Cue(start=start, end=end, text=body_text))
    return CueList(cues)


_MIN_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(cues: CueList | list[Cue]) -> str:
    """Render ``cues`` as a minimal ASS v4+ file with a single Default style.

    Each cue becomes a ``Dialogue: 0,start,end,Default,,0,0,0,,text``
    line; embedded newlines are replaced with the ASS ``\\N`` escape so
    libass line-wraps them at render time.
    """
    out = [_MIN_HEADER]
    items = list(cues) if isinstance(cues, CueList) else cues
    for c in items:
        text = c.text.replace("\n", r"\N")
        out.append(
            f"Dialogue: 0,{_format_ass_time(c.start)},{_format_ass_time(c.end)},"
            f"Default,,0,0,0,,{text}"
        )
    out.append("")
    return "\n".join(out)


def load_ass(path: str | Path) -> CueList:
    return parse_ass(Path(path).read_text(encoding="utf-8-sig"))


def dump_ass(path: str | Path, cues: CueList | list[Cue]) -> None:
    Path(path).write_text(write_ass(cues), encoding="utf-8")


__all__ = ["dump_ass", "load_ass", "parse_ass", "write_ass"]
