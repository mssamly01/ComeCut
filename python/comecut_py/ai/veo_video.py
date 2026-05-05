"""Google Veo (Gemini API) text-to-video adapter.

Uses the Gemini API's ``predictLongRunning`` endpoint:

  POST https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning?key=$KEY

Returns ``{"name": "operations/..."}``; we then poll
``GET https://generativelanguage.googleapis.com/v1beta/{name}?key=$KEY``
until ``done: true``. The completed payload contains a video URI which
we fetch (with the API key appended as a query parameter, per the
Gemini File API contract) and write to disk.

Reads ``GEMINI_API_KEY`` (Google's official env var name for Gemini).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .base import VideoProvider


def _extract_video_uri(payload: dict) -> str | None:
    """Pull the generated video URI out of a Veo operation payload.

    The exact shape has shifted across previews so we scan a few known
    locations rather than hard-coding one.
    """
    response = payload.get("response") or {}
    # Recent shape: response.generateVideoResponse.generatedSamples[0].video.uri
    gv = response.get("generateVideoResponse") or {}
    samples = gv.get("generatedSamples") or []
    if samples:
        video = (samples[0] or {}).get("video") or {}
        uri = video.get("uri") or video.get("url")
        if uri:
            return uri
    # Vertex-style shape: response.predictions[0].videoUri
    preds = response.get("predictions") or []
    if preds:
        uri = preds[0].get("videoUri") or preds[0].get("uri")
        if uri:
            return uri
    # google-genai Python SDK shape: response.generated_videos[0].video.uri
    gens = response.get("generated_videos") or []
    if gens:
        video = (gens[0] or {}).get("video") or {}
        uri = video.get("uri") or video.get("url")
        if uri:
            return uri
    return None


class VeoVideoGen(VideoProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "veo-3.1-generate-preview",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        poll_interval: float = 10.0,
        timeout: float = 1800.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set — pass api_key=… or export the env var."
            )
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._poll_interval = poll_interval
        self._timeout = timeout

    def generate(
        self,
        prompt: str,
        out_path: str | Path,
        *,
        duration: float = 5.0,
        aspect_ratio: str = "16:9",
        seed: int | None = None,
    ) -> Path:
        try:
            import requests  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "veo video-gen needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        params = {"key": self._api_key}
        body: dict[str, object] = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "aspectRatio": aspect_ratio,
                "durationSeconds": round(duration),
            },
        }
        if seed is not None:
            body["parameters"]["seed"] = seed  # type: ignore[index]

        r = requests.post(
            f"{self._base_url}/models/{self._model}:predictLongRunning",
            params=params,
            data=json.dumps(body),
            headers={"Content-Type": "application/json"},
            timeout=600,
        )
        r.raise_for_status()
        op_name = r.json().get("name")
        if not op_name:
            raise RuntimeError(f"Veo predictLongRunning response missing name: {r.json()!r}")

        start = time.monotonic()
        done = False
        payload: dict = {}
        while not done:
            if time.monotonic() - start > self._timeout:
                raise TimeoutError(
                    f"Veo operation {op_name} did not finish within {self._timeout}s."
                )
            time.sleep(self._poll_interval)
            poll = requests.get(
                f"{self._base_url}/{op_name}",
                params=params,
                timeout=60,
            )
            poll.raise_for_status()
            payload = poll.json()
            done = bool(payload.get("done"))

        if "error" in payload:
            raise RuntimeError(f"Veo operation {op_name} failed: {payload['error']!r}")

        video_uri = _extract_video_uri(payload)
        if not video_uri:
            raise RuntimeError(
                f"Veo operation {op_name} completed but produced no video URI: {payload!r}"
            )

        # Gemini File API URIs require the same API key on the GET.
        dst = Path(out_path)
        video = requests.get(video_uri, params=params, timeout=self._timeout)
        video.raise_for_status()
        dst.write_bytes(video.content)
        return dst


__all__ = ["VeoVideoGen"]
