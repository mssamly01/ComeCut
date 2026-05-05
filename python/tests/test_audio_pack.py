"""Unit tests for the audio-pack features (PR C).

Covers:
* Per-clip ``ClipAudioEffects``: fade_in, fade_out, pitch_semitones,
  denoise, normalize — default no-op, validators, and emitted filter chain.
* Standalone ``duck`` engine command — sidechain graph shape.
* Standalone ``loudnorm_twopass`` engine command — JSON parsing helper.
"""

from __future__ import annotations

import pytest

from comecut_py.core.project import (
    Clip,
    ClipAudioEffects,
    Project,
    Track,
)
from comecut_py.engine import render_project
from comecut_py.engine.ducking import duck
from comecut_py.engine.loudnorm import _parse_loudnorm_json
from comecut_py.engine.render import _audio_effect_chain

# ---- ClipAudioEffects defaults & validators ---------------------------------


def test_clip_audio_effects_defaults_are_noops():
    afx = ClipAudioEffects()
    assert afx.fade_in == 0.0
    assert afx.fade_out == 0.0
    assert afx.pitch_semitones == 0.0
    assert afx.denoise is False
    assert afx.normalize is False


def test_clip_audio_effects_validators_reject_invalid():
    with pytest.raises(ValueError):
        ClipAudioEffects(fade_in=-1.0)
    with pytest.raises(ValueError):
        ClipAudioEffects(fade_out=-0.5)
    with pytest.raises(ValueError):
        ClipAudioEffects(pitch_semitones=99.0)
    with pytest.raises(ValueError):
        ClipAudioEffects(pitch_semitones=-99.0)


# ---- _audio_effect_chain filter emission ------------------------------------


def test_audio_chain_default_clip_emits_only_volume():
    clip = Clip(source="in.mp4", in_point=0, out_point=5)
    chain = _audio_effect_chain(clip)
    # Default clip has volume=1.0 and no audio effects; nothing else fires.
    assert chain == "volume=1.0"


def test_audio_chain_fade_in_emits_afade_t_in():
    clip = Clip(
        source="in.mp4", in_point=0, out_point=5,
        audio_effects=ClipAudioEffects(fade_in=0.5),
    )
    chain = _audio_effect_chain(clip)
    assert "afade=t=in:ss=0:d=0.5" in chain
    # Fade-out shouldn't appear when only fade-in is set.
    assert "t=out" not in chain


def test_audio_chain_fade_out_uses_timeline_duration():
    # timeline_duration for in=0, out=5, speed=1 is 5.0; a 1.0 s fade-out
    # starts at st=4.0.
    clip = Clip(
        source="in.mp4", in_point=0, out_point=5,
        audio_effects=ClipAudioEffects(fade_out=1.0),
    )
    chain = _audio_effect_chain(clip)
    assert "afade=t=out:st=4.0:d=1.0" in chain


def test_audio_chain_fade_out_skipped_when_duration_unknown():
    # Open-ended clip (no out_point) has timeline_duration=None. Emitting
    # afade=t=out:st=0:d=d there would silence ALL audio after `d`
    # seconds, so the filter must be skipped entirely in that case.
    clip = Clip(
        source="in.mp4", in_point=0, out_point=None,
        audio_effects=ClipAudioEffects(fade_out=0.5),
    )
    chain = _audio_effect_chain(clip)
    assert "afade=t=out" not in chain


def test_audio_chain_fade_out_with_speed_scales_start():
    # 4 s clip at 2x speed has effective timeline duration 2.0 s → 0.5 s
    # fade-out starts at st=1.5.
    clip = Clip(
        source="in.mp4", in_point=0, out_point=4, speed=2.0,
        audio_effects=ClipAudioEffects(fade_out=0.5),
    )
    chain = _audio_effect_chain(clip)
    assert "afade=t=out:st=1.5:d=0.5" in chain


def test_audio_chain_pitch_shift_emits_rubberband_as_ratio():
    # rubberband's ``pitch`` parameter is a frequency ratio, not semitones.
    # +12 semitones = one octave up = ratio 2.0; -12 = ratio 0.5.
    for semitones, expected_ratio in [(12.0, 2.0), (-12.0, 0.5), (0.01, 2.0 ** (0.01 / 12.0))]:
        clip = Clip(
            source="in.mp4", in_point=0, out_point=5,
            audio_effects=ClipAudioEffects(pitch_semitones=semitones),
        )
        chain = _audio_effect_chain(clip)
        assert f"rubberband=pitch={expected_ratio}" in chain, chain
        # Never emit a negative value — negative ratio is invalid and makes
        # ffmpeg fail to open the filter.
        assert "rubberband=pitch=-" not in chain


def test_audio_chain_denoise_pitch_normalize_order():
    clip = Clip(
        source="in.mp4", in_point=0, out_point=5,
        audio_effects=ClipAudioEffects(
            denoise=True, pitch_semitones=2.0, normalize=True,
        ),
    )
    chain = _audio_effect_chain(clip)
    # Order matters: denoise first so the noise floor is cleaned;
    # rubberband BEFORE loudnorm because loudnorm flushes frames on EOF
    # that rubberband rejects with "Cannot process again after final
    # chunk".
    i_afftdn = chain.index("afftdn")
    i_rubber = chain.index("rubberband")
    i_loud = chain.index("loudnorm")
    assert i_afftdn < i_rubber < i_loud


def test_audio_chain_all_effects_roundtrip_through_render_project():
    """A full project using every audio effect renders through the
    filter-complex graph — smoke check that nothing crashes during build."""
    clip = Clip(
        source="in.mp4", in_point=0, out_point=5,
        audio_effects=ClipAudioEffects(
            fade_in=0.25,
            fade_out=0.25,
            pitch_semitones=-2.0,
            denoise=True,
            normalize=True,
        ),
    )
    p = Project(width=320, height=180)
    p.tracks.append(Track(kind="audio", clips=[clip]))
    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "afftdn" in fc
    assert "loudnorm" in fc
    # -2 semitones → ratio 2**(-2/12) ≈ 0.8909
    assert f"rubberband=pitch={2.0 ** (-2.0 / 12.0)}" in fc
    assert "afade=t=in" in fc
    assert "afade=t=out" in fc


def test_audio_effects_roundtrip_through_json():
    p = Project(width=320, height=180)
    p.tracks.append(Track(kind="audio", clips=[
        Clip(
            source="in.mp4", in_point=0, out_point=5,
            audio_effects=ClipAudioEffects(
                fade_in=0.1, fade_out=0.2,
                pitch_semitones=1.5,
                denoise=True, normalize=True,
            ),
        ),
    ]))
    data = p.model_dump_json()
    p2 = Project.model_validate_json(data)
    afx = p2.tracks[0].clips[0].audio_effects
    assert afx.fade_in == 0.1
    assert afx.fade_out == 0.2
    assert afx.pitch_semitones == 1.5
    assert afx.denoise is True
    assert afx.normalize is True


# ---- duck() sidechain graph -------------------------------------------------


def test_duck_builds_sidechain_compress_graph():
    cmd = duck(
        "voice.wav", "music.wav", "out.wav",
        threshold=0.1, ratio=6.0,
        attack=10.0, release=200.0,
        makeup=1.5, mix=0.9,
    )
    argv = cmd.build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # Voice is split so the same stream can be sent to both the sidechain
    # key and the final mix.
    assert "[0:a]asplit=2" in fc
    # Music (input 1) is compressed using voice as the sidechain key.
    assert "sidechaincompress=threshold=0.1:ratio=6.0" in fc
    assert "attack=10.0:release=200.0" in fc
    assert "makeup=1.5:mix=0.9" in fc
    # Final amix combines the clean voice with the ducked music. It MUST
    # set ``normalize=0`` — the default ``normalize=1`` halves both
    # inputs, dropping the voice by 6 dB and defeating the whole point
    # of sidechain ducking.
    assert "amix=inputs=2" in fc
    assert "normalize=0" in fc


def test_duck_registers_both_inputs_in_correct_order():
    cmd = duck("/tmp/voice.wav", "/tmp/music.wav", "/tmp/mix.wav")
    argv = cmd.build(ffmpeg_bin="ffmpeg")
    # The voice must be input 0 and music input 1 because the sidechain
    # graph references ``[0:a]`` (voice) as the key and ``[1:a]`` (music)
    # as the duckee.
    i_indices = [i for i, a in enumerate(argv) if a == "-i"]
    assert len(i_indices) == 2
    assert argv[i_indices[0] + 1] == "/tmp/voice.wav"
    assert argv[i_indices[1] + 1] == "/tmp/music.wav"


# ---- loudnorm JSON parsing --------------------------------------------------


def test_parse_loudnorm_json_picks_last_block_with_input_i():
    # Simulated ffmpeg stderr with pre-filter noise and a final JSON block.
    stderr = """[Parsed_something_0 @ 0x] some log
ffmpeg version n4.4.2 copyright ...
[Parsed_loudnorm_0 @ 0x]
{
    "input_i" : "-23.42",
    "input_tp" : "-5.20",
    "input_lra" : "12.30",
    "input_thresh" : "-34.80",
    "output_i" : "-16.00",
    "output_tp" : "-1.50",
    "output_lra" : "11.00",
    "output_thresh" : "-27.00",
    "normalization_type" : "dynamic",
    "target_offset" : "0.05"
}
size=N/A time=00:00:03.00
"""
    data = _parse_loudnorm_json(stderr)
    assert data["input_i"] == "-23.42"
    assert data["target_offset"] == "0.05"


def test_parse_loudnorm_json_raises_when_missing():
    with pytest.raises(RuntimeError):
        _parse_loudnorm_json("no json here at all")
