"""Tests for the plugin / provider registry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from comecut_py import plugins
from comecut_py.cli import app

# ---- list_providers / get_provider --------------------------------------


def test_list_providers_includes_every_builtin_video_adapter():
    names = {p.name for p in plugins.list_providers("video")}
    assert {"runway", "replicate", "luma", "kling", "veo"} <= names
    sources = {p.name: p.source for p in plugins.list_providers("video")}
    assert sources["runway"] == "builtin"


def test_list_providers_includes_every_builtin_image_adapter():
    names = {p.name for p in plugins.list_providers("image")}
    assert {"openai", "stability", "replicate"} <= names


def test_list_providers_includes_every_builtin_tts_adapter():
    names = {p.name for p in plugins.list_providers("tts")}
    assert {"openai", "elevenlabs"} <= names


def test_list_providers_includes_every_builtin_voice_clone_adapter():
    names = {p.name for p in plugins.list_providers("voice_clone")}
    assert "elevenlabs" in names


def test_list_providers_returns_sorted_output():
    names = [p.name for p in plugins.list_providers("video")]
    assert names == sorted(names)


def test_list_providers_rejects_unknown_group():
    with pytest.raises(ValueError, match="unknown provider group"):
        plugins.list_providers("not-a-group")


def test_get_provider_resolves_builtin_video(monkeypatch):
    monkeypatch.setenv("LUMAAI_API_KEY", "luma_test")
    inst = plugins.get_provider("video", "luma")
    from comecut_py.ai.luma_video import LumaVideoGen
    assert isinstance(inst, LumaVideoGen)


def test_get_provider_passes_model_kwarg(monkeypatch):
    monkeypatch.setenv("LUMAAI_API_KEY", "luma_test")
    inst = plugins.get_provider("video", "luma", model="ray-flash-2")
    assert inst._model == "ray-flash-2"


def test_get_provider_uses_factory_default_model(monkeypatch):
    monkeypatch.setenv("LUMAAI_API_KEY", "luma_test")
    # No model kwarg → builtin default kicks in.
    inst = plugins.get_provider("video", "luma")
    assert inst._model == "ray-2"


def test_get_provider_unknown_name_lists_known_providers():
    with pytest.raises(KeyError) as excinfo:
        plugins.get_provider("video", "not-a-real-provider")
    msg = str(excinfo.value)
    assert "not-a-real-provider" in msg
    # Help text mentions a real builtin so users know what's available.
    assert "runway" in msg


def test_get_provider_unknown_group():
    with pytest.raises(ValueError, match="unknown provider group"):
        plugins.get_provider("not-a-group", "anything")


# ---- entry-point integration --------------------------------------------


class _FakeEntryPoint:
    """Mimics importlib.metadata.EntryPoint for the bits we use."""

    def __init__(self, name: str, factory, dist_name: str | None = None):
        self.name = name
        self._factory = factory
        if dist_name:
            self.dist = MagicMock(name=dist_name)
            self.dist.name = dist_name
        else:
            self.dist = None

    def load(self):
        return self._factory


def _patch_entry_points(group_alias: str, eps: list[_FakeEntryPoint]):
    """Patch _entry_points_for to return ``eps`` only for ``group_alias``."""
    original = plugins._entry_points_for

    def fake(group: str):
        if group == group_alias:
            return eps
        return original(group)

    return patch.object(plugins, "_entry_points_for", side_effect=fake)


class _DummyVideo:
    def __init__(self, *, model: str | None = None, **_):
        self.model = model

    def generate(self, prompt, dst, *, duration=5.0, aspect_ratio="16:9", seed=None):
        Path(dst).write_bytes(b"DUMMY")
        return Path(dst)


def test_external_plugin_is_discovered_via_entry_points():
    ep = _FakeEntryPoint("custom", _DummyVideo, dist_name="my-plugin-pkg")
    with _patch_entry_points("video", [ep]):
        names = {p.name: p.source for p in plugins.list_providers("video")}
        assert names["custom"].startswith("plugin")
        assert "my-plugin-pkg" in names["custom"]
        # Builtins still present.
        assert names["runway"] == "builtin"


def test_external_plugin_can_be_resolved_by_get_provider():
    ep = _FakeEntryPoint("custom", _DummyVideo)
    with _patch_entry_points("video", [ep]):
        inst = plugins.get_provider("video", "custom", model="my-model")
        assert isinstance(inst, _DummyVideo)
        assert inst.model == "my-model"


def test_plugin_shadows_builtin_with_same_name():
    """Plugins win over builtins when the names collide."""
    ep = _FakeEntryPoint("runway", _DummyVideo, dist_name="overrides")
    with _patch_entry_points("video", [ep]):
        inst = plugins.get_provider("video", "runway")
        assert isinstance(inst, _DummyVideo)
        # list_providers reports the override source.
        sources = {p.name: p.source for p in plugins.list_providers("video")}
        assert sources["runway"].startswith("plugin")


# ---- CLI ----------------------------------------------------------------


def test_cli_providers_list_shows_every_group():
    r = CliRunner().invoke(app, ["providers", "list"])
    assert r.exit_code == 0, r.output
    # All 4 group titles should appear.
    for g in ("video", "image", "tts", "voice_clone"):
        assert f"{g} providers" in r.output
    # And every builtin video provider name should appear.
    for name in ("runway", "replicate", "luma", "kling", "veo"):
        assert name in r.output


def test_cli_providers_list_filters_by_group():
    r = CliRunner().invoke(app, ["providers", "list", "--group", "video"])
    assert r.exit_code == 0, r.output
    assert "video providers" in r.output
    assert "image providers" not in r.output


def test_cli_providers_list_rejects_unknown_group():
    r = CliRunner().invoke(app, ["providers", "list", "--group", "fake-group"])
    assert r.exit_code == 2
    assert "fake-group" in r.output


def test_cli_video_gen_uses_registry_for_builtins(monkeypatch, tmp_path):
    """`video-gen --provider luma` should reach the registry's Luma factory."""
    monkeypatch.setenv("LUMAAI_API_KEY", "luma_test")
    seen: dict[str, int] = {"luma": 0}

    class _Stub:
        def __init__(self, *, model=None, **_):
            self.model = model

        def generate(self, prompt, dst, *, duration=5.0, aspect_ratio="16:9", seed=None):
            seen["luma"] += 1
            Path(dst).write_bytes(b"STUB")

    with patch("comecut_py.ai.luma_video.LumaVideoGen", _Stub):
        r = CliRunner().invoke(app, [
            "video-gen", "hi", str(tmp_path / "v.mp4"),
            "--provider", "luma",
        ])
    assert r.exit_code == 0, r.output
    assert seen["luma"] == 1


def test_cli_video_gen_uses_registry_for_plugin(tmp_path):
    """A plugin entry-point can swap in a provider that the CLI then uses."""
    seen: dict[str, int] = {"calls": 0}

    def _factory(*, model=None, **_):
        seen["calls"] += 1

        class _Stub:
            def generate(self_, prompt, dst, *, duration=5.0, aspect_ratio="16:9", seed=None):
                Path(dst).write_bytes(b"PLUG")
                return Path(dst)

        return _Stub()

    ep = _FakeEntryPoint("custom", _factory)
    with _patch_entry_points("video", [ep]):
        r = CliRunner().invoke(app, [
            "video-gen", "hi", str(tmp_path / "p.mp4"),
            "--provider", "custom",
        ])
    assert r.exit_code == 0, r.output
    assert seen["calls"] == 1


def test_cli_video_gen_unknown_provider_exits_with_error(tmp_path):
    r = CliRunner().invoke(app, [
        "video-gen", "hi", str(tmp_path / "nope.mp4"),
        "--provider", "not-real",
    ])
    assert r.exit_code == 2
    assert "unknown provider" in r.output


def test_cli_image_gen_unknown_provider_exits_with_error(tmp_path):
    r = CliRunner().invoke(app, [
        "image-gen", "hi", str(tmp_path / "nope.png"),
        "--provider", "not-real",
    ])
    assert r.exit_code == 2
    assert "unknown provider" in r.output


def test_cli_tts_unknown_provider_exits_with_error(tmp_path):
    r = CliRunner().invoke(app, [
        "tts", "hi", str(tmp_path / "nope.mp3"),
        "--provider", "not-real",
    ])
    assert r.exit_code == 2
    assert "unknown provider" in r.output
