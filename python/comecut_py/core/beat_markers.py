"""Local beat-marker helpers for timeline snap anchors."""

from __future__ import annotations

from .project import BeatMarker, Project


def sorted_beat_markers(project: Project) -> list[BeatMarker]:
    return sorted(project.beat_markers, key=lambda marker: float(marker.time))


def beat_marker_times(project: Project) -> list[float]:
    return [float(marker.time) for marker in sorted_beat_markers(project)]


def add_beat_marker(
    project: Project,
    time_seconds: float,
    *,
    label: str = "Beat",
    source: str = "manual",
    dedupe_tolerance: float = 1e-3,
) -> BeatMarker:
    t = max(0.0, float(time_seconds))
    for marker in project.beat_markers:
        if abs(float(marker.time) - t) <= max(0.0, float(dedupe_tolerance)):
            marker.label = label or marker.label
            marker.source = source if source in {"manual", "detected"} else "manual"  # type: ignore[assignment]
            project.beat_markers = sorted_beat_markers(project)
            return marker
    marker = BeatMarker(
        time=t,
        label=(label or "Beat").strip() or "Beat",
        source=source if source in {"manual", "detected"} else "manual",  # type: ignore[arg-type]
    )
    project.beat_markers.append(marker)
    project.beat_markers = sorted_beat_markers(project)
    return marker


def remove_near_beat_marker(
    project: Project,
    time_seconds: float,
    *,
    tolerance: float = 0.05,
) -> bool:
    if not project.beat_markers:
        return False
    t = max(0.0, float(time_seconds))
    tol = max(0.0, float(tolerance))
    best_index: int | None = None
    best_dist = tol
    for index, marker in enumerate(project.beat_markers):
        dist = abs(float(marker.time) - t)
        if dist <= best_dist:
            best_index = index
            best_dist = dist
    if best_index is None:
        return False
    project.beat_markers.pop(best_index)
    project.beat_markers = sorted_beat_markers(project)
    return True


__all__ = [
    "add_beat_marker",
    "beat_marker_times",
    "remove_near_beat_marker",
    "sorted_beat_markers",
]
