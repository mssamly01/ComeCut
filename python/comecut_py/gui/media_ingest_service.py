"""Background ingest service for media metadata, thumbnails, and proxies."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QObject, Signal  # type: ignore

from ..core.media_cache import CachedMediaInfo, MediaCache
from ..core.media_probe import probe
from ..engine.audio_proxy import audio_proxy_path, make_audio_proxy
from ..engine.proxy import make_proxy, proxy_path
from ..engine.thumbnails import render_filmstrip_png


_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
_SUBTITLE_EXTS = {".srt", ".vtt", ".lrc", ".ass", ".ssa", ".txt"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class MediaIngestService(QObject):
    status_changed = Signal(object, object)  # Path, str
    metadata_ready = Signal(object, object)  # Path, CachedMediaInfo | str error
    thumbnail_ready = Signal(object, object)  # Path, Path | None
    proxy_ready = Signal(object, object)  # Path, Path | None
    audio_proxy_ready = Signal(object, object)  # Path, Path | None

    def __init__(self, cache: MediaCache | None = None) -> None:
        super().__init__()
        self.cache = cache or MediaCache()
        self._probe_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="media-probe")
        self._decode_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-decode")
        self._inflight_lock = Lock()
        self._inflight_probe: set[str] = set()
        self._inflight_decode: set[str] = set()

    def enqueue(self, path: Path | str) -> None:
        path_obj = Path(path)
        key = self._fast_key(path_obj)
        with self._inflight_lock:
            if key in self._inflight_probe:
                return
            self._inflight_probe.add(key)
        self._probe_executor.submit(self._dispatch_one, path_obj, key)

    def enqueue_many(self, paths: Iterable[Path | str]) -> None:
        accepted: list[Path] = []
        keys: list[str] = []
        with self._inflight_lock:
            for raw in paths:
                if raw is None:
                    continue
                path_obj = Path(raw)
                key = self._fast_key(path_obj)
                if key in self._inflight_probe:
                    continue
                self._inflight_probe.add(key)
                accepted.append(path_obj)
                keys.append(key)
        if accepted:
            self._probe_executor.submit(self._dispatch_batch, accepted, keys)

    def close(self) -> None:
        self._probe_executor.shutdown(wait=False, cancel_futures=True)
        self._decode_executor.shutdown(wait=False, cancel_futures=True)
        try:
            self.cache.flush()
        except Exception:
            pass

    @staticmethod
    def _fast_key(path: Path) -> str:
        return str(path).lower()

    @staticmethod
    def _key(path: Path) -> str:
        try:
            return str(path.resolve()).lower()
        except Exception:
            return str(path).lower()

    def _dispatch_one(self, path: Path, fast_key: str) -> None:
        try:
            self._dispatch_path(path, fast_key)
        except Exception:
            with self._inflight_lock:
                self._inflight_probe.discard(fast_key)

    def _dispatch_batch(self, paths: list[Path], fast_keys: list[str]) -> None:
        for path, fast_key in zip(paths, fast_keys):
            try:
                self._dispatch_path(path, fast_key)
            except Exception:
                with self._inflight_lock:
                    self._inflight_probe.discard(fast_key)

    def _dispatch_path(self, path: Path, fast_key: str) -> None:
        cached = None
        try:
            cached = self.cache.get(path)
        except Exception:
            cached = None
        if cached is not None and cached.status == "ready":
            with self._inflight_lock:
                self._inflight_probe.discard(fast_key)
            self.metadata_ready.emit(path, cached)
            self._emit_cached_assets(path, cached)
            self._maybe_enqueue_decode(path, cached)
            return
        self.status_changed.emit(path, "Analyzing...")
        self._probe_job(path, fast_key=fast_key)

    @staticmethod
    def should_make_video_proxy(info: CachedMediaInfo) -> bool:
        if not info.has_video:
            return False
        duration = float(info.duration or 0.0)
        long = duration >= 30.0
        high_res = (info.width or 0) >= 1920 or (info.height or 0) >= 1080
        heavy_codec = (info.video_codec or "").lower() in {"hevc", "h265", "av1", "vp9"}
        return long or high_res or heavy_codec

    @staticmethod
    def should_make_audio_proxy(info: CachedMediaInfo, path: Path) -> bool:
        if not info.has_audio or info.has_video:
            return False
        ext = path.suffix.lower()
        codec = (info.audio_codec or "").lower()
        duration = float(info.duration or 0.0)
        return ext != ".wav" or codec in {"mp3", "aac", "opus", "vorbis"} or duration >= 300.0

    def _probe_job(self, path: Path, *, fast_key: str | None = None) -> None:
        if fast_key is None:
            fast_key = self._fast_key(path)
        try:
            ext = path.suffix.lower()
            if ext in _SUBTITLE_EXTS:
                info = self.cache.update(path, status="ready", has_video=False, has_audio=False, error=None)
            elif ext in _IMAGE_EXTS:
                info = self.cache.update(path, status="ready", has_video=False, has_audio=False, error=None)
            else:
                probed = probe(path, timeout=15.0)
                info = self.cache.put(path, CachedMediaInfo.from_probe(path, probed))
            self.metadata_ready.emit(path, info)
            self._emit_cached_assets(path, info)
            self._maybe_enqueue_decode(path, info)
        except Exception as exc:
            msg = str(exc)
            try:
                self.cache.update(path, status="failed", error=msg)
            except Exception:
                pass
            self.metadata_ready.emit(path, msg)
            self.status_changed.emit(path, "Analyze failed")
        finally:
            with self._inflight_lock:
                self._inflight_probe.discard(fast_key)

    def _emit_cached_assets(self, path: Path, info: CachedMediaInfo) -> None:
        if info.thumbnail_path and Path(info.thumbnail_path).exists():
            self.thumbnail_ready.emit(path, Path(info.thumbnail_path))
        if info.video_proxy_path and Path(info.video_proxy_path).exists():
            self.proxy_ready.emit(path, Path(info.video_proxy_path))
        if info.audio_proxy_path and Path(info.audio_proxy_path).exists():
            self.audio_proxy_ready.emit(path, Path(info.audio_proxy_path))

    def _maybe_enqueue_decode(self, path: Path, info: CachedMediaInfo) -> None:
        ext = path.suffix.lower()
        if ext in _SUBTITLE_EXTS or ext in _IMAGE_EXTS:
            return
        key = self._key(path)
        with self._inflight_lock:
            if key in self._inflight_decode:
                return
        needs_thumbnail = info.has_video and not (info.thumbnail_path and Path(info.thumbnail_path).exists())
        needs_video_proxy = self.should_make_video_proxy(info) and not (
            info.video_proxy_path and Path(info.video_proxy_path).exists()
        )
        needs_audio_proxy = self.should_make_audio_proxy(info, path) and not (
            info.audio_proxy_path and Path(info.audio_proxy_path).exists()
        )
        if not (needs_thumbnail or needs_video_proxy or needs_audio_proxy):
            return
        with self._inflight_lock:
            if key in self._inflight_decode:
                return
            self._inflight_decode.add(key)
        self._decode_executor.submit(self._decode_job, path, info)

    def _decode_job(self, path: Path, info: CachedMediaInfo) -> None:
        key = self._key(path)
        try:
            video_proxy_for_thumb: Path | None = None
            if self.should_make_video_proxy(info):
                cached_video = proxy_path(path, width=720, crf=30, preset="veryfast", audio_bitrate="96k")
                if cached_video.exists() and cached_video.stat().st_size > 0:
                    info = self.cache.update(path, video_proxy_path=str(cached_video))
                    self.proxy_ready.emit(path, cached_video)
                    video_proxy_for_thumb = cached_video
                else:
                    self.status_changed.emit(path, "Creating proxy...")
                    proxy = make_proxy(
                        path,
                        width=720,
                        crf=30,
                        preset="veryfast",
                        audio_bitrate="96k",
                    )
                    info = self.cache.update(path, video_proxy_path=str(proxy))
                    self.proxy_ready.emit(path, proxy)
                    video_proxy_for_thumb = proxy

            if info.has_video:
                cached_thumb = info.thumbnail_path and Path(info.thumbnail_path)
                if not cached_thumb or not cached_thumb.exists():
                    thumb_source = video_proxy_for_thumb or path
                    thumb_duration = None if video_proxy_for_thumb else info.duration
                    self.status_changed.emit(path, "Creating thumbnail...")
                    try:
                        thumb = render_filmstrip_png(
                            str(thumb_source),
                            strip_width=138,
                            strip_height=78,
                            frames=1,
                            duration=thumb_duration,
                        )
                    except Exception:
                        thumb = None
                    if thumb is not None and Path(thumb).exists():
                        info = self.cache.update(path, thumbnail_path=str(thumb))
                        self.thumbnail_ready.emit(path, Path(thumb))

            if self.should_make_audio_proxy(info, path):
                cached_audio = audio_proxy_path(path)
                if cached_audio.exists() and cached_audio.stat().st_size > 0:
                    info = self.cache.update(path, audio_proxy_path=str(cached_audio))
                    self.audio_proxy_ready.emit(path, cached_audio)
                else:
                    self.status_changed.emit(path, "Creating audio proxy...")
                    proxy = make_audio_proxy(path, timeout=300.0)
                    info = self.cache.update(path, audio_proxy_path=str(proxy))
                    self.audio_proxy_ready.emit(path, proxy)

            self.status_changed.emit(path, "Ready")
        except Exception as exc:
            self.cache.update(path, status="failed", error=str(exc))
            self.status_changed.emit(path, "Cache failed")
        finally:
            with self._inflight_lock:
                self._inflight_decode.discard(key)


__all__ = ["MediaIngestService"]
