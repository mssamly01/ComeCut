"""OpenAI text-to-speech adapter.

Writes audio bytes streamed from the ``/v1/audio/speech`` endpoint directly to
the requested ``out_path``. Supports the ``mp3``/``wav``/``opus``/``aac``/
``flac``/``pcm`` formats that the OpenAI API exposes, inferred from the
output file extension.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .base import TTSProvider

_EXT_TO_FMT = {
    ".mp3": "mp3",
    ".wav": "wav",
    ".opus": "opus",
    ".aac": "aac",
    ".flac": "flac",
    ".pcm": "pcm",
}


class OpenAITTS(TTSProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "tts-1",
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set — pass api_key=… or export the env var."
            )
        self._model = model
        self._base_url = base_url.rstrip("/")

    def synthesize(self, text: str, out_path: str | Path, *, voice: str | None = None) -> Path:
        try:
            import requests  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "openai TTS needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        dst = Path(out_path)
        fmt = _EXT_TO_FMT.get(dst.suffix.lower(), "mp3")
        body = {
            "model": self._model,
            "input": text,
            "voice": voice or "alloy",
            "response_format": fmt,
        }
        r = requests.post(
            f"{self._base_url}/audio/speech",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
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


__all__ = ["OpenAITTS"]
