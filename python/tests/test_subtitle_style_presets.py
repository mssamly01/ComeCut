from __future__ import annotations

import pytest

from comecut_py.core.subtitle_style_presets import (
    SUBTITLE_STYLE_SCHEMA,
    list_subtitle_style_presets,
    load_subtitle_style_from_preset,
    merge_subtitle_force_styles,
    save_subtitle_style_preset,
    subtitle_style_from_payload,
    subtitle_style_payload_from_style,
)
from comecut_py.subtitles import SubtitleStyle


def test_subtitle_style_payload_round_trips_explicit_fields(tmp_path):
    style = SubtitleStyle(
        font_name="Arial",
        font_size=32,
        primary_colour="#FFFF00",
        outline_colour="#000000",
        bold=True,
        italic=False,
        outline=1.5,
        shadow=0.0,
        border_style=1,
        alignment="bottom-center",
        margin_v=42,
    )

    payload = subtitle_style_payload_from_style(style)
    path = save_subtitle_style_preset("Clean Subs", style, root=tmp_path)
    loaded = load_subtitle_style_from_preset("Clean Subs", root=tmp_path)

    assert payload["schema"] == SUBTITLE_STYLE_SCHEMA
    assert path.exists()
    assert loaded == style
    assert [preset.name for preset in list_subtitle_style_presets(root=tmp_path)] == [
        "Clean Subs"
    ]


def test_subtitle_style_from_payload_coerces_json_values():
    style = subtitle_style_from_payload(
        {
            "font_size": "28",
            "bold": "yes",
            "outline": "2.5",
            "border_style": "3",
            "alignment": "8",
            "margin_l": "10",
        }
    )

    assert style.font_size == 28
    assert style.bold is True
    assert style.outline == pytest.approx(2.5)
    assert style.border_style == 3
    assert style.alignment == 8
    assert style.margin_l == 10


def test_subtitle_style_from_payload_rejects_invalid_values():
    with pytest.raises(ValueError, match="border_style"):
        subtitle_style_from_payload({"border_style": 2})

    with pytest.raises(ValueError, match="alignment"):
        subtitle_style_from_payload({"alignment": 12})


def test_merge_subtitle_force_styles_keeps_override_order():
    preset = SubtitleStyle(font_size=24, primary_colour="#FFFFFF")
    typed = SubtitleStyle(font_size=40, outline=2)

    merged = merge_subtitle_force_styles(preset, typed, "Fontsize=52")

    assert merged is not None
    assert merged.index("Fontsize=24") < merged.index("Fontsize=40")
    assert merged.endswith("Fontsize=52")
