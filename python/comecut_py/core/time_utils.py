"""Timecode parsing/formatting utilities.

Supported input forms for :func:`parse_timecode`:

* seconds as ``int``/``float`` (already numeric)
* ``"SS"`` or ``"SS.mmm"`` (e.g. ``"12"`` or ``"12.345"``)
* ``"MM:SS"`` / ``"MM:SS.mmm"``
* ``"HH:MM:SS"`` / ``"HH:MM:SS.mmm"``
* SRT-style ``"HH:MM:SS,mmm"``

All values are returned as seconds (``float``).
"""

from __future__ import annotations

import re

_TC_RE = re.compile(
    r"""
    ^\s*
    (?:(?P<h>\d+):)?            # optional hours
    (?:(?P<m>\d+):)?            # optional minutes
    (?P<s>\d+(?:[.,]\d+)?)      # seconds with optional fractional part
    \s*$
    """,
    re.VERBOSE,
)


TimeLike = int | float | str


def parse_timecode(value: TimeLike) -> float:
    """Parse a timecode-like value into seconds.

    Raises :class:`ValueError` on unparseable input.
    """
    if isinstance(value, bool):  # bool is subclass of int — reject explicitly
        raise ValueError(f"Invalid timecode: {value!r}")
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError(f"Timecode must be non-negative, got {value}")
        return float(value)
    if not isinstance(value, str):
        raise ValueError(f"Invalid timecode type: {type(value).__name__}")

    parts = value.strip().split(":")
    if not parts or any(p == "" for p in parts) or len(parts) > 3:
        raise ValueError(f"Invalid timecode: {value!r}")

    # Normalise comma decimal separator (SRT style).
    parts = [p.replace(",", ".") for p in parts]

    try:
        nums = [float(p) for p in parts]
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid timecode: {value!r}") from exc

    if any(n < 0 for n in nums):
        raise ValueError(f"Timecode components must be non-negative: {value!r}")

    if len(nums) == 1:
        total = nums[0]
    elif len(nums) == 2:
        total = nums[0] * 60 + nums[1]
    else:
        total = nums[0] * 3600 + nums[1] * 60 + nums[2]
    return total


def format_timecode(seconds: float, *, srt: bool = False, millis: bool = True) -> str:
    """Format a number of seconds as ``HH:MM:SS.mmm`` (or ``HH:MM:SS,mmm`` when ``srt``).

    When ``millis=False`` the fractional part is dropped and the result is ``HH:MM:SS``.
    """
    if seconds < 0:
        raise ValueError(f"Timecode must be non-negative, got {seconds}")
    total_ms = round(seconds * 1000)
    hours, rem = divmod(total_ms, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    secs, ms = divmod(rem, 1000)
    if not millis:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    sep = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"
