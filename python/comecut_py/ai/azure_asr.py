"""Azure AI Speech ASR adapter (Speech-to-Text REST ``transcriptions`` flavour).

Uses the short-form ``/speechtotext/v3.1/transcriptions:transcribe`` endpoint
(or compatible ``base_url``) which accepts raw audio bytes and returns JSON
with word-level timing. For anything longer than a minute or two you'd
normally want the async batch API — this adapter is aimed at the same
per-clip transcription workflow as the other ASR providers here.

Reads ``AZURE_SPEECH_KEY`` + ``AZURE_SPEECH_REGION`` from the environment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..subtitles.cue import Cue, CueList
from .base import ASRProvider


class AzureSpeechASR(ASRProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        region: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("AZURE_SPEECH_KEY")
        self._region = region or os.environ.get("AZURE_SPEECH_REGION")
        if not self._api_key:
            raise RuntimeError(
                "AZURE_SPEECH_KEY is not set — pass api_key=… or export the env var."
            )
        if base_url:
            self._endpoint = base_url.rstrip("/") + "/speech/recognition/conversation/cognitiveservices/v1"
        else:
            if not self._region:
                raise RuntimeError(
                    "AZURE_SPEECH_REGION is not set — pass region=… or export the env var."
                )
            self._endpoint = (
                f"https://{self._region}.stt.speech.microsoft.com"
                "/speech/recognition/conversation/cognitiveservices/v1"
            )

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
                "azure ASR needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        params = {
            "language": language or "en-US",
            "format": "detailed",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        path = Path(media_path)
        # Azure expects raw audio with a matching Content-Type. The user is
        # responsible for feeding WAV 16kHz mono here — matches the sample
        # approach in the OpenAI adapter too.
        with path.open("rb") as fh:
            r = requests.post(
                f"{self._endpoint}?{query}",
                headers={
                    "Ocp-Apim-Subscription-Key": self._api_key,
                    "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                    "Accept": "application/json",
                },
                data=fh.read(),
                timeout=600,
            )
        r.raise_for_status()
        payload = r.json() if hasattr(r, "json") else json.loads(r.text)
        return _payload_to_cues(payload)


def _payload_to_cues(payload: dict) -> CueList:
    """Azure short-form transcription payload.

    Shape (``format=detailed``):
      {"RecognitionStatus":"Success","DisplayText":"…",
       "NBest":[{"Display":"…","Words":[{"Word":"hi","Offset":0,"Duration":1e7}, …]}]}
    Offsets and durations are in 100-ns ticks.
    """
    best = (payload.get("NBest") or [{}])[0]
    display = (best.get("Display") or payload.get("DisplayText") or "").strip()
    if not display:
        return CueList([])

    words = best.get("Words") or []
    if words:
        # Pack every ~10 consecutive words into a single cue to keep line
        # lengths readable.
        out: list[Cue] = []
        chunk: list[str] = []
        chunk_start = _ticks_to_sec(words[0].get("Offset", 0))
        chunk_end = chunk_start
        for i, w in enumerate(words):
            word_text = (w.get("Word") or "").strip()
            if not word_text:
                continue
            off = _ticks_to_sec(w.get("Offset", 0))
            dur = _ticks_to_sec(w.get("Duration", 0))
            if not chunk:
                chunk_start = off
            chunk.append(word_text)
            chunk_end = off + dur
            if len(chunk) >= 10:
                out.append(
                    Cue(
                        start=chunk_start,
                        end=max(chunk_end, chunk_start + 0.1),
                        text=" ".join(chunk),
                        index=len(out) + 1,
                    )
                )
                chunk = []
        if chunk:
            out.append(
                Cue(
                    start=chunk_start,
                    end=max(chunk_end, chunk_start + 0.1),
                    text=" ".join(chunk),
                    index=len(out) + 1,
                )
            )
        return CueList(out)

    offset = _ticks_to_sec(payload.get("Offset", 0))
    duration = _ticks_to_sec(payload.get("Duration", 0)) or 1.0
    return CueList(
        [Cue(start=offset, end=max(offset + duration, offset + 0.1), text=display, index=1)]
    )


def _ticks_to_sec(ticks: int | float) -> float:
    return float(ticks) / 10_000_000.0


__all__ = ["AzureSpeechASR"]
