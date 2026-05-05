"""Tests for the generative-AI adapter pack (PR A).

All network calls are stubbed via ``unittest.mock.patch`` on the
provider module's ``requests`` binding — no test ever actually hits
a third-party API.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---- OpenAI image gen -----------------------------------------------------


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


def test_openai_image_gen_writes_b64_payload(tmp_path: Path, monkeypatch):
    from comecut_py.ai import openai_image as mod

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    png_bytes = b"\x89PNG\r\n\x1a\nFAKE"
    fake_requests = MagicMock()
    fake_requests.post.return_value = _FakeResponse(
        json_body={"data": [{"b64_json": base64.b64encode(png_bytes).decode()}]},
    )
    monkeypatch.setattr(mod, "requests", fake_requests, raising=False)

    # Ensure module imports its own `requests` from the stdlib path
    # rather than re-importing inside the call. The provider's
    # implementation uses a local ``import requests`` — shim via
    # sys.modules to intercept that.
    import sys
    sys.modules["requests"] = fake_requests

    gen = mod.OpenAIImageGen(model="gpt-image-1")
    dst = tmp_path / "img.png"
    gen.generate("a red apple", dst, size="1024x1024")

    assert dst.read_bytes() == png_bytes
    call = fake_requests.post.call_args
    assert call.args[0].endswith("/images/generations")
    body = json.loads(call.kwargs["data"])
    assert body["prompt"] == "a red apple"
    assert body["size"] == "1024x1024"
    assert body["model"] == "gpt-image-1"
    # gpt-image-1 does NOT force response_format=b64_json (that's default).
    assert "response_format" not in body


def test_openai_image_gen_dalle3_follows_url(tmp_path: Path, monkeypatch):
    from comecut_py.ai import openai_image as mod

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_requests = MagicMock()
    fake_requests.post.return_value = _FakeResponse(
        json_body={"data": [{"url": "https://example.invalid/fake.png"}]},
    )
    # The download step uses ``requests.get``.
    fake_requests.get.return_value = _FakeResponse(content=b"PNGBYTES")
    import sys
    sys.modules["requests"] = fake_requests
    monkeypatch.setattr(mod, "requests", fake_requests, raising=False)

    gen = mod.OpenAIImageGen(model="dall-e-3")
    dst = tmp_path / "img.png"
    gen.generate("a red apple", dst)

    # Two HTTP calls: POST (generate) then GET (download).
    assert fake_requests.post.called
    assert fake_requests.get.called
    body = json.loads(fake_requests.post.call_args.kwargs["data"])
    # DALL-E 3 explicitly requests b64_json → we fall back to URL
    # only when the response didn't have b64_json (simulated here).
    assert body["response_format"] == "b64_json"
    assert dst.read_bytes() == b"PNGBYTES"


def test_openai_image_gen_requires_api_key(monkeypatch):
    from comecut_py.ai.openai_image import OpenAIImageGen

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIImageGen()


# ---- Stability image gen --------------------------------------------------


def test_stability_image_gen_sends_multipart_and_writes_bytes(
    tmp_path: Path, monkeypatch,
):
    from comecut_py.ai import stability_image as mod

    monkeypatch.setenv("STABILITY_API_KEY", "sk-test")
    fake_requests = MagicMock()
    fake_requests.post.return_value = _FakeResponse(content=b"JPEGBYTES")
    import sys
    sys.modules["requests"] = fake_requests
    monkeypatch.setattr(mod, "requests", fake_requests, raising=False)

    gen = mod.StabilityImageGen(engine="ultra")
    dst = tmp_path / "img.jpg"
    gen.generate("mountain", dst, size="16:9", negative_prompt="blurry", seed=42)

    call = fake_requests.post.call_args
    assert call.args[0].endswith("/v2beta/stable-image/generate/ultra")
    # Should send multipart; no `data=json.dumps(...)`.
    assert "files" in call.kwargs
    data = call.kwargs["data"]
    assert data["prompt"] == "mountain"
    assert data["aspect_ratio"] == "16:9"
    assert data["negative_prompt"] == "blurry"
    assert data["seed"] == "42"
    assert data["output_format"] == "jpeg"
    assert dst.read_bytes() == b"JPEGBYTES"


def test_stability_image_gen_rejects_unknown_engine(monkeypatch):
    from comecut_py.ai.stability_image import StabilityImageGen

    monkeypatch.setenv("STABILITY_API_KEY", "sk-test")
    with pytest.raises(ValueError, match="engine"):
        StabilityImageGen(engine="not-an-engine")


# ---- Replicate image + video ---------------------------------------------


def test_replicate_image_gen_polls_and_downloads(tmp_path: Path, monkeypatch):
    from comecut_py.ai import replicate as mod

    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test")
    fake_requests = MagicMock()
    # First POST returns a submitted prediction with status=starting.
    fake_requests.post.return_value = _FakeResponse(
        json_body={
            "id": "abc",
            "status": "starting",
            "urls": {"get": "https://api.example/predictions/abc"},
        },
    )
    # Two GET polls: processing → succeeded.
    fake_requests.get.side_effect = [
        _FakeResponse(
            json_body={"status": "processing", "urls": {"get": "..."}},
        ),
        _FakeResponse(
            json_body={
                "status": "succeeded",
                "output": ["https://example.invalid/image.png"],
                "urls": {"get": "..."},
            },
        ),
        _FakeResponse(content=b"FINALBYTES"),  # final download
    ]
    import sys
    sys.modules["requests"] = fake_requests
    monkeypatch.setattr(mod, "requests", fake_requests, raising=False)

    gen = mod.ReplicateImageGen(
        model="black-forest-labs/flux-schnell", poll_interval=0.0,
    )
    dst = tmp_path / "img.png"
    gen.generate("cat", dst, size="16:9", seed=7)

    assert dst.read_bytes() == b"FINALBYTES"
    post_call = fake_requests.post.call_args
    assert "models/black-forest-labs/flux-schnell/predictions" in post_call.args[0]
    body = json.loads(post_call.kwargs["data"])
    assert body["input"]["prompt"] == "cat"
    assert body["input"]["aspect_ratio"] == "16:9"
    assert body["input"]["seed"] == 7


def test_replicate_propagates_failed_status(tmp_path: Path, monkeypatch):
    from comecut_py.ai import replicate as mod

    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test")
    fake_requests = MagicMock()
    fake_requests.post.return_value = _FakeResponse(
        json_body={
            "id": "abc", "status": "failed", "error": "NSFW rejected",
            "urls": {"get": "..."},
        },
    )
    import sys
    sys.modules["requests"] = fake_requests
    monkeypatch.setattr(mod, "requests", fake_requests, raising=False)

    gen = mod.ReplicateImageGen(poll_interval=0.0)
    with pytest.raises(RuntimeError, match="failed"):
        gen.generate("cat", tmp_path / "img.png")


def test_replicate_video_gen_passes_duration_and_aspect(
    tmp_path: Path, monkeypatch,
):
    from comecut_py.ai import replicate as mod

    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test")
    fake_requests = MagicMock()
    fake_requests.post.return_value = _FakeResponse(
        json_body={
            "id": "v1",
            "status": "succeeded",
            "output": "https://example.invalid/video.mp4",
            "urls": {"get": "..."},
        },
    )
    fake_requests.get.return_value = _FakeResponse(content=b"MP4")
    import sys
    sys.modules["requests"] = fake_requests
    monkeypatch.setattr(mod, "requests", fake_requests, raising=False)

    gen = mod.ReplicateVideoGen(model="minimax/video-01", poll_interval=0.0)
    dst = tmp_path / "v.mp4"
    gen.generate("a cat", dst, duration=5.0, aspect_ratio="9:16")

    body = json.loads(fake_requests.post.call_args.kwargs["data"])
    assert body["input"]["prompt"] == "a cat"
    assert body["input"]["aspect_ratio"] == "9:16"
    assert body["input"]["duration"] == 5.0
    assert dst.read_bytes() == b"MP4"


# ---- Runway video gen ----------------------------------------------------


def test_runway_video_gen_clamps_duration_and_polls(
    tmp_path: Path, monkeypatch,
):
    from comecut_py.ai import runway_video as mod

    monkeypatch.setenv("RUNWAYML_API_SECRET", "key_test")
    fake_requests = MagicMock()
    fake_requests.post.return_value = _FakeResponse(json_body={"id": "task-1"})
    fake_requests.get.side_effect = [
        _FakeResponse(json_body={"status": "RUNNING", "output": []}),
        _FakeResponse(json_body={
            "status": "SUCCEEDED", "output": ["https://example.invalid/out.mp4"],
        }),
        _FakeResponse(content=b"RUNWAYMP4"),
    ]
    import sys
    sys.modules["requests"] = fake_requests
    monkeypatch.setattr(mod, "requests", fake_requests, raising=False)

    gen = mod.RunwayVideoGen(poll_interval=0.0)
    dst = tmp_path / "r.mp4"
    gen.generate("a dog", dst, duration=7.0, aspect_ratio="16:9")

    post_body = json.loads(fake_requests.post.call_args.kwargs["data"])
    # 7 s is not a supported preset; clamps to 5 (the < 8 branch).
    assert post_body["duration"] == 5
    assert post_body["ratio"] == "16:9"
    assert post_body["promptText"] == "a dog"
    assert dst.read_bytes() == b"RUNWAYMP4"


def test_runway_video_gen_raises_on_failed_task(tmp_path: Path, monkeypatch):
    from comecut_py.ai import runway_video as mod

    monkeypatch.setenv("RUNWAYML_API_SECRET", "key_test")
    fake_requests = MagicMock()
    fake_requests.post.return_value = _FakeResponse(json_body={"id": "task-2"})
    fake_requests.get.return_value = _FakeResponse(json_body={
        "status": "FAILED", "failure": "rate_limited",
    })
    import sys
    sys.modules["requests"] = fake_requests
    monkeypatch.setattr(mod, "requests", fake_requests, raising=False)

    gen = mod.RunwayVideoGen(poll_interval=0.0)
    with pytest.raises(RuntimeError, match="FAILED"):
        gen.generate("a dog", tmp_path / "r.mp4")


# ---- ElevenLabs voice clone ----------------------------------------------


def test_elevenlabs_voice_clone_uploads_samples_and_returns_voice_id(
    tmp_path: Path, monkeypatch,
):
    from comecut_py.ai import elevenlabs_voice_clone as mod

    monkeypatch.setenv("ELEVENLABS_API_KEY", "el_test")
    # Two fake audio samples.
    s1 = tmp_path / "a.mp3"
    s2 = tmp_path / "b.mp3"
    s1.write_bytes(b"fake-mp3-1")
    s2.write_bytes(b"fake-mp3-2")

    fake_requests = MagicMock()
    fake_requests.post.return_value = _FakeResponse(
        json_body={"voice_id": "voice_abc", "requires_verification": False},
    )
    import sys
    sys.modules["requests"] = fake_requests
    monkeypatch.setattr(mod, "requests", fake_requests, raising=False)

    cloner = mod.ElevenLabsVoiceClone()
    voice_id = cloner.clone("My Voice", [s1, s2], description="test")
    assert voice_id == "voice_abc"

    call = fake_requests.post.call_args
    # Multipart upload contract: `files=[…]`, `data={"name":…}`, xi-api-key header.
    assert "voices/add" in call.args[0]
    assert call.kwargs["headers"]["xi-api-key"] == "el_test"
    data = call.kwargs["data"]
    assert data["name"] == "My Voice"
    assert data["description"] == "test"
    files = call.kwargs["files"]
    assert len(files) == 2
    assert all(f[0] == "files" for f in files)
    assert files[0][1][0] == "a.mp3"
    assert files[1][1][0] == "b.mp3"


def test_elevenlabs_voice_clone_requires_samples(tmp_path: Path, monkeypatch):
    from comecut_py.ai.elevenlabs_voice_clone import ElevenLabsVoiceClone

    monkeypatch.setenv("ELEVENLABS_API_KEY", "el_test")
    cloner = ElevenLabsVoiceClone()
    with pytest.raises(ValueError, match="sample"):
        cloner.clone("foo", [])


def test_elevenlabs_voice_clone_rejects_missing_files(tmp_path: Path, monkeypatch):
    from comecut_py.ai.elevenlabs_voice_clone import ElevenLabsVoiceClone

    monkeypatch.setenv("ELEVENLABS_API_KEY", "el_test")
    cloner = ElevenLabsVoiceClone()
    with pytest.raises(FileNotFoundError):
        cloner.clone("foo", [tmp_path / "does-not-exist.mp3"])


# ---- CLI plumbing ---------------------------------------------------------


def test_cli_image_gen_dispatches_to_openai_adapter(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from comecut_py.cli import app

    fake = MagicMock()
    fake.generate.return_value = tmp_path / "out.png"

    def _factory(**kwargs):
        fake.init_kwargs = kwargs
        return fake

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with patch(
        "comecut_py.ai.openai_image.OpenAIImageGen", side_effect=_factory,
    ):
        result = CliRunner().invoke(
            app, ["image-gen", "a cat", str(tmp_path / "out.png"),
                  "--size", "1024x1024"],
        )
    assert result.exit_code == 0, result.output
    fake.generate.assert_called_once()
    # Positional: prompt, out_path. Keyword: size/negative_prompt/seed.
    args, kwargs = fake.generate.call_args
    assert args[0] == "a cat"
    assert kwargs["size"] == "1024x1024"


def test_cli_video_gen_dispatches_to_runway(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from comecut_py.cli import app

    fake = MagicMock()
    fake.generate.return_value = tmp_path / "out.mp4"
    monkeypatch.setenv("RUNWAYML_API_SECRET", "key_test")
    with patch(
        "comecut_py.ai.runway_video.RunwayVideoGen", return_value=fake,
    ):
        result = CliRunner().invoke(
            app, ["video-gen", "a dog", str(tmp_path / "out.mp4"),
                  "--provider", "runway", "--duration", "10",
                  "--aspect", "9:16"],
        )
    assert result.exit_code == 0, result.output
    _, kwargs = fake.generate.call_args
    assert kwargs["duration"] == 10.0
    assert kwargs["aspect_ratio"] == "9:16"


def test_cli_voice_clone_prints_voice_id(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from comecut_py.cli import app

    fake = MagicMock()
    fake.clone.return_value = "voice_xyz"
    sample = tmp_path / "s.mp3"
    sample.write_bytes(b"fake")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el_test")
    with patch(
        "comecut_py.ai.elevenlabs_voice_clone.ElevenLabsVoiceClone",
        return_value=fake,
    ):
        result = CliRunner().invoke(
            app, ["voice-clone", "My Voice", str(sample)],
        )
    assert result.exit_code == 0, result.output
    assert "voice_xyz" in result.output


def test_cli_rejects_unknown_provider(tmp_path: Path):
    from typer.testing import CliRunner

    from comecut_py.cli import app

    result = CliRunner().invoke(
        app, ["image-gen", "a", str(tmp_path / "x.png"),
              "--provider", "not-real"],
    )
    assert result.exit_code == 2
    assert "unknown provider" in result.output
