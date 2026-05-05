from __future__ import annotations

import json

import pytest

from comecut_py.core.project import Clip, Project, TextOverlay, Track


def test_clip_duration_closed():
    c = Clip(source="a.mp4", in_point=2.0, out_point=5.0, start=0.0)
    assert c.source_duration == pytest.approx(3.0)
    assert c.timeline_duration == pytest.approx(3.0)


def test_clip_duration_open_ended():
    c = Clip(source="a.mp4", in_point=0.0, out_point=None)
    assert c.source_duration is None
    assert c.timeline_duration is None


def test_clip_speed_affects_timeline_duration():
    c = Clip(source="a.mp4", in_point=0.0, out_point=10.0, speed=2.0)
    assert c.timeline_duration == pytest.approx(5.0)


def test_clip_rejects_bad_out_point():
    with pytest.raises(ValueError):
        Clip(source="a", in_point=5, out_point=3)


def test_project_duration_empty():
    assert Project().duration == 0.0


def test_project_duration_from_clips_and_overlays():
    p = Project()
    t = Track(kind="video")
    t.clips.append(Clip(source="a", in_point=0, out_point=3, start=0))
    t.clips.append(Clip(source="b", in_point=0, out_point=4, start=5))
    t.overlays.append(TextOverlay(text="hi", start=0, end=12))
    p.tracks.append(t)
    assert p.duration == pytest.approx(12.0)


def test_text_clip_model_fields():
    c = Clip(
        clip_type="text",
        source="subs.srt",
        in_point=0.0,
        out_point=2.5,
        start=1.0,
        text_main="Hello",
        text_second="Xin chao",
        text_display="bilingual",
    )
    assert c.is_text_clip is True
    assert c.timeline_duration == pytest.approx(2.5)
    assert c.text_main == "Hello"


def test_project_json_roundtrip(tmp_path):
    p = Project(name="x", width=1280, height=720, fps=25)
    t = Track(kind="video")
    t.clips.append(Clip(source="a.mp4", in_point=0, out_point=5, start=0))
    p.tracks.append(t)
    path = tmp_path / "p.json"
    p.to_json(path)
    parsed = json.loads(path.read_text())
    assert parsed["name"] == "x"
    loaded = Project.from_json(path)
    assert loaded.width == 1280
    assert loaded.tracks[0].clips[0].source == "a.mp4"
