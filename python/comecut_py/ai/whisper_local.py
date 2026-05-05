"""Local ASR adapter using ``faster-whisper`` (optional dependency).

Installed via ``pip install 'comecut-py[ai]'``. Runs fully offline once the
model weights are downloaded.
"""

from __future__ import annotations

from pathlib import Path

from ..subtitles.cue import Cue, CueList
from ..subtitles.realign import ASRWord
from ..subtitles.srt import dump_srt
from .base import ASRProvider


class FasterWhisperASR(ASRProvider):
    def __init__(self, model_size: str = "small", device: str = "auto", compute_type: str = "auto"):
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as e:  # pragma: no cover - depends on extra install
            raise ImportError(
                "faster-whisper is not installed. Install AI extras: "
                "pip install 'comecut-py[ai]'"
            ) from e
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, media_path: str | Path, *, language: str | None = None) -> CueList:
        segments, _info = self._model.transcribe(str(media_path), language=language, vad_filter=True)
        out: list[Cue] = []
        for i, seg in enumerate(segments, start=1):
            text = (seg.text or "").strip()
            if not text:
                continue
            start = float(seg.start)
            end = float(seg.end)
            if end <= start:
                end = start + 0.1
            out.append(Cue(start=start, end=end, text=text, index=i))
        return CueList(out)

    def transcribe_words(
        self, media_path: str | Path, *, language: str | None = None,
    ) -> list[ASRWord]:
        """Return per-word timestamps from faster-whisper's word-alignment output."""
        segments, _info = self._model.transcribe(
            str(media_path),
            language=language,
            vad_filter=True,
            word_timestamps=True,
        )
        out: list[ASRWord] = []
        for seg in segments:
            for w in (getattr(seg, "words", None) or []):
                word = (w.word or "").strip()
                if not word:
                    continue
                start = float(w.start)
                end = float(w.end)
                if end <= start:
                    end = start + 0.02
                out.append(ASRWord(word=word, start=start, end=end))
        return out


def transcribe_to_srt(
    media_path: str | Path,
    srt_path: str | Path,
    *,
    model_size: str = "small",
    language: str | None = None,
) -> Path:
    """Convenience wrapper: transcribe ``media_path`` and write an SRT to ``srt_path``."""
    asr = FasterWhisperASR(model_size=model_size)
    cues = asr.transcribe(media_path, language=language)
    out = Path(srt_path)
    dump_srt(out, cues)
    return out


__all__ = ["FasterWhisperASR", "transcribe_to_srt"]
