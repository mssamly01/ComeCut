"""Unit tests for the OpenAI adapters.

These never hit the network — we inject a fake ``requests`` module via
``sys.modules`` and assert the adapters produce the right request payloads
and parse the fake responses correctly.
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest


class _FakeResponse:
    def __init__(self, payload: Any = None, *, content: bytes | None = None, status: int = 200):
        self._payload = payload
        self.content = content if content is not None else b""
        self.status_code = status
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _install_fake_requests(
    *,
    response: _FakeResponse,
    captured: dict,
) -> None:
    mod = types.ModuleType("requests")

    def post(url, headers=None, data=None, files=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = data
        captured["files"] = files
        captured["timeout"] = timeout
        return response

    mod.post = post  # type: ignore[attr-defined]
    sys.modules["requests"] = mod


@pytest.fixture
def fake_requests(monkeypatch):
    captured: dict = {}

    def install(response: _FakeResponse) -> dict:
        _install_fake_requests(response=response, captured=captured)
        return captured

    yield install
    sys.modules.pop("requests", None)


def test_openai_asr_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from comecut_py.ai.openai_asr import OpenAIASR

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIASR()


def test_openai_asr_parses_segments(fake_requests, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-TOKEN")
    payload = {
        "text": "hello world foo bar",
        "segments": [
            {"start": 0.0, "end": 1.5, "text": "hello world"},
            {"start": 1.5, "end": 3.0, "text": "foo bar"},
            {"start": 3.0, "end": 3.0, "text": ""},  # degenerate, should be dropped
        ],
    }
    captured = fake_requests(_FakeResponse(payload))
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFFfake")

    from comecut_py.ai.openai_asr import OpenAIASR

    asr = OpenAIASR(model="whisper-1")
    cues = asr.transcribe(audio, language="en")
    assert len(cues) == 2
    assert cues.cues[0].text == "hello world"
    assert cues.cues[1].start == pytest.approx(1.5)

    assert captured["url"].endswith("/audio/transcriptions")
    assert captured["headers"]["Authorization"] == "Bearer sk-test-TOKEN"
    assert captured["data"]["model"] == "whisper-1"
    assert captured["data"]["response_format"] == "verbose_json"
    assert captured["data"]["language"] == "en"


def test_openai_asr_handles_plain_text_fallback(fake_requests, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    payload = {"text": "just some text", "duration": 2.5, "segments": []}
    fake_requests(_FakeResponse(payload))
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")

    from comecut_py.ai.openai_asr import OpenAIASR

    cues = OpenAIASR().transcribe(audio)
    assert len(cues) == 1
    assert cues.cues[0].end == pytest.approx(2.5)
    assert cues.cues[0].text == "just some text"


def test_openai_translate_posts_chat(fake_requests, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    payload = {"choices": [{"message": {"content": "Xin chào thế giới"}}]}
    captured = fake_requests(_FakeResponse(payload))

    from comecut_py.ai.openai_translate import OpenAITranslate

    tr = OpenAITranslate(model="gpt-4o-mini")
    out = tr.translate("Hello world", target="Vietnamese")
    assert out == "Xin chào thế giới"

    sent = json.loads(captured["data"])
    assert sent["model"] == "gpt-4o-mini"
    assert sent["messages"][1]["content"] == "Hello world"
    assert "Vietnamese" in sent["messages"][0]["content"]


def test_openai_translate_empty_passthrough(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from comecut_py.ai.openai_translate import OpenAITranslate

    # No fake requests installed — empty input must short-circuit before any HTTP.
    assert OpenAITranslate().translate("", target="vi") == ""
    assert OpenAITranslate().translate("   ", target="vi") == "   "

def test_openai_translate_items_structured_json(fake_requests, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        "[{\"id\":\"1\",\"text\":\"xin chào\"},"
                        "{\"id\":\"2\",\"text\":\"thế giới\"}]"
                    )
                }
            }
        ]
    }
    captured = fake_requests(_FakeResponse(payload))

    from comecut_py.ai.openai_translate import OpenAITranslate

    tr = OpenAITranslate(model="gpt-4o-mini")
    out = tr.translate_items(
        [{"id": "1", "text": "hello"}, {"id": "2", "text": "world"}],
        target="Vietnamese",
    )
    assert out == [
        {"id": "1", "text": "xin chào"},
        {"id": "2", "text": "thế giới"},
    ]

    sent = json.loads(captured["data"])
    assert sent["model"] == "gpt-4o-mini"
    assert "Items:" in sent["messages"][1]["content"]
    assert "\"id\": \"1\"" in sent["messages"][1]["content"]


def test_translate_cues_default_impl(fake_requests, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    payload = {"choices": [{"message": {"content": "bonjour"}}]}
    fake_requests(_FakeResponse(payload))

    from comecut_py.ai.openai_translate import OpenAITranslate
    from comecut_py.subtitles.cue import Cue, CueList

    cues = CueList([Cue(0, 1, "hello"), Cue(1, 2, "hello")])
    out = OpenAITranslate().translate_cues(cues, target="French")
    assert all(c.text == "bonjour" for c in out)
    assert out.cues[0].start == 0 and out.cues[0].end == 1


def test_openai_tts_writes_bytes(fake_requests, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    audio_bytes = b"\xff\xfb\x90\x64"  # fake MP3 header bytes
    captured = fake_requests(_FakeResponse(content=audio_bytes))
    dst = tmp_path / "out.mp3"

    from comecut_py.ai.openai_tts import OpenAITTS

    path = OpenAITTS(model="tts-1").synthesize("hello", dst, voice="nova")
    assert path == dst
    assert dst.read_bytes() == audio_bytes

    sent = json.loads(captured["data"])
    assert sent["model"] == "tts-1"
    assert sent["voice"] == "nova"
    assert sent["response_format"] == "mp3"


def test_openai_tts_infers_format_from_extension(fake_requests, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = fake_requests(_FakeResponse(content=b"\x00"))
    from comecut_py.ai.openai_tts import OpenAITTS

    OpenAITTS().synthesize("hi", tmp_path / "a.flac")
    assert json.loads(captured["data"])["response_format"] == "flac"
