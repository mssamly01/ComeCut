"""Kling AI text-to-video adapter.

Uses the public Kling API (``https://api.klingai.com/v1``). Auth is a
JWT signed with the user's secret key — issuer (``iss``) is the access
key, expiry (``exp``) is now+30 minutes. We hand-roll the HS256 JWT
with ``hmac``/``hashlib`` so the package doesn't depend on PyJWT.

Reads ``KLING_ACCESS_KEY`` and ``KLING_SECRET_KEY`` from the
environment. Submission is asynchronous: ``POST /videos/text2video``
returns a ``task_id``, then a poll on
``GET /videos/text2video/{task_id}`` runs until ``task_status`` is
``succeed`` (note: the Kling API uses the bare verb, not ``succeeded``)
or ``failed``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from .base import VideoProvider

# Kling rejects any duration that isn't one of these.
_ALLOWED_DURATIONS: tuple[str, ...] = ("5", "10")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_jwt(access_key: str, secret_key: str, *, ttl: int = 1800) -> str:
    """Build an HS256 JWT compatible with Kling's auth contract.

    ``iss`` = access key, ``exp`` = now + ``ttl``, ``nbf`` = now - 5
    (Kling accepts a few seconds of clock skew).
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "iss": access_key,
        "exp": now + ttl,
        "nbf": now - 5,
    }
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode("ascii")
    sig = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


class KlingVideoGen(VideoProvider):
    def __init__(
        self,
        *,
        access_key: str | None = None,
        secret_key: str | None = None,
        model: str = "kling-v2-6",
        mode: str = "standard",
        base_url: str = "https://api.klingai.com/v1",
        poll_interval: float = 5.0,
        timeout: float = 1200.0,
    ) -> None:
        self._access_key = access_key or os.environ.get("KLING_ACCESS_KEY")
        self._secret_key = secret_key or os.environ.get("KLING_SECRET_KEY")
        if not self._access_key or not self._secret_key:
            raise RuntimeError(
                "KLING_ACCESS_KEY / KLING_SECRET_KEY are not set — "
                "pass access_key=…/secret_key=… or export the env vars."
            )
        self._model = model
        self._mode = mode
        self._base_url = base_url.rstrip("/")
        self._poll_interval = poll_interval
        self._timeout = timeout

    def _auth_headers(self) -> dict[str, str]:
        token = _make_jwt(self._access_key, self._secret_key)  # type: ignore[arg-type]
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

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
                "kling video-gen needs the `requests` package. "
                "Install AI extras: pip install 'comecut-py[ai]'"
            ) from e

        # Kling only accepts the strings "5" or "10".
        dur_int = round(duration)
        dur_str = str(dur_int)
        if dur_str not in _ALLOWED_DURATIONS:
            dur_str = "5" if dur_int < 8 else "10"

        body: dict[str, object] = {
            "model_name": self._model,
            "prompt": prompt,
            "duration": dur_str,
            "aspect_ratio": aspect_ratio,
            "mode": self._mode,
        }
        if seed is not None:
            body["seed"] = seed

        r = requests.post(
            f"{self._base_url}/videos/text2video",
            headers=self._auth_headers(),
            data=json.dumps(body),
            timeout=600,
        )
        r.raise_for_status()
        envelope = r.json()
        task_id = (envelope.get("data") or {}).get("task_id")
        if not task_id:
            raise RuntimeError(
                f"Kling text2video response missing task_id: {envelope!r}"
            )

        start = time.monotonic()
        status: str | None = None
        video_url: str | None = None
        payload: dict = {}
        while status not in {"succeed", "failed"}:
            if time.monotonic() - start > self._timeout:
                raise TimeoutError(
                    f"Kling task {task_id} did not finish within {self._timeout}s; "
                    f"last task_status={status}"
                )
            time.sleep(self._poll_interval)
            poll = requests.get(
                f"{self._base_url}/videos/text2video/{task_id}",
                headers=self._auth_headers(),
                timeout=60,
            )
            poll.raise_for_status()
            payload = poll.json()
            data = payload.get("data") or {}
            status = data.get("task_status")
            videos = (data.get("task_result") or {}).get("videos") or []
            if videos:
                video_url = videos[0].get("url")

        if status != "succeed" or not video_url:
            data = payload.get("data") or {}
            raise RuntimeError(
                f"Kling task {task_id} ended with task_status={status}: "
                f"{data.get('task_status_msg') or payload!r}"
            )

        dst = Path(out_path)
        video = requests.get(video_url, timeout=self._timeout)
        video.raise_for_status()
        dst.write_bytes(video.content)
        return dst


__all__ = ["KlingVideoGen", "_make_jwt"]
