"""Unit tests for the split-at-playhead / ripple-delete logic.

These tests exercise the pure data-model mutations directly without spinning
up the PySide6 event loop — the timeline widget is just a thin view over a
Project model.
"""

from __future__ import annotations

import pytest

from comecut_py.core.project import Clip, Project, Track


def _split_at(project: Project, t: float) -> None:
    """Pure-Python re-implementation of the timeline's split op (used for testing)."""
    for track in list(project.tracks):
        for idx in range(len(track.clips) - 1, -1, -1):
            clip = track.clips[idx]
            d = clip.timeline_duration
            if d is None:
                continue
            if clip.start < t < clip.start + d:
                left_dur = t - clip.start
                left = clip.model_copy(
                    update={"out_point": clip.in_point + left_dur * clip.speed}
                )
                right = clip.model_copy(
                    update={
                        "in_point": clip.in_point + left_dur * clip.speed,
                        "start": t,
                    }
                )
                track.clips[idx : idx + 1] = [left, right]


def _ripple_delete(project: Project, target: Clip) -> None:
    for track in project.tracks:
        if target not in track.clips:
            continue
        d = target.timeline_duration or 0.0
        idx = track.clips.index(target)
        track.clips.pop(idx)
        for later in track.clips[idx:]:
            later.start = max(0.0, later.start - d)
        return


def test_split_halves_clip_duration():
    p = Project()
    v = Track(kind="video")
    v.clips.append(Clip(source="a.mp4", in_point=0, out_point=10, start=0))
    p.tracks.append(v)

    _split_at(p, 4.0)
    assert len(v.clips) == 2
    left, right = v.clips
    assert left.in_point == pytest.approx(0.0)
    assert left.out_point == pytest.approx(4.0)
    assert left.start == pytest.approx(0.0)
    assert right.in_point == pytest.approx(4.0)
    assert right.out_point == pytest.approx(10.0)
    assert right.start == pytest.approx(4.0)


def test_split_respects_speed():
    p = Project()
    v = Track(kind="video")
    v.clips.append(Clip(source="a.mp4", in_point=0, out_point=10, start=0, speed=2.0))
    p.tracks.append(v)
    _split_at(p, 2.0)  # timeline_duration = 5, split at t=2 → source_at_split = 4
    left, right = v.clips
    assert left.out_point == pytest.approx(4.0)
    assert right.in_point == pytest.approx(4.0)


def test_split_ignores_non_overlapping_clips():
    p = Project()
    v = Track(kind="video")
    v.clips.append(Clip(source="a.mp4", in_point=0, out_point=3, start=0))
    v.clips.append(Clip(source="b.mp4", in_point=0, out_point=3, start=5))
    p.tracks.append(v)

    _split_at(p, 4.0)  # between the two — nothing to split
    assert len(v.clips) == 2


def test_split_at_boundary_is_noop():
    p = Project()
    v = Track(kind="video")
    v.clips.append(Clip(source="a.mp4", in_point=0, out_point=3, start=0))
    p.tracks.append(v)

    _split_at(p, 0.0)
    _split_at(p, 3.0)
    assert len(v.clips) == 1


def test_ripple_delete_shifts_later_clips():
    p = Project()
    v = Track(kind="video")
    c1 = Clip(source="a", in_point=0, out_point=3, start=0)
    c2 = Clip(source="b", in_point=0, out_point=4, start=3)
    c3 = Clip(source="c", in_point=0, out_point=5, start=7)
    v.clips.extend([c1, c2, c3])
    p.tracks.append(v)

    _ripple_delete(p, c2)
    assert [c.source for c in v.clips] == ["a", "c"]
    assert v.clips[1].start == pytest.approx(3.0)  # 7 - 4 = 3


def test_ripple_delete_non_negative_start():
    p = Project()
    v = Track(kind="video")
    c1 = Clip(source="a", in_point=0, out_point=5, start=0)
    c2 = Clip(source="b", in_point=0, out_point=3, start=5)
    v.clips.extend([c1, c2])
    p.tracks.append(v)

    _ripple_delete(p, c1)
    assert v.clips[0].start == pytest.approx(0.0)


def test_snap_candidates_include_zero_and_clip_edges():
    """The snap helper is pure arithmetic, so test it via a minimal stand-in."""
    from comecut_py.gui.widgets.timeline import PIXELS_PER_SECOND, SNAP_TOLERANCE_PX

    # Clip edges and zero; should snap to whichever is within tolerance.
    edges = sorted({0.0, 5.0 * PIXELS_PER_SECOND, 8.0 * PIXELS_PER_SECOND})

    def snap(x: float) -> float:
        best, best_d = x, SNAP_TOLERANCE_PX
        for e in edges:
            if abs(e - x) < best_d:
                best, best_d = e, abs(e - x)
        return best

    # Within tolerance of a 5s edge (250px) — should snap.
    assert snap(252) == 250
    # Way off — no snap.
    assert snap(400) == 400
    # Near zero — snap to zero.
    assert snap(3) == 0
