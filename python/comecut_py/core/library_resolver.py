"""Resolve stale library paths after the user moves files or opens a project on another machine."""
from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Iterable

from .project import LibraryEntry, Project


def _norm_name(name: str) -> str:
    """Normalize filename for cross-platform comparison.

    Different platforms encode filenames differently:
    - Windows/Linux: typically NFC (composed)
    - macOS: NFD (decomposed)
    - Network drives / cloud sync may convert between forms

    Returns NFC + casefold form for robust matching.
    """
    if not name:
        return ""
    # Normalize to NFC and use casefold for Unicode-aware case-insensitive comparison
    return unicodedata.normalize("NFC", name).casefold().strip()


def fingerprint(path: Path) -> tuple[str, int] | None:
    try:
        st = path.stat()
        return (path.name, st.st_size)
    except (OSError, ValueError):
        return None


def collect_search_dirs(project: Project, *, project_file: Path | None = None) -> list[Path]:
    """Gather candidate folders to search for relocated media."""
    dirs: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path | None) -> None:
        if p is None:
            return
        try:
            resolved = p.resolve()
        except (OSError, RuntimeError):
            return
        if not resolved.is_dir():
            return
        if resolved in seen:
            return
        seen.add(resolved)
        dirs.append(resolved)

    if project_file is not None:
        _add(project_file.parent)

    for track in project.tracks:
        for clip in track.clips:
            try:
                clip_path = Path(clip.source)
                if clip_path.is_file():
                    _add(clip_path.parent)
            except Exception:
                continue

    for entry in list(project.library_media) + list(project.library_subtitles):
        try:
            entry_path = Path(entry.source)
            if entry_path.is_file():
                _add(entry_path.parent)
        except Exception:
            continue

    return dirs


def _try_resolve(entry: LibraryEntry, search_dirs: Iterable[Path]) -> Path | None:
    """Search for a file matching ``entry.name`` (and optionally ``entry.size``).

    Returns the first matching path or ``None``.
    """
    if not entry.name:
        return None

    target_norm = _norm_name(entry.name)
    if not target_norm:
        return None

    def _scan_dir(d: Path) -> Path | None:
        """Scan a single directory for a match using normalized names."""
        try:
            # Phase 1: Try direct file check first (fastest)
            candidate = d / entry.name
            if candidate.is_file():
                try:
                    if entry.size > 0 and candidate.stat().st_size != entry.size:
                        pass # Mismatch, but we'll try fuzzy below
                    else:
                        return candidate
                except OSError:
                    pass

            # Phase 2: Iterative search for NFC/NFD or case-insensitive match
            for f in d.iterdir():
                if not f.is_file():
                    continue
                if _norm_name(f.name) == target_norm:
                    try:
                        if entry.size > 0 and f.stat().st_size != entry.size:
                            continue
                        return f
                    except OSError:
                        continue
        except OSError:
            pass
        return None

    for d in search_dirs:
        # Check current search dir
        found = _scan_dir(d)
        if found:
            return found

        # Check subdirectories (depth-1) to handle slightly nested structures
        try:
            for sub in d.iterdir():
                try:
                    if sub.is_dir():
                        found = _scan_dir(sub)
                        if found:
                            return found
                except OSError:
                    continue
        except OSError:
            continue

    return None


def resolve_entry(entry: LibraryEntry, search_dirs: list[Path]) -> tuple[LibraryEntry, bool]:
    """Resolve one entry. Returns ``(updated_entry, is_missing)``.

    If the original ``source`` exists, updates ``size``/``mtime`` from disk.
    If it doesn't exist, searches ``search_dirs`` by name+size. If found,
    rewrites ``source`` to the new path. Otherwise leaves source as-is and
    flags missing=True.
    """
    src = Path(entry.source) if entry.source else None
    if src is not None and src.is_file():
        try:
            st = src.stat()
            return entry.model_copy(update={"size": st.st_size, "mtime": st.st_mtime, "name": src.name or entry.name}), False
        except OSError:
            return entry, False

    found = _try_resolve(entry, search_dirs)
    if found is not None:
        try:
            st = found.stat()
            return entry.model_copy(
                update={"source": str(found), "size": st.st_size, "mtime": st.st_mtime, "name": found.name},
            ), False
        except OSError:
            return entry.model_copy(update={"source": str(found)}), False

    return entry, True


def resolve_in_folder(
    entries: list[LibraryEntry], folder: Path, *, recursive: bool = False
) -> dict[int, LibraryEntry]:
    """Re-search a single user-picked folder for the given entries.

    Returns ``{index: updated_entry}`` for entries that were successfully
    relocated (caller applies updates). Used by the dialog's "pick folder"
    flow where the user explicitly tells us where the moved files now live.
    """
    if not folder.is_dir():
        return {}
    updates: dict[int, LibraryEntry] = {}
    iterator = folder.rglob("*") if recursive else folder.iterdir()
    
    # Pre-index folder contents for fast lookup
    by_norm: dict[str, list[Path]] = {}
    by_size: dict[int, list[Path]] = {}
    
    for p in iterator:
        try:
            if p.is_file():
                by_norm.setdefault(_norm_name(p.name), []).append(p)
                try:
                    sz = p.stat().st_size
                    by_size.setdefault(sz, []).append(p)
                except OSError:
                    pass
        except OSError:
            continue

    for i, entry in enumerate(entries):
        target_norm = _norm_name(entry.name)
        if not target_norm and entry.size <= 0:
            continue

        chosen: Path | None = None
        
        # Phase 1: Try normalized name match (handles NFC/NFD/Case)
        if target_norm:
            candidates = by_norm.get(target_norm, [])
            for c in candidates:
                try:
                    if entry.size > 0 and c.stat().st_size != entry.size:
                        continue
                    chosen = c
                    break
                except OSError:
                    continue
        
        # Phase 2: Fallback to size-only match if name failed (handles renamed files)
        if chosen is None and entry.size > 0:
            same_size = by_size.get(entry.size, [])
            # Prefer same extension to avoid matching unrelated files (e.g. mp4 vs srt)
            target_ext = Path(entry.name).suffix.lower() if entry.name else ""
            for c in same_size:
                if target_ext and c.suffix.lower() != target_ext:
                    continue
                chosen = c
                break

        if chosen is not None:
            try:
                st = chosen.stat()
                updates[i] = entry.model_copy(
                    update={
                        "source": str(chosen),
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "name": chosen.name,
                    }
                )
            except OSError:
                continue
    return updates


def resolve_project_library(
    project: Project, *, project_file: Path | None = None
) -> dict[str, any]:
    """Resolve every entry in ``library_media`` and ``library_subtitles`` in place.

    Returns ``{"media": [bool], "subtitles": [bool], "path_map": {old_src: new_src}}``.
    """
    search_dirs = collect_search_dirs(project, project_file=project_file)
    path_map: dict[str, str] = {}

    def _norm(p: str) -> str:
        try:
            return str(Path(p).resolve())
        except Exception:
            return p

    media_missing: list[bool] = []
    new_media: list[LibraryEntry] = []
    for entry in project.library_media:
        old_src = entry.source
        new_entry, missing = resolve_entry(entry, search_dirs)
        new_media.append(new_entry)
        media_missing.append(missing)
        if not missing and _norm(new_entry.source) != _norm(old_src):
            path_map[_norm(old_src)] = new_entry.source

    sub_missing: list[bool] = []
    new_subs: list[LibraryEntry] = []
    for entry in project.library_subtitles:
        old_src = entry.source
        new_entry, missing = resolve_entry(entry, search_dirs)
        new_subs.append(new_entry)
        sub_missing.append(missing)
        if not missing and _norm(new_entry.source) != _norm(old_src):
            path_map[_norm(old_src)] = new_entry.source

    project.library_media = new_media
    project.library_subtitles = new_subs

    return {
        "media": media_missing,
        "subtitles": sub_missing,
        "path_map": path_map,
    }


__all__ = [
    "collect_search_dirs",
    "fingerprint",
    "resolve_entry",
    "resolve_in_folder",
    "resolve_project_library",
]
