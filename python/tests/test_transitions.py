from __future__ import annotations

import pytest

from comecut_py.core.project import Clip, Track, Transition
from comecut_py.core.transitions import (
    adjacent_pair_from_clips,
    clamp_transition_duration,
    find_transition,
    normalize_track_transitions,
    reindex_transitions_after_clip_delete,
    remove_track_transition,
    set_track_transition,
    transition_duration_limit,
)


def _clip(source: str, start: float, duration: float) -> Clip:
    return Clip(source=source, in_point=0.0, out_point=duration, start=start)


def test_set_track_transition_clamps_to_half_shorter_clip():
    track = Track(
        kind="video",
        clips=[
            _clip("a.mp4", 0.0, 10.0),
            _clip("b.mp4", 10.0, 0.6),
        ],
    )

    transition = set_track_transition(track, 0, kind="dissolve", duration=1.0)

    assert transition.kind == "dissolve"
    assert transition.from_index == 0
    assert transition.to_index == 1
    assert transition.duration == pytest.approx(0.3)
    assert transition_duration_limit(track, 0) == pytest.approx(0.3)
    assert clamp_transition_duration(track, 0, 0.01) == pytest.approx(0.05)


def test_set_track_transition_replaces_existing_from_index():
    track = Track(
        kind="video",
        clips=[
            _clip("a.mp4", 0.0, 2.0),
            _clip("b.mp4", 2.0, 2.0),
        ],
    )

    set_track_transition(track, 0, kind="fade", duration=0.4)
    set_track_transition(track, 0, kind="wipeleft", duration=0.2)

    assert len(track.transitions) == 1
    assert find_transition(track, 0) is not None
    assert track.transitions[0].kind == "wipeleft"
    assert track.transitions[0].duration == pytest.approx(0.2)


def test_remove_track_transition():
    track = Track(
        kind="video",
        clips=[
            _clip("a.mp4", 0.0, 2.0),
            _clip("b.mp4", 2.0, 2.0),
        ],
    )
    set_track_transition(track, 0)

    assert remove_track_transition(track, 0) is True
    assert remove_track_transition(track, 0) is False
    assert track.transitions == []


def test_adjacent_pair_from_clips_requires_same_track_and_adjacency():
    a = _clip("a.mp4", 0.0, 2.0)
    b = _clip("b.mp4", 2.0, 2.0)
    c = _clip("c.mp4", 4.0, 2.0)
    track = Track(kind="video", clips=[a, b, c])

    assert adjacent_pair_from_clips(track, [b, a]) == 0
    assert adjacent_pair_from_clips(track, [a, c]) is None
    assert adjacent_pair_from_clips(track, [a]) is None


def test_normalize_track_transitions_removes_invalid_and_clamps():
    track = Track(
        kind="video",
        clips=[
            _clip("a.mp4", 0.0, 2.0),
            _clip("b.mp4", 2.0, 0.4),
            _clip("c.mp4", 2.4, 2.0),
        ],
        transitions=[
            Transition(from_index=0, to_index=1, duration=1.0, kind="fade"),
            Transition(from_index=0, to_index=1, duration=0.1, kind="dissolve"),
            Transition(from_index=0, to_index=2, duration=0.2, kind="wipeleft"),
            Transition(from_index=9, to_index=10, duration=0.2, kind="fade"),
        ],
    )

    changed = normalize_track_transitions(track)

    assert changed is True
    assert len(track.transitions) == 1
    assert track.transitions[0].from_index == 0
    assert track.transitions[0].duration == pytest.approx(0.2)


def test_reindex_transitions_after_clip_delete_keeps_surviving_pairs():
    track = Track(
        kind="video",
        clips=[
            _clip("a.mp4", 0.0, 2.0),
            _clip("b.mp4", 2.0, 2.0),
            _clip("c.mp4", 4.0, 2.0),
            _clip("d.mp4", 6.0, 2.0),
        ],
        transitions=[
            Transition(from_index=0, to_index=1, duration=0.2, kind="fade"),
            Transition(from_index=2, to_index=3, duration=0.3, kind="dissolve"),
        ],
    )
    old_transitions = list(track.transitions)
    del track.clips[1]

    reindex_transitions_after_clip_delete(
        track,
        {1},
        old_transitions,
        old_clip_count=4,
    )

    assert len(track.transitions) == 1
    assert track.transitions[0].from_index == 1
    assert track.transitions[0].to_index == 2
    assert track.transitions[0].kind == "dissolve"
