from __future__ import annotations

import json
from pathlib import Path

import pytest

from comecut_py.core import import_capcut_draft, is_capcut_format
from comecut_py.core.project import Project
from comecut_py.core.store import load_project, save_project


REPO_ROOT = Path(__file__).resolve().parents[2]
CAPCUT_SAMPLE = REPO_ROOT / "draft_content.json"


def test_is_capcut_format_distinguishes_capcut_v2_and_legacy():
    capcut_data = json.loads(CAPCUT_SAMPLE.read_text(encoding="utf-8"))
    comecut_v2 = Project(name="V2").to_draft_dict()
    legacy = Project(name="Legacy").model_dump(mode="json")

    assert is_capcut_format(capcut_data) is True
    assert is_capcut_format(comecut_v2) is False
    assert is_capcut_format(legacy) is False


def test_import_capcut_sample_shape_and_text_fields():
    project = import_capcut_draft(CAPCUT_SAMPLE)

    assert len(project.tracks) == 4
    assert sum(len(track.clips) for track in project.tracks) == 25
    assert [(track.kind, len(track.clips)) for track in project.tracks] == [
        ("video", 1),
        ("text", 12),
        ("audio", 7),
        ("audio", 5),
    ]

    text_clip = project.tracks[1].clips[0]
    assert text_clip.text_main
    assert text_clip.text_color == "#ffffff"
    assert text_clip.text_font_size == 30
    assert text_clip.text_stroke_width == 8


def test_project_from_json_routes_capcut_v2_and_legacy(tmp_path: Path):
    capcut_project = Project.from_json(CAPCUT_SAMPLE)
    assert len(capcut_project.tracks) == 4

    v2_path = tmp_path / "draft_content.json"
    v2_path.write_text(
        json.dumps(Project(name="V2 Project").to_draft_dict()),
        encoding="utf-8",
    )
    assert Project.from_json(v2_path).name == "V2 Project"

    legacy_path = tmp_path / "current.json"
    Project(name="Legacy Project").to_json(legacy_path)
    assert Project.from_json(legacy_path).name == "Legacy Project"


def test_import_capcut_falls_back_to_target_duration(tmp_path: Path):
    draft = {
        "version": 360000,
        "new_version": "153.0.0",
        "name": "Fallbacks",
        "fps": 30.0,
        "canvas_config": {"width": 1280, "height": 720},
        "materials": {
            "videos": [{"id": "video-1", "path": "video.mp4"}],
            "audios": [{"id": "audio-1", "path": "audio.wav"}],
            "texts": [
                {
                    "id": "text-1",
                    "content": json.dumps({"text": "Hello"}),
                    "text_color": "#FFFFFF",
                    "text_size": 24,
                }
            ],
        },
        "tracks": [
            {
                "type": "video",
                "segments": [
                    {
                        "material_id": "video-1",
                        "source_timerange": {"start": 1_000_000},
                        "target_timerange": {"start": 0, "duration": 2_000_000},
                        "speed": 2.0,
                        "clip": {},
                    }
                ],
            },
            {
                "type": "audio",
                "segments": [
                    {
                        "material_id": "audio-1",
                        "source_timerange": {"start": 0},
                        "target_timerange": {"start": 0, "duration": 4_000_000},
                        "speed": 0.5,
                    }
                ],
            },
            {
                "type": "text",
                "segments": [
                    {
                        "material_id": "text-1",
                        "target_timerange": {"start": 0, "duration": 0},
                    }
                ],
            },
        ],
    }
    path = tmp_path / "draft_content.json"
    path.write_text(json.dumps(draft), encoding="utf-8")

    project = import_capcut_draft(path)

    assert project.tracks[0].clips[0].out_point == pytest.approx(5.0)
    assert project.tracks[1].clips[0].out_point == pytest.approx(2.0)
    assert project.tracks[2].clips[0].out_point == pytest.approx(0.001)


def test_imported_capcut_project_saves_and_loads_from_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("COMECUT_PY_HOME", str(tmp_path))
    project = import_capcut_draft(CAPCUT_SAMPLE)

    meta = save_project(project)
    loaded = load_project(meta.project_id)

    assert len(loaded.tracks) == len(project.tracks)
    assert sum(len(track.clips) for track in loaded.tracks) == 25
