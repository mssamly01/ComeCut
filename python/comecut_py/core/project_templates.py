"""Local project template helpers.

Project templates intentionally store only reusable structure: canvas settings
and empty track layout. They never copy media clips, library entries, beat
markers, or external paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .local_presets import (
    LocalPreset,
    list_local_presets,
    load_local_preset,
    save_local_preset,
)
from .project import Project, Track


PROJECT_TEMPLATE_SCHEMA = "comecut.project_template.v1"
PROJECT_TEMPLATE_TRACK_FIELDS = (
    "kind",
    "name",
    "locked",
    "hidden",
    "muted",
    "volume",
    "role",
)


def _track_template_payload(track: Track) -> dict[str, Any]:
    return {
        "kind": track.kind,
        "name": track.name,
        "locked": bool(track.locked),
        "hidden": bool(track.hidden),
        "muted": bool(track.muted),
        "volume": float(track.volume),
        "role": str(track.role),
    }


def project_template_payload_from_project(project: Project) -> dict[str, Any]:
    """Build a JSON-safe template payload from project structure only."""
    tracks = [_track_template_payload(track) for track in project.tracks]
    if not tracks:
        tracks = [_track_template_payload(Track(kind="video", name="Main"))]
    return {
        "schema": PROJECT_TEMPLATE_SCHEMA,
        "width": int(project.width),
        "height": int(project.height),
        "fps": float(project.fps),
        "sample_rate": int(project.sample_rate),
        "tracks": tracks,
    }


def project_from_template_payload(
    payload: dict[str, Any],
    *,
    name: str = "Untitled",
) -> Project:
    """Create a new empty project from a local template payload."""
    if not isinstance(payload, dict):
        raise TypeError("Project template payload must be a JSON object")
    schema = payload.get("schema")
    if schema is not None and schema != PROJECT_TEMPLATE_SCHEMA:
        raise ValueError(f"Unsupported project template schema: {schema!r}")

    raw_tracks = payload.get("tracks", [])
    if not isinstance(raw_tracks, list):
        raise ValueError("Project template tracks must be a list")
    tracks: list[Track] = []
    for raw in raw_tracks:
        if not isinstance(raw, dict):
            raise ValueError("Project template track entries must be JSON objects")
        data: dict[str, Any] = {}
        for field in PROJECT_TEMPLATE_TRACK_FIELDS:
            if field not in raw:
                continue
            value = raw.get(field)
            if value is not None:
                data[field] = value
        data["clips"] = []
        data["overlays"] = []
        data["image_overlays"] = []
        data["transitions"] = []
        tracks.append(Track.model_validate(data))
    if not tracks:
        tracks.append(Track(kind="video", name="Main"))

    return Project(
        name=(name or "Untitled").strip() or "Untitled",
        width=int(payload.get("width") or 1920),
        height=int(payload.get("height") or 1080),
        fps=float(payload.get("fps") or 30.0),
        sample_rate=int(payload.get("sample_rate") or 48_000),
        tracks=tracks,
    )


def save_project_template(
    name: str,
    project: Project,
    *,
    root: Path | None = None,
) -> Path:
    return save_local_preset(
        "project",
        name,
        project_template_payload_from_project(project),
        root=root,
    )


def load_project_template(name: str, *, root: Path | None = None) -> LocalPreset:
    return load_local_preset("project", name, root=root)


def list_project_templates(*, root: Path | None = None) -> list[LocalPreset]:
    return list_local_presets("project", root=root)


def new_project_from_template(
    template_name: str,
    *,
    project_name: str | None = None,
    root: Path | None = None,
) -> Project:
    preset = load_project_template(template_name, root=root)
    return project_from_template_payload(
        preset.payload,
        name=project_name or preset.name,
    )


__all__ = [
    "PROJECT_TEMPLATE_SCHEMA",
    "PROJECT_TEMPLATE_TRACK_FIELDS",
    "list_project_templates",
    "load_project_template",
    "new_project_from_template",
    "project_from_template_payload",
    "project_template_payload_from_project",
    "save_project_template",
]
