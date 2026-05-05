"""Stability AI text-to-image adapter (``stable-image-ultra`` / ``core``).

Uses the ``/v2beta/stable-image/generate/{engine}`` multipart endpoint.
Output format is inferred from the destination file extension; the
default is PNG. Reads ``STABILITY_API_KEY`` from the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import ImageProvider

_ENGINE_PATHS = {
    "ultra": "ultra",
    "core": "core",
    "sd3": "sd3",
}

_EXT_TO_FMT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}


class StabilityImageGen(ImageProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        engine: str = "ultra",
        base_url: str = "https://api.stability.ai",
    ) -> None:
        self._api_key = api_key or os.environ.get("STABILITY_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "STABILITY_API_KEY is not set — pass api_key=… or export the env var."
            )
        if engine not in _ENGINE_PATHS:
            raise ValueError(
                f"Unknown Stability engine {engine!r}. Known: {sorted(_ENGINE_PATHS)}"
            )
        self._engine = engine
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
                "stability image-gen needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        dst = Path(out_path)
        fmt = _EXT_TO_FMT.get(dst.suffix.lower(), "png")
        # Stability's v2beta uses multipart/form-data, not JSON. The
        # `files={"none": ""}` trick forces requests to send the body
        # as multipart even when every field is a simple form value.
        fields: dict[str, str] = {"prompt": prompt, "output_format": fmt}
        if negative_prompt:
            fields["negative_prompt"] = negative_prompt
        if seed is not None:
            fields["seed"] = str(seed)
        if size:
            # Stability uses `aspect_ratio` (e.g. "16:9"), not pixel dims.
            fields["aspect_ratio"] = size
        r = requests.post(
            f"{self._base_url}/v2beta/stable-image/generate/{_ENGINE_PATHS[self._engine]}",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "image/*",
            },
            files={"none": ""},
            data=fields,
            timeout=600,
        )
        r.raise_for_status()
        dst.write_bytes(r.content)
        return dst


__all__ = ["StabilityImageGen"]
