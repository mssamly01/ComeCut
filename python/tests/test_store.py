"""Tests for the on-disk project store."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from comecut_py.core.project import Project
from comecut_py.core.store import (
    MAX_VERSIONS,
    default_store_dir,
    delete_project,
    list_projects,
    list_versions,
    load_project,
    save_project,
)


@pytest.fixture
def store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the per-user store under a tmp dir for the test."""
    monkeypatch.setenv("COMECUT_PY_HOME", str(tmp_path))
    return tmp_path / "projects"


def test_default_store_dir_honours_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("COMECUT_PY_HOME", str(tmp_path))
    assert default_store_dir() == tmp_path / "projects"


def test_default_store_dir_falls_back_to_xdg(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("COMECUT_PY_HOME", raising=False)
    p = default_store_dir()
    assert p.name == "projects"
    assert p.parent.name == "comecut-py"


def test_save_allocates_uuid_and_writes_current_json(store_dir: Path):
    p = Project(name="My Edit")
    meta = save_project(p)
    assert meta.project_id  # non-empty
    assert (store_dir / meta.project_id / "current.json").is_file()
    assert meta.name == "My Edit"
    # No history on first save — the very first ``current.json`` is the
    # current version, there's nothing to snapshot yet.
    assert meta.versions == 0


def test_save_creates_history_snapshot_on_overwrite(store_dir: Path):
    p1 = Project(name="v1")
    meta = save_project(p1)
    pid = meta.project_id

    # Tiny pause so the timestamped snapshot filename differs (the
    # filename collision fallback would still produce a unique path,
    # but a fresh second avoids exercising it).
    time.sleep(0.05)

    p2 = Project(name="v2")
    meta = save_project(p2, project_id=pid)
    assert meta.name == "v2"
    assert meta.versions == 1

    # ``current.json`` reflects v2; the historical snapshot reflects v1.
    assert load_project(pid).name == "v2"

    versions = list_versions(pid)
    assert len(versions) == 1
    assert Project.from_json(versions[0]).name == "v1"


def test_save_prunes_old_versions_beyond_keep(store_dir: Path):
    p = Project(name="v0")
    meta = save_project(p)
    pid = meta.project_id

    keep = 3
    for i in range(keep + 5):
        time.sleep(0.02)
        save_project(Project(name=f"v{i}"), project_id=pid, keep_versions=keep)

    versions = list_versions(pid)
    assert len(versions) == keep


def test_max_versions_default_is_ten():
    assert MAX_VERSIONS == 10


def test_list_projects_empty_returns_empty_list(store_dir: Path):
    assert list_projects() == []


def test_list_projects_sorts_newest_first(store_dir: Path):
    a = save_project(Project(name="A"))
    time.sleep(0.02)
    b = save_project(Project(name="B"))
    time.sleep(0.02)
    c = save_project(Project(name="C"))

    metas = list_projects()
    ids = [m.project_id for m in metas]
    assert ids == [c.project_id, b.project_id, a.project_id]


def test_load_project_round_trips(store_dir: Path):
    p = Project(name="Round trip", width=1280, height=720)
    meta = save_project(p)
    loaded = load_project(meta.project_id)
    assert loaded.name == "Round trip"
    assert loaded.width == 1280


def test_load_project_missing_raises(store_dir: Path):
    with pytest.raises(FileNotFoundError):
        load_project("not-a-real-id")


def test_delete_project_removes_directory(store_dir: Path):
    meta = save_project(Project(name="Doomed"))
    assert (store_dir / meta.project_id).is_dir()
    delete_project(meta.project_id)
    assert not (store_dir / meta.project_id).exists()


def test_delete_missing_raises(store_dir: Path):
    with pytest.raises(FileNotFoundError):
        delete_project("not-a-real-id")


def test_corrupt_project_dir_does_not_break_listing(store_dir: Path):
    good = save_project(Project(name="Good"))
    # A leftover dir with no current.json (e.g. a half-finished save)
    # should be silently ignored by list_projects.
    bogus = store_dir / "bogus"
    bogus.mkdir(parents=True)
    (bogus / "garbage.json").write_text("{}")

    metas = list_projects()
    ids = {m.project_id for m in metas}
    assert good.project_id in ids
    assert "bogus" not in ids


def test_meta_modified_iso_is_z_suffixed(store_dir: Path):
    meta = save_project(Project(name="iso"))
    assert meta.modified_iso.endswith("Z")
    assert "T" in meta.modified_iso
