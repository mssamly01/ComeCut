from __future__ import annotations

import pytest

from comecut_py.core.project import Clip
from comecut_py.core.text_style_presets import (
    TEXT_STYLE_SCHEMA,
    apply_text_style_payload,
    apply_text_style_preset,
    copy_text_style,
    list_text_style_presets,
    save_text_style_preset,
    text_style_payload_from_clip,
)


def _text_clip(**overrides) -> Clip:
    data = {
        "clip_type": "text",
        "source": "captions.srt",
        "in_point": 0.0,
        "out_point": 3.0,
        "start": 1.0,
        "text_main": "Hello",
        "text_second": "Xin chao",
        "text_display": "bilingual",
        "text_font_family": "Georgia",
        "text_font_size": 44,
        "text_color": "#ABCDEF",
        "text_second_font_size": 34,
        "text_second_color": "#00ff00",
        "text_stroke_color": "#111111",
        "text_stroke_width": 4,
    }
    data.update(overrides)
    return Clip(**data)


def test_text_style_payload_from_clip_excludes_content_and_timing():
    clip = _text_clip()

    payload = text_style_payload_from_clip(clip)

    assert payload["schema"] == TEXT_STYLE_SCHEMA
    assert payload["text_font_family"] == "Georgia"
    assert payload["text_color"] == "#abcdef"
    assert "text_main" not in payload
    assert "start" not in payload


def test_apply_text_style_payload_preserves_content_and_timing():
    target = _text_clip(
        text_main="Keep main",
        text_second="Keep second",
        text_font_family="Arial",
        text_color="#ffffff",
        text_stroke_width=1,
    )
    payload = text_style_payload_from_clip(_text_clip(text_main="Do not copy"))

    apply_text_style_payload(target, payload)

    assert target.text_main == "Keep main"
    assert target.text_second == "Keep second"
    assert target.start == pytest.approx(1.0)
    assert target.text_font_family == "Georgia"
    assert target.text_color == "#abcdef"
    assert target.text_stroke_width == 4


def test_copy_text_style_between_text_clips_only_copies_style():
    source = _text_clip(text_font_family="Impact", text_main="Source")
    target = _text_clip(text_font_family="Arial", text_main="Target")

    copy_text_style(source, target)

    assert target.text_main == "Target"
    assert target.text_font_family == "Impact"


def test_save_and_apply_text_style_preset(tmp_path):
    source = _text_clip(text_font_size=52, text_color="#123456")
    target = _text_clip(text_font_size=20, text_color="#ffffff")

    path = save_text_style_preset("Caption Pop", source, root=tmp_path)
    preset = apply_text_style_preset(target, "Caption Pop", root=tmp_path)

    assert path.exists()
    assert preset.name == "Caption Pop"
    assert target.text_font_size == 52
    assert target.text_color == "#123456"
    assert [item.name for item in list_text_style_presets(root=tmp_path)] == ["Caption Pop"]


def test_text_style_preset_rejects_media_clip():
    media = Clip(source="video.mp4", in_point=0.0, out_point=2.0, start=0.0)

    with pytest.raises(ValueError, match="text clips"):
        text_style_payload_from_clip(media)
