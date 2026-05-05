"""AI provider adapters (ASR, translation, TTS).

All providers are optional: the core package must remain usable with just
FFmpeg. Providers are imported lazily from the CLI. The concrete OpenAI /
faster-whisper adapters are NOT auto-imported here — doing so would force
``requests`` / ``faster-whisper`` as hard dependencies.
"""

from .base import (
    ASRProvider,
    ImageProvider,
    TranslateProvider,
    TTSProvider,
    VideoProvider,
    VoiceCloneProvider,
)

__all__ = [
    "ASRProvider",
    "ImageProvider",
    "TTSProvider",
    "TranslateProvider",
    "VideoProvider",
    "VoiceCloneProvider",
]
