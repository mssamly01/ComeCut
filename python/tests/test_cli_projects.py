"""Tests for the `projects` and `batch` CLI subcommands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from comecut_py.cli import app
from comecut_py.core.project import Project
from comecut_py.core.store import default_store_dir, save_project


@pytest.fixture
def store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("COMECUT_PY_HOME", str(tmp_path))
    return tmp_path / "projects"


# ---- projects -----------------------------------------------------------


def test_projects_save_writes_to_store_and_prints_id(store_dir: Path, tmp_path: Path):
    src = tmp_path / "p.json"
    Project(name="From CLI").to_json(src)

    runner = CliRunner()
    result = runner.invoke(app, ["projects", "save", str(src)])
    assert result.exit_code == 0, result.output
    # Output is "<id>\t<name>\t<path>"
    pid = result.output.split()[0]
    assert (default_store_dir() / pid / "current.json").is_file()


def test_projects_save_renames_with_flag(store_dir: Path, tmp_path: Path):
    src = tmp_path / "p.json"
    Project(name="Original").to_json(src)

    runner = CliRunner()
    result = runner.invoke(
        app, ["projects", "save", str(src), "--name", "Renamed"]
    )
    assert result.exit_code == 0, result.output
    pid = result.output.split()[0]
    assert Project.from_json(
        default_store_dir() / pid / "current.json"
    ).name == "Renamed"


def test_projects_list_shows_saved_projects(store_dir: Path):
    save_project(Project(name="Alpha"))
    save_project(Project(name="Beta"))

    runner = CliRunner()
    result = runner.invoke(app, ["projects", "list"])
    assert result.exit_code == 0, result.output
    assert "Alpha" in result.output
    assert "Beta" in result.output


def test_projects_list_empty_message(store_dir: Path):
    runner = CliRunner()
    result = runner.invoke(app, ["projects", "list"])
    assert result.exit_code == 0
    assert "no projects" in result.output


def test_projects_open_prints_current_path(store_dir: Path):
    meta = save_project(Project(name="Open Me"))

    runner = CliRunner()
    result = runner.invoke(app, ["projects", "open", meta.project_id])
    assert result.exit_code == 0, result.output
    assert "current.json" in result.output


def test_projects_open_copies_to_out(store_dir: Path, tmp_path: Path):
    meta = save_project(Project(name="Copy Me"))
    dst = tmp_path / "copied.json"

    runner = CliRunner()
    result = runner.invoke(
        app, ["projects", "open", meta.project_id, "--out", str(dst)]
    )
    assert result.exit_code == 0, result.output
    assert dst.is_file()
    assert Project.from_json(dst).name == "Copy Me"


def test_projects_open_unknown_id_fails(store_dir: Path):
    runner = CliRunner()
    result = runner.invoke(app, ["projects", "open", "nope"])
    assert result.exit_code != 0


def test_projects_delete_removes_directory(store_dir: Path):
    meta = save_project(Project(name="Doomed"))
    assert (default_store_dir() / meta.project_id).is_dir()

    runner = CliRunner()
    result = runner.invoke(app, ["projects", "delete", meta.project_id])
    assert result.exit_code == 0, result.output
    assert not (default_store_dir() / meta.project_id).exists()


def test_projects_delete_unknown_id_fails(store_dir: Path):
    runner = CliRunner()
    result = runner.invoke(app, ["projects", "delete", "nope"])
    assert result.exit_code != 0


def test_projects_history_lists_versions(store_dir: Path):
    import time

    meta = save_project(Project(name="v0"))
    time.sleep(0.05)
    save_project(Project(name="v1"), project_id=meta.project_id)
    time.sleep(0.05)
    save_project(Project(name="v2"), project_id=meta.project_id)

    runner = CliRunner()
    result = runner.invoke(app, ["projects", "history", meta.project_id])
    assert result.exit_code == 0, result.output
    # Two snapshots on disk after three saves — assert by filename count
    # via the underlying API rather than by parsing rich-printed output
    # (rich may soft-wrap long paths over the 80-col test terminal).
    from comecut_py.core.store import list_versions
    assert len(list_versions(meta.project_id)) == 2


# ---- batch --------------------------------------------------------------


class _FakeProbe:
    duration = 2.5
    has_audio = True
    width = 1920
    height = 1080
    fps = 30.0


def test_batch_apply_effects_runs_per_input(store_dir: Path, tmp_path: Path):
    inputs = [tmp_path / f"in{i}.mp4" for i in range(3)]
    for p in inputs:
        p.write_bytes(b"fake")

    out_dir = tmp_path / "out"

    rendered: list[Path] = []

    class _FakeCmd:
        def build(self, ffmpeg_bin="ffmpeg"):
            return [ffmpeg_bin]

        def run(self, check=True):
            return 0

    def fake_render(project, dst):
        rendered.append(Path(dst))
        return _FakeCmd()

    runner = CliRunner()
    with (
        patch("comecut_py.cli.probe_media", return_value=_FakeProbe()),
        patch("comecut_py.cli.render_project", side_effect=fake_render),
    ):
        result = runner.invoke(app, [
            "batch", "apply-effects",
            str(inputs[0]), str(inputs[1]), str(inputs[2]),
            "-o", str(out_dir),
            "--blur", "1.5",
        ])
    assert result.exit_code == 0, result.output
    assert len(rendered) == 3
    assert {p.name for p in rendered} == {
        "in0_processed.mp4", "in1_processed.mp4", "in2_processed.mp4",
    }
    assert out_dir.is_dir()


def test_batch_apply_effects_keep_going_skips_failures(
    store_dir: Path, tmp_path: Path,
):
    inputs = [tmp_path / f"in{i}.mp4" for i in range(3)]
    for p in inputs:
        p.write_bytes(b"fake")

    out_dir = tmp_path / "out"

    class _FakeCmd:
        def build(self, ffmpeg_bin="ffmpeg"):
            return [ffmpeg_bin]

        def run(self, check=True):
            return 0

    seen: list[Path] = []

    def fake_render(project, dst):
        seen.append(Path(dst))
        if "in1" in str(dst):
            raise RuntimeError("boom")
        return _FakeCmd()

    runner = CliRunner()
    with (
        patch("comecut_py.cli.probe_media", return_value=_FakeProbe()),
        patch("comecut_py.cli.render_project", side_effect=fake_render),
    ):
        result = runner.invoke(app, [
            "batch", "apply-effects",
            str(inputs[0]), str(inputs[1]), str(inputs[2]),
            "-o", str(out_dir),
            "--keep-going",
        ])
    assert result.exit_code == 0, result.output
    assert len(seen) == 3
    assert "1 failed" in result.output


def test_batch_apply_effects_aborts_without_keep_going(
    store_dir: Path, tmp_path: Path,
):
    inputs = [tmp_path / f"in{i}.mp4" for i in range(3)]
    for p in inputs:
        p.write_bytes(b"fake")

    out_dir = tmp_path / "out"

    seen: list[Path] = []

    def fake_render(project, dst):
        seen.append(Path(dst))
        raise RuntimeError("boom")

    runner = CliRunner()
    with (
        patch("comecut_py.cli.probe_media", return_value=_FakeProbe()),
        patch("comecut_py.cli.render_project", side_effect=fake_render),
    ):
        result = runner.invoke(app, [
            "batch", "apply-effects",
            str(inputs[0]), str(inputs[1]), str(inputs[2]),
            "-o", str(out_dir),
        ])
    assert result.exit_code != 0
    assert len(seen) == 1  # aborted on first failure


def test_batch_render_uses_preset_extension(store_dir: Path, tmp_path: Path):
    project_a = tmp_path / "a.json"
    project_b = tmp_path / "b.json"
    Project(name="A").to_json(project_a)
    Project(name="B").to_json(project_b)

    out_dir = tmp_path / "out"
    rendered: list[Path] = []

    class _FakeCmd:
        def build(self, ffmpeg_bin="ffmpeg"):
            return [ffmpeg_bin]

        def run(self, check=True):
            return 0

    def fake_render(project, dst, *, preset=None, use_proxies=False):
        rendered.append(Path(dst))
        return _FakeCmd()

    runner = CliRunner()
    with patch("comecut_py.cli.render_project", side_effect=fake_render):
        result = runner.invoke(app, [
            "batch", "render",
            str(project_a), str(project_b),
            "-o", str(out_dir),
            "--preset", "webm",
        ])
    assert result.exit_code == 0, result.output
    assert {p.name for p in rendered} == {"a.webm", "b.webm"}


def test_batch_render_unknown_preset_fails(store_dir: Path, tmp_path: Path):
    project_a = tmp_path / "a.json"
    Project(name="A").to_json(project_a)

    runner = CliRunner()
    result = runner.invoke(app, [
        "batch", "render", str(project_a),
        "-o", str(tmp_path / "out"),
        "--preset", "nope",
    ])
    assert result.exit_code != 0
