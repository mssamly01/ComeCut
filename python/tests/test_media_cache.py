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
