"""Subtitle cue model shared by SRT / VTT / LRC parsers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Cue:
    start: float
    end: float
    text: str
    # ``None`` for LRC-style karaoke cues where end is derived from the next line.
    index: int | None = None

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"start must be non-negative: {self.start}")
        if self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be > start ({self.start})")
        if not isinstance(self.text, str):
            raise TypeError("text must be a str")


@dataclass
class CueList:
    cues: list[Cue] = field(default_factory=list)

    def __iter__(self):
        return iter(self.cues)

    def __len__(self) -> int:
        return len(self.cues)

    def append(self, cue: Cue) -> None:
        self.cues.append(cue)

    def sorted(self) -> CueList:
        return CueList(sorted(self.cues, key=lambda c: (c.start, c.end)))


__all__ = ["Cue", "CueList"]
