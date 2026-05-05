"""Abstract base classes for AI providers.

The browser app integrates with 100+ external AI services. Rather than hard-code
any single provider, we define a small set of interfaces here so that the rest
of the codebase stays provider-agnostic. Concrete adapters live as siblings
(``whisper_local.py``, ``openai_asr.py`` etc.) and are imported lazily.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..subtitles.cue import CueList


class ASRProvider(ABC):
    """Automatic speech recognition — audio/video → subtitles."""

    @abstractmethod
    def transcribe(
        self,
        media_path: str | Path,
        *,
        language: str | None = None,
    ) -> CueList:
        ...


class TranslateProvider(ABC):
    """Text-to-text translation."""

    @abstractmethod
    def translate(self, text: str, *, target: str, source: str | None = None) -> str:
        ...

    def translate_items(
        self,
        items: list[dict[str, str]],
        *,
        target: str,
        source: str | None = None,
    ) -> list[dict[str, str]]:
        """Translate structured ``[{id, text}, ...]`` items.

        Default implementation falls back to per-item ``translate``.
        """
        out: list[dict[str, str]] = []
        for row in items:
            item_id = str((row or {}).get("id") or "").strip()
            if not item_id:
                continue
            text = str((row or {}).get("text") or "")
            out.append(
                {
                    "id": item_id,
                    "text": self.translate(text, target=target, source=source),
                }
            )
        return out

    def translate_cues(self, cues: CueList, *, target: str, source: str | None = None) -> CueList:
        """Translate every cue in-place; returns a new CueList."""
        from ..subtitles.cue import Cue
        from ..subtitles.cue import CueList as _CueList

        out: list[Cue] = []
        for c in cues:
            out.append(
                Cue(
                    start=c.start,
                    end=c.end,
                    text=self.translate(c.text, target=target, source=source),
                    index=c.index,
                )
            )
        return _CueList(out)


class TTSProvider(ABC):
    """Text-to-speech — text → audio file on disk."""

    @abstractmethod
    def synthesize(self, text: str, out_path: str | Path, *, voice: str | None = None) -> Path:
        ...


class ImageProvider(ABC):
    """Text-to-image generation — prompt → image file on disk."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        out_path: str | Path,
        *,
        size: str | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
    ) -> Path:
        ...


class VideoProvider(ABC):
    """Text-to-video generation — prompt → video file on disk.

    Most providers are **asynchronous** (submit → poll → download);
    implementations should hide the polling so callers see a simple
    blocking ``generate()``.
    """

    @abstractmethod
    def generate(
        self,
        prompt: str,
        out_path: str | Path,
        *,
        duration: float = 5.0,
        aspect_ratio: str = "16:9",
        seed: int | None = None,
    ) -> Path:
        ...


class VoiceCloneProvider(ABC):
    """Voice cloning — uploads one or more sample recordings and
    returns a provider-specific ``voice_id`` string that can be passed
    to a matching :class:`TTSProvider` as the ``voice=`` argument.
    """

    @abstractmethod
    def clone(
        self,
        name: str,
        samples: list[str | Path],
        *,
        description: str | None = None,
    ) -> str:
        ...


__all__ = [
    "ASRProvider",
    "ImageProvider",
    "TTSProvider",
    "TranslateProvider",
    "VideoProvider",
    "VoiceCloneProvider",
]
