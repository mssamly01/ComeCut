from __future__ import annotations

import pytest

from comecut_py.core.project import Clip, Project, Track, Transition
from comecut_py.engine import render_project


def _video_project_with_transitions() -> Project:
    p = Project(width=640, height=360, fps=24)
    v = Track(kind="video")
    v.clips.append(Clip(source="a.mp4", in_point=0, out_point=5, start=0))
    v.clips.append(Clip(source="b.mp4", in_point=0, out_point=5, start=4))  # 1s overlap
    v.transitions.append(Transition(from_index=0, to_index=1, duration=1.0, kind="fade"))
    p.tracks.append(v)
    return p


def test_transition_validation():
    with pytest.raises(ValueError):
        Transition(from_index=1, to_index=1, duration=1)
    with pytest.raises(ValueError):
        Transition(from_index=2, to_index=1, duration=1)
    with pytest.raises(ValueError):
        Transition(from_index=0, to_index=1, duration=0)


def test_transition_non_adjacent_rejected():
    p = Project()
    v = Track(kind="video")
    v.clips.append(Clip(source="a", in_point=0, out_point=3))
    v.clips.append(Clip(source="b", in_point=0, out_point=3, start=3))
    v.clips.append(Clip(source="c", in_point=0, out_point=3, start=6))
    v.transitions.append(Transition(from_index=0, to_index=2, duration=1))
    p.tracks.append(v)
    with pytest.raises(ValueError):
        render_project(p, "out.mp4")


def test_render_with_xfade_filter():
    p = _video_project_with_transitions()
    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "xfade=transition=fade:duration=1.0" in fc
    # Offset is (duration of first clip) - (transition duration) = 5 - 1 = 4
    assert "offset=4" in fc


def test_render_requires_out_point_for_transitions():
    p = Project()
    v = Track(kind="video")
    v.clips.append(Clip(source="a.mp4", in_point=0, out_point=None))
    v.clips.append(Clip(source="b.mp4", in_point=0, out_point=5, start=4))
    v.transitions.append(Transition(from_index=0, to_index=1, duration=1.0))
    p.tracks.append(v)
    with pytest.raises(ValueError, match="transitions need explicit clip durations"):
        render_project(p, "out.mp4")


def test_audio_transition_uses_acrossfade():
    p = Project()
    a = Track(kind="audio")
    a.clips.append(Clip(source="a.mp3", in_point=0, out_point=5, start=0))
    a.clips.append(Clip(source="b.mp3", in_point=0, out_point=5, start=4))
    a.transitions.append(Transition(from_index=0, to_index=1, duration=1.0))
    p.tracks.append(a)
    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "acrossfade=d=1.0" in fc


def _count_label_definitions(filter_complex: str) -> dict[str, int]:
    """Return a {label: count} map for every ``[name]`` label *definition*.

    A label is considered a definition when it appears as the last ``[...]``
    on a filter step (i.e. immediately before ``;`` or end-of-string).
    """
    import re

    counts: dict[str, int] = {}
    for step in filter_complex.split(";"):
        m = re.findall(r"\[([^\]]+)\](?=[^\]]*$)", step)
        for name in m:
            counts[name] = counts.get(name, 0) + 1
    return counts


def test_multiple_video_tracks_with_transitions_have_unique_labels():
    """Regression: ``vx_{i}``/``vshift_…`` labels used to collide across tracks."""
    p = Project(width=320, height=180, fps=24)
    for _ in range(2):
        v = Track(kind="video")
        v.clips.append(Clip(source="x.mp4", in_point=0, out_point=5, start=0))
        v.clips.append(Clip(source="y.mp4", in_point=0, out_point=5, start=4))
        v.transitions.append(Transition(from_index=0, to_index=1, duration=1.0))
        p.tracks.append(v)

    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    counts = _count_label_definitions(fc)
    duplicates = {k: v for k, v in counts.items() if v > 1}
    assert not duplicates, f"duplicate filter labels: {duplicates}"


def test_multiple_audio_tracks_with_transitions_have_unique_labels():
    p = Project()
    for _ in range(2):
        a = Track(kind="audio")
        a.clips.append(Clip(source="m.mp3", in_point=0, out_point=5, start=0))
        a.clips.append(Clip(source="n.mp3", in_point=0, out_point=5, start=4))
        a.transitions.append(Transition(from_index=0, to_index=1, duration=1.0))
        p.tracks.append(a)
    # Need at least one video track for render_project.
    v = Track(kind="video")
    v.clips.append(Clip(source="v.mp4", in_point=0, out_point=5, start=0))
    p.tracks.insert(0, v)

    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    counts = _count_label_definitions(fc)
    duplicates = {k: v for k, v in counts.items() if v > 1}
    assert not duplicates, f"duplicate filter labels: {duplicates}"


def test_render_without_transitions_still_works_with_gaps():
    p = Project()
    v = Track(kind="video")
    v.clips.append(Clip(source="a.mp4", in_point=0, out_point=3, start=0))
    v.clips.append(Clip(source="b.mp4", in_point=0, out_point=3, start=10))  # 7s gap
    p.tracks.append(v)
    # No transitions — per-clip overlay path. Must not raise.
    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "xfade" not in fc
    assert "overlay" in fc


def test_project_json_roundtrip_with_transitions(tmp_path):
    p = _video_project_with_transitions()
    path = tmp_path / "p.json"
    p.to_json(path)
    loaded = Project.from_json(path)
    assert len(loaded.tracks[0].transitions) == 1
    assert loaded.tracks[0].transitions[0].kind == "fade"
