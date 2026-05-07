"""Local adapter around the bundled capcut_generator reference project."""

from .adapter import (
    TimelineVoiceMatchInputs,
    TimelineVoiceMatchOptions,
    generate_voice_match_from_timeline,
    prepare_timeline_voice_match_inputs,
)

__all__ = [
    "TimelineVoiceMatchInputs",
    "TimelineVoiceMatchOptions",
    "generate_voice_match_from_timeline",
    "prepare_timeline_voice_match_inputs",
]
