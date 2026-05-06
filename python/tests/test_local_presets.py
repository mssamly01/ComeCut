from __future__ import annotations

import pytest

from comecut_py.core.local_presets import (
    delete_local_preset,
    list_local_presets,
    load_local_preset,
    preset_file_path,
    save_local_preset,
    slugify_preset_name,
)


def test_slugify_preset_name_is_filesystem_safe():
    assert slugify_preset_name("My Text Style!") == "my-text-style"
    assert slugify_preset_name("  ") == "preset"


def test_save_load_list_and_delete_local_preset(tmp_path):
    payload = {"font_family": "Verdana", "font_size": 42, "color": "#ffffff"}

    path = save_local_preset("text", "Clean Caption", payload, root=tmp_path)

    assert path == preset_file_path("text", "Clean Caption", root=tmp_path)
    assert path.exists()

    loaded = load_local_preset("text", "Clean Caption", root=tmp_path)
    assert loaded.category == "text"
    assert loaded.name == "Clean Caption"
    assert loaded.payload == payload

    presets = list_local_presets("text", root=tmp_path)
    assert [preset.name for preset in presets] == ["Clean Caption"]

    assert delete_local_preset("text", "Clean Caption", root=tmp_path) is True
    assert delete_local_preset("text", "Clean Caption", root=tmp_path) is False
    assert list_local_presets("text", root=tmp_path) == []


def test_save_local_preset_rejects_unknown_category(tmp_path):
    with pytest.raises(ValueError, match="Unknown preset category"):
        save_local_preset("cloud", "Nope", {}, root=tmp_path)


def test_save_local_preset_requires_json_object(tmp_path):
    with pytest.raises(TypeError, match="JSON object"):
        save_local_preset("effect", "Bad", ["not", "object"], root=tmp_path)  # type: ignore[arg-type]
