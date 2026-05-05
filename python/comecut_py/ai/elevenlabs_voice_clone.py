"""ElevenLabs voice cloning adapter.

Uploads one or more reference clips to the ``/v1/voices/add`` endpoint
and returns the ``voice_id`` that the matching
:class:`~comecut_py.ai.elevenlabs_tts.ElevenLabsTTS` adapter can pass
as its ``voice=`` argument.

Reads ``ELEVENLABS_API_KEY`` from the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import VoiceCloneProvider


class ElevenLabsVoiceClone(VoiceCloneProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.elevenlabs.io/v1",
    ) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "ELEVENLABS_API_KEY is not set — pass api_key=… or export the env var."
            )
        self._base_url = base_url.rstrip("/")

    def clone(
        self,
        name: str,
        samples: list[str | Path],
        *,
        description: str | None = None,
    ) -> str:
        try:
            import requests  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "elevenlabs voice-clone needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        if not samples:
            raise ValueError("at least one audio sample is required to clone a voice.")

        sample_paths = [Path(p) for p in samples]
        for p in sample_paths:
            if not p.exists():
                raise FileNotFoundError(f"sample not found: {p}")

        # The API expects a multipart upload with one ``files`` field
        # per sample. Python's ``requests.post(files=…)`` accepts a list
        # of ``(field_name, (filename, fileobj, mime))`` tuples for
        # exactly this case.
        opened: list = []
        files = []
        try:
            for p in sample_paths:
                fh = p.open("rb")
                opened.append(fh)
                files.append(("files", (p.name, fh, "audio/mpeg")))
            data: dict[str, str] = {"name": name}
            if description:
                data["description"] = description
            r = requests.post(
                f"{self._base_url}/voices/add",
                headers={"xi-api-key": self._api_key},
                files=files,
                data=data,
                timeout=600,
            )
        finally:
            for fh in opened:
                fh.close()
        r.raise_for_status()
        body = r.json()
        voice_id = body.get("voice_id")
        if not voice_id:
            raise RuntimeError(
                f"ElevenLabs /voices/add response missing voice_id: {body!r}"
            )
        return voice_id


__all__ = ["ElevenLabsVoiceClone"]
