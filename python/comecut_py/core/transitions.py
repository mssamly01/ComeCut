"""Helpers for local clip-to-clip transitions."""

from __future__ import annotations

from collections.abc import Sequence

from .project import Clip, Track, Transition, TransitionKind


DEFAULT_TRANSITION_DURATION = 0.5
MIN_TRANSITION_DURATION = 0.05


COMMON_TRANSITION_KINDS: tuple[TransitionKind, ...] = (
    "fade",
    "dissolve",
    "wipeleft",
    "wiperight",
    "slideleft",
    "slideright",
)


def _clip_duration(clip: Clip) -> float | None:
    duration = clip.timeline_duration
    if duration is None:
        return None
    return max(0.0, float(duration))


def transition_duration_limit(track: Track, from_index: int) -> float:
    """Return the maximum safe transition duration for adjacent clips."""
    if from_index < 0 or from_index + 1 >= len(track.clips):
        return 0.0
    left = _clip_duration(track.clips[from_index])
    right = _clip_duration(track.clips[from_index + 1])
    if left is None or right is None:
        return 0.0
    return max(0.0, min(left, right) * 0.5)


def clamp_transition_duration(
    track: Track,
    from_index: int,
    duration: float = DEFAULT_TRANSITION_DURATION,
) -> float:
    limit = transition_duration_limit(track, from_index)
    if limit < MIN_TRANSITION_DURATION:
        return 0.0
    requested = max(MIN_TRANSITION_DURATION, float(duration))
    return min(requested, limit)


def find_transition(track: Track, from_index: int) -> Transition | None:
    for transition in track.transitions:
        if int(transition.from_index) == int(from_index):
            return transition
    return None


def adjacent_pair_from_clips(track: Track, clips: Sequence[Clip]) -> int | None:
    """Return ``from_index`` if ``clips`` are exactly two adjacent track clips."""
    if len(clips) != 2:
        return None
    indices: list[int] = []
    for clip in clips:
        try:
            indices.append(track.clips.index(clip))
        except ValueError:
            return None
    indices.sort()
    if indices[1] != indices[0] + 1:
        return None
    return indices[0]


def set_track_transition(
    track: Track,
    from_index: int,
    *,
    kind: TransitionKind = "fade",
    duration: float = DEFAULT_TRANSITION_DURATION,
) -> Transition:
    """Add or replace a transition between ``from_index`` and the next clip."""
    if from_index < 0 or from_index + 1 >= len(track.clips):
        raise ValueError("Transition requires two adjacent clips")
    safe_duration = clamp_transition_duration(track, from_index, duration)
    if safe_duration <= 0.0:
        raise ValueError("Transition duration is longer than the adjacent clips")
    transition = Transition(
        from_index=from_index,
        to_index=from_index + 1,
        duration=safe_duration,
        kind=kind,
    )
    track.transitions = [
        existing
        for existing in track.transitions
        if int(existing.from_index) != int(from_index)
    ]
    track.transitions.append(transition)
    track.transitions.sort(key=lambda item: int(item.from_index))
    normalize_track_transitions(track)
    stored = find_transition(track, from_index)
    if stored is None:
        raise ValueError("Transition could not be stored")
    return stored


def remove_track_transition(track: Track, from_index: int) -> bool:
    before = len(track.transitions)
    track.transitions = [
        transition
        for transition in track.transitions
        if int(transition.from_index) != int(from_index)
    ]
    return len(track.transitions) != before


def normalize_track_transitions(track: Track) -> bool:
    """Remove invalid transitions and clamp durations after clip edits."""
    clean: list[Transition] = []
    seen: set[int] = set()
    changed = False
    for transition in sorted(track.transitions, key=lambda item: int(item.from_index)):
        from_index = int(transition.from_index)
        to_index = int(transition.to_index)
        if from_index in seen or to_index != from_index + 1:
            changed = True
            continue
        safe_duration = clamp_transition_duration(track, from_index, transition.duration)
        if safe_duration <= 0.0:
            changed = True
            continue
        seen.add(from_index)
        if abs(safe_duration - float(transition.duration)) > 1e-6:
            changed = True
            transition = transition.model_copy(update={"duration": safe_duration})
        clean.append(transition)
    if clean != track.transitions:
        changed = True
        track.transitions = clean
    return changed


def reindex_transitions_after_clip_delete(
    track: Track,
    removed_indices: set[int],
    old_transitions: Sequence[Transition],
    *,
    old_clip_count: int,
) -> bool:
    """Reindex transitions after deleting clips from ``track``.

    Transitions touching deleted clips are dropped. Transitions after the
    deleted range keep their relative clip pair.
    """
    mapping: dict[int, int] = {}
    new_index = 0
    for old_index in range(max(0, int(old_clip_count))):
        if old_index in removed_indices:
            continue
        mapping[old_index] = new_index
        new_index += 1

    clean: list[Transition] = []
    for transition in old_transitions:
        old_from = int(transition.from_index)
        old_to = int(transition.to_index)
        if old_from not in mapping or old_to not in mapping:
            continue
        new_from = mapping[old_from]
        new_to = mapping[old_to]
        if new_to != new_from + 1:
            continue
        clean.append(
            transition.model_copy(
                update={"from_index": new_from, "to_index": new_to}
            )
        )
    before = list(track.transitions)
    track.transitions = clean
    normalize_track_transitions(track)
    return track.transitions != before


__all__ = [
    "COMMON_TRANSITION_KINDS",
    "DEFAULT_TRANSITION_DURATION",
    "MIN_TRANSITION_DURATION",
    "adjacent_pair_from_clips",
    "clamp_transition_duration",
    "find_transition",
    "normalize_track_transitions",
    "reindex_transitions_after_clip_delete",
    "remove_track_transition",
    "set_track_transition",
    "transition_duration_limit",
]
