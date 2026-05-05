"""Deepgram ASR adapter.

Uses the ``/v1/listen`` pre-recorded transcription endpoint. Reads
``DEEPGRAM_API_KEY`` from the environment. ``requests`` is imported lazily.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..subtitles.cue import Cue, CueList
from .base import ASRProvider


class DeepgramASR(ASRProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "nova-2",
        base_url: str = "https://api.deepgram.com/v1",
    ) -> None:
        self._api_key = api_key or os.environ.get("DEEPGRAM_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "DEEPGRAM_API_KEY is not set — pass api_key=… or export the env var."
            )
        self._model = model
        self._base_url = base_url.rstrip("/")

    def transcribe(
        self,
        media_path: str | Path,
        *,
        language: str | None = None,
    ) -> CueList:
        try:
            import requests  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "deepgram ASR needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        params = {
            "model": self._model,
            "smart_format": "true",
            "punctuate": "true",
            "utterances": "true",
        }
        if language:
            params["language"] = language
        query = "&".join(f"{k}={v}" for k, v in params.items())
        path = Path(media_path)
        with path.open("rb") as fh:
            r = requests.post(
                f"{self._base_url}/listen?{query}",
                headers={
                    "Authorization": f"Token {self._api_key}",
                    "Content-Type": "application/octet-stream",
                },
                data=fh.read(),
                timeout=600,
            )
        r.raise_for_status()
        payload = r.json() if hasattr(r, "json") else json.loads(r.text)
        return _payload_to_cues(payload)


def _payload_to_cues(payload: dict) -> CueList:
    """Deepgram returns a `results.utterances[]` array when utterances=true."""
    results = payload.get("results") or {}
    utterances = results.get("utterances") or []
    out: list[Cue] = []
    for i, u in enumerate(utterances, start=1):
        start = float(u.get("start", 0.0))
        end = float(u.get("end", start + 0.1))
        if end <= start:
            end = start + 0.1
        text = (u.get("transcript") or "").strip()
        if not text:
            continue
        out.append(Cue(start=start, end=end, text=text, index=i))
    # Fall back to the top-level transcript if utterances aren't present.
    if not out:
        channels = results.get("channels") or []
        if channels:
            alt = (channels[0].get("alternatives") or [{}])[0]
            transcript = (alt.get("transcript") or "").strip()
            if transcript:
                words = alt.get("words") or []
                if words:
                    start = float(words[0].get("start", 0.0))
                    end = float(words[-1].get("end", start + 0.1))
                else:
                    start, end = 0.0, 1.0
                if end <= start:
                    end = start + 0.1
                out.append(Cue(start=start, end=end, text=transcript, index=1))
    return CueList(out)


__all__ = ["DeepgramASR"]
