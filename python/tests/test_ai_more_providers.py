"""Unit tests for Gemini / Claude / Deepgram / ElevenLabs / Azure adapters.

All tests inject a fake ``requests`` module via ``sys.modules`` so nothing
hits the real network. We assert the adapters:
  * send the right URL + headers + payload shape for each provider
  * decode the provider's response into the right CueList / string / bytes
  * raise cleanly when the expected env var / credentials are missing
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest


class _FakeResponse:
    def __init__(
        self,
        payload: Any = None,
        *,
        content: bytes | None = None,
        status: int = 200,
    ):
        self._payload = payload
        self.content = content if content is not None else b""
        self.status_code = status
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _install_fake_requests(response: _FakeResponse, captured: dict) -> None:
    mod = types.ModuleType("requests")

    def post(url, headers=None, data=None, files=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers or {}
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
        _install_fake_requests(response, captured)
        return captured

    yield install
    sys.modules.pop("requests", None)


# ---- Gemini --------------------------------------------------------------


def test_gemini_translate_happy_path(fake_requests, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    captured = fake_requests(
        _FakeResponse({"candidates": [{"content": {"parts": [{"text": "xin chào"}]}}]})
    )
    from comecut_py.ai.gemini_translate import GeminiTranslate

    tr = GeminiTranslate(model="gemini-1.5-flash")
    out = tr.translate("hello", target="Vietnamese")
    assert out == "xin chào"
    assert "generativelanguage.googleapis.com" in captured["url"]
    assert "key=g-key" in captured["url"]
    body = json.loads(captured["data"])
    assert body["contents"][0]["parts"][0]["text"].startswith("You are a professional")


def test_gemini_empty_text_passthrough(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    from comecut_py.ai.gemini_translate import GeminiTranslate

    assert GeminiTranslate().translate("   ", target="vi") == "   "

def test_gemini_translate_items_happy_path(fake_requests, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                "[{\"id\":\"1\",\"text\":\"xin chào\"},"
                                "{\"id\":\"2\",\"text\":\"thế giới\"}]"
                            )
                        }
                    ]
                }
            }
        ]
    }
    fake_requests(_FakeResponse(payload))
    from comecut_py.ai.gemini_translate import GeminiTranslate

    out = GeminiTranslate().translate_items(
        [{"id": "1", "text": "hello"}, {"id": "2", "text": "world"}],
        target="Vietnamese",
    )
    assert out == [
        {"id": "1", "text": "xin chào"},
        {"id": "2", "text": "thế giới"},
    ]


def test_gemini_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from comecut_py.ai.gemini_translate import GeminiTranslate

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiTranslate()


# ---- Claude --------------------------------------------------------------


def test_claude_translate_happy_path(fake_requests, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "c-key")
    captured = fake_requests(
        _FakeResponse({"content": [{"type": "text", "text": "xin chào"}]})
    )
    from comecut_py.ai.claude_translate import ClaudeTranslate

    tr = ClaudeTranslate()
    out = tr.translate("hello", target="Vietnamese")
    assert out == "xin chào"
    assert captured["url"].endswith("/messages")
    assert captured["headers"]["x-api-key"] == "c-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    body = json.loads(captured["data"])
    assert body["messages"][0]["content"] == "hello"


def test_claude_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from comecut_py.ai.claude_translate import ClaudeTranslate

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ClaudeTranslate()

def test_claude_translate_items_happy_path(fake_requests, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "c-key")
    payload = {
        "content": [
            {
                "type": "text",
                "text": (
                    "[{\"id\":\"1\",\"text\":\"xin chào\"},"
                    "{\"id\":\"2\",\"text\":\"thế giới\"}]"
                ),
            }
        ]
    }
    fake_requests(_FakeResponse(payload))
    from comecut_py.ai.claude_translate import ClaudeTranslate

    out = ClaudeTranslate().translate_items(
        [{"id": "1", "text": "hello"}, {"id": "2", "text": "world"}],
        target="Vietnamese",
    )
    assert out == [
        {"id": "1", "text": "xin chào"},
        {"id": "2", "text": "thế giới"},
    ]


# ---- Deepgram ------------------------------------------------------------


def test_deepgram_asr_parses_utterances(fake_requests, monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "d-key")
    captured = fake_requests(
        _FakeResponse(
            {
                "results": {
                    "utterances": [
                        {"start": 0.0, "end": 1.2, "transcript": "hello there"},
                        {"start": 1.2, "end": 2.5, "transcript": "how are you"},
                    ]
                }
            }
        )
    )
    from comecut_py.ai.deepgram_asr import DeepgramASR

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    cues = DeepgramASR(model="nova-2").transcribe(audio)
    assert len(cues) == 2
    assert cues.cues[0].text == "hello there"
    assert cues.cues[1].start == pytest.approx(1.2)
    assert captured["headers"]["Authorization"] == "Token d-key"
    assert "model=nova-2" in captured["url"]


def test_deepgram_asr_fallback_to_top_transcript(fake_requests, monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "d-key")
    fake_requests(
        _FakeResponse(
            {
                "results": {
                    "channels": [
                        {
                            "alternatives": [
                                {
                                    "transcript": "one two",
                                    "words": [
                                        {"word": "one", "start": 0.0, "end": 0.5},
                                        {"word": "two", "start": 0.5, "end": 1.0},
                                    ],
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    from comecut_py.ai.deepgram_asr import DeepgramASR

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    cues = DeepgramASR().transcribe(audio)
    assert len(cues) == 1
    assert cues.cues[0].text == "one two"
    assert cues.cues[0].end == pytest.approx(1.0)


# ---- ElevenLabs ----------------------------------------------------------


def test_elevenlabs_tts_writes_bytes(fake_requests, monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "e-key")
    captured = fake_requests(_FakeResponse(None, content=b"AUDIO"))
    from comecut_py.ai.elevenlabs_tts import ElevenLabsTTS

    out = tmp_path / "speak.mp3"
    dst = ElevenLabsTTS().synthesize("hello", out, voice="VOICE123")
    assert dst == out
    assert out.read_bytes() == b"AUDIO"
    assert "text-to-speech/VOICE123" in captured["url"]
    assert "output_format=mp3_44100_128" in captured["url"]
    assert captured["headers"]["xi-api-key"] == "e-key"


def test_elevenlabs_tts_format_from_extension(fake_requests, monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "e-key")
    captured = fake_requests(_FakeResponse(None, content=b"WAVE"))
    from comecut_py.ai.elevenlabs_tts import ElevenLabsTTS

    ElevenLabsTTS().synthesize("hi", tmp_path / "out.wav")
    assert "output_format=pcm_24000" in captured["url"]


# ---- Azure ---------------------------------------------------------------


def test_azure_asr_parses_words_into_chunks(fake_requests, monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "az-key")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "eastus")
    # 12 words → 2 chunks (first 10, then 2). Offset/Duration are in 100-ns ticks.
    words = []
    for i in range(12):
        words.append(
            {
                "Word": f"w{i}",
                "Offset": int(i * 10_000_000),  # each word starts 1 s apart
                "Duration": int(5_000_000),  # each word lasts 0.5 s
            }
        )
    fake_requests(
        _FakeResponse(
            {
                "RecognitionStatus": "Success",
                "DisplayText": "w0 w1 w2 w3 w4 w5 w6 w7 w8 w9 w10 w11",
                "NBest": [
                    {
                        "Display": "w0 w1 w2 w3 w4 w5 w6 w7 w8 w9 w10 w11",
                        "Words": words,
                    }
                ],
            }
        )
    )
    from comecut_py.ai.azure_asr import AzureSpeechASR

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    cues = AzureSpeechASR().transcribe(audio)
    assert len(cues) == 2
    assert cues.cues[0].text.startswith("w0 w1")
    assert cues.cues[0].end == pytest.approx(9.5)  # word 9 offset 9s + 0.5s
    assert cues.cues[1].text == "w10 w11"


def test_azure_asr_missing_region(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "k")
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)
    from comecut_py.ai.azure_asr import AzureSpeechASR

    with pytest.raises(RuntimeError, match="AZURE_SPEECH_REGION"):
        AzureSpeechASR()
