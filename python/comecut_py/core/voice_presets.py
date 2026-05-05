"""Voice changer presets — thin layer over :class:`ClipAudioEffects`.

Each preset is a frozen dataclass of audio-effect parameter overrides.
Click a preset in the inspector ⇒ all listed fields are written into the
clip's ``audio_effects``; non-listed fields stay untouched. Selecting
'none' clears every voice changer field back to defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .project import ClipAudioEffects


@dataclass(frozen=True)
class VoicePreset:
    """Static description of a preset card."""

    id: str
    label: str
    icon: str  # emoji or short glyph
    pitch_semitones: float = 0.0
    formant_shift: float = 0.0
    chorus_depth: float = 0.0


# Preset list — order = grid layout (4 cols × 2 rows).
PRESETS: tuple[VoicePreset, ...] = (
    VoicePreset(id="none",   label="Tắt",      icon="⊘"),
    VoicePreset(id="kid_girl", label="Bé gái", icon="👧",
                pitch_semitones=+5.0, formant_shift=+3.0),
    VoicePreset(id="robot",  label="Robot",    icon="🤖",
                pitch_semitones=-2.0, chorus_depth=0.6),
    VoicePreset(id="monster", label="Quái thú", icon="👹",
                pitch_semitones=-7.0, formant_shift=-3.0, chorus_depth=0.4),
    VoicePreset(id="kid_boy", label="Bé trai", icon="👦",
                pitch_semitones=+3.0, formant_shift=+2.0),
    VoicePreset(id="elder",  label="Già",      icon="👴",
                pitch_semitones=-3.0, formant_shift=-2.0),
    VoicePreset(id="helium", label="Helium",   icon="🎈",
                pitch_semitones=+8.0, formant_shift=+5.0),
    VoicePreset(id="lofi",   label="Lo-fi",    icon="📻",
                chorus_depth=0.3),
)

PRESETS_BY_ID: Mapping[str, VoicePreset] = {p.id: p for p in PRESETS}


def apply_preset(audio_effects: ClipAudioEffects, preset_id: str) -> None:
    """Mutate ``audio_effects`` in place to match the preset.

    ``preset_id='none'`` clears all voice-changer fields. Unknown ids are
    treated as ``'none'``. Safe to call when the clip has additional
    non-voice fields (denoise, normalize, fade) — those are untouched.
    """
    preset = PRESETS_BY_ID.get(preset_id, PRESETS_BY_ID["none"])
    audio_effects.pitch_semitones = preset.pitch_semitones
    audio_effects.formant_shift = preset.formant_shift
    audio_effects.chorus_depth = preset.chorus_depth
    audio_effects.voice_preset_id = preset.id


def detect_preset_id(audio_effects: ClipAudioEffects) -> str:
    """Best-effort: which preset, if any, currently matches the effects?

    Used after a CapCut import or a legacy project load where
    ``voice_preset_id`` may be empty but the numeric values match a known
    preset. Returns ``""`` (custom) if no exact match.
    """
    if audio_effects.voice_preset_id:
        return audio_effects.voice_preset_id
    for preset in PRESETS:
        if (
            abs(audio_effects.pitch_semitones - preset.pitch_semitones) < 0.01
            and abs(audio_effects.formant_shift - preset.formant_shift) < 0.01
            and abs(audio_effects.chorus_depth - preset.chorus_depth) < 0.01
        ):
            return preset.id
    return ""


__all__ = [
    "PRESETS",
    "PRESETS_BY_ID",
    "VoicePreset",
    "apply_preset",
    "detect_preset_id",
]
