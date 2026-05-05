"""On-disk project store — auto-save, versioning, listing, and recall.

Projects are persisted under a per-user data directory (default
``~/.local/share/comecut-py/projects``, overridable with the
``COMECUT_PY_HOME`` environment variable). Each project lives in its
own ``<uuid>/`` directory:

::

    ~/.local/share/comecut-py/projects/
    └── 7f1c…/
        ├── current.json          # latest legacy version
        ├── draft_content.json    # latest V2/CapCut-style version
        └── versions/
            ├── 20240101T120000.json
            └── 20240101T120532.json
            └── … (oldest pruned beyond MAX_VERSIONS)

The store is intentionally minimal: it does not own the in-memory
project lifecycle, it only provides a filesystem layout + a save/load
API that the CLI and any future GUI auto-save loop can call. The
project's own ``Project.name`` field is used as the human-readable
display name; the directory's UUID is the stable identifier.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .project import Project

MAX_VERSIONS: int = 10
"""Number of historical snapshots kept per project before the oldest is pruned."""

_ENV_VAR = "COMECUT_PY_HOME"
_DRAFT_CONTENT_FILENAME = "draft_content.json"


def default_store_dir() -> Path:
    """Return the default on-disk project root.

    Honours ``$COMECUT_PY_HOME`` (full path to the data directory) so
    tests can redirect storage to a temp dir without monkey-patching.
    """
    override = os.environ.get(_ENV_VAR)
    if override:
        return Path(override).expanduser() / "projects"
    # XDG-ish path on Linux; the same path works fine on macOS/Windows
    # for this use-case (we don't write anywhere else).
    return Path.home() / ".local" / "share" / "comecut-py" / "projects"


@dataclass(frozen=True)
class ProjectMeta:
    """Lightweight metadata for one stored project (no clip data)."""

    project_id: str
    name: str
    path: Path
    modified: float  # POSIX timestamp of the preferred project JSON
    versions: int  # number of files under ``versions/``

    @property
    def modified_iso(self) -> str:
        return (
            datetime.fromtimestamp(self.modified, tz=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )


def _project_dir(store_dir: Path, project_id: str) -> Path:
    return store_dir / project_id


def _versions_dir(project_dir: Path) -> Path:
    return project_dir / "versions"


def _current_path(project_dir: Path) -> Path:
    return project_dir / "current.json"


def _draft_content_path(project_dir: Path) -> Path:
    return project_dir / _DRAFT_CONTENT_FILENAME


def _project_json_candidates(project_dir: Path) -> list[Path]:
    """Return load order for project JSON files.

    ``current.json`` is the canonical legacy format and the strict superset
    (it carries fields V2 doesn't model, e.g. library cards). Always prefer
    it when present. Fall back to ``draft_content.json`` only when current
    is missing (e.g. a CapCut import that hasn't been saved yet).
    """
    current = _current_path(project_dir)
    draft = _draft_content_path(project_dir)
    if current.exists():
        return [current, draft]
    if draft.exists():
        return [draft]
    return []


def _new_version_path(project_dir: Path) -> Path:
    """Pick a fresh timestamped filename in ``versions/``.

    Uses UTC down to the second; if two saves land in the same second
    we append a counter so existing snapshots are never clobbered.
    """
    versions = _versions_dir(project_dir)
    versions.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
    candidate = versions / f"{stamp}.json"
    counter = 1
    while candidate.exists():
        candidate = versions / f"{stamp}-{counter}.json"
        counter += 1
    return candidate


def _prune_old_versions(project_dir: Path, keep: int = MAX_VERSIONS) -> None:
    versions = _versions_dir(project_dir)
    if not versions.is_dir():
        return
    snapshots = sorted(versions.glob("*.json"), key=lambda p: p.stat().st_mtime)
    excess = len(snapshots) - keep
    for old in snapshots[:max(0, excess)]:
        old.unlink(missing_ok=True)


def save_project(
    project: Project,
    *,
    project_id: str | None = None,
    store_dir: Path | None = None,
    keep_versions: int = MAX_VERSIONS,
) -> ProjectMeta:
    """Persist ``project`` and return the resulting metadata.

    A new ``project_id`` is allocated on the first save. Subsequent
    saves to the same ``project_id`` overwrite legacy ``current.json``,
    best-effort write V2 ``draft_content.json``, and drop a fresh snapshot
    under ``versions/``; the oldest snapshots are pruned beyond
    ``keep_versions``.
    """
    store_dir = store_dir or default_store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)

    if project_id is None:
        project_id = uuid.uuid4().hex

    project_dir = _project_dir(store_dir, project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot before overwriting current.json so the history reflects
    # the pre-save state. We write current.json afterwards so a crash
    # in the middle still leaves a recoverable snapshot.
    if _current_path(project_dir).exists():
        snapshot = _new_version_path(project_dir)
        shutil.copy2(_current_path(project_dir), snapshot)
        _prune_old_versions(project_dir, keep=keep_versions)

    project.to_json(_current_path(project_dir))
    with contextlib.suppress(Exception):
        project.to_draft_json(_draft_content_path(project_dir))

    return _read_meta(project_id, project_dir)


def load_project(
    project_id: str,
    *,
    store_dir: Path | None = None,
) -> Project:
    store_dir = store_dir or default_store_dir()
    project_dir = _project_dir(store_dir, project_id)
    if not project_dir.is_dir():
        raise FileNotFoundError(f"no project with id {project_id!r} under {store_dir}")
    last_error: Exception | None = None
    for path in _project_json_candidates(project_dir):
        if not path.is_file():
            continue
        try:
            return Project.from_json(path)
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise FileNotFoundError(
        f"project {project_id!r} has neither current.json nor {_DRAFT_CONTENT_FILENAME}"
    )


def delete_project(
    project_id: str,
    *,
    store_dir: Path | None = None,
) -> None:
    store_dir = store_dir or default_store_dir()
    project_dir = _project_dir(store_dir, project_id)
    if not project_dir.exists():
        raise FileNotFoundError(f"no project with id {project_id!r} under {store_dir}")
    shutil.rmtree(project_dir)


def list_projects(
    *,
    store_dir: Path | None = None,
) -> list[ProjectMeta]:
    """Return every project under ``store_dir``, newest-modified first."""
    store_dir = store_dir or default_store_dir()
    if not store_dir.is_dir():
        return []
    metas: list[ProjectMeta] = []
    for entry in store_dir.iterdir():
        if (
            not entry.is_dir()
            or (
                not _current_path(entry).is_file()
                and not _draft_content_path(entry).is_file()
            )
        ):
            continue
        try:
            metas.append(_read_meta(entry.name, entry))
        except Exception:
            # Corrupt entries (e.g. half-finished saves with garbage JSON)
            # must not crash the listing — skip them silently.
            continue
    metas.sort(key=lambda m: m.modified, reverse=True)
    return metas


def list_versions(
    project_id: str,
    *,
    store_dir: Path | None = None,
) -> list[Path]:
    """Return historical snapshot paths for ``project_id``, oldest first."""
    store_dir = store_dir or default_store_dir()
    project_dir = _project_dir(store_dir, project_id)
    versions = _versions_dir(project_dir)
    if not versions.is_dir():
        return []
    return sorted(versions.glob("*.json"), key=lambda p: p.stat().st_mtime)


def _read_meta(project_id: str, project_dir: Path) -> ProjectMeta:
    target: Path | None = None
    name = "Untitled"
    for path in _project_json_candidates(project_dir):
        if not path.is_file():
            continue
        if target is None:
            target = path
        try:
            project = Project.from_json(path)
        except Exception:
            continue
        target = path
        name = project.name
        break
    versions = _versions_dir(project_dir)
    n_versions = len(list(versions.glob("*.json"))) if versions.is_dir() else 0
    return ProjectMeta(
        project_id=project_id,
        name=name,
        path=project_dir,
        modified=target.stat().st_mtime if target and target.exists() else time.time(),
        versions=n_versions,
    )


__all__ = [
    "MAX_VERSIONS",
    "ProjectMeta",
    "default_store_dir",
    "delete_project",
    "list_projects",
    "list_versions",
    "load_project",
    "save_project",
]
