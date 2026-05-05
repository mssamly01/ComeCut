"""Runway Gen-3 Alpha text-to-video adapter.

Uses the ``/v1/image_to_video`` and ``/v1/text_to_video`` endpoints
(submit → poll → download). Reads ``RUNWAYML_API_SECRET`` from the
environment.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .base import VideoProvider


class RunwayVideoGen(VideoProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gen3a_turbo",
        base_url: str = "https://api.dev.runwayml.com/v1",
        poll_interval: float = 5.0,
        timeout: float = 1200.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("RUNWAYML_API_SECRET")
        if not self._api_key:
            raise RuntimeError(
                "RUNWAYML_API_SECRET is not set — pass api_key=… or export the env var."
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
                "runway video-gen needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        # Runway rejects fractional seconds; round to the nearest int
        # and clamp to the 5 / 10 presets the Gen-3 API accepts.
        dur_int = round(duration)
        if dur_int not in (5, 10):
            dur_int = 5 if dur_int < 8 else 10

        body: dict[str, object] = {
            "promptText": prompt,
            "duration": dur_int,
            "ratio": aspect_ratio,
            "model": self._model,
        }
        if seed is not None:
            body["seed"] = seed

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Runway-Version": "2024-11-06",
        }
        r = requests.post(
            f"{self._base_url}/text_to_video",
            headers=headers,
            data=json.dumps(body),
            timeout=600,
        )
        r.raise_for_status()
        task_id = r.json().get("id")
        if not task_id:
            raise RuntimeError(f"Runway text_to_video response missing id: {r.json()!r}")

        # Poll for completion.
        start = time.monotonic()
        status: str | None = None
        output_url: str | None = None
        while status not in {"SUCCEEDED", "FAILED", "CANCELED"}:
            if time.monotonic() - start > self._timeout:
                raise TimeoutError(
                    f"Runway task {task_id} did not finish within {self._timeout}s; "
                    f"last status={status}"
                )
            time.sleep(self._poll_interval)
            poll = requests.get(
                f"{self._base_url}/tasks/{task_id}",
                headers=headers,
                timeout=60,
            )
            poll.raise_for_status()
            payload = poll.json()
            status = payload.get("status")
            outs = payload.get("output") or []
            if outs:
                output_url = outs[0]

        if status != "SUCCEEDED" or not output_url:
            raise RuntimeError(
                f"Runway task {task_id} ended with status={status}: "
                f"{payload.get('failure') or payload!r}"
            )

        dst = Path(out_path)
        video = requests.get(output_url, timeout=self._timeout)
        video.raise_for_status()
        dst.write_bytes(video.content)
        return dst


__all__ = ["RunwayVideoGen"]
