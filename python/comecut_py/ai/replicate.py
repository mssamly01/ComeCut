"""Replicate generic adapter (image OR video).

Replicate exposes thousands of community models through a uniform
``/v1/predictions`` submit-and-poll API. This adapter is intentionally
generic — callers pass a ``model`` string (e.g.
``"stability-ai/sdxl"`` or ``"black-forest-labs/flux-schnell"``) and
the input dict is forwarded verbatim.

Reads ``REPLICATE_API_TOKEN`` from the environment.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .base import ImageProvider, VideoProvider


def _submit_and_wait(
    *,
    api_key: str,
    base_url: str,
    model: str,
    inputs: dict,
    poll_interval: float,
    timeout: float,
) -> list[str]:
    """Submit a Replicate prediction and return the list of output URLs."""
    import requests  # type: ignore

    url = f"{base_url}/models/{model}/predictions"
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Prefer": "wait=60",  # Replicate will block up to 60s before falling back to polling.
        },
        data=json.dumps({"input": inputs}),
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    status = payload.get("status")
    get_url = payload.get("urls", {}).get("get")

    # Manual polling for cases where the 60-s hint wasn't enough.
    start = time.monotonic()
    while status not in {"succeeded", "failed", "canceled"}:
        if time.monotonic() - start > timeout:
            raise TimeoutError(
                f"Replicate prediction did not finish within {timeout}s; last status={status}"
            )
        if not get_url:
            raise RuntimeError(
                f"Replicate response missing urls.get: {payload!r}"
            )
        time.sleep(poll_interval)
        poll = requests.get(
            get_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )
        poll.raise_for_status()
        payload = poll.json()
        status = payload.get("status")

    if status != "succeeded":
        raise RuntimeError(
            f"Replicate prediction ended with status={status}: "
            f"{payload.get('error') or payload.get('logs')!r}"
        )
    output = payload.get("output")
    if isinstance(output, str):
        return [output]
    if isinstance(output, list) and all(isinstance(x, str) for x in output):
        return output
    raise RuntimeError(
        f"Replicate prediction succeeded but output shape was unexpected: {output!r}"
    )


def _download(url: str, dst: Path, *, timeout: float = 600) -> Path:
    import requests  # type: ignore

    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    dst.write_bytes(r.content)
    return dst


class ReplicateImageGen(ImageProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "black-forest-labs/flux-schnell",
        base_url: str = "https://api.replicate.com/v1",
        poll_interval: float = 2.0,
        timeout: float = 600.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("REPLICATE_API_TOKEN")
        if not self._api_key:
            raise RuntimeError(
                "REPLICATE_API_TOKEN is not set — pass api_key=… or export the env var."
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
        size: str | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
    ) -> Path:
        try:
            import requests  # type: ignore  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "replicate image-gen needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        inputs: dict[str, object] = {"prompt": prompt}
        if size:
            inputs["aspect_ratio"] = size
        if negative_prompt:
            inputs["negative_prompt"] = negative_prompt
        if seed is not None:
            inputs["seed"] = seed

        urls = _submit_and_wait(
            api_key=self._api_key,
            base_url=self._base_url,
            model=self._model,
            inputs=inputs,
            poll_interval=self._poll_interval,
            timeout=self._timeout,
        )
        return _download(urls[0], Path(out_path), timeout=self._timeout)


class ReplicateVideoGen(VideoProvider):
    """Generic Replicate text-to-video adapter (e.g. ``minimax/video-01``)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "minimax/video-01",
        base_url: str = "https://api.replicate.com/v1",
        poll_interval: float = 5.0,
        timeout: float = 1200.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("REPLICATE_API_TOKEN")
        if not self._api_key:
            raise RuntimeError(
                "REPLICATE_API_TOKEN is not set — pass api_key=… or export the env var."
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
            import requests  # type: ignore  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "replicate video-gen needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        inputs: dict[str, object] = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "duration": duration,
        }
        if seed is not None:
            inputs["seed"] = seed

        urls = _submit_and_wait(
            api_key=self._api_key,
            base_url=self._base_url,
            model=self._model,
            inputs=inputs,
            poll_interval=self._poll_interval,
            timeout=self._timeout,
        )
        return _download(urls[0], Path(out_path), timeout=self._timeout)


__all__ = ["ReplicateImageGen", "ReplicateVideoGen"]
