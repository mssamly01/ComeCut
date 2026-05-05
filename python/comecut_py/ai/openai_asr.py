"""OpenAI Whisper API adapter for speech-to-text.

Reads the API key from the ``OPENAI_API_KEY`` environment variable (or an
explicit ``api_key=`` argument). Never commit or log the key.

Note: the OpenAI transcription endpoint returns flat text or verbose JSON with
segment-level timings — we ask for the verbose JSON format so we can produce
proper SRT cues.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..subtitles.cue import Cue, CueList
from .base import ASRProvider


class OpenAIASR(ASRProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "whisper-1",
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set — pass api_key=… or export the env var."
            )
        self._model = model
        self._base_url = base_url.rstrip("/")

    def transcribe(
        self,
        media_path: str | Path,
        *,
        language: str | None = None,
    ) -> CueList:
        # Lazy-import so the ``requests`` (or ``httpx``) dependency isn't forced on
        # users who only want the local whisper adapter.
        try:
            import requests  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "openai ASR needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        url = f"{self._base_url}/audio/transcriptions"
        path = Path(media_path)
        with path.open("rb") as fh:
            files = {"file": (path.name, fh, "application/octet-stream")}
            data = {
                "model": self._model,
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            }
            if language:
                data["language"] = language
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                files=files,
                data=data,
                timeout=600,
            )
        r.raise_for_status()
        payload = r.json() if hasattr(r, "json") else json.loads(r.text)
        return _payload_to_cues(payload)


def _payload_to_cues(payload: dict) -> CueList:
    segments = payload.get("segments") or []
    out: list[Cue] = []
    for i, seg in enumerate(segments, start=1):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 0.1))
        if end <= start:
            end = start + 0.1
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        out.append(Cue(start=start, end=end, text=text, index=i))
    # Fall back to one big cue if the API returned no segments (e.g., plain text mode).
    if not out and payload.get("text"):
        duration = float(payload.get("duration", 0.0)) or 1.0
        out.append(Cue(start=0.0, end=duration, text=str(payload["text"]).strip(), index=1))
    return CueList(out)


__all__ = ["OpenAIASR"]
