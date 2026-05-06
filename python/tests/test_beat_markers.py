from __future__ import annotations

import pytest

from comecut_py.core.beat_markers import (
    add_beat_marker,
    beat_marker_times,
    remove_near_beat_marker,
)
from comecut_py.core.project import Project


def test_add_beat_marker_sorts_and_dedupes():
    project = Project()

    add_beat_marker(project, 2.0, label="Beat 2")
    add_beat_marker(project, 1.0, label="Beat 1")
    add_beat_marker(project, 2.0004, label="Beat 2 renamed")

    assert beat_marker_times(project) == [1.0, 2.0]
    assert project.beat_markers[1].label == "Beat 2 renamed"


def test_remove_near_beat_marker():
    project = Project()
    add_beat_marker(project, 1.0)
    add_beat_marker(project, 2.0)

    assert remove_near_beat_marker(project, 2.03, tolerance=0.05) is True
    assert beat_marker_times(project) == [1.0]
    assert remove_near_beat_marker(project, 4.0, tolerance=0.05) is False


def test_beat_markers_round_trip_json(tmp_path):
    project = Project()
    add_beat_marker(project, 1.25, label="Kick", source="detected")
    path = tmp_path / "project.json"

    project.to_json(path)
    loaded = Project.from_json(path)

    assert len(loaded.beat_markers) == 1
    assert loaded.beat_markers[0].time == pytest.approx(1.25)
    assert loaded.beat_markers[0].label == "Kick"
    assert loaded.beat_markers[0].source == "detected"
