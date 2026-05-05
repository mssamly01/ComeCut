"""ElevenLabs text-to-speech adapter.

Uses the ``/v1/text-to-speech/{voice_id}`` endpoint. Reads
``ELEVENLABS_API_KEY`` from the environment. ``requests`` is imported lazily.

The default voice (``21m00Tcm4TlvDq8ikWAM``) is "Rachel" from the ElevenLabs
voice library. Output format follows the ``out_path`` extension — mp3 is the
recommended default.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .base import TTSProvider

_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (available on free tier)

_EXT_TO_FMT = {
    ".mp3": "mp3_44100_128",
    ".wav": "pcm_24000",
    ".pcm": "pcm_24000",
    ".ulaw": "ulaw_8000",
    ".ogg": "opus_48000_128",
}


class ElevenLabsTTS(TTSProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "eleven_multilingual_v2",
        base_url: str = "https://api.elevenlabs.io/v1",
    ) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "ELEVENLABS_API_KEY is not set — pass api_key=… or export the env var."
            )
        self._model = model
        self._base_url = base_url.rstrip("/")

    def synthesize(self, text: str, out_path: str | Path, *, voice: str | None = None) -> Path:
        try:
            import requests  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "elevenlabs TTS needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        dst = Path(out_path)
        fmt = _EXT_TO_FMT.get(dst.suffix.lower(), "mp3_44100_128")
        voice_id = voice or _DEFAULT_VOICE_ID
        body = {
            "text": text,
            "model_id": self._model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        r = requests.post(
            f"{self._base_url}/text-to-speech/{voice_id}?output_format={fmt}",
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg" if fmt.startswith("mp3") else "*/*",
            },
            data=json.dumps(body),
            timeout=600,
        )
        r.raise_for_status()
        content = r.content if hasattr(r, "content") else b""
        if not content and hasattr(r, "text"):
            content = r.text.encode("utf-8")
        dst.write_bytes(content)
        return dst


__all__ = ["ElevenLabsTTS"]
