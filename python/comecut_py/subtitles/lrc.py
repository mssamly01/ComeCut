"""LRC (lyric) subtitle parser/writer.

LRC cues only have a start time; the ``end`` is derived from the next cue's
start (or a trailing duration that the caller may pass in). Metadata tags like
``[ar:Artist]``, ``[ti:Title]``, ``[al:Album]`` are preserved as a
case-insensitive dict on the returned ``(cues, meta)`` tuple.
"""

from __future__ import annotations

import re
from pathlib import Path

from .cue import Cue, CueList

_TIME_TAG = re.compile(r"\[(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:[.:](?P<f>\d{1,3}))?\]")
_META_TAG = re.compile(r"^\[(?P<k>[a-zA-Z]+):(?P<v>.*)\]$")

_DEFAULT_TAIL = 3.0


def _time_from_tag(m: re.Match) -> float:
    mins = int(m.group("m"))
    secs = int(m.group("s"))
    frac = m.group("f") or "0"
    # LRC fractions are hundredths or thousandths — normalise to ms.
    if len(frac) == 1:
        ms = int(frac) * 100
    elif len(frac) == 2:
        ms = int(frac) * 10
    else:
        ms = int(frac[:3].ljust(3, "0"))
    return mins * 60 + secs + ms / 1000.0


def parse_lrc(
    text: str, *, tail_duration: float = _DEFAULT_TAIL
) -> tuple[CueList, dict[str, str]]:
    """Parse LRC text. Returns ``(cues, metadata)``.

    ``tail_duration`` is used as the duration of the last cue (since LRC has no
    explicit end time).
    """
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    meta: dict[str, str] = {}
    raw: list[tuple[float, str]] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.rstrip()
        if not line:
            continue
        times = list(_TIME_TAG.finditer(line))
        if not times:
            m = _META_TAG.match(line.strip())
            if m and m.group("k").lower() in {"ar", "ti", "al", "by", "offset", "length"}:
                meta[m.group("k").lower()] = m.group("v").strip()
            continue
        # The actual lyric text starts after the last time tag.
        body = line[times[-1].end() :].strip()
        for tm in times:
            raw.append((_time_from_tag(tm), body))
    raw.sort(key=lambda p: p[0])

    cues: list[Cue] = []
    for i, (start, body) in enumerate(raw):
        if i + 1 < len(raw):
            end = raw[i + 1][0]
            if end <= start:
                end = start + tail_duration
        else:
            end = start + tail_duration
        # Skip empty cues — LRC often has placeholder blank lines.
        if body == "":
            continue
        cues.append(Cue(start=start, end=end, text=body))
    return CueList(cues), meta


def _format_lrc_time(t: float) -> str:
    total_ms = round(t * 1000)
    minutes, rem = divmod(total_ms, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"[{minutes:02d}:{secs:02d}.{ms // 10:02d}]"


def write_lrc(cues: CueList | list[Cue], *, metadata: dict[str, str] | None = None) -> str:
    items = list(cues) if isinstance(cues, CueList) else cues
    out: list[str] = []
    if metadata:
        for k, v in metadata.items():
            out.append(f"[{k}:{v}]")
        if out:
            out.append("")
    for c in items:
        out.append(f"{_format_lrc_time(c.start)}{c.text}")
    return "\n".join(out) + "\n"


def load_lrc(path: str | Path) -> tuple[CueList, dict[str, str]]:
    return parse_lrc(Path(path).read_text(encoding="utf-8-sig"))


def dump_lrc(
    path: str | Path, cues: CueList | list[Cue], *, metadata: dict[str, str] | None = None
) -> None:
    Path(path).write_text(write_lrc(cues, metadata=metadata), encoding="utf-8")


__all__ = ["dump_lrc", "load_lrc", "parse_lrc", "write_lrc"]
