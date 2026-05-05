"""Tests for voice changer preset registry + apply/detect."""
from __future__ import annotations

import pytest

from comecut_py.core.project import Clip, ClipAudioEffects
from comecut_py.core.voice_presets import (
    PRESETS,
    PRESETS_BY_ID,
    apply_preset,
    detect_preset_id,
)


def test_preset_registry_has_8_entries():
    assert len(PRESETS) == 8
    assert PRESETS[0].id == "none"
    assert all(p.id in PRESETS_BY_ID for p in PRESETS)


def test_preset_ids_are_unique():
    ids = [p.id for p in PRESETS]
    assert len(ids) == len(set(ids))


def test_apply_preset_writes_all_voice_fields():
    afx = ClipAudioEffects()
    apply_preset(afx, "kid_girl")
    assert afx.pitch_semitones == pytest.approx(5.0)
    assert afx.formant_shift == pytest.approx(3.0)
    assert afx.chorus_depth == pytest.approx(0.0)
    assert afx.voice_preset_id == "kid_girl"


def test_apply_preset_none_clears_voice_fields():
    afx = ClipAudioEffects(pitch_semitones=4.0, formant_shift=2.0, chorus_depth=0.5, voice_preset_id="kid_girl")
    apply_preset(afx, "none")
    assert afx.pitch_semitones == 0.0
    assert afx.formant_shift == 0.0
    assert afx.chorus_depth == 0.0
    assert afx.voice_preset_id == "none"


def test_apply_preset_unknown_id_is_treated_as_none():
    afx = ClipAudioEffects(pitch_semitones=4.0)
    apply_preset(afx, "made_up_preset")
    assert afx.pitch_semitones == 0.0
    assert afx.voice_preset_id == "none"


def test_apply_preset_does_not_touch_unrelated_fields():
    afx = ClipAudioEffects(denoise=True, fade_in=0.5, normalize=True)
    apply_preset(afx, "robot")
    assert afx.denoise is True
    assert afx.fade_in == pytest.approx(0.5)
    assert afx.normalize is True


def test_detect_preset_id_from_preset_field():
    afx = ClipAudioEffects(voice_preset_id="robot")
    assert detect_preset_id(afx) == "robot"


def test_detect_preset_id_from_numeric_match():
    afx = ClipAudioEffects(pitch_semitones=8.0, formant_shift=5.0)
    # voice_preset_id empty but matches helium numerically
    assert detect_preset_id(afx) == "helium"


def test_detect_preset_id_returns_empty_for_custom_values():
    afx = ClipAudioEffects(pitch_semitones=2.5)  # not any preset
    assert detect_preset_id(afx) == ""


def test_clip_audio_effects_defaults_voice_preset_empty():
    afx = ClipAudioEffects()
    assert afx.voice_preset_id == ""
    assert afx.formant_shift == 0.0
    assert afx.chorus_depth == 0.0


def test_apply_preset_to_clip_full_roundtrip():
    c = Clip(source="/x.mp4", in_point=0.0, out_point=5.0, start=0.0)
    apply_preset(c.audio_effects, "monster")
    dump = c.model_dump()
    c2 = Clip.model_validate(dump)
    assert c2.audio_effects.voice_preset_id == "monster"
    assert c2.audio_effects.pitch_semitones == pytest.approx(-7.0)
    assert detect_preset_id(c2.audio_effects) == "monster"


def test_render_chain_includes_chorus_when_depth_set():
    from comecut_py.engine.render import _audio_effect_chain
    c = Clip(source="/x.mp4", in_point=0.0, out_point=5.0, start=0.0)
    apply_preset(c.audio_effects, "robot")
    chain = _audio_effect_chain(c)
    assert "chorus=" in chain
    assert "rubberband=" in chain


def test_render_chain_uses_formant_when_only_formant_set():
    from comecut_py.engine.render import _audio_effect_chain
    c = Clip(source="/x.mp4", in_point=0.0, out_point=5.0, start=0.0)
    c.audio_effects.formant_shift = 3.0
    chain = _audio_effect_chain(c)
    assert "formantscale=" in chain


def test_voice_preset_round_trips_through_capcut_export_import(tmp_path):
    """Export with helium preset → re-import → preset must survive."""
    from comecut_py.core.project import Project, Track, Clip
    from comecut_py.core.voice_presets import apply_preset
    from comecut_py.core.capcut_exporter import export_to_capcut
    from comecut_py.core.capcut_importer import import_capcut_draft

    p = Project(name="VoiceRT")
    t = Track(kind="video", name="Main")
    # Need a real source file path so the importer can find the material
    src = tmp_path / "v.mp4"; src.write_bytes(b"x" * 100)
    c = Clip(source=str(src), in_point=0.0, out_point=5.0, start=0.0)
    apply_preset(c.audio_effects, "helium")
    t.clips.append(c)
    p.tracks.append(t)

    fp = tmp_path / "draft_content.json"
    export_to_capcut(p, fp)

    p2 = import_capcut_draft(fp)
    # Find the imported clip
    found = None
    for tr in p2.tracks:
        for cc in tr.clips:
            if cc.audio_effects.voice_preset_id:
                found = cc
                break
    assert found is not None, "voice_preset_id was lost on round-trip"
    assert found.audio_effects.voice_preset_id == "helium"
    assert found.audio_effects.pitch_semitones == pytest.approx(8.0)
    assert found.audio_effects.formant_shift == pytest.approx(5.0)
