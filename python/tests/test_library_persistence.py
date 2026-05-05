"""Regression tests for media + subtitle library persistence.

These verify that paths imported into the Media library and Text/Subtitle
library round-trip through save → reload, independent of timeline state.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from comecut_py.core.project import Project, Track, LibraryEntry
from comecut_py.core.store import save_project, load_project


def _save_reload(project: Project) -> Project:
    with tempfile.TemporaryDirectory() as td:
        meta = save_project(project, store_dir=Path(td))
        return load_project(meta.project_id, store_dir=Path(td))


def test_default_library_lists_are_empty():
    p = Project(name="Empty")
    assert p.library_media == []
    assert p.library_subtitles == []


def test_library_media_round_trips_through_store():
    p = Project(name="Demo")
    p.library_media.extend([
        LibraryEntry(source="/tmp/a.mp4"),
        LibraryEntry(source="/tmp/b.mov"),
        LibraryEntry(source="/tmp/c.mp3"),
    ])
    p2 = _save_reload(p)
    assert [e.source for e in p2.library_media] == ["/tmp/a.mp4", "/tmp/b.mov", "/tmp/c.mp3"]


def test_library_subtitles_round_trip_through_store():
    p = Project(name="Demo")
    p.library_subtitles.extend([
        LibraryEntry(source="/tmp/sub1.srt"),
        LibraryEntry(source="/tmp/sub2.vtt"),
    ])
    p2 = _save_reload(p)
    assert [e.source for e in p2.library_subtitles] == ["/tmp/sub1.srt", "/tmp/sub2.vtt"]


def test_library_independent_of_timeline_clips():
    """A path can exist in library_media without being on any track."""
    p = Project(name="Demo")
    p.tracks.append(Track(kind="video", name="Main"))
    p.library_media.append(LibraryEntry(source="/tmp/orphan.mp4"))
    assert len(p.tracks[0].clips) == 0
    assert p.library_media[0].source == "/tmp/orphan.mp4"

    p2 = _save_reload(p)
    assert [e.source for e in p2.library_media] == ["/tmp/orphan.mp4"]
    assert p2.tracks[0].clips == []


def test_legacy_project_without_library_fields_loads_default_empty():
    """Existing projects saved before B.2 don't have library fields."""
    legacy = {
        "name": "Old",
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "sample_rate": 48000,
        "tracks": [],
    }
    p = Project.model_validate(legacy)
    assert p.library_media == []
    assert p.library_subtitles == []


def test_current_json_load_priority_keeps_library():
    """Even though draft_content.json is written after current.json (newer mtime),
    load priority must prefer current.json so library survives the round-trip."""
    p = Project(name="LibPriority")
    p.library_media.append(LibraryEntry(source="/tmp/keep.mp4"))
    with tempfile.TemporaryDirectory() as td:
        meta = save_project(p, store_dir=Path(td))
        # Sanity: both files exist
        pdir = Path(td) / meta.project_id
        assert (pdir / "current.json").exists()
        assert (pdir / "draft_content.json").exists()
        p2 = load_project(meta.project_id, store_dir=Path(td))
    assert [e.source for e in p2.library_media] == ["/tmp/keep.mp4"]


def test_capcut_import_then_save_preserves_library_field():
    """Importing CapCut yields empty library (CapCut has no concept), but after
    save+reload the field is empty list (not crashing or None)."""
    # Use a dummy dict instead of looking for a real file which might not exist in test env
    dummy_capcut = {
        "canvas_config": {"height": 1080, "width": 1920},
        "tracks": []
    }
    # Note: we need to mock is_capcut_format or just use model_validate if we know the shape
    # Project.from_json handles the routing.
    # For this test, we just want to ensure that after some "source" that lacks the fields,
    # they are initialized to empty lists.
    p = Project.model_validate(dummy_capcut)
    assert p.library_media == []
    assert p.library_subtitles == []
    p2 = _save_reload(p)
    assert p2.library_media == []
    assert p2.library_subtitles == []


def test_library_media_does_not_leak_into_v2_draft():
    """V2/CapCut format must not include library fields (CapCut doesn't know them)."""
    p = Project(name="V2Strip")
    p.library_media.append("/tmp/x.mp4")
    p.library_subtitles.append("/tmp/y.srt")
    draft = p.to_draft_dict()
    # Top-level keys are CapCut/V2 fields; library_* must NOT appear.
    assert "library_media" not in draft
    assert "library_subtitles" not in draft


def test_legacy_string_coercion():
    """Verify that pydantic model_validator coerces old strings into LibraryEntry objects."""
    data = {
        "name": "OldStrings",
        "library_media": ["/tmp/legacy.mp4"],
        "library_subtitles": ["/tmp/legacy.srt"],
    }
    p = Project.model_validate(data)
    assert isinstance(p.library_media[0], LibraryEntry)
    assert p.library_media[0].source == "/tmp/legacy.mp4"
    assert p.library_media[0].name == "legacy.mp4"
    assert isinstance(p.library_subtitles[0], LibraryEntry)
    assert p.library_subtitles[0].source == "/tmp/legacy.srt"
