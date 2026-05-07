from __future__ import annotations

from pathlib import Path

from comecut_py.core.media_cache import CachedMediaInfo, MediaCache, user_cache_root


def test_user_cache_root_honors_xdg_cache_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("COMECUT_CACHE_HOME", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

    assert user_cache_root() == tmp_path / "xdg" / "comecut-py"


def test_media_cache_invalidates_when_mtime_changes(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"first")
    cache = MediaCache(tmp_path / "media-index.json")

    cache.put(source, CachedMediaInfo(source=str(source), duration=12.5, has_video=True))
    assert cache.get(source).duration == 12.5

    source.write_bytes(b"second version")
    assert cache.get(source) is None


def test_media_cache_debounces_writes_until_flush(tmp_path: Path) -> None:
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    index = tmp_path / "media-index.json"
    cache = MediaCache(index, save_interval=999.0)

    cache.put(first, CachedMediaInfo(source=str(first), duration=1.0, has_audio=True))
    first_size = index.stat().st_size
    cache.put(second, CachedMediaInfo(source=str(second), duration=2.0, has_audio=True))

    assert cache.get(second).duration == 2.0
    assert index.stat().st_size == first_size
    cache.flush()
    assert index.stat().st_size > first_size
