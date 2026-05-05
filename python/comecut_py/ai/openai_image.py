"""OpenAI text-to-image adapter.

Supports the ``gpt-image-1`` and legacy ``dall-e-3`` models via the
``/v1/images/generations`` endpoint. When the API returns a base64
payload we write it directly; when it returns a URL we follow it with
a second GET to fetch the PNG bytes.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from .base import ImageProvider


class OpenAIImageGen(ImageProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-image-1",
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set — pass api_key=… or export the env var."
            )
        self._model = model
        self._base_url = base_url.rstrip("/")

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
            import requests  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "openai image-gen needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        dst = Path(out_path)
        body: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
            "size": size or "1024x1024",
            "n": 1,
        }
        # ``gpt-image-1`` returns b64 by default; ``dall-e-3`` returns a
        # URL by default but also supports ``response_format=b64_json``.
        if self._model == "dall-e-3":
            body["response_format"] = "b64_json"
        r = requests.post(
            f"{self._base_url}/images/generations",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(body),
            timeout=600,
        )
        r.raise_for_status()
        data = r.json()
        item = data["data"][0]
        b64 = item.get("b64_json")
        url = item.get("url")
        if b64:
            dst.write_bytes(base64.b64decode(b64))
        elif url:
            img = requests.get(url, timeout=600)
            img.raise_for_status()
            dst.write_bytes(img.content)
        else:
            raise RuntimeError(
                f"OpenAI image response missing both `b64_json` and `url`: {item!r}"
            )
        return dst


__all__ = ["OpenAIImageGen"]
