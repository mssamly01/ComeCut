"""Luma Dream Machine text-to-video adapter.

Uses the Dream Machine REST API at
``https://api.lumalabs.ai/dream-machine/v1/generations`` with bearer
auth (``LUMAAI_API_KEY``). Generation is asynchronous: ``POST`` returns
an id, then a ``GET`` against the same path is polled until the state
reaches ``completed`` or ``failed``.

Model names follow Luma's conventions (e.g. ``ray-2``, ``ray-flash-2``).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .base import VideoProvider


class LumaVideoGen(VideoProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "ray-2",
        base_url: str = "https://api.lumalabs.ai/dream-machine/v1",
        poll_interval: float = 5.0,
        timeout: float = 1200.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("LUMAAI_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "LUMAAI_API_KEY is not set — pass api_key=… or export the env var."
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
                "luma video-gen needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        body: dict[str, object] = {
            "prompt": prompt,
            "model": self._model,
            "aspect_ratio": aspect_ratio,
            "loop": False,
        }
        # Luma's API rounds to 5/9-second presets internally; pass the
        # user's requested duration as a hint via ``duration`` if the
        # caller asked for something other than the default.
        if duration and duration != 5.0:
            body["duration"] = f"{round(duration)}s"
        if seed is not None:
            body["seed"] = seed

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        r = requests.post(
            f"{self._base_url}/generations",
            headers=headers,
            data=json.dumps(body),
            timeout=600,
        )
        r.raise_for_status()
        gen_id = r.json().get("id")
        if not gen_id:
            raise RuntimeError(f"Luma generations response missing id: {r.json()!r}")

        start = time.monotonic()
        state: str | None = None
        video_url: str | None = None
        payload: dict = {}
        while state not in {"completed", "failed"}:
            if time.monotonic() - start > self._timeout:
                raise TimeoutError(
                    f"Luma generation {gen_id} did not finish within {self._timeout}s; "
                    f"last state={state}"
                )
            time.sleep(self._poll_interval)
            poll = requests.get(
                f"{self._base_url}/generations/{gen_id}",
                headers=headers,
                timeout=60,
            )
            poll.raise_for_status()
            payload = poll.json()
            state = payload.get("state")
            assets = payload.get("assets") or {}
            video_url = assets.get("video")

        if state != "completed" or not video_url:
            raise RuntimeError(
                f"Luma generation {gen_id} ended with state={state}: "
                f"{payload.get('failure_reason') or payload!r}"
            )

        dst = Path(out_path)
        video = requests.get(video_url, timeout=self._timeout)
        video.raise_for_status()
        dst.write_bytes(video.content)
        return dst


__all__ = ["LumaVideoGen"]
