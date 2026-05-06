from __future__ import annotations

import pytest

from comecut_py.core.project import Clip, Project, Track
from comecut_py.core.project_templates import (
    PROJECT_TEMPLATE_SCHEMA,
    list_project_templates,
    new_project_from_template,
    project_from_template_payload,
    project_template_payload_from_project,
    save_project_template,
)


def test_project_template_payload_excludes_clips_library_and_markers():
    clip = Clip(source="video.mp4", in_point=0.0, out_point=3.0, start=0.0)
    project = Project(
        name="Source",
        width=1080,
        height=1920,
        fps=60.0,
        tracks=[
            Track(kind="video", name="Main", clips=[clip]),
            Track(kind="audio", name="Music", role="music", volume=0.6, muted=True),
        ],
    )
    project.beat_markers = []

    payload = project_template_payload_from_project(project)

    assert payload["schema"] == PROJECT_TEMPLATE_SCHEMA
    assert payload["width"] == 1080
    assert payload["height"] == 1920
    assert payload["fps"] == pytest.approx(60.0)
    assert payload["tracks"][0]["name"] == "Main"
    assert "clips" not in payload["tracks"][0]
    assert "library_media" not in payload
    assert "beat_markers" not in payload


def test_project_from_template_payload_creates_empty_track_layout():
    payload = {
        "schema": PROJECT_TEMPLATE_SCHEMA,
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "sample_rate": 44100,
        "tracks": [
            {"kind": "video", "name": "Main"},
            {"kind": "audio", "name": "Voice", "role": "voice", "volume": 0.8},
            {"kind": "text", "name": "Captions", "hidden": True},
        ],
    }

    project = project_from_template_payload(payload, name="New Short")

    assert project.name == "New Short"
    assert project.width == 1080
    assert project.height == 1920
    assert project.sample_rate == 44100
    assert [(track.kind, track.name) for track in project.tracks] == [
        ("video", "Main"),
        ("audio", "Voice"),
        ("text", "Captions"),
    ]
    assert all(track.clips == [] for track in project.tracks)
    assert project.tracks[1].role == "voice"
    assert project.tracks[2].hidden is True


def test_project_template_save_list_and_new_project(tmp_path):
    project = Project(
        name="Template Source",
        tracks=[
            Track(kind="video", name="Main"),
            Track(kind="audio", name="Music", role="music"),
        ],
    )

    path = save_project_template("Vertical Podcast", project, root=tmp_path)
    created = new_project_from_template(
        "Vertical Podcast",
        project_name="Episode 01",
        root=tmp_path,
    )

    assert path.exists()
    assert [preset.name for preset in list_project_templates(root=tmp_path)] == [
        "Vertical Podcast"
    ]
    assert created.name == "Episode 01"
    assert len(created.tracks) == 2
    assert created.tracks[1].role == "music"
    assert created.tracks[1].clips == []


def test_project_template_payload_rejects_bad_tracks():
    with pytest.raises(ValueError, match="tracks"):
        project_from_template_payload({"tracks": "bad"})

    with pytest.raises(ValueError, match="track entries"):
        project_from_template_payload({"tracks": ["bad"]})
