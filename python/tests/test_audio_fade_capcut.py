from __future__ import annotations

import json
from pathlib import Path

import pytest

from comecut_py.core.capcut_exporter import export_to_capcut
from comecut_py.core.capcut_importer import import_capcut_draft
from comecut_py.core.project import Clip, Project, Track


def _make_audio_project(
    tmp_path: Path,
    *,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
) -> tuple[Project, Path]:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"\x00" * 1024)

    project = Project(name="FadeRT")
    track = Track(kind="audio", name="Music")
    clip = Clip(source=str(source), in_point=0.0, out_point=10.0, start=0.0)
    clip.audio_effects.fade_in = fade_in
    clip.audio_effects.fade_out = fade_out
    track.clips.append(clip)
    project.tracks.append(track)
    return project, source


def test_export_writes_audio_fade_pool(tmp_path: Path):
    project, _ = _make_audio_project(tmp_path, fade_in=1.5, fade_out=2.0)
    draft = tmp_path / "draft_content.json"
    export_to_capcut(project, draft)

    payload = json.loads(draft.read_text(encoding="utf-8"))
    pool = payload.get("materials", {}).get("audio_fades", [])
    assert len(pool) == 1
    fade = pool[0]
    assert fade["fade_in_duration"] == 1_500_000
    assert fade["fade_out_duration"] == 2_000_000


def test_no_fade_means_no_pool_entry(tmp_path: Path):
    project, _ = _make_audio_project(tmp_path)
    draft = tmp_path / "draft_content.json"
    export_to_capcut(project, draft)

    payload = json.loads(draft.read_text(encoding="utf-8"))
    assert payload.get("materials", {}).get("audio_fades", []) == []


def test_round_trip_preserves_fade(tmp_path: Path):
    project, _ = _make_audio_project(tmp_path, fade_in=0.5, fade_out=1.25)
    draft = tmp_path / "draft_content.json"
    export_to_capcut(project, draft)
    imported = import_capcut_draft(draft)

    found = None
    for track in imported.tracks:
        for clip in track.clips:
            if clip.audio_effects.fade_in or clip.audio_effects.fade_out:
                found = clip
                break
        if found is not None:
            break

    assert found is not None
    assert found.audio_effects.fade_in == pytest.approx(0.5)
    assert found.audio_effects.fade_out == pytest.approx(1.25)


def test_segment_extra_material_refs_includes_fade_id(tmp_path: Path):
    project, _ = _make_audio_project(tmp_path, fade_in=1.0, fade_out=0.0)
    draft = tmp_path / "draft_content.json"
    export_to_capcut(project, draft)

    payload = json.loads(draft.read_text(encoding="utf-8"))
    fade_ids = {item["id"] for item in payload["materials"]["audio_fades"]}

    found_ref = False
    for track in payload["tracks"]:
        for seg in track.get("segments", []):
            refs = seg.get("extra_material_refs") or []
            if any(ref in fade_ids for ref in refs):
                found_ref = True
                break
        if found_ref:
            break

    assert found_ref, "audio_fade material id was not referenced from any segment"
