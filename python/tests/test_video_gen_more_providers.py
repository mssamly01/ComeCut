"""Tests for the Luma / Kling / Veo video-gen adapters.

All network I/O is stubbed via ``unittest.mock.patch`` on the
provider module's ``requests`` binding — no test ever actually hits
a third-party API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class _FakeResponse:
    def __init__(self, *, json_body=None, content=b"", status=200):
        self._json = json_body
        self.content = content
        self.status_code = status
        self.text = content.decode("utf-8", errors="replace") if content else ""

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# ---- Luma ----------------------------------------------------------------


def test_luma_video_gen_polls_until_completed(tmp_path: Path, monkeypatch):
    from comecut_py.ai import luma_video as mod

    monkeypatch.setenv("LUMAAI_API_KEY", "luma_test")
    fake = MagicMock()
    fake.post.return_value = _FakeResponse(json_body={"id": "gen-1"})
    fake.get.side_effect = [
        _FakeResponse(json_body={"state": "queued", "assets": {}}),
        _FakeResponse(json_body={"state": "dreaming", "assets": {}}),
        _FakeResponse(json_body={
            "state": "completed",
            "assets": {"video": "https://example.invalid/luma.mp4"},
        }),
        _FakeResponse(content=b"LUMAMP4"),
    ]
    sys.modules["requests"] = fake
    monkeypatch.setattr(mod, "requests", fake, raising=False)

    gen = mod.LumaVideoGen(poll_interval=0.0)
    dst = tmp_path / "v.mp4"
    gen.generate("a sunset", dst, duration=5.0, aspect_ratio="16:9", seed=42)

    body = json.loads(fake.post.call_args.kwargs["data"])
    assert body["prompt"] == "a sunset"
    assert body["aspect_ratio"] == "16:9"
    assert body["model"] == "ray-2"
    assert body["seed"] == 42
    assert dst.read_bytes() == b"LUMAMP4"


def test_luma_video_gen_raises_on_failed_state(tmp_path: Path, monkeypatch):
    from comecut_py.ai import luma_video as mod

    monkeypatch.setenv("LUMAAI_API_KEY", "luma_test")
    fake = MagicMock()
    fake.post.return_value = _FakeResponse(json_body={"id": "gen-2"})
    fake.get.return_value = _FakeResponse(json_body={
        "state": "failed",
        "failure_reason": "content policy",
        "assets": {},
    })
    sys.modules["requests"] = fake
    monkeypatch.setattr(mod, "requests", fake, raising=False)

    gen = mod.LumaVideoGen(poll_interval=0.0)
    with pytest.raises(RuntimeError, match="failed"):
        gen.generate("naughty", tmp_path / "v.mp4")


def test_luma_video_gen_requires_api_key(monkeypatch):
    from comecut_py.ai.luma_video import LumaVideoGen

    monkeypatch.delenv("LUMAAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LUMAAI_API_KEY"):
        LumaVideoGen()


# ---- Kling ---------------------------------------------------------------


def test_kling_jwt_is_signed_with_secret_key():
    from comecut_py.ai.kling_video import _make_jwt

    token = _make_jwt("ak_test", "sk_secret", ttl=60)
    header_b64, payload_b64, sig_b64 = token.split(".")

    def _b64decode(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    header = json.loads(_b64decode(header_b64))
    payload = json.loads(_b64decode(payload_b64))
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert payload["iss"] == "ak_test"
    assert payload["exp"] > payload["nbf"]

    expected = hmac.new(
        b"sk_secret", f"{header_b64}.{payload_b64}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    assert _b64decode(sig_b64) == expected


def test_kling_video_gen_clamps_duration_and_polls(tmp_path: Path, monkeypatch):
    from comecut_py.ai import kling_video as mod

    monkeypatch.setenv("KLING_ACCESS_KEY", "ak_test")
    monkeypatch.setenv("KLING_SECRET_KEY", "sk_test")
    fake = MagicMock()
    fake.post.return_value = _FakeResponse(
        json_body={"data": {"task_id": "task-1"}},
    )
    fake.get.side_effect = [
        _FakeResponse(json_body={"data": {"task_status": "submitted"}}),
        _FakeResponse(json_body={"data": {"task_status": "processing"}}),
        _FakeResponse(json_body={"data": {
            "task_status": "succeed",
            "task_result": {"videos": [{"url": "https://example.invalid/kling.mp4"}]},
        }}),
        _FakeResponse(content=b"KLINGMP4"),
    ]
    sys.modules["requests"] = fake
    monkeypatch.setattr(mod, "requests", fake, raising=False)

    gen = mod.KlingVideoGen(poll_interval=0.0)
    dst = tmp_path / "v.mp4"
    # 7 s isn't a Kling preset; should clamp to "5".
    gen.generate("a robot", dst, duration=7.0, aspect_ratio="9:16")

    body = json.loads(fake.post.call_args.kwargs["data"])
    assert body["model_name"] == "kling-v2-6"
    assert body["prompt"] == "a robot"
    assert body["duration"] == "5"
    assert body["aspect_ratio"] == "9:16"
    assert body["mode"] == "standard"

    # Auth header is a Bearer JWT.
    auth = fake.post.call_args.kwargs["headers"]["Authorization"]
    assert auth.startswith("Bearer ")
    assert dst.read_bytes() == b"KLINGMP4"


def test_kling_video_gen_raises_on_failed_status(tmp_path: Path, monkeypatch):
    from comecut_py.ai import kling_video as mod

    monkeypatch.setenv("KLING_ACCESS_KEY", "ak_test")
    monkeypatch.setenv("KLING_SECRET_KEY", "sk_test")
    fake = MagicMock()
    fake.post.return_value = _FakeResponse(
        json_body={"data": {"task_id": "task-x"}},
    )
    fake.get.return_value = _FakeResponse(json_body={"data": {
        "task_status": "failed",
        "task_status_msg": "rate limited",
    }})
    sys.modules["requests"] = fake
    monkeypatch.setattr(mod, "requests", fake, raising=False)

    gen = mod.KlingVideoGen(poll_interval=0.0)
    with pytest.raises(RuntimeError, match="failed"):
        gen.generate("anything", tmp_path / "v.mp4")


def test_kling_video_gen_requires_credentials(monkeypatch):
    from comecut_py.ai.kling_video import KlingVideoGen

    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="KLING_ACCESS_KEY"):
        KlingVideoGen()


# ---- Veo -----------------------------------------------------------------


def test_veo_video_gen_polls_until_done(tmp_path: Path, monkeypatch):
    from comecut_py.ai import veo_video as mod

    monkeypatch.setenv("GEMINI_API_KEY", "gem_test")
    fake = MagicMock()
    fake.post.return_value = _FakeResponse(json_body={"name": "operations/op-1"})
    fake.get.side_effect = [
        _FakeResponse(json_body={"name": "operations/op-1", "done": False}),
        _FakeResponse(json_body={
            "name": "operations/op-1",
            "done": True,
            "response": {
                "generateVideoResponse": {
                    "generatedSamples": [
                        {"video": {"uri": "https://example.invalid/veo.mp4"}}
                    ]
                }
            },
        }),
        _FakeResponse(content=b"VEOMP4"),
    ]
    sys.modules["requests"] = fake
    monkeypatch.setattr(mod, "requests", fake, raising=False)

    gen = mod.VeoVideoGen(poll_interval=0.0)
    dst = tmp_path / "v.mp4"
    gen.generate("a city at night", dst, duration=8.0, aspect_ratio="16:9")

    body = json.loads(fake.post.call_args.kwargs["data"])
    assert body["instances"][0]["prompt"] == "a city at night"
    assert body["parameters"]["aspectRatio"] == "16:9"
    assert body["parameters"]["durationSeconds"] == 8

    # API key is appended as a query parameter, not a header.
    assert fake.post.call_args.kwargs["params"]["key"] == "gem_test"
    assert dst.read_bytes() == b"VEOMP4"


def test_veo_video_gen_raises_on_operation_error(tmp_path: Path, monkeypatch):
    from comecut_py.ai import veo_video as mod

    monkeypatch.setenv("GEMINI_API_KEY", "gem_test")
    fake = MagicMock()
    fake.post.return_value = _FakeResponse(json_body={"name": "operations/op-2"})
    fake.get.return_value = _FakeResponse(json_body={
        "name": "operations/op-2",
        "done": True,
        "error": {"code": 9, "message": "FAILED_PRECONDITION"},
    })
    sys.modules["requests"] = fake
    monkeypatch.setattr(mod, "requests", fake, raising=False)

    gen = mod.VeoVideoGen(poll_interval=0.0)
    with pytest.raises(RuntimeError, match="FAILED_PRECONDITION"):
        gen.generate("anything", tmp_path / "v.mp4")


def test_veo_video_gen_extracts_predictions_shape(tmp_path: Path, monkeypatch):
    """The Vertex-style ``predictions[0].videoUri`` shape is supported."""
    from comecut_py.ai import veo_video as mod

    monkeypatch.setenv("GEMINI_API_KEY", "gem_test")
    fake = MagicMock()
    fake.post.return_value = _FakeResponse(json_body={"name": "operations/op-3"})
    fake.get.side_effect = [
        _FakeResponse(json_body={
            "name": "operations/op-3",
            "done": True,
            "response": {"predictions": [{"videoUri": "https://example.invalid/veo2.mp4"}]},
        }),
        _FakeResponse(content=b"VEOPRED"),
    ]
    sys.modules["requests"] = fake
    monkeypatch.setattr(mod, "requests", fake, raising=False)

    gen = mod.VeoVideoGen(poll_interval=0.0)
    dst = tmp_path / "v.mp4"
    gen.generate("anything", dst)
    assert dst.read_bytes() == b"VEOPRED"


def test_veo_video_gen_requires_api_key(monkeypatch):
    from comecut_py.ai.veo_video import VeoVideoGen

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        VeoVideoGen()


# ---- CLI dispatch --------------------------------------------------------


def test_cli_video_gen_dispatches_to_each_provider(tmp_path: Path, monkeypatch):
    """`comecut-py video-gen --provider luma|kling|veo` reaches the right adapter."""
    from typer.testing import CliRunner

    from comecut_py.cli import app

    monkeypatch.setenv("LUMAAI_API_KEY", "luma_test")
    monkeypatch.setenv("KLING_ACCESS_KEY", "ak_test")
    monkeypatch.setenv("KLING_SECRET_KEY", "sk_test")
    monkeypatch.setenv("GEMINI_API_KEY", "gem_test")

    seen: dict[str, int] = {"luma": 0, "kling": 0, "veo": 0}

    class _StubGen:
        def __init__(self, key, **_):
            self._key = key

        def generate(self, prompt, dst, *, duration=5.0, aspect_ratio="16:9", seed=None):
            seen[self._key] += 1
            Path(dst).write_bytes(b"OK")
            return Path(dst)

    runner = CliRunner()
    with (
        monkeypatch.context() as m,
    ):
        m.setattr(
            "comecut_py.ai.luma_video.LumaVideoGen",
            lambda **kw: _StubGen("luma", **kw),
        )
        m.setattr(
            "comecut_py.ai.kling_video.KlingVideoGen",
            lambda **kw: _StubGen("kling", **kw),
        )
        m.setattr(
            "comecut_py.ai.veo_video.VeoVideoGen",
            lambda **kw: _StubGen("veo", **kw),
        )
        for provider in ("luma", "kling", "veo"):
            dst = tmp_path / f"{provider}.mp4"
            r = runner.invoke(app, [
                "video-gen", "hello", str(dst), "--provider", provider,
            ])
            assert r.exit_code == 0, r.output
            assert dst.read_bytes() == b"OK"
    assert seen == {"luma": 1, "kling": 1, "veo": 1}
