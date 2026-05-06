from __future__ import annotations

import pytest

from comecut_py.core.effect_presets import (
    EFFECT_PRESET_SCHEMA,
    apply_effect_payload,
    apply_effect_preset,
    clip_effects_from_payload,
    copy_clip_effects,
    effect_payload_from_clip,
    list_effect_presets,
    save_effect_preset,
)
from comecut_py.core.project import ChromaKey, Clip, CropRect


def _media_clip(**overrides) -> Clip:
    data = {
        "source": "C:/media/video.mp4",
        "in_point": 1.0,
        "out_point": 5.0,
        "start": 2.0,
        "volume": 0.8,
    }
    data.update(overrides)
    return Clip(**data)


def _styled_clip() -> Clip:
    clip = _media_clip()
    clip.effects.blur = 3.5
    clip.effects.brightness = 0.2
    clip.effects.contrast = 1.4
    clip.effects.saturation = 0.7
    clip.effects.grayscale = True
    clip.effects.crop = CropRect(x=10, y=20, width=640, height=360)
    clip.effects.rotate = 12.0
    clip.effects.hflip = True
    clip.effects.vflip = False
    clip.effects.chromakey = ChromaKey(color="#00ff00", similarity=0.2, blend=0.05)
    return clip


def test_effect_payload_round_trips_clip_effects():
    clip = _styled_clip()

    payload = effect_payload_from_clip(clip)
    effects = clip_effects_from_payload(payload)

    assert payload["schema"] == EFFECT_PRESET_SCHEMA
    assert payload["blur"] == pytest.approx(3.5)
    assert payload["crop"] == {"x": 10, "y": 20, "width": 640, "height": 360}
    assert effects == clip.effects


def test_apply_effect_payload_preserves_clip_identity_and_timing():
    target = _media_clip(source="C:/keep/me.mp4", start=10.0, in_point=2.0, out_point=7.0)

    apply_effect_payload(target, effect_payload_from_clip(_styled_clip()))

    assert target.source == "C:/keep/me.mp4"
    assert target.start == pytest.approx(10.0)
    assert target.in_point == pytest.approx(2.0)
    assert target.out_point == pytest.approx(7.0)
    assert target.effects.blur == pytest.approx(3.5)
    assert target.effects.chromakey is not None
    assert target.effects.chromakey.similarity == pytest.approx(0.2)


def test_copy_clip_effects_between_media_clips_only_copies_effects():
    source = _styled_clip()
    target = _media_clip(source="C:/target.mp4")

    copy_clip_effects(source, target)

    assert target.source == "C:/target.mp4"
    assert target.effects == source.effects


def test_save_and_apply_effect_preset(tmp_path):
    source = _styled_clip()
    target = _media_clip()

    path = save_effect_preset("Soft Green Screen", source, root=tmp_path)
    preset = apply_effect_preset(target, "Soft Green Screen", root=tmp_path)

    assert path.exists()
    assert preset.name == "Soft Green Screen"
    assert target.effects == source.effects
    assert [item.name for item in list_effect_presets(root=tmp_path)] == [
        "Soft Green Screen"
    ]


def test_effect_preset_rejects_text_clip():
    text_clip = Clip(clip_type="text", source="", in_point=0.0, out_point=2.0, start=0.0)

    with pytest.raises(ValueError, match="media clips"):
        effect_payload_from_clip(text_clip)

    with pytest.raises(ValueError, match="media clips"):
        apply_effect_payload(text_clip, effect_payload_from_clip(_styled_clip()))


def test_effect_payload_rejects_invalid_values_and_schema():
    with pytest.raises(ValueError, match="Unsupported"):
        clip_effects_from_payload({"schema": "bad.schema"})

    with pytest.raises(ValueError, match="Invalid effect preset"):
        clip_effects_from_payload({"blur": -1.0})
