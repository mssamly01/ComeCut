"""Re-align subtitle timings against an ASR transcription.

Given an existing :class:`CueList` (e.g. a hand-written SRT) and a list
of **word-level** ASR hits — ``(word, start, end)`` tuples produced by
Whisper or another engine — this module recomputes each cue's start
and end so it matches when the corresponding words are actually spoken
in the audio.

The matcher uses stdlib :mod:`difflib.SequenceMatcher`; no third-party
fuzzy-match dependency is required. This keeps the surface simple:
fuzzy misalignments at scene transitions are typically off by a few
hundred milliseconds, which is fine for most lip-sync.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .cue import Cue, CueList


@dataclass(frozen=True)
class ASRWord:
    word: str
    start: float
    end: float


_PUNCT = re.compile(r"[^\w\s'']", flags=re.UNICODE)


def _normalise(word: str) -> str:
    # NFKC + lowercase + strip punctuation, so ``"Hello,"`` matches
    # ``"hello"`` in the ASR output.
    w = unicodedata.normalize("NFKC", word).lower()
    return _PUNCT.sub("", w).strip()


def _tokenise_cue(text: str) -> list[str]:
    return [t for t in (_normalise(w) for w in text.split()) if t]


def realign_cues(
    cues: CueList | list[Cue],
    asr_words: list[ASRWord] | list[tuple[str, float, float]],
    *,
    min_confidence: float = 0.5,
) -> CueList:
    """Return a copy of ``cues`` with timings pulled from ``asr_words``.

    For each cue, find the best-matching contiguous span in the ASR
    word list via :class:`difflib.SequenceMatcher`. If the match ratio
    is below ``min_confidence`` the cue's original timing is kept so
    the result degrades gracefully on e.g. background-music-only
    stretches where ASR produced no hits.
    """
    items = list(cues) if isinstance(cues, CueList) else cues
    words: list[ASRWord] = [
        w if isinstance(w, ASRWord) else ASRWord(*w) for w in asr_words
    ]
    if not words:
        return CueList([
            Cue(start=c.start, end=c.end, text=c.text, index=c.index)
            for c in items
        ])
    asr_tokens = [_normalise(w.word) for w in words]
    # Build a cursor so we don't re-scan the whole ASR list for every
    # cue — subtitles are usually in speaking order.
    cursor = 0

    out: list[Cue] = []
    for c in items:
        cue_tokens = _tokenise_cue(c.text)
        if not cue_tokens:
            out.append(Cue(start=c.start, end=c.end, text=c.text, index=c.index))
            continue
        window = asr_tokens[cursor:]
        sm = SequenceMatcher(a=cue_tokens, b=window, autojunk=False)
        match = sm.find_longest_match(0, len(cue_tokens), 0, len(window))
        if match.size == 0 or match.size / len(cue_tokens) < min_confidence:
            out.append(Cue(start=c.start, end=c.end, text=c.text, index=c.index))
            continue
        j0 = cursor + match.b
        j1 = cursor + match.b + match.size - 1
        out.append(Cue(
            start=words[j0].start,
            end=words[j1].end,
            text=c.text,
            index=c.index,
        ))
        # Advance the cursor past the matched span so the next cue
        # searches forward, not the whole transcript.
        cursor = j1 + 1
    return CueList(out)


__all__ = ["ASRWord", "realign_cues"]
