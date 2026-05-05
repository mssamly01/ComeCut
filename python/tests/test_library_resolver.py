"""Tests for the library path resolver and missing-flag pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest

from comecut_py.core.library_resolver import (
    collect_search_dirs,
    resolve_entry,
    resolve_in_folder,
    resolve_project_library,
)
from comecut_py.core.project import LibraryEntry, Project, Track, Clip


def _touch(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_resolve_entry_existing_path_updates_metadata(tmp_path):
    f = tmp_path / "video.mp4"
    _touch(f, b"some content")
    e = LibraryEntry(source=str(f), name=f.name, size=0, mtime=0.0)
    resolved, missing = resolve_entry(e, [tmp_path])
    assert missing is False
    assert resolved.source == str(f)
    assert resolved.size == len(b"some content")
    assert resolved.mtime > 0.0


def test_resolve_entry_finds_moved_file_by_name_size(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    f = new_dir / "v.mp4"
    _touch(f, b"hello world")
    # Entry's stale path points to old location
    e = LibraryEntry(source=str(old_dir / "v.mp4"), name="v.mp4", size=11, mtime=0.0)
    resolved, missing = resolve_entry(e, [new_dir])
    assert missing is False
    assert resolved.source == str(f)


def test_resolve_entry_skips_when_size_mismatches(tmp_path):
    new_dir = tmp_path / "new"
    f = new_dir / "v.mp4"
    _touch(f, b"hello")  # size = 5
    e = LibraryEntry(source="/old/v.mp4", name="v.mp4", size=11, mtime=0.0)
    resolved, missing = resolve_entry(e, [new_dir])
    assert missing is True
    assert resolved.source == "/old/v.mp4"


def test_resolve_entry_size_zero_bypasses_check(tmp_path):
    new_dir = tmp_path / "new"
    f = new_dir / "v.mp4"
    _touch(f, b"any content")
    e = LibraryEntry(source="/old/v.mp4", name="v.mp4", size=0, mtime=0.0)
    resolved, missing = resolve_entry(e, [new_dir])
    assert missing is False
    assert resolved.source == str(f)


def test_resolve_entry_missing_when_not_found(tmp_path):
    e = LibraryEntry(source="/nonexistent/x.mp4", name="x.mp4", size=99, mtime=0.0)
    resolved, missing = resolve_entry(e, [tmp_path])
    assert missing is True
    assert resolved.source == "/nonexistent/x.mp4"  # Unchanged


def test_collect_search_dirs_includes_clip_parents(tmp_path):
    clip_dir = tmp_path / "clips"
    clip_file = clip_dir / "clip.mp4"
    _touch(clip_file)
    p = Project()
    p.tracks.append(
        Track(kind="video", name="Main", clips=[
            Clip(source=str(clip_file), in_point=0, out_point=5, start=0)
        ])
    )
    dirs = collect_search_dirs(p)
    assert clip_dir.resolve() in dirs


def test_collect_search_dirs_includes_existing_library_parents(tmp_path):
    lib_dir = tmp_path / "lib"
    lib_file = lib_dir / "v.mp4"
    _touch(lib_file)
    p = Project()
    p.library_media.append(LibraryEntry(source=str(lib_file), name="v.mp4"))
    dirs = collect_search_dirs(p)
    assert lib_dir.resolve() in dirs


def test_resolve_project_library_relocates_all_media(tmp_path):
    src_dir = tmp_path / "src"
    a = src_dir / "a.mp4"; _touch(a, b"a" * 10)
    b = src_dir / "b.mp4"; _touch(b, b"b" * 20)
    p = Project()
    # All entries point to a stale `/old/...` path with metadata
    p.library_media.append(LibraryEntry(source="/old/a.mp4", name="a.mp4", size=10))
    p.library_media.append(LibraryEntry(source="/old/b.mp4", name="b.mp4", size=20))
    # Use a clip path that DOES exist to seed search_dirs
    p.tracks.append(Track(kind="video", clips=[
        Clip(source=str(a), in_point=0, out_point=1, start=0)
    ]))
    res = resolve_project_library(p)
    assert res["media"] == [False, False]
    assert p.library_media[0].source == str(a)
    assert p.library_media[1].source == str(b)
    
    # Path map should contain mappings for the stale entries
    # (Note: we use a helper to match the resolver's internal norm)
    def norm(p):
        try: return str(Path(p).resolve())
        except: return p
        
    assert res["path_map"][norm("/old/a.mp4")] == str(a)
    assert res["path_map"][norm("/old/b.mp4")] == str(b)


def test_resolve_project_library_returns_path_map_for_subtitles(tmp_path):
    src_dir = tmp_path / "src"
    s = src_dir / "s.srt"; _touch(s, b"1\n00:00:00,000 -> 00:00:01,000\nHello")
    p = Project()
    p.library_subtitles.append(LibraryEntry(source="/stale/s.srt", name="s.srt", size=len(s.read_bytes())))
    # Seed search_dirs with tmp_path itself
    _touch(tmp_path / "seed.mp4")
    p.library_media.append(LibraryEntry(source=str(tmp_path / "seed.mp4"), name="seed.mp4"))
    
    # resolver should find s.srt in tmp_path/src because it's depth-1 from tmp_path
    res = resolve_project_library(p)
    assert res["subtitles"] == [False]
    assert p.library_subtitles[0].source == str(s)
    
    def norm(p):
        try: return str(Path(p).resolve())
        except: return p
    assert res["path_map"][norm("/stale/s.srt")] == str(s)


def test_resolve_in_folder_handles_nfc_nfd_mismatch(tmp_path):
    """Vietnamese filename stored as NFC, on disk as NFD (or vice versa)."""
    import unicodedata
    nfc_name = unicodedata.normalize("NFC", "tệp.mp4")
    nfd_name = unicodedata.normalize("NFD", "tệp.mp4")
    assert nfc_name != nfd_name

    f = tmp_path / nfd_name
    f.write_bytes(b"x" * 50)

    entries = [LibraryEntry(source="/old/" + nfc_name, name=nfc_name, size=50)]
    updates = resolve_in_folder(entries, tmp_path)
    assert 0 in updates
    assert Path(updates[0].source).read_bytes() == b"x" * 50


def test_resolve_in_folder_size_fallback_when_renamed(tmp_path):
    """File renamed but size unchanged — should match by size + extension."""
    f = tmp_path / "renamed.mp4"
    f.write_bytes(b"y" * 100)

    entries = [LibraryEntry(source="/old/original.mp4", name="original.mp4", size=100)]
    updates = resolve_in_folder(entries, tmp_path)
    assert 0 in updates
    assert updates[0].source == str(f)


def test_resolve_in_folder_size_fallback_respects_extension(tmp_path):
    """Don't match wrong-extension file even if size matches."""
    (tmp_path / "audio.mp3").write_bytes(b"z" * 100)
    (tmp_path / "doc.pdf").write_bytes(b"w" * 100)

    # Looking for "music.mp3" — should match audio.mp3 by size+ext, NOT doc.pdf
    entries = [LibraryEntry(source="/old/music.mp3", name="music.mp3", size=100)]
    updates = resolve_in_folder(entries, tmp_path)
    assert 0 in updates
    assert updates[0].source == str(tmp_path / "audio.mp3")


def test_resolve_in_folder_no_match_returns_empty(tmp_path):
    (tmp_path / "different.mp4").write_bytes(b"x" * 100)
    entries = [LibraryEntry(source="/old/missing.mp4", name="missing.mp4", size=999)]
    # size doesn't match either, so no fallback
    updates = resolve_in_folder(entries, tmp_path)
    assert updates == {}


def test_norm_name_handles_unicode():
    from comecut_py.core.library_resolver import _norm_name
    import unicodedata
    nfc = unicodedata.normalize("NFC", "tệp.MP4")
    nfd = unicodedata.normalize("NFD", "tệp.MP4")
    assert _norm_name(nfc) == _norm_name(nfd)


def test_norm_name_casefold():
    from comecut_py.core.library_resolver import _norm_name
    assert _norm_name("Test.MP4") == _norm_name("test.mp4")
    assert _norm_name("TEST.mp4") == "test.mp4"
