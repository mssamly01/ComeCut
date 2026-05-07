"""Persistent metadata cache for imported media."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from threading import RLock

from .media_probe import MediaInfo


@dataclass
class CachedMediaInfo:
    source: str
    size: int = 0
    mtime_ns: int = 0
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    has_video: bool = False
    has_audio: bool = False
    thumbnail_path: str | None = None
    audio_proxy_path: str | None = None
    video_proxy_path: str | None = None
    status: str = "pending"
    error: str | None = None

    @classmethod
    def from_probe(cls, path: str | Path, info: MediaInfo) -> "CachedMediaInfo":
        size, mtime_ns = media_file_stat(path)
        return cls(
            source=str(Path(path)),
            size=size,
            mtime_ns=mtime_ns,
            duration=info.duration,
            width=info.width,
            height=info.height,
            fps=info.fps,
            video_codec=info.video_codec,
            audio_codec=info.audio_codec,
            sample_rate=info.sample_rate,
            channels=info.channels,
            has_video=info.has_video,
            has_audio=info.has_audio,
            status="ready",
            error=None,
        )

    def to_probe_info(self) -> MediaInfo:
        return MediaInfo(
            path=self.source,
            duration=self.duration,
            width=self.width,
            height=self.height,
            fps=self.fps,
            video_codec=self.video_codec,
            audio_codec=self.audio_codec,
            sample_rate=self.sample_rate,
            channels=self.channels,
            has_video=self.has_video,
            has_audio=self.has_audio,
        )


def user_cache_root() -> Path:
    override = os.environ.get("COMECUT_CACHE_HOME")
    if override:
        root = Path(override)
    elif os.environ.get("XDG_CACHE_HOME"):
        root = Path(os.environ["XDG_CACHE_HOME"]) / "comecut-py"
    elif os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "ComeCut" / "cache"
    else:
        root = Path.home() / ".cache" / "comecut-py"
    root.mkdir(parents=True, exist_ok=True)
    return root


def media_file_stat(path: str | Path) -> tuple[int, int]:
    try:
        st = Path(path).stat()
        return int(st.st_size), int(st.st_mtime_ns)
    except OSError:
        return 0, 0


def media_source_key(path: str | Path) -> str:
    resolved = str(Path(path).resolve())
    size, mtime_ns = media_file_stat(path)
    raw = f"{resolved}:{size}:{mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


class MediaCache:
    def __init__(self, index_path: Path | None = None) -> None:
        self._index_path = index_path or (user_cache_root() / "media-index.json")
        self._lock = RLock()
        self._index: dict[str, dict[str, object]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(self._index_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self._index = {}
            return
        self._index = data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._index, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            "utf-8",
        )
        tmp.replace(self._index_path)

    def get(self, path: str | Path) -> CachedMediaInfo | None:
        key = media_source_key(path)
        with self._lock:
            self._load()
            raw = self._index.get(key)
        if not isinstance(raw, dict):
            return None
        try:
            info = CachedMediaInfo(**raw)
        except TypeError:
            return None
        size, mtime_ns = media_file_stat(path)
        if info.size != size or info.mtime_ns != mtime_ns:
            return None
        return info

    def put(self, path: str | Path, info: CachedMediaInfo) -> CachedMediaInfo:
        size, mtime_ns = media_file_stat(path)
        info.source = str(Path(path))
        info.size = size
        info.mtime_ns = mtime_ns
        key = media_source_key(path)
        with self._lock:
            self._load()
            self._index[key] = asdict(info)
            self._save()
        return info

    def update(self, path: str | Path, **fields: object) -> CachedMediaInfo:
        info = self.get(path) or CachedMediaInfo(source=str(Path(path)))
        for key, value in fields.items():
            if hasattr(info, key):
                setattr(info, key, value)
        return self.put(path, info)


__all__ = [
    "CachedMediaInfo",
    "MediaCache",
    "media_file_stat",
    "media_source_key",
    "user_cache_root",
]
