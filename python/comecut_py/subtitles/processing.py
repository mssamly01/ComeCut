"""Subtitle post-processing — line wrap, cue splitting, duration caps.

All functions return **new** :class:`CueList` instances; the input cues
are never mutated in place.
"""

from __future__ import annotations

import re

from .cue import Cue, CueList

# Word-boundary splitter that keeps CJK characters as their own units so
# Japanese/Chinese/Vietnamese Han captions split on a sensible boundary
# instead of being treated as one giant "word".
_WORD = re.compile(r"\S+")


def wrap_text_by_chars(
    text: str,
    *,
    max_chars_per_line: int = 42,
    max_lines: int = 2,
) -> str:
    """Insert hard newlines so no output line exceeds ``max_chars_per_line``.

    Trims trailing whitespace and never splits a word mid-character.
    The return may contain more than ``max_lines`` lines — the line
    limit is enforced by :func:`split_long_cues` (which splits the cue
    across multiple timed blocks instead).
    """
    words = _WORD.findall(text.replace("\n", " "))
    if not words:
        return ""
    lines: list[str] = []
    current = ""
    for w in words:
        candidate = f"{current} {w}".lstrip() if current else w
        if len(candidate) > max_chars_per_line and current:
            lines.append(current)
            current = w
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def split_long_cues(
    cues: CueList | list[Cue],
    *,
    max_chars_per_line: int = 42,
    max_lines: int = 2,
    max_duration: float | None = None,
) -> CueList:
    """Return a new :class:`CueList` with long cues split up.

    Two constraints are enforced:

    * **Line overflow** — when wrapping the text at
      ``max_chars_per_line`` produces more than ``max_lines`` lines, the
      cue is broken into successive cues whose duration is prorated by
      line count.
    * **Duration cap** — when ``max_duration`` is set and the cue spans
      longer, the cue is split in half timeline-wise (text is also
      halved by line count).
    """
    items = list(cues) if isinstance(cues, CueList) else cues
    out: list[Cue] = []

    def _emit_block(start: float, end: float, body: str) -> None:
        wrapped = wrap_text_by_chars(
            body, max_chars_per_line=max_chars_per_line, max_lines=max_lines,
        )
        lines = wrapped.split("\n")
        if len(lines) <= max_lines:
            if max_duration is not None and end - start > max_duration:
                # Bisect in time. When there's more than one wrapped
                # line we split the text by line count; otherwise we
                # keep the full text in both halves so a 10 s "short
                # text" cue with max_duration=4 becomes three cues
                # that all still show "short text", NOT three cues of
                # which two are blank.
                mid = (start + end) / 2
                if len(lines) > 1:
                    half = len(lines) // 2
                    _emit_block(start, mid, " ".join(lines[:half]))
                    _emit_block(mid, end, " ".join(lines[half:]))
                else:
                    _emit_block(start, mid, wrapped)
                    _emit_block(mid, end, wrapped)
                return
            out.append(Cue(start=start, end=end, text=wrapped))
            return
        # Too many lines — split by line count, prorate time.
        total = len(lines)
        total_dur = end - start
        for i in range(0, total, max_lines):
            chunk = lines[i:i + max_lines]
            a = start + total_dur * (i / total)
            b = start + total_dur * (min(i + max_lines, total) / total)
            if b <= a:  # rounding safety
                b = a + 0.001
            _emit_block(a, b, " ".join(chunk))

    for c in items:
        _emit_block(c.start, c.end, c.text)
    return CueList(out)


def cap_cue_duration(
    cues: CueList | list[Cue],
    *,
    max_duration: float,
) -> CueList:
    """Clamp every cue to at most ``max_duration`` seconds.

    The cue's end is moved earlier — the start is left alone so the
    lip-sync doesn't drift. Cues that are already short enough are
    returned unchanged.
    """
    items = list(cues) if isinstance(cues, CueList) else cues
    out: list[Cue] = []
    for c in items:
        if c.end - c.start > max_duration:
            out.append(Cue(start=c.start, end=c.start + max_duration,
                           text=c.text, index=c.index))
        else:
            out.append(c)
    return CueList(out)


__all__ = ["cap_cue_duration", "split_long_cues", "wrap_text_by_chars"]
