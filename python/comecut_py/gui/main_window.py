"""Main window - assembles the editor in the same shape as the HTML build."""

from __future__ import annotations

from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import re
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QEvent, QThread, QTimer, Qt, Signal  # type: ignore
from PySide6.QtGui import QKeySequence  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QComboBox,
    QFrame,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.media_cache import CachedMediaInfo
from ..core.media_probe import probe
from ..core.auto_ducking import (
    AutoDuckingConfig,
    apply_auto_ducking_to_tracks,
    collect_role_intervals,
)
from ..core.beat_markers import add_beat_marker, remove_near_beat_marker
from ..core.audio_mixer import audible_audio_tracks, track_output_gain
from ..core.project_templates import (
    list_project_templates,
    new_project_from_template,
    save_project_template,
)
from ..core.time_utils import format_timecode
from ..core.project import Clip, Project, Track
from ..core.store import default_store_dir
from ..core.store import load_project as store_load_project
from ..core.store import save_project as store_save_project
from ..engine.audio_proxy import audio_proxy_path, make_audio_proxy
from ..engine.proxy import make_proxy, proxy_path
from ..engine import render_project, render_project_audio_only, render_project_still_frame
from ..i18n import t
from ..subtitles.ass import parse_ass, write_ass
from ..subtitles.cue import Cue, CueList
from ..subtitles.lrc import parse_lrc
from ..subtitles.srt import load_srt, parse_srt, write_srt
from ..subtitles.translate_batch import (
    apply_clip_translations,
    chunked,
    collect_clip_translate_items,
)
from ..subtitles.vtt import parse_vtt, write_vtt
from .dialogs.export_dialog import ExportDialog
from .dialogs.plugin_manager import PluginManagerDialog
from .media_ingest_service import MediaIngestService
from .dialogs.subtitle_edit_translate import SubtitleDialogInfo, SubtitleEditTranslateDialog
from .plugin_config import PluginConfigStore, build_translate_provider
from .preview_timeline import (
    _ClipIntervalIndex,
    clip_fade_multiplier,
    next_playable_time_after,
    pick_timeline_audio_clip,
)
from .widgets.inspector import InspectorPanel
from .widgets.left_rail import TAB_MEDIA, TAB_TEXT, TAB_VOICE_MATCH, LeftRail
from .widgets.media_library import MediaLibraryPanel
from .widgets.preview import PreviewPanel
from .widgets.text_panel import TextPanel
from .widgets.timeline import TimelinePanel
from .widgets.topbar import TopBar
from .widgets.voice_match_panel import VoiceMatchPanel, VoiceMatchPanelSettings


def _clip_speed_value(clip: Clip) -> float:
    try:
        speed = float(getattr(clip, "speed", 1.0) or 1.0)
    except Exception:
        speed = 1.0
    return max(1e-9, speed)


def _timeline_to_source_seconds(clip: Clip, timeline_seconds: float) -> float:
    rel_t = max(0.0, float(timeline_seconds) - float(clip.start))
    return max(0.0, rel_t * _clip_speed_value(clip) + float(clip.in_point))


def _source_to_timeline_seconds(clip: Clip, source_seconds: float) -> float:
    rel_src = max(0.0, float(source_seconds) - float(clip.in_point))
    return float(clip.start) + (rel_src / _clip_speed_value(clip))


class _VoiceMatchWorker(QThread):
    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, options: object) -> None:
        super().__init__()
        self.options = options

    def run(self) -> None:
        try:
            from ..integrations.capcut_generator.adapter import generate_voice_match_from_timeline

            result = generate_voice_match_from_timeline(
                self.options,  # type: ignore[arg-type]
                progress_callback=lambda percent, message: self.progress.emit(
                    int(percent),
                    str(message),
                ),
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class MainWindow(QMainWindow):
    _VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
    _AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
    _SUBTITLE_EXTS = {".srt", ".vtt", ".lrc", ".ass", ".ssa", ".txt"}
    _PROXY_MIN_DURATION_SECONDS = 30.0
    _PROXY_PREVIEW_WIDTH = 720
    _PROXY_PREVIEW_CRF = 30
    _VIDEO_CLOCK_RESYNC_THRESHOLD_MS = 450
    _VIDEO_CLOCK_RESYNC_INTERVAL = 1.0
    _VIDEO_RESUME_RESYNC_DELAY_MS = 120
    _LARGE_SUBTITLE_IMPORT_CUE_COUNT = 500
    _GAP_PLAY_FULL_SYNC_INTERVAL = 0.080
    _SCRUB_FINISH_SYNC_DELAY_MS = 180
    _proxy_ready = Signal(object, object, object)
    _audio_proxy_ready = Signal(object, object, object)
    _timeline_audio_mix_ready = Signal(object, object, object)
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setWindowTitle(t("app.title"))
        self.resize(1440, 900)

        self.project = Project(name="Untitled")
        self.project.tracks.append(Track(kind="video", name="Main"))
        self._store_project_id: str | None = None
        self._plugin_store = PluginConfigStore.load_default()
        self._preview_source_path: str | None = None
        self._preview_sync_mode: str = "timeline"
        self._preview_active_text_clip: Clip | None = None
        self._subtitle_lookup_dirty = True
        self._subtitle_lookup_starts: list[float] = []
        self._subtitle_lookup_items: list[tuple[float, float, Clip]] = []
        self._subtitle_overlay_state: tuple | None = None
        self._menu_just_closed = False
        self._suspend_timeline_selection_sync = False
        self._history_snapshots: list[str] = []
        self._history_index: int = -1
        self._history_replaying = False
        self._history_limit = 300
        self._proxy_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="comecut-proxy")
        self._audio_proxy_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="comecut-audio-proxy")
        self._proxy_inflight: set[str] = set()
        self._proxy_source_to_clips: dict[str, list[Clip]] = {}
        self._audio_proxy_by_source: dict[str, str] = {}
        self._audio_proxy_inflight: set[str] = set()
        self._use_audio_proxies = False
        self._audio_proxy_path_cache: dict[str, Path | None] = {}
        self._clip_audio_preview_path_cache: dict[int, Path] = {}
        self._clip_deferred_audio_proxy_cache: dict[int, bool] = {}
        self._timeline_audio_active_clip_id: int | None = None
        self._preview_audio_presence_cache: dict[str, bool] = {}
        self._preview_active_media_clip: Clip | None = None
        self._audio_clip_index = _ClipIntervalIndex()
        self._video_clip_index = _ClipIntervalIndex()
        self._clip_interval_indexes_dirty = True
        self._timeline_duration_cache: float | None = None
        self._clip_track_map: dict[int, Track] = {}
        self._media_ingest = MediaIngestService(enable_audio_proxies=False)
        self._duration_placeholder_clip_ids: set[int] = set()
        self._duration_placeholder_by_source_key: dict[str, list[Clip]] = {}
        self._pending_ingest_metadata: list[tuple[Path, CachedMediaInfo]] = []
        self._pending_ingest_failures: list[Path] = []
        self._ingest_flush_timer = QTimer(self)
        self._ingest_flush_timer.setSingleShot(True)
        self._ingest_flush_timer.setInterval(120)
        self._ingest_flush_timer.timeout.connect(self._flush_pending_ingest_metadata)
        self._suspend_text_autoselect = False
        self._voice_match_worker: _VoiceMatchWorker | None = None
        self._voice_match_original_project: Project | None = None
        self._voice_match_matched_project: Project | None = None
        self._voice_match_view_state: str | None = None
        self._timeline_audio_mix_proxy: str | None = None
        self._timeline_audio_mix_window_start: float | None = None
        self._timeline_audio_mix_window_duration: float | None = None
        self._timeline_audio_mix_is_windowed = False
        self._timeline_audio_next_mix_proxy: str | None = None
        self._timeline_audio_next_window_start: float | None = None
        self._timeline_audio_next_window_duration: float | None = None
        self._timeline_audio_mix_dirty = True
        self._timeline_audio_mix_inflight = False
        self._timeline_audio_mix_generation_id = 0
        self._preview_resume_resync_generation = 0
        self._gap_play_timer = QTimer(self)
        self._gap_play_timer.setInterval(16)
        self._gap_play_timer.timeout.connect(self._on_gap_play_tick)
        self._gap_play_active = False
        self._gap_play_last_ts = 0.0
        self._gap_play_last_full_sync_ts = 0.0
        self._video_clock_last_resync_ts = 0.0
        self._scrub_finish_generation = 0
        self._timeline_preview_prime_generation = 0
        self._proxy_ready.connect(self._on_proxy_ready)
        self._audio_proxy_ready.connect(self._on_audio_proxy_ready)
        self._timeline_audio_mix_ready.connect(self._on_timeline_audio_mix_ready)

        self._build_ui()
        self._build_menu()
        self._sync_preview_play_availability()
        self._reset_timeline_history()
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(t("status.ready"))
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        QTimer.singleShot(0, self._ensure_project_overview_panel)

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.topbar = TopBar()
        self.topbar.set_project_title(self.project.name)
        self.topbar.plugins_clicked.connect(self._open_plugin_manager)
        self.topbar.export_clicked.connect(self._export_video)
        self.topbar.minimize_requested.connect(self.showMinimized)
        self.topbar.maximize_requested.connect(self._toggle_maximize)
        self.topbar.close_requested.connect(self.close)
        self.topbar.project_title_changed.connect(self._on_topbar_project_title_changed)
        outer.addWidget(self.topbar)

        self.left_rail = LeftRail()

        # New: 2-column structure for the left area
        self.left_panel_container = QWidget()
        self.left_panel_layout = QVBoxLayout(self.left_panel_container)
        self.left_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.left_panel_layout.setSpacing(0)
        self.left_panel_layout.addWidget(self.left_rail)

        self.left_content_split = QWidget()
        self.left_content_layout = QHBoxLayout(self.left_content_split)
        self.left_content_layout.setContentsMargins(0, 0, 0, 0)
        self.left_content_layout.setSpacing(0)

        # New: Container for sub-navigation with border and background
        self.sub_nav_container = QFrame()
        self.sub_nav_container.setFixedWidth(80)
        self.sub_nav_container.setStyleSheet("""
            QFrame { 
                background: #16181d; 
                border-right: 1px solid #2a2e37;
            }
        """)
        sub_nav_container_layout = QVBoxLayout(self.sub_nav_container)
        sub_nav_container_layout.setContentsMargins(0, 0, 0, 0)
        sub_nav_container_layout.setSpacing(0)

        # The dynamic stack goes inside the container
        self.sub_nav_stack = QStackedWidget()
        self.sub_nav_stack.setStyleSheet("background: transparent; border: none;")
        sub_nav_container_layout.addWidget(self.sub_nav_stack)

        # --- Page 1: Media Sub-Nav ---
        self.media_sub_nav = QWidget()
        media_sub_layout = QVBoxLayout(self.media_sub_nav)
        media_sub_layout.setContentsMargins(0, 6, 0, 10)
        media_sub_layout.setSpacing(5)
        media_sub_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        media_label = QLabel("Nhập")
        media_label.setStyleSheet("color: #22d3c5; font-size: 11px; font-weight: normal; padding: 6px 12px; background: #22262d; border-radius: 2px;")
        media_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        media_sub_layout.addWidget(media_label)

        self.media_voice_nav_label = QLabel("Thêm Voice")
        self.media_voice_nav_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.media_voice_nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.media_voice_nav_label.setStyleSheet(
            "color: #8c93a0; font-size: 11px; font-weight: normal; "
            "padding: 6px 8px; background: transparent; border-radius: 2px;"
        )
        self.media_voice_nav_label.mousePressEvent = (
            lambda e: self._open_voice_folder_picker()
        )
        media_sub_layout.addWidget(self.media_voice_nav_label)
        self.sub_nav_stack.addWidget(self.media_sub_nav)

        # --- Page 2: Text Sub-Nav ---
        self.text_sub_nav = QWidget()
        text_sub_layout = QVBoxLayout(self.text_sub_nav)
        text_sub_layout.setContentsMargins(0, 6, 0, 10)
        text_sub_layout.setSpacing(5)
        text_sub_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.text_import_nav_label = QLabel("Nhập")
        self.text_import_nav_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.text_import_nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_import_nav_label.mousePressEvent = lambda e: self._on_show_subtitle_list_requested()
        text_sub_layout.addWidget(self.text_import_nav_label)

        self.ocr_nav_label = QLabel("OCR")
        self.ocr_nav_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ocr_nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ocr_nav_label.mousePressEvent = lambda e: self._on_ocr_mode_requested()
        text_sub_layout.addWidget(self.ocr_nav_label)
        
        self._update_text_sub_nav_visuals("list") # Initial state
        self.sub_nav_stack.addWidget(self.text_sub_nav)

        # --- Page 3: Voice Match has no secondary source picker ---
        self.voice_match_sub_nav = QWidget()
        self.sub_nav_stack.addWidget(self.voice_match_sub_nav)
        
        self.side_stack = QStackedWidget()
        self.side_stack.setMinimumWidth(300)

        self.left_content_layout.addWidget(self.sub_nav_container)
        self.left_content_layout.addWidget(self.side_stack, stretch=1)
        self.left_panel_layout.addWidget(self.left_content_split, stretch=1)

        self.media_panel = MediaLibraryPanel()
        self.text_panel = TextPanel()
        self.voice_match_panel = VoiceMatchPanel()
        self.side_stack.addWidget(self.media_panel)
        self.side_stack.addWidget(self.text_panel)
        self.side_stack.addWidget(self.voice_match_panel)
        self.text_panel.subtitle_import_requested.connect(self._import_subtitles_into_text_panel)

        self.preview_panel = PreviewPanel()
        self.preview_panel.setMinimumWidth(350)

        self.inspector_panel = InspectorPanel()
        self.inspector_panel.setMinimumWidth(350)
        self.inspector_panel.set_project(self.project)

        top_row = QSplitter(Qt.Orientation.Horizontal)
        top_row.addWidget(self.left_panel_container)
        top_row.addWidget(self.preview_panel)
        top_row.addWidget(self.inspector_panel)

        top_row.setSizes([450, 600, 350])
        top_row.setStretchFactor(0, 1)
        top_row.setStretchFactor(1, 2)
        top_row.setStretchFactor(2, 1)

        self.timeline_panel = TimelinePanel(self.project)

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.addWidget(top_row)
        main_splitter.addWidget(self.timeline_panel)
        main_splitter.setStretchFactor(0, 5)
        main_splitter.setStretchFactor(1, 3)
        main_splitter.setSizes([550, 350])

        outer.addWidget(main_splitter, stretch=1)
        self.setCentralWidget(central)

        self.left_rail.tab_selected.connect(self._on_tab_changed)
        self.media_panel.files_imported.connect(self._on_media_files_imported)
        self.media_panel.voice_folder_import_requested.connect(self._on_add_voice_folder_requested)
        self.media_panel.files_removed.connect(self._on_media_files_removed)
        self.media_panel.media_double_clicked.connect(self._on_add_clip)
        self.media_panel.media_add_requested.connect(self._on_add_clip_from_card)
        self.media_panel.media_selection_changed.connect(self._on_media_selection_changed)
        self._media_ingest.status_changed.connect(self._on_ingest_status_changed)
        self._media_ingest.metadata_ready.connect(self._on_ingest_metadata_ready)
        self._media_ingest.thumbnail_ready.connect(self._on_ingest_thumbnail_ready)
        self._media_ingest.proxy_ready.connect(self._on_ingest_proxy_ready)
        self._media_ingest.audio_proxy_ready.connect(self._on_ingest_audio_proxy_ready)
        self.text_panel.subtitle_add_requested.connect(self._on_add_clip_from_card)
        self.text_panel.subtitle_files_imported.connect(self._on_subtitle_files_imported)
        self.text_panel.subtitle_files_removed.connect(self._on_subtitle_files_removed)
        self.voice_match_panel.generate_requested.connect(self._on_voice_match_generate_requested)
        self.voice_match_panel.import_requested.connect(self._on_voice_match_import_requested)
        self.voice_match_panel.show_original_requested.connect(self._on_voice_match_show_original)
        self.voice_match_panel.show_matched_requested.connect(self._on_voice_match_show_matched)
        self.timeline_panel.media_drop_requested.connect(self._on_drop_add_clip)
        self.media_panel.relink_requested.connect(self._on_relink_media)
        self.text_panel.relink_subtitle_requested.connect(self._on_relink_subtitle)
        self.timeline_panel.selection_changed.connect(self._on_timeline_selection_changed)
        self.timeline_panel.subtitle_edit_translate_requested.connect(
            self._on_timeline_edit_subtitle_translate
        )
        self.timeline_panel.subtitle_batch_translate_requested.connect(
            self._translate_subtitle_track_batch
        )
        self.inspector_panel.clip_changed.connect(self._on_inspector_clip_changed)
        self.inspector_panel.translate_requested.connect(self._translate_subtitle_clip)
        self.timeline_panel.save_requested.connect(self._save_project)
        self.timeline_panel.undo_requested.connect(self._undo_timeline)
        self.timeline_panel.redo_requested.connect(self._redo_timeline)
        self.preview_panel.playpause_requested.connect(self._on_preview_playpause_requested)
        self.preview_panel.position_changed.connect(self._on_preview_position_changed)
        self.timeline_panel.seek_requested.connect(self._on_timeline_seek)
        self.preview_panel.playback_state_changed.connect(
            self._on_preview_playback_state_changed
        )
        self.preview_panel.media_ended.connect(self._on_preview_media_ended)
        self.text_panel.template_chosen.connect(self._on_subtitle_template)
        self.timeline_panel.user_pause_requested.connect(
            self._pause_timeline_playback_for_user_action
        )
        self.timeline_panel.project_mutated.connect(self._on_timeline_project_mutated)
        # OCR connections
        self.text_panel.start_ocr_requested.connect(self._on_start_ocr_button_clicked)
        self.text_panel.ocr_cancel_requested.connect(self._on_ocr_cancelled)
        self.preview_panel.ocr_cancelled.connect(self._on_ocr_cancelled)
        self.inspector_panel.cue_double_clicked.connect(self._on_ocr_cue_double_clicked)
        self.inspector_panel.caption_clip_double_clicked.connect(
            self._on_caption_clip_double_clicked
        )
        self.inspector_panel.caption_clip_selected.connect(
            self._on_caption_clip_selected
        )
        self.inspector_panel.caption_add_requested.connect(self._on_caption_add)
        self.inspector_panel.caption_delete_requested.connect(self._on_caption_delete)
        self.inspector_panel.caption_text_edit_requested.connect(
            self._on_caption_text_edit
        )
        self.inspector_panel.caption_find_replace_requested.connect(
            self._on_caption_find_replace
        )
        self.inspector_panel.caption_filter_requested.connect(self._on_caption_filter)
        self.text_panel.card_selected.connect(self._on_text_card_selected)
        if hasattr(self.preview_panel, "_sub_overlay"):
            self.preview_panel._sub_overlay.position_changed.connect(
                self._on_overlay_position_changed
            )
            self.preview_panel._sub_overlay.font_size_changed.connect(
                self._on_overlay_font_size_changed
            )
            self.preview_panel._sub_overlay.drag_finished.connect(
                self._push_timeline_history
            )
        self.preview_panel.transform_changed.connect(self._on_overlay_transform_changed)
        self.preview_panel.transform_finished.connect(self._push_timeline_history)
        # self.inspector_panel.start_ocr_requested.connect(self._on_start_ocr_button_clicked) # Removed
        self._ocr_worker = None
        # Cache last OCR cues so user can re-open the OCR RESULTS panel.
        self._last_ocr_cues: CueList | None = None

    def _on_preview_position_changed(self, ms: int) -> None:
        if self._preview_sync_mode != "timeline":
            return
        if self._gap_play_active:
            # Timeline playback is clock-driven so source loading cannot stall the playhead.
            return
        if self.timeline_panel.is_playhead_scrubbing():
            return
        media_seconds = ms / 1000.0
        timeline_seconds = media_seconds
        clip = self._preview_active_media_clip
        if clip is not None and not clip.is_text_clip:
            timeline_seconds = _source_to_timeline_seconds(clip, media_seconds)
            clip_end = self._clip_end_seconds(clip)
            if timeline_seconds >= clip_end - 1e-4:
                transition_time = self._clamp_timeline_seconds(max(clip_end, timeline_seconds))
                self.timeline_panel.set_playhead(transition_time)
                self.timeline_panel.set_playing_state(True)
                self._start_timeline_playback_at(transition_time)
                return
        timeline_seconds = self._clamp_timeline_seconds(timeline_seconds)
        self._apply_preview_audio_state(clip, timeline_seconds)
        self._sync_timeline_audio_for_time(
            timeline_seconds,
            playing=self.preview_panel.is_playing(),
        )
        self.timeline_panel.set_playhead(timeline_seconds)
        self._update_subtitle_overlay(timeline_seconds)
        self._auto_select_text_clip_at_playhead()
        try:
            info = self.inspector_panel._info
            if info._btn_text_tab_caption.isChecked() and info._text_tab_stack.currentIndex() == 0:
                info._caption_list.scroll_to_clip_at_time(timeline_seconds)
        except Exception:
            pass

    def _on_timeline_selection_changed(self, clip: object) -> None:
        self._preview_sync_mode = "timeline"
        if self._suspend_timeline_selection_sync:
            return
        try:
            selected = self.timeline_panel.selected_clips()
        except Exception:
            selected = []
        if len(selected) > 1 and all(bool(getattr(c, "is_text_clip", False)) for c in selected):
            QTimer.singleShot(0, self.inspector_panel.show_caption_list_neutral)
            return
        QTimer.singleShot(
            0,
            lambda c=clip: self._set_clip_in_inspector(
                c,
                prefer_caption_tab_for_text=isinstance(c, Clip) and bool(c.is_text_clip),
            ),
        )
        
        # Toggle transform overlay based on selection
        selected = self.timeline_panel.selected_clips()
        if len(selected) == 1 and isinstance(selected[0], Clip) and not selected[0].is_text_clip:
            self.preview_panel.set_transform_overlay_active(True)
        else:
            self.preview_panel.set_transform_overlay_active(False)

    @staticmethod
    def _clip_restore_key(clip: Clip | None) -> tuple[str, float, float, float, bool, str] | None:
        if clip is None:
            return None
        return (
            clip.source,
            float(clip.start),
            float(clip.in_point),
            float(clip.out_point if clip.out_point is not None else -1.0),
            bool(getattr(clip, "is_text_clip", False)),
            (clip.text_main or "") if bool(getattr(clip, "is_text_clip", False)) else "",
        )

    def _find_clip_by_restore_key(
        self, key: tuple[str, float, float, float, bool, str] | None
    ) -> Clip | None:
        if key is None:
            return None
        src, start, in_point, out_point, is_text, text_main = key
        for track in self.project.tracks:
            for clip in track.clips:
                if clip.source != src:
                    continue
                if abs(float(clip.start) - start) > 1e-6:
                    continue
                if abs(float(clip.in_point) - in_point) > 1e-6:
                    continue
                clip_out = float(clip.out_point if clip.out_point is not None else -1.0)
                if abs(clip_out - out_point) > 1e-6:
                    continue
                clip_is_text = bool(getattr(clip, "is_text_clip", False))
                if clip_is_text != is_text:
                    continue
                if is_text and (clip.text_main or "") != text_main:
                    continue
                return clip
        return None

    def _snapshot_window_toggle_state(self) -> dict[str, object]:
        info = self.inspector_panel._info
        selected_clip = self.inspector_panel.current_clip()
        selected_timeline_clips = self.timeline_panel.selected_clips()
        side_idx = int(self.side_stack.currentIndex())
        left_tab_key = {
            0: TAB_MEDIA,
            1: TAB_TEXT,
            2: TAB_VOICE_MATCH,
        }.get(side_idx, TAB_MEDIA)
        inspector_title = ""
        try:
            inspector_title = str(info.current_title())
        except Exception:
            inspector_title = ""
        caption_neutral = bool(
            info._btn_text_tab_caption.isChecked()
            and selected_clip is None
            and selected_timeline_clips
            and all(bool(getattr(c, "is_text_clip", False)) for c in selected_timeline_clips)
        )
        timeline_hscroll = 0
        try:
            timeline_hscroll = int(self.timeline_panel._view.horizontalScrollBar().value())
        except Exception:
            timeline_hscroll = 0
        caption_scroll = 0
        try:
            caption_scroll = int(info._caption_list._table.verticalScrollBar().value())
        except Exception:
            caption_scroll = 0
        return {
            "side_stack": side_idx,
            "sub_nav_stack": int(self.sub_nav_stack.currentIndex()),
            "left_tab_key": left_tab_key,
            "inspector_stack": int(self.inspector_panel._stack.currentIndex()),
            "inspector_title": inspector_title,
            "is_project_properties": inspector_title == "PROJECT PROPERTIES" and selected_clip is None,
            "is_text_properties_neutral": inspector_title == "TEXT PROPERTIES" and selected_clip is None,
            "text_tab_index": int(info._text_tab_stack.currentIndex()),
            "tab_caption_checked": bool(info._btn_text_tab_caption.isChecked()),
            "tab_text_checked": bool(info._btn_text_tab_text.isChecked()),
            "selected_clip_obj": selected_clip,
            "selected_clip_key": self._clip_restore_key(selected_clip),
            "selected_timeline_clip_objs": selected_timeline_clips,
            "selected_timeline_clip_keys": [
                key
                for key in (self._clip_restore_key(c) for c in selected_timeline_clips)
                if key is not None
            ],
            "caption_neutral": caption_neutral,
            "playhead": float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)),
            "timeline_hscroll": timeline_hscroll,
            "caption_scroll": caption_scroll,
        }

    def _restore_window_toggle_state(self, snap: dict[str, object]) -> None:
        side_idx = int(snap.get("side_stack", 0))
        left_tab_key = snap.get("left_tab_key")
        if left_tab_key not in (TAB_MEDIA, TAB_TEXT, TAB_VOICE_MATCH):
            left_tab_key = {
                0: TAB_MEDIA,
                1: TAB_TEXT,
                2: TAB_VOICE_MATCH,
            }.get(side_idx, TAB_MEDIA)
        self._set_left_tab(left_tab_key)

        inspector_idx = int(snap.get("inspector_stack", 0))
        if 0 <= inspector_idx < self.inspector_panel._stack.count():
            self.inspector_panel._stack.setCurrentIndex(inspector_idx)

        selected_clips: list[Clip] = []
        clip_objs = snap.get("selected_timeline_clip_objs")
        if isinstance(clip_objs, list):
            selected_clips = [c for c in clip_objs if isinstance(c, Clip)]
        if not selected_clips:
            clip_keys = snap.get("selected_timeline_clip_keys")
            if isinstance(clip_keys, list):
                for key in clip_keys:
                    if not isinstance(key, tuple):
                        continue
                    restored = self._find_clip_by_restore_key(key)
                    if restored is not None:
                        selected_clips.append(restored)

        selected_clip = snap.get("selected_clip_obj")
        clip = selected_clip if isinstance(selected_clip, Clip) else None
        if clip is None:
            key = snap.get("selected_clip_key")
            clip = self._find_clip_by_restore_key(key if isinstance(key, tuple) else None)

        if selected_clips:
            self.timeline_panel.select_clips(selected_clips)
        else:
            self.timeline_panel.select_clip(clip)

        restore_caption_neutral = bool(snap.get("caption_neutral", False))
        want_caption_tab = bool(snap.get("tab_caption_checked", False))
        was_project_properties = bool(snap.get("is_project_properties", False))
        was_text_properties_neutral = bool(snap.get("is_text_properties_neutral", False))
        has_only_text_selection = bool(selected_clips) and all(
            bool(getattr(c, "is_text_clip", False)) for c in selected_clips
        )
        if was_project_properties:
            self._set_clip_in_inspector(None)
        elif was_text_properties_neutral or (restore_caption_neutral and has_only_text_selection):
            self.inspector_panel.show_caption_list_neutral()
        elif (
            want_caption_tab
            and clip is not None
            and bool(getattr(clip, "is_text_clip", False))
        ):
            self._set_clip_in_inspector(clip, prefer_caption_tab_for_text=True)
        else:
            self._set_clip_in_inspector(clip)

        info = self.inspector_panel._info
        if (
            (clip is not None and bool(getattr(clip, "is_text_clip", False)))
            or was_text_properties_neutral
            or (restore_caption_neutral and has_only_text_selection)
        ):
            text_tab_index = int(snap.get("text_tab_index", 0))
            if bool(snap.get("tab_caption_checked", False)):
                info._btn_text_tab_caption.setChecked(True)
            elif bool(snap.get("tab_text_checked", False)):
                info._btn_text_tab_text.setChecked(True)
            elif text_tab_index in (0, 1):
                info._text_tab_stack.setCurrentIndex(text_tab_index)

            try:
                caption_scroll = int(snap.get("caption_scroll", 0))
                info._caption_list._table.verticalScrollBar().setValue(caption_scroll)
            except Exception:
                pass

        playhead = float(snap.get("playhead", 0.0))
        self.timeline_panel.set_playhead(playhead)

        try:
            timeline_hscroll = int(snap.get("timeline_hscroll", 0))
            self.timeline_panel._view.horizontalScrollBar().setValue(max(0, timeline_hscroll))
        except Exception:
            pass

    def _pause_timeline_playback_for_user_action(self) -> bool:
        if not bool(getattr(self.timeline_panel, "_is_playing", False)):
            return False
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        self._stop_gap_playback()
        self.timeline_panel.set_playing_state(False)
        self.preview_panel.pause()
        self.preview_panel.set_timeline_playing_override(False)
        self._set_preview_timeline_time_display(current)
        self._sync_timeline_audio_for_time(
            current,
            playing=False,
            force_seek=False,
        )
        return True

    def _on_timeline_playpause_requested(self) -> None:
        self._preview_sync_mode = "timeline"
        want_play = bool(getattr(self.timeline_panel, "_is_playing", False))
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        if not want_play:
            self._stop_gap_playback()
            self.timeline_panel.set_playing_state(False)
            self.preview_panel.pause()
            self.preview_panel.set_timeline_playing_override(False)
            self._set_preview_timeline_time_display(current)
            self._sync_timeline_audio_for_time(
                current,
                playing=False,
                force_seek=False,
            )
            return
        if not self._timeline_has_any_components():
            self.timeline_panel.set_playing_state(False)
            self.preview_panel.set_timeline_playing_override(False)
            self._sync_timeline_audio_for_time(
                current,
                playing=False,
                force_seek=True,
            )
            return
        play_time, _clip = self._resolve_timeline_play_start(current)
        duration = self._timeline_duration_seconds()
        if duration > 0.0 and play_time >= duration:
            play_time = 0.0
            self.timeline_panel.set_playhead(play_time)
        self._start_gap_playback()
        self._start_timeline_playback_at(play_time)

    def _on_preview_playpause_requested(self) -> None:
        if self._timeline_has_any_components():
            self._preview_sync_mode = "timeline"
            want_play = not bool(getattr(self.timeline_panel, "_is_playing", False))
            self.timeline_panel.set_playing_state(want_play)
            self._on_timeline_playpause_requested()
            return
        self.preview_panel.clear_timeline_time_display()
        self.preview_panel.set_timeline_playing_override(None)
        self.preview_panel.toggle_play_pause()

    def _on_preview_playback_state_changed(self, playing: bool) -> None:
        if self._preview_sync_mode != "timeline":
            return
        if self._gap_play_active:
            # Timeline master clock owns transport; player state changes are only sink state.
            self.timeline_panel.set_playing_state(True)
            return
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        self._sync_timeline_audio_for_time(
            current,
            playing=bool(playing),
            force_seek=True,
        )

    def _on_preview_media_ended(self) -> None:
        if self._preview_sync_mode != "timeline":
            return
        if self._gap_play_active:
            return

        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        ended_clip = self._preview_active_media_clip
        if ended_clip is not None:
            current = max(current, self._clip_end_seconds(ended_clip))

        next_time = next_playable_time_after(self.project.tracks, current)
        if next_time is None:
            self._stop_gap_playback()
            self.timeline_panel.set_playing_state(False)
            self.preview_panel.set_timeline_playing_override(False)
            self.preview_panel.clear_timeline_audio()
            return

        self._on_timeline_seek(next_time)
        self.timeline_panel.set_playing_state(True)
        self._start_timeline_playback_at(next_time)

    def _set_preview_source(self, path: Path | str, *, force: bool = False) -> None:
        path_str = str(path)
        if not force and self._preview_source_path == path_str:
            return
        self.preview_panel.load(path)
        self._preview_source_path = path_str

    def _timeline_duration_seconds(self) -> float:
        cached = self._timeline_duration_cache
        if cached is not None:
            return cached
        try:
            duration = max(0.0, float(self.project.duration))
        except Exception:
            duration = 0.0
        self._timeline_duration_cache = duration
        return duration

    def _clamp_timeline_seconds(self, seconds: float) -> float:
        try:
            s = max(0.0, float(seconds))
        except Exception:
            s = 0.0
        end = self._timeline_duration_seconds()
        if end > 0.0:
            return min(s, end)
        return 0.0

    def _set_preview_timeline_time_display(self, seconds: float) -> None:
        seconds = self._clamp_timeline_seconds(seconds)
        self.preview_panel.set_timeline_time_display(
            int(seconds * 1000.0),
            int(self._timeline_duration_seconds() * 1000.0),
        )

    def _clear_preview_video_when_no_video(self) -> None:
        self._preview_active_media_clip = None
        self._preview_source_path = None
        self._apply_preview_video_transform(None)
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        self._apply_preview_audio_state(None, current)
        self.preview_panel.clear_video_preview()

    @staticmethod
    def _source_key_for_path(path: Path | str) -> str:
        try:
            return str(Path(path).resolve())
        except Exception:
            return str(path)

    def _invalidate_clip_interval_indexes(self) -> None:
        self._clip_interval_indexes_dirty = True
        self._timeline_duration_cache = None
        self._clip_track_map.clear()
        self._audio_proxy_path_cache.clear()
        self._clip_audio_preview_path_cache.clear()
        self._clip_deferred_audio_proxy_cache.clear()
        self._timeline_audio_active_clip_id = None

    def _ensure_clip_interval_indexes(self) -> None:
        if not self._clip_interval_indexes_dirty:
            return
        self._audio_clip_index.rebuild(audible_audio_tracks(self.project.tracks))
        video_tracks: list[Track] = []
        main_track = self._main_video_track()
        if main_track is not None and main_track.clips:
            video_tracks.append(main_track)
        for track in self.project.tracks:
            if track is main_track:
                continue
            if track.kind == "video" and track.clips and not self._is_track_hidden(track):
                video_tracks.append(track)
        self._video_clip_index.rebuild(video_tracks)
        self._clip_interval_indexes_dirty = False

    def _cached_media_info_for_path(self, path: Path | str) -> CachedMediaInfo | None:
        try:
            return self._media_ingest.cache.get(path)
        except Exception:
            return None

    def _duration_for_insert(
        self,
        path: Path | str,
        *,
        fallback: float = 5.0,
    ) -> tuple[float, bool]:
        path_obj = Path(path)
        cached = self._cached_media_info_for_path(path_obj)
        if cached is not None and cached.duration and cached.duration > 0.0:
            return float(cached.duration), False
        try:
            norm = str(path_obj.resolve()).lower()
        except Exception:
            norm = str(path_obj).lower()
        for entry in getattr(self.project, "library_media", []) or []:
            try:
                entry_norm = str(Path(str(entry.source)).resolve()).lower()
            except Exception:
                entry_norm = str(getattr(entry, "source", "") or "").lower()
            if entry_norm == norm:
                try:
                    duration = float(getattr(entry, "duration", 0.0) or 0.0)
                except Exception:
                    duration = 0.0
                if duration > 0.0:
                    return duration, False
                break
        return max(0.001, float(fallback)), True

    def _register_placeholder_clip(self, clip: Clip) -> None:
        self._duration_placeholder_clip_ids.add(id(clip))
        source_key = self._source_key_for_path(clip.source)
        self._duration_placeholder_by_source_key.setdefault(source_key, []).append(clip)

    def _unregister_placeholder_clip(self, clip: Clip) -> None:
        self._duration_placeholder_clip_ids.discard(id(clip))
        source_key = self._source_key_for_path(clip.source)
        bucket = self._duration_placeholder_by_source_key.get(source_key)
        if bucket is None:
            return
        try:
            bucket.remove(clip)
        except ValueError:
            pass
        if not bucket:
            self._duration_placeholder_by_source_key.pop(source_key, None)

    def _audio_proxy_for_source_path(self, path: Path | str) -> Path | None:
        raw_key = str(path)
        if raw_key in self._audio_proxy_path_cache:
            return self._audio_proxy_path_cache[raw_key]

        proxy = self._audio_proxy_by_source.get(raw_key)
        if proxy:
            proxy_path_obj = Path(proxy)
            if proxy_path_obj.exists():
                self._audio_proxy_path_cache[raw_key] = proxy_path_obj
                return proxy_path_obj

        key = self._source_key_for_path(path)
        proxy = self._audio_proxy_by_source.get(key)
        if proxy:
            proxy_path_obj = Path(proxy)
            if proxy_path_obj.exists():
                self._audio_proxy_path_cache[raw_key] = proxy_path_obj
                return proxy_path_obj

        cached = audio_proxy_path(path)
        if cached.exists() and cached.stat().st_size > 0:
            self._audio_proxy_by_source[key] = str(cached)
            self._audio_proxy_by_source[raw_key] = str(cached)
            self._audio_proxy_path_cache[raw_key] = cached
            return cached
        self._audio_proxy_path_cache[raw_key] = None
        return None

    def _clip_audio_preview_path(self, clip: Clip) -> Path:
        if not self._use_audio_proxies:
            return Path(clip.source)
        clip_key = id(clip)
        cached = self._clip_audio_preview_path_cache.get(clip_key)
        if cached is not None:
            return cached
        proxy = self._audio_proxy_for_source_path(clip.source)
        if proxy is not None:
            self._clip_audio_preview_path_cache[clip_key] = proxy
            return proxy
        source = Path(clip.source)
        self._clip_audio_preview_path_cache[clip_key] = source
        return source

    def _clip_uses_deferred_audio_proxy(self, clip: Clip, path: Path) -> bool:
        clip_key = id(clip)
        cached = self._clip_deferred_audio_proxy_cache.get(clip_key)
        if cached is not None:
            return cached
        source_raw = str(getattr(clip, "source", "") or "")
        if str(path) != source_raw:
            self._clip_deferred_audio_proxy_cache[clip_key] = False
            return False
        uses_deferred = Path(source_raw).suffix.lower() != ".wav"
        self._clip_deferred_audio_proxy_cache[clip_key] = uses_deferred
        return uses_deferred

    def _clip_preview_path(self, clip: Clip) -> Path:
        track = self._find_track_for_clip(clip)
        if track is not None and track.kind == "audio":
            return self._clip_audio_preview_path(clip)

        proxy = str(getattr(clip, "proxy", "") or "").strip()
        if proxy:
            proxy_path_obj = Path(proxy)
            if proxy_path_obj.exists():
                return proxy_path_obj
        return Path(clip.source)

    def _source_has_audio_stream(self, path: Path) -> bool:
        ext = path.suffix.lower()
        if ext in self._AUDIO_EXTS:
            return True
        key = self._source_key_for_path(path)
        cached = self._preview_audio_presence_cache.get(key)
        if cached is not None:
            return cached
        info = self._cached_media_info_for_path(path)
        if info is not None:
            has_audio = bool(info.has_audio)
            self._preview_audio_presence_cache[key] = has_audio
            return has_audio
        try:
            self._media_ingest.enqueue(path)
        except Exception:
            pass
        return True

    def _clip_has_preview_audio(self, clip: Clip) -> bool:
        track = self._find_track_for_clip(clip)
        if track is not None and track.kind == "audio":
            return True
        if clip.is_text_clip:
            return False
        return self._source_has_audio_stream(self._clip_preview_path(clip))

    def _set_preview_source_for_clip(self, clip: Clip, *, force: bool = False) -> None:
        self._preview_active_media_clip = clip
        self._set_preview_source(self._clip_preview_path(clip), force=force)
        self.preview_panel.set_playback_rate(float(getattr(clip, "speed", 1.0) or 1.0))

    def _play_preview_clip_at(self, clip: Clip, timeline_seconds: float) -> None:
        self._preview_active_media_clip = clip
        preview_path = self._clip_preview_path(clip)
        source_ms = int(_timeline_to_source_seconds(clip, timeline_seconds) * 1000.0)
        self._preview_source_path = str(preview_path)
        self.preview_panel.load_seek_play(
            preview_path,
            source_ms,
            rate=float(getattr(clip, "speed", 1.0) or 1.0),
        )

    def _prewarm_timeline_cache_for_clips(self, clips: list[Clip]) -> None:
        if not clips:
            return
        try:
            self.timeline_panel.prewarm_track_clips(clips)
            self.statusBar().showMessage(
                "Loading timeline media cache in background...",
                3500,
            )
        except Exception:
            pass

    def _schedule_timeline_cache_prewarm(self, clips: list[Clip]) -> None:
        if not clips:
            return
        QTimer.singleShot(
            0,
            lambda items=list(clips): self._prewarm_timeline_cache_for_clips(items),
        )

    def _start_gap_playback(self) -> None:
        # This timer is the timeline master clock; it also drives gaps.
        self._gap_play_active = True
        self._gap_play_last_ts = monotonic()
        self._gap_play_last_full_sync_ts = self._gap_play_last_ts
        self._video_clock_last_resync_ts = 0.0
        if not self._gap_play_timer.isActive():
            self._gap_play_timer.start()
        self.timeline_panel.set_playing_state(True)
        self.preview_panel.set_timeline_playing_override(True)
        self._set_preview_timeline_time_display(
            float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        )

    def _stop_gap_playback(self) -> None:
        self._gap_play_active = False
        self._gap_play_last_ts = 0.0
        self._gap_play_last_full_sync_ts = 0.0
        self._video_clock_last_resync_ts = 0.0
        if self._gap_play_timer.isActive():
            self._gap_play_timer.stop()

    def _start_timeline_playback_at(self, timeline_seconds: float) -> None:
        s = self._clamp_timeline_seconds(timeline_seconds)
        if bool(getattr(self.timeline_panel, "_is_playing", False)) and not self._gap_play_active:
            self._start_gap_playback()
        self._sync_preview_for_timeline_clock(
            s,
            playing=True,
            force_seek=True,
        )
        self._schedule_preview_resume_resync()

    def _schedule_preview_resume_resync(self) -> None:
        self._preview_resume_resync_generation += 1
        generation = self._preview_resume_resync_generation

        def _resync() -> None:
            if generation != self._preview_resume_resync_generation:
                return
            if self._preview_sync_mode != "timeline" or not self._gap_play_active:
                return
            if not bool(getattr(self.timeline_panel, "_is_playing", False)):
                return
            current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
            if self._pick_video_clip_for_time(current) is None:
                return
            self._sync_preview_for_timeline_clock(
                current,
                playing=True,
                force_seek=True,
            )

        QTimer.singleShot(self._VIDEO_RESUME_RESYNC_DELAY_MS, _resync)

    def _resync_preview_video_if_clock_drifted(
        self,
        source_ms: int,
        *,
        rate: float,
    ) -> bool:
        try:
            player_ms = int(self.preview_panel.main_player_position_ms())
        except Exception:
            return False
        threshold_ms = int(
            getattr(
                self,
                "_VIDEO_CLOCK_RESYNC_THRESHOLD_MS",
                MainWindow._VIDEO_CLOCK_RESYNC_THRESHOLD_MS,
            )
        )
        if abs(player_ms - int(source_ms)) <= threshold_ms:
            return False
        self.preview_panel.set_playback_rate(rate)
        self.preview_panel.force_seek(source_ms)
        if not self.preview_panel.main_player_is_playing():
            self.preview_panel.play()
        return True

    def _ensure_video_preview_for_time(
        self,
        seconds: float,
        *,
        playing: bool,
        force_seek: bool,
        throttle_preview: bool = False,
    ) -> None:
        s = self._clamp_timeline_seconds(seconds)
        video_clip = self._pick_video_clip_for_time(s)
        if video_clip is None:
            if (
                self._preview_active_media_clip is not None
                or self._preview_source_path is not None
                or self.preview_panel.main_player_is_playing()
            ):
                current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
                self._clear_preview_video_when_no_video()
                self._subtitle_overlay_state = None
                self._set_preview_timeline_time_display(current)
            return

        track = self._find_track_for_clip(video_clip)
        if track is not None and track.kind == "video":
            self._apply_preview_video_transform(video_clip)
        else:
            self._apply_preview_video_transform(None)
        self._apply_preview_audio_state(video_clip, s)

        preview_path = self._clip_preview_path(video_clip)
        preview_path_s = str(preview_path)
        source_ms = int(_timeline_to_source_seconds(video_clip, s) * 1000.0)
        same_clip = (
            self._preview_active_media_clip is video_clip
            and self._preview_source_path == preview_path_s
        )
        try:
            player_has_source = bool(self.preview_panel.main_player_has_source())
        except Exception:
            player_has_source = bool(self._preview_source_path)

        if playing:
            if not same_clip or force_seek or not self.preview_panel.main_player_is_playing():
                self._preview_active_media_clip = video_clip
                self._preview_source_path = preview_path_s
                self._video_clock_last_resync_ts = 0.0
                if not same_clip or force_seek:
                    self._subtitle_overlay_state = None
                self.preview_panel.load_seek_play(
                    preview_path,
                    source_ms,
                    rate=float(getattr(video_clip, "speed", 1.0) or 1.0),
                )
            else:
                now = monotonic()
                if (
                    self._video_clock_last_resync_ts <= 0.0
                    or now - self._video_clock_last_resync_ts >= self._VIDEO_CLOCK_RESYNC_INTERVAL
                ):
                    self._video_clock_last_resync_ts = now
                    self._resync_preview_video_if_clock_drifted(
                        source_ms,
                        rate=float(getattr(video_clip, "speed", 1.0) or 1.0),
                    )
            return

        self._preview_active_media_clip = video_clip
        if not same_clip or force_seek:
            self._subtitle_overlay_state = None
        self._set_preview_source_for_clip(
            video_clip,
            force=bool(force_seek and not player_has_source),
        )
        self.preview_panel.seek(source_ms, throttle=throttle_preview)
        self.preview_panel.pause()

    def _sync_preview_for_timeline_clock(
        self,
        seconds: float,
        *,
        playing: bool,
        force_seek: bool,
        throttle_preview: bool = False,
        sync_audio: bool = True,
        sync_selection: bool = True,
        sync_caption_scroll: bool = True,
    ) -> None:
        s = self._clamp_timeline_seconds(seconds)
        self._set_preview_timeline_time_display(s)
        self._ensure_video_preview_for_time(
            s,
            playing=playing,
            force_seek=force_seek,
            throttle_preview=throttle_preview,
        )
        if sync_audio:
            self._sync_timeline_audio_for_time(
                s,
                playing=playing,
                force_seek=force_seek,
            )
        self._update_subtitle_overlay(s)
        if sync_selection:
            self._auto_select_text_clip_at_playhead()
        if sync_caption_scroll and not playing:
            try:
                info = self.inspector_panel._info
                if info._btn_text_tab_caption.isChecked() and info._text_tab_stack.currentIndex() == 0:
                    info._caption_list.scroll_to_clip_at_time(s)
            except Exception:
                pass

    def _on_gap_play_tick(self) -> None:
        if not self._gap_play_active or self._preview_sync_mode != "timeline":
            self._stop_gap_playback()
            return
        if not bool(getattr(self.timeline_panel, "_is_playing", False)):
            self._stop_gap_playback()
            return

        now = monotonic()
        if self._gap_play_last_ts <= 0.0:
            self._gap_play_last_ts = now
            return
        dt = now - self._gap_play_last_ts
        self._gap_play_last_ts = now
        if dt <= 0.0:
            return
        dt = min(dt, 0.2)
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        next_seconds = self._clamp_timeline_seconds(current + dt)
        duration = self._timeline_duration_seconds()
        if duration > 0.0 and next_seconds >= duration - 1e-6:
            self.timeline_panel.set_playhead(next_seconds)
            self._sync_preview_for_timeline_clock(
                next_seconds,
                playing=False,
                force_seek=False,
            )
            self._stop_gap_playback()
            self.timeline_panel.set_playing_state(False)
            self.preview_panel.set_timeline_playing_override(False)
            return
        should_full_sync = not (
            self._gap_play_last_full_sync_ts > 0.0
            and now - self._gap_play_last_full_sync_ts < self._GAP_PLAY_FULL_SYNC_INTERVAL
        )
        if not should_full_sync:
            self.timeline_panel.set_playhead_fast(next_seconds)
            self._set_preview_timeline_time_display(next_seconds)
            return
        self._gap_play_last_full_sync_ts = now
        self.timeline_panel.set_playhead(next_seconds)
        self._sync_preview_for_timeline_clock(
            next_seconds,
            playing=True,
            force_seek=False,
            sync_selection=False,
            sync_caption_scroll=False,
        )

    def _start_proxy_generation_if_needed(
        self,
        clip: Clip,
        *,
        duration: float | None = None,
        kind: str | None = None,
    ) -> None:
        if kind is not None and kind != "video":
            return
        source = str(Path(clip.source))
        if not source:
            return
        if clip.proxy and Path(clip.proxy).exists():
            return
        try:
            dur = float(duration if duration is not None else (clip.timeline_duration or 0.0))
        except Exception:
            dur = 0.0
        if dur < self._PROXY_MIN_DURATION_SECONDS:
            return

        src_path = Path(source)
        cached = proxy_path(
            src_path,
            width=self._PROXY_PREVIEW_WIDTH,
            crf=self._PROXY_PREVIEW_CRF,
            preset="veryfast",
            audio_bitrate="96k",
        )
        if cached.exists() and cached.stat().st_size > 0:
            clip.proxy = str(cached)
            return

        source_key = str(src_path.resolve())
        self._proxy_source_to_clips.setdefault(source_key, []).append(clip)
        if source_key in self._proxy_inflight:
            return
        self._proxy_inflight.add(source_key)
        self.statusBar().showMessage(f"Creating preview proxy: {src_path.name}", 5000)

        def _job() -> None:
            try:
                info = probe(src_path)
                if not info.has_video:
                    self._proxy_ready.emit(source_key, None, "")
                    return
                generated = make_proxy(
                    src_path,
                    width=self._PROXY_PREVIEW_WIDTH,
                    crf=self._PROXY_PREVIEW_CRF,
                    preset="veryfast",
                    audio_bitrate="96k",
                )
                self._proxy_ready.emit(source_key, str(generated), "")
            except Exception as e:
                self._proxy_ready.emit(source_key, None, str(e))

        self._proxy_executor.submit(_job)

    def _on_proxy_ready(self, source_key_obj: object, proxy_obj: object, error_obj: object) -> None:
        source_key = str(source_key_obj or "")
        self._proxy_inflight.discard(source_key)
        clips = self._proxy_source_to_clips.pop(source_key, [])
        proxy = str(proxy_obj or "")
        error = str(error_obj or "")
        if not proxy:
            if error:
                self.statusBar().showMessage(f"Proxy failed: {Path(source_key).name}", 5000)
            return

        for clip in clips:
            clip.proxy = proxy
        self._prewarm_timeline_cache_for_clips(clips)

        self.timeline_panel.refresh()
        self.statusBar().showMessage(f"Preview proxy ready: {Path(source_key).name}", 5000)

        if self._preview_sync_mode == "timeline":
            current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
            active_clip = self._pick_video_clip_for_time(current)
            if active_clip is not None and str(Path(active_clip.source).resolve()) == source_key:
                playing = bool(getattr(self.timeline_panel, "_is_playing", False))
                self._sync_preview_for_timeline_clock(
                    current,
                    playing=playing,
                    force_seek=not playing,
                )

    def _start_project_proxy_generation(self) -> None:
        for track in self.project.tracks:
            if track.kind != "video":
                continue
            for clip in track.clips:
                self._start_proxy_generation_if_needed(
                    clip,
                    duration=clip.timeline_duration,
                    kind=track.kind,
                )

    def _start_audio_proxy_generation_if_needed(self, clip: Clip) -> None:
        if not self._use_audio_proxies:
            return
        if clip.is_text_clip:
            return
        source = str(getattr(clip, "source", "") or "")
        if not source:
            return
        if source in self._audio_proxy_by_source:
            return
        if source in self._audio_proxy_inflight:
            return
        src_path = Path(source)
        if not src_path.exists():
            return
        if not self._clip_has_preview_audio(clip):
            return

        source_key = self._source_key_for_path(src_path)
        if source_key in self._audio_proxy_by_source:
            self._audio_proxy_by_source[source] = self._audio_proxy_by_source[source_key]
            return
        cached = audio_proxy_path(src_path)
        if cached.exists() and cached.stat().st_size > 0:
            self._audio_proxy_by_source[source_key] = str(cached)
            self._audio_proxy_by_source[source] = str(cached)
            return
        if source_key in self._audio_proxy_inflight:
            self._audio_proxy_inflight.add(source)
            return
        self._audio_proxy_inflight.add(source_key)
        self._audio_proxy_inflight.add(source)

        def _job() -> None:
            try:
                generated = make_audio_proxy(src_path)
                self._audio_proxy_ready.emit((source_key, source), str(generated), "")
            except Exception as e:
                self._audio_proxy_ready.emit((source_key, source), "", str(e))

        self._audio_proxy_executor.submit(_job)

    def _start_project_audio_proxy_generation(self) -> None:
        if not self._use_audio_proxies:
            return
        for track in self.project.tracks:
            if track.kind not in {"video", "audio"}:
                continue
            for clip in track.clips:
                self._start_audio_proxy_generation_if_needed(clip)

    def _timeline_audio_mix_path(self) -> Path | None:
        return None

    def _invalidate_timeline_audio_mix(self, *, clear_player: bool = True) -> None:
        self._timeline_audio_mix_dirty = True
        self._timeline_audio_mix_proxy = None
        self._timeline_audio_mix_window_start = None
        self._timeline_audio_mix_window_duration = None
        self._timeline_audio_mix_is_windowed = False
        self._timeline_audio_next_mix_proxy = None
        self._timeline_audio_next_window_start = None
        self._timeline_audio_next_window_duration = None
        self._timeline_audio_mix_inflight = False
        self._timeline_audio_mix_generation_id += 1
        if clear_player:
            self.preview_panel.clear_timeline_audio()

    def _start_timeline_audio_mix_generation_if_needed(
        self,
        *,
        force: bool = False,
        anchor_seconds: float | None = None,
    ) -> None:
        # Timeline mix proxies are disabled; playback uses per-clip audio preview.
        if (
            self._timeline_audio_mix_proxy
            or self._timeline_audio_next_mix_proxy
            or self._timeline_audio_mix_inflight
        ):
            self._timeline_audio_mix_proxy = None
            self._timeline_audio_mix_window_start = None
            self._timeline_audio_mix_window_duration = None
            self._timeline_audio_mix_is_windowed = False
            self._timeline_audio_next_mix_proxy = None
            self._timeline_audio_next_window_start = None
            self._timeline_audio_next_window_duration = None
            self._timeline_audio_mix_inflight = False
            self._timeline_audio_mix_generation_id += 1
        self._timeline_audio_mix_dirty = False

    def _on_timeline_audio_mix_ready(
        self,
        generation_obj: object,
        proxy_obj: object,
        error_obj: object,
    ) -> None:
        self._timeline_audio_mix_inflight = False
        self._timeline_audio_mix_proxy = None
        self._timeline_audio_mix_window_start = None
        self._timeline_audio_mix_window_duration = None
        self._timeline_audio_mix_is_windowed = False
        self._timeline_audio_next_mix_proxy = None
        self._timeline_audio_next_window_start = None
        self._timeline_audio_next_window_duration = None
        self._timeline_audio_mix_dirty = False

    def _on_audio_proxy_ready(self, source_key_obj: object, proxy_obj: object, error_obj: object) -> None:
        raw_source = ""
        if isinstance(source_key_obj, tuple) and source_key_obj:
            source_key = str(source_key_obj[0] or "")
            if len(source_key_obj) > 1:
                raw_source = str(source_key_obj[1] or "")
        else:
            source_key = str(source_key_obj or "")
        self._audio_proxy_inflight.discard(source_key)
        if raw_source:
            self._audio_proxy_inflight.discard(raw_source)
        self._audio_proxy_path_cache.clear()
        self._clip_audio_preview_path_cache.clear()
        self._clip_deferred_audio_proxy_cache.clear()
        proxy = str(proxy_obj or "")
        if proxy:
            self._audio_proxy_by_source[source_key] = proxy
            if raw_source:
                self._audio_proxy_by_source[raw_source] = proxy
            self.statusBar().showMessage(
                f"Audio preview ready: {Path(source_key).name}",
                3000,
            )
            current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
            self._ensure_clip_interval_indexes()
            active_clip = pick_timeline_audio_clip(
                self.project.tracks,
                current,
                fallback_to_first=False,
                index=self._audio_clip_index,
            )
            if (
                bool(getattr(self.timeline_panel, "_is_playing", False))
                and active_clip is not None
                and self._source_key_for_path(active_clip.source) == source_key
            ):
                self._sync_preview_for_timeline_clock(
                    current,
                    playing=True,
                    force_seek=False,
                )
            return

        error = str(error_obj or "")
        if error:
            self.statusBar().showMessage(
                f"Audio preview failed: {Path(source_key).name}",
                3000,
            )

    @staticmethod
    def _clip_end_seconds(clip: Clip) -> float:
        dur = clip.timeline_duration or 0.0
        return clip.start + max(0.0, dur)

    @staticmethod
    def _clip_contains_time(clip: Clip, seconds: float) -> bool:
        start = float(clip.start)
        end = start + float(clip.timeline_duration or 0.0)
        return start <= float(seconds) < end

    @staticmethod
    def _preview_fade_multiplier(clip: Clip, timeline_seconds: float) -> float:
        return clip_fade_multiplier(clip, timeline_seconds)

    def _apply_preview_audio_state(self, clip: Clip | None, timeline_seconds: float) -> None:
        if self._preview_sync_mode == "timeline" and self._timeline_audio_mix_path() is not None:
            self.preview_panel.set_audio_muted(True)
            self.preview_panel.set_audio_gain(0.0)
            return
        if clip is None:
            self.preview_panel.set_audio_muted(False)
            self.preview_panel.set_audio_gain(1.0)
            return
        track = self._find_track_for_clip(clip)
        is_muted = self._is_track_muted(track) if track is not None else False
        self.preview_panel.set_audio_muted(is_muted)
        if is_muted:
            self.preview_panel.set_audio_gain(0.0)
            return
        base = max(0.0, float(getattr(clip, "volume", 1.0) or 0.0))
        base *= track_output_gain(track)
        gain = base * self._preview_fade_multiplier(clip, timeline_seconds)
        self.preview_panel.set_audio_gain(gain)

    def _pick_video_clip_for_time(self, seconds: float) -> Clip | None:
        s = max(0.0, float(seconds))
        self._ensure_clip_interval_indexes()
        return self._video_clip_index.find(s)

    def _pick_preview_clip_for_time(
        self,
        seconds: float,
        *,
        fallback_to_first: bool = False,
    ) -> Clip | None:
        s = max(0.0, float(seconds))
        video_candidate = self._pick_video_clip_for_time(s)
        if video_candidate is not None:
            return video_candidate

        audio_index = None
        ensure_indexes = getattr(self, "_ensure_clip_interval_indexes", None)
        if callable(ensure_indexes):
            ensure_indexes()
            audio_index = getattr(self, "_audio_clip_index", None)
        audio_candidate = pick_timeline_audio_clip(
            self.project.tracks,
            s,
            fallback_to_first=fallback_to_first,
            index=audio_index,
        )
        if audio_candidate is not None:
            return audio_candidate

        if fallback_to_first:
            main = self._main_video_track()
            if main is not None and main.clips:
                return main.clips[0]
            for track in self.project.tracks:
                if track.kind == "video" and track.clips and not self._is_track_hidden(track):
                    return track.clips[0]
        return None

    def _main_preview_is_audio_clip(self, clip: Clip | None) -> bool:
        if clip is None:
            return False
        track = self._find_track_for_clip(clip)
        return track is not None and track.kind == "audio"

    def _sync_timeline_audio_for_time(
        self,
        timeline_seconds: float,
        *,
        playing: bool,
        force_seek: bool = False,
    ) -> None:
        self._ensure_clip_interval_indexes()
        audio_clip = pick_timeline_audio_clip(
            self.project.tracks,
            timeline_seconds,
            fallback_to_first=False,
            index=self._audio_clip_index,
        )
        if audio_clip is None:
            if (
                self._timeline_audio_active_clip_id is not None
                or getattr(self.preview_panel, "_timeline_audio_source_path", None)
            ):
                self.preview_panel.clear_timeline_audio()
            self._timeline_audio_active_clip_id = None
            return

        track = self._find_track_for_clip(audio_clip)
        if track is None or self._is_track_hidden(track) or self._is_track_muted(track):
            if (
                self._timeline_audio_active_clip_id is not None
                or getattr(self.preview_panel, "_timeline_audio_source_path", None)
            ):
                self.preview_panel.clear_timeline_audio()
            self._timeline_audio_active_clip_id = None
            return

        clip_id = id(audio_clip)
        if playing and not force_seek and self._timeline_audio_active_clip_id == clip_id:
            return

        source_ms = int(_timeline_to_source_seconds(audio_clip, timeline_seconds) * 1000.0)
        gain = max(0.0, float(audio_clip.volume or 0.0))
        gain *= track_output_gain(track)
        gain *= self._preview_fade_multiplier(audio_clip, timeline_seconds)
        audio_path = self._clip_audio_preview_path(audio_clip)
        if self._use_audio_proxies and self._clip_uses_deferred_audio_proxy(audio_clip, audio_path):
            self._start_audio_proxy_generation_if_needed(audio_clip)
        self._timeline_audio_active_clip_id = clip_id
        self.preview_panel.sync_timeline_audio(
            audio_path,
            source_ms,
            playback_rate=float(audio_clip.speed or 1.0),
            gain=gain,
            muted=False,
            playing=playing,
            force_seek=force_seek,
        )

    def _ensure_preview_source_for_time(self, seconds: float) -> None:
        clip = self._pick_video_clip_for_time(seconds)
        if clip is None:
            return
        self._set_preview_source_for_clip(clip)

    def _apply_preview_video_transform(self, clip: Clip | None) -> None:
        if clip is None:
            self.preview_panel.clear_video_transform()
            return
        self.preview_panel.set_video_transform(
            scale=clip.scale,
            scale_x=clip.scale_x,
            scale_y=clip.scale_y,
            pos_x=clip.pos_x,
            pos_y=clip.pos_y,
            rotate=clip.effects.rotate,
            canvas_size=(int(self.project.width), int(self.project.height)),
        )

    def _on_timeline_seek(self, seconds: float) -> None:
        self._preview_sync_mode = "timeline"
        seconds = self._clamp_timeline_seconds(seconds)
        if abs(float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)) - seconds) > 1e-6:
            self.timeline_panel.set_playhead(seconds)
        try:
            throttle_preview = self.timeline_panel.take_last_seek_request_was_scrub()
        except Exception:
            throttle_preview = False
        try:
            is_user_scrub = bool(throttle_preview or self.timeline_panel.is_playhead_scrubbing())
        except Exception:
            is_user_scrub = bool(throttle_preview)
        if is_user_scrub:
            self._pause_timeline_playback_for_user_action()
            if (
                self._timeline_audio_active_clip_id is not None
                or getattr(self.preview_panel, "_timeline_audio_source_path", None)
            ):
                self.preview_panel.clear_timeline_audio()
                self._timeline_audio_active_clip_id = None
            self._schedule_scrub_finish_sync(seconds)
        self._sync_preview_for_timeline_clock(
            float(seconds),
            playing=bool(getattr(self.timeline_panel, "_is_playing", False)),
            force_seek=True,
            throttle_preview=throttle_preview,
            sync_audio=not is_user_scrub,
            sync_selection=not is_user_scrub,
            sync_caption_scroll=not is_user_scrub,
        )

    def _schedule_timeline_preview_prime(self, seconds: float) -> None:
        self._timeline_preview_prime_generation += 1
        generation = int(self._timeline_preview_prime_generation)
        target_seconds = float(seconds)

        def _prime() -> None:
            if generation != int(self._timeline_preview_prime_generation):
                return
            if self._preview_sync_mode != "timeline":
                return
            if bool(getattr(self.timeline_panel, "_is_playing", False)):
                return
            try:
                if self.timeline_panel.is_playhead_scrubbing():
                    return
            except Exception:
                pass
            current = self._clamp_timeline_seconds(
                float(getattr(self.timeline_panel, "_playhead_seconds", target_seconds))
            )
            self._sync_preview_for_timeline_clock(
                current,
                playing=False,
                force_seek=True,
                throttle_preview=False,
                sync_selection=False,
                sync_caption_scroll=False,
            )

        QTimer.singleShot(0, _prime)
        QTimer.singleShot(180, _prime)

    def _schedule_scrub_finish_sync(self, seconds: float) -> None:
        self._scrub_finish_generation += 1
        generation = self._scrub_finish_generation
        target_seconds = float(seconds)

        def _sync_after_scrub() -> None:
            if generation != self._scrub_finish_generation:
                return
            try:
                if self.timeline_panel.is_playhead_scrubbing():
                    return
            except Exception:
                pass
            if bool(getattr(self.timeline_panel, "_is_playing", False)):
                return
            current = float(getattr(self.timeline_panel, "_playhead_seconds", target_seconds))
            self._sync_preview_for_timeline_clock(
                current,
                playing=False,
                force_seek=True,
                throttle_preview=False,
            )

        QTimer.singleShot(self._SCRUB_FINISH_SYNC_DELAY_MS, _sync_after_scrub)

    def _invalidate_subtitle_lookup_cache(self) -> None:
        self._subtitle_lookup_dirty = True
        self._subtitle_lookup_starts = []
        self._subtitle_lookup_items = []
        self._subtitle_overlay_state = None

    def _ensure_subtitle_lookup_cache(self) -> None:
        if not self._subtitle_lookup_dirty:
            return
        items: list[tuple[float, float, Clip]] = []
        for track in self.project.tracks:
            if track.kind != "text" or self._is_track_hidden(track):
                continue
            for clip in track.clips:
                if clip.clip_type != "text":
                    continue
                dur = max(0.0, (clip.out_point or 0.0) - clip.in_point) / max(
                    1e-9,
                    clip.speed,
                )
                if dur <= 0.0:
                    dur = clip.timeline_duration or 0.0
                if dur <= 0.0:
                    continue
                start = float(clip.start)
                items.append((start, start + float(dur), clip))
        items.sort(key=lambda item: (item[0], item[1]))
        self._subtitle_lookup_items = items
        self._subtitle_lookup_starts = [item[0] for item in items]
        self._subtitle_lookup_dirty = False

    def _active_text_clip_at(self, seconds: float) -> Clip | None:
        self._ensure_subtitle_lookup_cache()
        if not self._subtitle_lookup_items:
            return None
        s = float(seconds)
        idx = bisect_right(self._subtitle_lookup_starts, s) - 1
        while idx >= 0:
            start, end, clip = self._subtitle_lookup_items[idx]
            if s >= end:
                break
            if start <= s < end:
                return clip
            idx -= 1
        return None

    def _update_subtitle_overlay(self, seconds: float) -> None:
        """Find the active text clip at *seconds* and push its text to the preview."""
        active_text_clip = self._active_text_clip_at(seconds)
        main_txt = (active_text_clip.text_main or "") if active_text_clip is not None else ""
        second_txt = (active_text_clip.text_second or "") if active_text_clip is not None else ""
        if active_text_clip is None:
            state = (None, "", "")
        else:
            state = (
                id(active_text_clip),
                main_txt,
                second_txt,
                active_text_clip.pos_x,
                active_text_clip.pos_y,
                int(getattr(active_text_clip, "text_font_size", 36)),
                int(self.project.width),
                int(self.project.height),
            )
        if state == self._subtitle_overlay_state:
            self._preview_active_text_clip = active_text_clip
            return
        self._subtitle_overlay_state = state
        self._preview_active_text_clip = active_text_clip
        self.preview_panel.set_subtitle(main_txt, second_txt)
        if active_text_clip is not None:
            self.preview_panel.set_subtitle_position(
                pos_x=active_text_clip.pos_x,
                pos_y=active_text_clip.pos_y,
                font_size=int(getattr(active_text_clip, "text_font_size", 36)),
                canvas_size=(int(self.project.width), int(self.project.height)),
            )
            self.preview_panel.set_subtitle_overlay_active(True)
        else:
            self.preview_panel.set_subtitle_overlay_active(False)

    def _auto_select_text_clip_at_playhead(self) -> None:
        """Auto-select active text clip when playhead overlaps it."""
        if self._suspend_text_autoselect:
            return
        if bool(getattr(self.timeline_panel, "_is_playing", False)):
            return
        active_clip = getattr(self, "_preview_active_text_clip", None)
        if active_clip is None:
            return

        current = self.inspector_panel.current_clip()
        if current is active_clip:
            return
        if isinstance(current, Clip) and not bool(getattr(current, "is_text_clip", False)):
            return

        try:
            is_filter_active = self.inspector_panel._info._caption_list.is_filter_active()
        except Exception:
            is_filter_active = False

        if (
            isinstance(current, Clip)
            and bool(getattr(current, "is_text_clip", False))
            and current is not active_clip
            and is_filter_active
        ):
            return

        info = self.inspector_panel._info
        preserve_caption_tab = bool(info._btn_text_tab_caption.isChecked())
        preserve_text_tab = bool(info._btn_text_tab_text.isChecked())
        preserve_stack_idx = int(info._text_tab_stack.currentIndex())

        self._suspend_timeline_selection_sync = True
        try:
            self.timeline_panel.select_clip(active_clip)
        finally:
            self._suspend_timeline_selection_sync = False

        info.set_clip(active_clip)
        if active_clip.is_text_clip:
            if preserve_caption_tab:
                info._btn_text_tab_caption.setChecked(True)
            elif preserve_text_tab:
                info._btn_text_tab_text.setChecked(True)
            elif preserve_stack_idx in (0, 1):
                info._text_tab_stack.setCurrentIndex(preserve_stack_idx)

    def _overlay_target_clip(self) -> Clip | None:
        current = self.inspector_panel.current_clip()
        if isinstance(current, Clip) and bool(getattr(current, "is_text_clip", False)):
            return current
        if isinstance(self._preview_active_text_clip, Clip):
            return self._preview_active_text_clip
        return None

    def _on_overlay_position_changed(self, x: int, y: int) -> None:
        self._pause_timeline_playback_for_user_action()
        clip = self._overlay_target_clip()
        if clip is None or not bool(getattr(clip, "is_text_clip", False)):
            return
        clip.pos_x = int(x)
        clip.pos_y = int(y)
        self._subtitle_overlay_state = None
        self.preview_panel.set_subtitle_position(
            pos_x=clip.pos_x,
            pos_y=clip.pos_y,
            font_size=int(getattr(clip, "text_font_size", 36)),
            canvas_size=(int(self.project.width), int(self.project.height)),
        )
        info = self.inspector_panel._info
        if info.current_clip() is clip:
            info._transform_x.blockSignals(True)
            info._transform_y.blockSignals(True)
            info._transform_x.setValue(int(x))
            info._transform_y.setValue(int(y))
            info._transform_x.blockSignals(False)
            info._transform_y.blockSignals(False)

    def _on_overlay_transform_changed(self, scale: float, x: int, y: int, rotate: float) -> None:
        self._pause_timeline_playback_for_user_action()
        clip = self.inspector_panel.current_clip()
        if clip is None or clip.is_text_clip:
            return
            
        clip.scale = scale
        clip.scale_x = None
        clip.scale_y = None
        clip.pos_x = None if int(x) == 0 else int(x)
        clip.pos_y = None if int(y) == 0 else int(y)
        clip.effects.rotate = rotate
        
        # Update preview (direct canvas call for speed)
        self.preview_panel._video.set_video_transform(
            scale,
            x,
            y,
            rotate,
            (int(self.project.width), int(self.project.height)),
            scale_x=None,
            scale_y=None,
        )
        self.preview_panel.update()
        
        # Update inspector if it's showing this clip
        info = self.inspector_panel._info
        if info.current_clip() is clip and hasattr(info, "_clip_box_video"):
            vbox = info._clip_box_video
            vbox._binding = True
            try:
                percent = int(round(scale * 100))
                vbox._uniform_cb.setChecked(True)
                vbox._scale_slider.setValue(percent)
                vbox._scale_spin.setValue(percent)
                vbox._scale_x_slider.setValue(percent)
                vbox._scale_x_spin.setValue(percent)
                vbox._scale_y_slider.setValue(percent)
                vbox._scale_y_spin.setValue(percent)
                vbox._x_spin.setValue(int(x))
                vbox._y_spin.setValue(int(y))
                vbox._rotate_spin.setValue(rotate)
                # Sync dial
                dial_val = int(round(rotate)) % 360
                if dial_val > 180: dial_val -= 360
                elif dial_val < -180: dial_val += 360
                vbox._rotate_dial.setValue(dial_val)
            finally:
                vbox._binding = False
                vbox._sync_uniform_scale_ui()
        
        self.timeline_panel.refresh()

    def _on_overlay_font_size_changed(self, size: int) -> None:
        self._pause_timeline_playback_for_user_action()
        clip = self._overlay_target_clip()
        if clip is None or not bool(getattr(clip, "is_text_clip", False)):
            return
        clip.text_font_size = max(8, int(size))
        self.preview_panel.set_subtitle_position(
            pos_x=clip.pos_x,
            pos_y=clip.pos_y,
            font_size=int(clip.text_font_size),
            canvas_size=(int(self.project.width), int(self.project.height)),
        )
        info = self.inspector_panel._info
        if info.current_clip() is clip:
            info._text_main_size.blockSignals(True)
            info._text_second_size.blockSignals(True)
            info._text_main_size.setValue(int(clip.text_font_size))
            info._text_second_size.setValue(
                int(getattr(clip, "text_second_font_size", clip.text_font_size))
            )
            info._text_main_size.blockSignals(False)
            info._text_second_size.blockSignals(False)

    def _on_tab_changed(self, key: str) -> None:
        self._set_left_tab(key)

    def _set_left_tab(self, key: str) -> None:
        safe_key = key if key in (TAB_MEDIA, TAB_TEXT, TAB_VOICE_MATCH) else TAB_MEDIA
        idx = {
            TAB_MEDIA: 0,
            TAB_TEXT: 1,
            TAB_VOICE_MATCH: 2,
        }.get(safe_key, 0)
        self.left_rail.set_active(safe_key)
        self.side_stack.setCurrentIndex(idx)
        self.sub_nav_stack.setCurrentIndex(idx)

    def _voice_match_work_dir(self) -> Path:
        project_key = self._store_project_id or "_unsaved"
        return default_store_dir() / project_key / "voice_match"

    def _default_voice_match_output_path(self) -> Path:
        work_dir = self._voice_match_work_dir()
        work_dir.mkdir(parents=True, exist_ok=True)
        stamp = int(monotonic() * 1000)
        return work_dir / f"voice_match_{stamp}.json"

    def _on_voice_match_generate_requested(self, settings: VoiceMatchPanelSettings) -> None:
        if self._voice_match_worker is not None and self._voice_match_worker.isRunning():
            QMessageBox.information(
                self,
                "Khớp voice",
                "ang tạo draft khớp voice, vui lòng ch hoàn tất.",
            )
            return

        from ..integrations.capcut_generator.adapter import TimelineVoiceMatchOptions

        original_snapshot = self.project.model_copy(deep=True)
        self._voice_match_original_project = original_snapshot
        self._voice_match_matched_project = None
        self._voice_match_view_state = None
        self.voice_match_panel.set_compare_state(None, has_original=False, has_matched=False)

        work_dir = self._voice_match_work_dir()
        output_path = settings.output_json_path or self._default_voice_match_output_path()
        options = TimelineVoiceMatchOptions(
            project=original_snapshot.model_copy(deep=True),
            output_json_path=Path(output_path),
            work_dir=work_dir,
            sync_mode=settings.sync_mode,
            target_audio_speed=settings.target_audio_speed,
            keep_pitch=settings.keep_pitch,
            video_speed_enabled=settings.video_speed_enabled,
            target_video_speed=settings.target_video_speed,
            remove_silence=settings.remove_silence,
            waveform_sync=settings.waveform_sync,
            skip_stretch_shorter=settings.skip_stretch_shorter,
            export_lt8=settings.export_lt8,
        )

        self.voice_match_panel.set_running(True)
        self.voice_match_panel.set_progress(0, "Bắt đầu tạo draft khớp voice từ timeline...")
        worker = _VoiceMatchWorker(options)
        self._voice_match_worker = worker
        worker.progress.connect(self.voice_match_panel.set_progress)
        worker.succeeded.connect(self._on_voice_match_worker_succeeded)
        worker.failed.connect(self._on_voice_match_worker_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_voice_match_worker_succeeded(self, path_obj: object) -> None:
        from ..core.capcut_importer import import_capcut_draft

        path = Path(path_obj)
        try:
            if self._voice_match_original_project is None:
                raise RuntimeError("Thiếu snapshot ban đầu để áp dụng khớp voice.")
            matched_project = import_capcut_draft(path)
            matched_snapshot = self._build_direct_main_matched_project(
                original=self._voice_match_original_project,
                matched=matched_project,
            )
        except Exception as exc:
            self._on_voice_match_worker_failed(str(exc))
            return

        self._voice_match_matched_project = matched_snapshot.model_copy(deep=True)
        self.voice_match_panel.set_running(False)
        self.voice_match_panel.set_progress(100, "Hoàn tất.")
        self.voice_match_panel.set_generated_path(path)
        self._apply_voice_match_project_snapshot(self._voice_match_matched_project, "matched")
        self.voice_match_panel.set_compare_state("matched", has_original=True, has_matched=True)
        self.statusBar().showMessage(
            f"ã áp dụng khớp voice trực tiếp lên track Main: {path.name}",
            4000,
        )
        self._voice_match_worker = None

    def _on_voice_match_worker_failed(self, message: str) -> None:
        text = str(message).strip() or "Không thể tạo draft khớp voice."
        self.voice_match_panel.set_running(False)
        self.voice_match_panel.append_log(text)
        self._voice_match_worker = None
        QMessageBox.warning(self, "Không thể khớp voice", text)

    @staticmethod
    def _main_video_track_for_project(project: Project) -> Track | None:
        for track in project.tracks:
            if (
                track.kind == "video"
                and track.name.strip().lower() == "main"
                and not bool(getattr(track, "hidden", False))
            ):
                return track
        return next(
            (
                track
                for track in project.tracks
                if track.kind == "video" and not bool(getattr(track, "hidden", False))
            ),
            None,
        )

    @staticmethod
    def _first_visible_video_track(project: Project) -> Track | None:
        return next(
            (
                track
                for track in project.tracks
                if track.kind == "video"
                and track.clips
                and not bool(getattr(track, "hidden", False))
            ),
            None,
        )

    @staticmethod
    def _matched_tracks_for_kind(matched: Project, kind: str, default_name: str) -> list[Track]:
        tracks: list[Track] = []
        for track in matched.tracks:
            if track.kind != kind or not track.clips:
                continue
            copied = track.model_copy(deep=True)
            if not copied.name.strip():
                index = len(tracks) + 1
                copied.name = default_name if index == 1 else f"{default_name} {index}"
            tracks.append(copied)
        return tracks

    @staticmethod
    def _copy_matched_main_video_clips(
        matched_video_track: Track,
        original_main_track: Track | None = None,
    ) -> list[Clip]:
        def _source_key(source: object) -> str:
            raw = str(source or "").strip()
            if not raw:
                return ""
            try:
                return str(Path(raw).resolve()).lower()
            except Exception:
                return raw.lower()

        original_volume_by_source: dict[str, float] = {}
        if original_main_track is not None:
            for original_clip in original_main_track.clips:
                if bool(getattr(original_clip, "is_text_clip", False)):
                    continue
                key = _source_key(getattr(original_clip, "source", ""))
                if not key or key in original_volume_by_source:
                    continue
                try:
                    original_volume_by_source[key] = max(0.0, float(original_clip.volume))
                except Exception:
                    original_volume_by_source[key] = 1.0

        clips: list[Clip] = []
        for clip in matched_video_track.clips:
            copied = clip.model_copy(deep=True)
            # Voice match cuts/speeds video into segments. Keep source audio embedded
            # in each Main segment, but remove generated fade/gain automation at edges.
            source_key = _source_key(getattr(copied, "source", ""))
            if source_key in original_volume_by_source:
                copied.volume = original_volume_by_source[source_key]
            copied.volume_keyframes = []
            copied.audio_effects.fade_in = 0.0
            copied.audio_effects.fade_out = 0.0
            clips.append(copied)
        return clips

    @staticmethod
    def _build_direct_main_matched_project(original: Project, matched: Project) -> Project:
        result = original.model_copy(deep=True)
        result_main = MainWindow._main_video_track_for_project(result)
        matched_video_track = MainWindow._first_visible_video_track(matched)
        if result_main is None or matched_video_track is None:
            raise ValueError("Không tìm thấy track Main hoặc track video đã khớp.")

        result_main.name = "Main"
        original_main_track = MainWindow._main_video_track_for_project(original)
        result_main.clips = MainWindow._copy_matched_main_video_clips(
            matched_video_track,
            original_main_track,
        )
        result_main.transitions = [
            transition.model_copy(deep=True)
            for transition in getattr(matched_video_track, "transitions", [])
        ]
        matched_text_tracks = MainWindow._matched_tracks_for_kind(
            matched,
            "text",
            "Khớp voice - Text",
        )
        matched_audio_tracks = MainWindow._matched_tracks_for_kind(
            matched,
            "audio",
            "Khớp voice - Voice",
        )
        if not matched_text_tracks and not matched_audio_tracks:
            return result

        rebuilt_tracks: list[Track] = []
        inserted_text = False
        inserted_audio = False
        for track in result.tracks:
            if matched_text_tracks and track.kind == "text":
                if not inserted_text:
                    rebuilt_tracks.extend([tr.model_copy(deep=True) for tr in matched_text_tracks])
                    inserted_text = True
                continue
            if matched_audio_tracks and track.kind == "audio":
                if not inserted_audio:
                    rebuilt_tracks.extend([tr.model_copy(deep=True) for tr in matched_audio_tracks])
                    inserted_audio = True
                continue
            rebuilt_tracks.append(track)

        if matched_text_tracks and not inserted_text:
            main_idx = next(
                (idx for idx, track in enumerate(rebuilt_tracks) if track is result_main),
                len(rebuilt_tracks),
            )
            for track in reversed(matched_text_tracks):
                rebuilt_tracks.insert(main_idx, track.model_copy(deep=True))
        if matched_audio_tracks and not inserted_audio:
            main_idx = next(
                (idx for idx, track in enumerate(rebuilt_tracks) if track is result_main),
                len(rebuilt_tracks) - 1,
            )
            insert_idx = max(0, main_idx + 1)
            for offset, track in enumerate(matched_audio_tracks):
                rebuilt_tracks.insert(insert_idx + offset, track.model_copy(deep=True))

        result.tracks = rebuilt_tracks
        return result

    def _apply_voice_match_project_snapshot(self, snapshot: Project, view_state: str) -> None:
        self._stop_preview_playback()
        self.project = snapshot.model_copy(deep=True)
        self._voice_match_view_state = view_state if view_state in {"original", "matched"} else None
        self._preview_source_path = None
        self._preview_active_media_clip = None
        self._preview_active_text_clip = None
        self._invalidate_clip_interval_indexes()
        self._invalidate_timeline_audio_mix(clear_player=True)
        self.timeline_panel.set_project(self.project)
        self.inspector_panel.set_project(self.project)
        self.topbar.set_project_title(self.project.name)
        self.timeline_panel.refresh()
        self._set_clip_in_inspector(None)
        self.inspector_panel.refresh()
        self._update_media_library_added_states()
        self._sync_preview_play_availability()
        all_clips = [clip for track in self.project.tracks for clip in track.clips]
        self._schedule_timeline_cache_prewarm(all_clips)
        self._preview_sync_mode = "timeline"
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        seek_to = min(max(0.0, current), max(0.0, self.project.duration))
        self.timeline_panel.set_playhead(seek_to)
        self._schedule_timeline_preview_prime(seek_to)
        self._refresh_auto_speed_issue_overlays()
        self._reset_timeline_history()

    def _on_voice_match_show_original(self) -> None:
        if self._voice_match_original_project is None:
            return
        self._apply_voice_match_project_snapshot(
            self._voice_match_original_project,
            "original",
        )
        self.voice_match_panel.set_compare_state("original", has_original=True, has_matched=True)

    def _on_voice_match_show_matched(self) -> None:
        if self._voice_match_matched_project is None:
            return
        self._apply_voice_match_project_snapshot(
            self._voice_match_matched_project,
            "matched",
        )
        self.voice_match_panel.set_compare_state("matched", has_original=True, has_matched=True)

    def _on_voice_match_import_requested(self, path_obj: object) -> None:
        from ..core.capcut_importer import import_capcut_draft

        path = Path(path_obj)
        try:
            project = import_capcut_draft(path)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Import khớp voice thất bại",
                f"Không thể import draft đã tạo:\n\n{exc}",
            )
            return

        self._apply_loaded_project(project)
        self._store_project_id = None
        self.statusBar().showMessage(f"ã import draft khớp voice: {path.name}", 4000)

    def _tracks_snapshot(self) -> str:
        tracks_payload = [track.model_dump(mode="json") for track in self.project.tracks]
        return json.dumps(tracks_payload, ensure_ascii=False, separators=(",", ":"))

    def _restore_tracks_snapshot(self, snapshot: str) -> None:
        raw = json.loads(snapshot)
        self.project.tracks = [Track.model_validate(item) for item in raw]
        self._invalidate_clip_interval_indexes()

    def _set_history_index(self, index: int) -> None:
        self._history_index = max(0, min(index, len(self._history_snapshots) - 1))
        can_undo = self._history_index > 0
        can_redo = self._history_index < len(self._history_snapshots) - 1
        self.timeline_panel.set_history_state(can_undo=can_undo, can_redo=can_redo)

    def _reset_timeline_history(self) -> None:
        self._invalidate_subtitle_lookup_cache()
        self._invalidate_clip_interval_indexes()
        self._invalidate_timeline_audio_mix(clear_player=True)
        self._history_snapshots = [self._tracks_snapshot()]
        self._set_history_index(0)

    def _push_timeline_history(self) -> None:
        self._sync_preview_play_availability()
        if self._history_replaying:
            return
        snap = self._tracks_snapshot()
        if self._history_index >= 0 and self._history_snapshots[self._history_index] == snap:
            self._set_history_index(self._history_index)
            return
        self._invalidate_subtitle_lookup_cache()
        self._invalidate_clip_interval_indexes()
        self._invalidate_timeline_audio_mix(clear_player=True)
        if self._history_index < len(self._history_snapshots) - 1:
            self._history_snapshots = self._history_snapshots[: self._history_index + 1]
        self._history_snapshots.append(snap)
        if len(self._history_snapshots) > self._history_limit:
            overflow = len(self._history_snapshots) - self._history_limit
            self._history_snapshots = self._history_snapshots[overflow:]
            new_index = max(0, self._history_index + 1 - overflow)
            self._set_history_index(new_index)
            return
        self._set_history_index(len(self._history_snapshots) - 1)

    def _apply_history_snapshot(self, index: int) -> None:
        if index < 0 or index >= len(self._history_snapshots):
            return
        self._invalidate_subtitle_lookup_cache()
        self._invalidate_clip_interval_indexes()
        self._invalidate_timeline_audio_mix(clear_player=True)
        self._history_replaying = True
        try:
            snapshot = self._history_snapshots[index]
            self._restore_tracks_snapshot(snapshot)
            self._sync_preview_play_availability()
            self.timeline_panel.refresh()
            self._set_clip_in_inspector(None)
            self.inspector_panel.refresh()
            self._update_media_library_added_states()
            self._preview_sync_mode = "timeline"
            current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
            seek_to = min(max(0.0, current), max(0.0, self.project.duration))
            self.timeline_panel.set_playhead(seek_to)
            self._on_timeline_seek(seek_to)
            self._refresh_auto_speed_issue_overlays()
        finally:
            self._history_replaying = False
        self._set_history_index(index)

    def _timeline_has_any_components(self) -> bool:
        return any(bool(track.clips) for track in self.project.tracks)

    def _resolve_timeline_play_start(self, current: float) -> tuple[float, Clip | None]:
        current_s = max(0.0, float(current))
        return current_s, self._pick_preview_clip_for_time(current_s)

    def _sync_preview_play_availability(self) -> None:
        self.preview_panel.set_timeline_play_available(self._timeline_has_any_components())
        if self._preview_sync_mode == "timeline":
            self._set_preview_timeline_time_display(
                float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
            )

    def _undo_timeline(self) -> None:
        self._pause_timeline_playback_for_user_action()
        if self._history_index <= 0:
            return
        self._apply_history_snapshot(self._history_index - 1)

    def _redo_timeline(self) -> None:
        self._pause_timeline_playback_for_user_action()
        if self._history_index >= len(self._history_snapshots) - 1:
            return
        self._apply_history_snapshot(self._history_index + 1)

    def _on_timeline_project_mutated(self) -> None:
        self._pause_timeline_playback_for_user_action()
        self._invalidate_subtitle_lookup_cache()
        self._invalidate_clip_interval_indexes()
        self._sync_preview_play_availability()
        self._update_media_library_added_states()
        self._push_timeline_history()
        self.inspector_panel.refresh()
        self._refresh_auto_speed_issue_overlays()
        if bool(getattr(self.timeline_panel, "_is_playing", False)):
            current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
            self._sync_preview_for_timeline_clock(
                current,
                playing=True,
                force_seek=False,
            )

    @staticmethod
    def _is_text_entry_focus_widget(widget: object | None) -> bool:
        current = widget if isinstance(widget, QWidget) else None
        while current is not None:
            if isinstance(
                current,
                (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox),
            ):
                return True
            current = current.parentWidget()
        return False

    def _handle_space_play_pause_shortcut(self) -> bool:
        fw = QApplication.focusWidget()
        if fw is None:
            return False
        if fw.window() is not self:
            return False
        if self._is_text_entry_focus_widget(fw):
            return False

        has_clips = any(len(track.clips) > 0 for track in self.project.tracks)
        if not has_clips:
            return True

        want_play = not bool(getattr(self.timeline_panel, "_is_playing", False))
        self.timeline_panel.set_playing_state(want_play)
        self._preview_sync_mode = "timeline"
        self._on_timeline_playpause_requested()
        return True

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if (
            event is not None
            and event.type() == QEvent.Type.KeyPress
            and self.isActiveWindow()
            and getattr(event, "key", lambda: None)() == Qt.Key.Key_Space
            and not bool(getattr(event, "isAutoRepeat", lambda: False)())
        ):
            if self._handle_space_play_pause_shortcut():
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _on_topbar_project_title_changed(self, title: str) -> None:
        new_name = (title or "").strip() or "Untitled"
        self.project.name = new_name
        self.topbar.set_project_title(new_name)
        self.inspector_panel.refresh()

    def _on_inspector_clip_changed(self) -> None:
        self._pause_timeline_playback_for_user_action()
        clip = self.inspector_panel.current_clip()
        info = self.inspector_panel._info
        focus = QApplication.focusWidget()
        is_typing_text_fields = (
            isinstance(clip, Clip)
            and bool(getattr(clip, "is_text_clip", False))
            and focus is not None
            and (
                focus is info._text_main
                or focus is info._text_second
                or info._text_main.isAncestorOf(focus)
                or info._text_second.isAncestorOf(focus)
            )
        )
        if is_typing_text_fields:
            # Avoid full inspector/timeline refresh while typing in Main/Second,
            # otherwise focus is reset after each keystroke.
            self._update_subtitle_overlay(
                float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
            )
            return
        self._invalidate_timeline_audio_mix(clear_player=True)
        change_source = ""
        try:
            change_source = self.inspector_panel._info.take_last_change_source()
        except Exception:
            change_source = ""
        self.timeline_panel.refresh()
        current_seconds = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        if self._preview_sync_mode == "timeline":
            is_playing = bool(getattr(self.timeline_panel, "_is_playing", False))
            self._sync_preview_for_timeline_clock(
                current_seconds,
                playing=is_playing,
                force_seek=not is_playing,
                sync_selection=False,
                sync_caption_scroll=False,
            )
        if clip is not None:
            try:
                selected = self.timeline_panel.selected_clips()
            except Exception:
                selected = []
            if len(selected) != 1 or selected[0] is not clip:
                self.timeline_panel.select_clip(clip)
        if change_source != "video_speed":
            self.inspector_panel.refresh()
        self._update_subtitle_overlay(current_seconds)
        self._refresh_auto_speed_issue_overlays()

    def _iter_text_clips(self) -> list[Clip]:
        clips: list[Clip] = []
        for track in self.project.tracks:
            if track.kind != "text":
                continue
            for clip in track.clips:
                if clip.is_text_clip:
                    clips.append(clip)
        clips.sort(key=lambda c: (c.start, c.timeline_duration or 0.0))
        return clips

    @staticmethod
    def _display_text_from_clip(clip: Clip, display: str) -> str:
        main = (clip.text_main or "").strip()
        second = (clip.text_second or "").strip()
        if display == "second":
            return second or main
        if display == "bilingual":
            if main and second:
                return f"{main}\n{second}"
            return main or second
        return main or second

    def _collect_subtitle_cues(self, *, display: str) -> CueList:
        cues: list[Cue] = []
        for clip in self._iter_text_clips():
            dur = clip.timeline_duration
            if dur is None or dur <= 0.0:
                continue
            text = self._display_text_from_clip(clip, display)
            if not text.strip():
                continue
            start = max(0.0, clip.start)
            end = max(start + 0.001, clip.start + dur)
            cues.append(Cue(start=start, end=end, text=text))
        cues.sort(key=lambda c: (c.start, c.end))
        return CueList(cues)

    def _write_subtitles_file(self, path: Path, *, fmt: str, display: str) -> int:
        cues = self._collect_subtitle_cues(display=display)
        if len(cues) == 0:
            raise ValueError("No subtitle clips found on text tracks.")

        fmt = fmt.lower().strip(".")
        if fmt == "srt":
            path.write_text(write_srt(cues), encoding="utf-8")
        elif fmt == "vtt":
            path.write_text(write_vtt(cues), encoding="utf-8")
        elif fmt == "ass":
            path.write_text(write_ass(cues), encoding="utf-8")
        elif fmt == "txt":
            lines: list[str] = []
            for cue in cues:
                span = (
                    f"{format_timecode(cue.start, srt=False)} --> "
                    f"{format_timecode(cue.end, srt=False)}"
                )
                body = cue.text.replace("\r\n", "\n").replace("\n", " | ")
                lines.append(f"{span}  {body}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            raise ValueError(f"Unsupported subtitle format: {fmt}")
        return len(cues)

    def _export_subtitles_manual(self) -> None:
        default_name = f"{self.project.name or 'subtitle'}.srt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export subtitles",
            default_name,
            "Subtitles (*.srt *.vtt *.txt *.ass)",
        )
        if not path:
            return
        target = Path(path)
        fmt = target.suffix.lower().strip(".") or "srt"
        if target.suffix == "":
            target = target.with_suffix(".srt")
            fmt = "srt"
        display, ok = QInputDialog.getItem(
            self,
            "Export subtitles",
            "Display mode:",
            ["bilingual", "main", "second"],
            0,
            False,
        )
        if not ok:
            return
        try:
            count = self._write_subtitles_file(target, fmt=fmt, display=display)
            self.statusBar().showMessage(
                f"Exported subtitles: {target.name} ({count} cues)",
                5000,
            )
        except Exception as e:
            QMessageBox.critical(self, "Export subtitles failed", str(e))

    def _translate_selected_subtitle(self) -> None:
        clip = self.inspector_panel.current_clip()
        self._translate_subtitle_clip(clip)

    def _translate_selected_subtitle_track_batch(self) -> None:
        clip = self.inspector_panel.current_clip()
        self._translate_subtitle_track_batch(clip)

    def _find_track_for_clip(self, clip: Clip) -> Track | None:
        cache_key = id(clip)
        cached = self._clip_track_map.get(cache_key)
        if cached is not None:
            return cached
        if not self._clip_track_map:
            for track in self.project.tracks:
                for existing in track.clips:
                    self._clip_track_map[id(existing)] = track
            cached = self._clip_track_map.get(cache_key)
            if cached is not None:
                return cached
        for track in self.project.tracks:
            if any(existing is clip for existing in track.clips):
                self._clip_track_map[cache_key] = track
                return track
        for track in self.project.tracks:
            if clip in track.clips:
                self._clip_track_map[cache_key] = track
                return track
        return None

    def _set_clip_in_inspector(
        self,
        clip: object | None,
        *,
        prefer_caption_tab_for_text: bool = False,
    ) -> None:
        current = clip if isinstance(clip, Clip) else None
        track_kind: str | None = None
        if current is not None:
            track = self._find_track_for_clip(current)
            track_kind = track.kind if track is not None else None
        self.inspector_panel.set_clip(
            current,
            prefer_caption_tab_for_text=prefer_caption_tab_for_text,
            track_kind=track_kind,
        )

    def _on_timeline_edit_subtitle_translate(self, clip: object) -> None:
        c = clip if isinstance(clip, Clip) else None
        if c is None or not c.is_text_clip:
            return
        # Match HTML right-click flow: jump to subtitle editing context.
        self.left_rail.set_active(TAB_TEXT)
        self._on_tab_changed(TAB_TEXT)
        self.timeline_panel.select_clip(c)
        self._set_clip_in_inspector(c)
        self._open_subtitle_edit_translate_dialog(c)

    def _create_subtitle_translator(self):
        settings = self._plugin_store.translation
        provider = self._plugin_store.get_provider(settings.provider_id)
        if provider is None:
            raise RuntimeError(
                "No valid translation provider selected. Open Plugin -> Subtitle Translation."
            )
        runtime_provider = replace(provider)
        runtime_provider.current_model = (
            (settings.current_model or "").strip()
            or (provider.current_model or "").strip()
            or (provider.models[0] if provider.models else "")
        )
        if runtime_provider.current_model and runtime_provider.current_model not in runtime_provider.models:
            runtime_provider.models = list(provider.models) + [runtime_provider.current_model]
        translator = build_translate_provider(runtime_provider, settings)
        target = (settings.target_language or "").strip() or "Vietnamese"
        source = (settings.source_language or "").strip() or None
        provider_info = f"{provider.name} ({runtime_provider.current_model})"
        return translator, target, source, provider_info

    def _try_handle_translate_config_error(self, msg: str) -> bool:
        need_config = (
            "No valid translation provider selected" in msg
            or "API_KEY" in msg
            or "API key" in msg
        )
        if not need_config:
            return False
        answer = QMessageBox.question(
            self,
            "Translate subtitle failed",
            f"{msg}\n\nOpen Plugin settings now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._open_plugin_manager(initial_tab=1)
        return True

    def _translate_text_via_plugin(self, source_text: str) -> str:
        text = (source_text or "").strip()
        if not text:
            raise RuntimeError("Selected subtitle clip has no text.")
        translator, target, source, provider_info = self._create_subtitle_translator()
        self.statusBar().showMessage(f"Translating subtitle via {provider_info}...", 5000)
        translated = translator.translate(text, target=target, source=source)
        translated = (translated or "").strip()
        if not translated:
            raise RuntimeError("Empty translation returned by provider.")
        return translated

    def _translate_subtitle_track_batch(self, clip: object) -> None:
        c = clip if isinstance(clip, Clip) else None
        if c is None or not c.is_text_clip:
            QMessageBox.information(
                self,
                "Batch subtitle translate",
                "Select a subtitle clip first.",
            )
            return

        track = self._find_track_for_clip(c)
        if track is None:
            QMessageBox.warning(
                self,
                "Batch subtitle translate",
                "Cannot find track for selected subtitle clip.",
            )
            return

        track_clips = sorted(
            [x for x in track.clips if x.is_text_clip],
            key=lambda x: (x.start, x.timeline_duration or 0.0),
        )
        if not track_clips:
            QMessageBox.information(
                self,
                "Batch subtitle translate",
                "No subtitle clips found on this track.",
            )
            return

        items = collect_clip_translate_items(track_clips, only_missing_second=True)
        if not items:
            QMessageBox.information(
                self,
                "Batch subtitle translate",
                "No subtitle clips need translation on this track.",
            )
            return

        settings = self._plugin_store.translation
        batch_size = max(1, int(settings.batch_size or 1))

        try:
            translator, target, source, provider_info = self._create_subtitle_translator()
        except Exception as e:
            msg = str(e)
            if self._try_handle_translate_config_error(msg):
                return
            QMessageBox.critical(self, "Batch subtitle translate failed", msg)
            return

        batches = chunked(items, batch_size)
        progress = QProgressDialog("Batch translating subtitles...", "Cancel", 0, len(items), self)
        progress.setWindowTitle("Batch subtitle translate")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        total = len(items)
        translated_count = 0
        processed = 0
        canceled = False

        try:
            for idx, batch in enumerate(batches, start=1):
                if progress.wasCanceled():
                    canceled = True
                    break
                progress.setLabelText(
                    f"Batch translating subtitles... {processed}/{total} (batch {idx}/{len(batches)})"
                )
                self.statusBar().showMessage(
                    f"Translating subtitle batch {idx}/{len(batches)} via {provider_info}..."
                )
                payload = [{"id": item.item_id, "text": item.source_text} for item in batch]
                translated_rows = translator.translate_items(payload, target=target, source=source)
                translated_count += apply_clip_translations(batch, translated_rows)
                processed += len(batch)
                progress.setValue(processed)
                QApplication.processEvents()
                if progress.wasCanceled():
                    canceled = True
                    break
        except Exception as e:
            progress.close()
            msg = str(e)
            if self._try_handle_translate_config_error(msg):
                return
            QMessageBox.critical(self, "Batch subtitle translate failed", msg)
            return

        progress.close()
        self._on_inspector_clip_changed()
        if canceled:
            self.statusBar().showMessage(
                f"Batch translation canceled: updated {translated_count}/{total} subtitles.",
                5000,
            )
            QMessageBox.information(
                self,
                "Batch subtitle translate",
                f"Canceled. Updated {translated_count}/{total} subtitles.",
            )
            return

        self.statusBar().showMessage(
            f"Batch subtitle translation done via {provider_info}: updated {translated_count}/{total} subtitles.",
            5000,
        )

    def _open_subtitle_edit_translate_dialog(self, clip: Clip) -> None:
        def _batch_rows() -> list[tuple[str, str, str]]:
            track = self._find_track_for_clip(clip)
            if track is None:
                return []
            rows: list[tuple[str, str, str]] = []
            text_clips = [c for c in track.clips if c.is_text_clip]
            text_clips.sort(key=lambda c: (c.start, c.timeline_duration or 0.0))
            for idx, c in enumerate(text_clips, start=1):
                dur = c.timeline_duration or 0.0
                end = max(c.start, c.start + dur)
                span = f"{format_timecode(c.start, millis=False)} -- {format_timecode(end, millis=False)}"
                main = (c.text_main or "").strip()
                second = (c.text_second or "").strip()
                text = f"{main}\n{second}" if second else main
                rows.append((str(idx), span, text))
            return rows

        settings = self._plugin_store.translation
        provider = self._plugin_store.get_provider(settings.provider_id)
        provider_name = provider.name if provider is not None else "No provider"
        model = (settings.current_model or (provider.current_model if provider else "") or "").strip()
        provider_info = f"{provider_name}{f' ({model})' if model else ''}"
        info = SubtitleDialogInfo(
            provider_info=provider_info,
            target_language=(settings.target_language or "Vietnamese").strip() or "Vietnamese",
            source_language=(settings.source_language or "").strip() or None,
        )

        def _save_fields(main_text: str, second_text: str) -> None:
            clip.text_main = (main_text or "").strip()
            clip.text_second = (second_text or "").strip()
            if clip.text_main and clip.text_second:
                clip.text_display = "bilingual"
            elif clip.text_main:
                clip.text_display = "main"
            else:
                clip.text_display = "second"
            self._on_inspector_clip_changed()

        dlg_ref: list[SubtitleEditTranslateDialog] = []

        def _batch_translate_and_refresh_dialog() -> None:
            self._translate_subtitle_track_batch(clip)
            if dlg_ref:
                dlg_ref[0].set_second_text(clip.text_second or "")
                dlg_ref[0].set_batch_rows(_batch_rows())

        dlg = SubtitleEditTranslateDialog(
            self,
            title="Edit subtitles & translate",
            main_text=clip.text_main or "",
            second_text=clip.text_second or "",
            info=info,
            batch_rows=_batch_rows(),
            on_open_plugin_settings=lambda: self._open_plugin_manager(initial_tab=1, modal=False),
            on_translate_to_second=lambda text: self._translate_text_via_plugin(text),
            on_batch_translate_track=_batch_translate_and_refresh_dialog,
            on_save=_save_fields,
        )
        dlg_ref.append(dlg)
        if dlg.exec() != QDialog.Accepted:
            return

    def _translate_subtitle_clip(self, clip: object) -> None:
        c = clip if isinstance(clip, Clip) else None
        if c is None or not c.is_text_clip:
            QMessageBox.information(
                self,
                "Translate subtitle",
                "Select a subtitle clip first.",
            )
            return
        source_text = (c.text_main or c.text_second or "").strip()
        if not source_text:
            QMessageBox.warning(self, "Translate subtitle", "Selected subtitle clip has no text.")
            return

        try:
            translated = self._translate_text_via_plugin(source_text)
            c.text_second = translated
            c.text_display = "bilingual" if (c.text_main or "").strip() else "second"
            self._on_inspector_clip_changed()
            self.statusBar().showMessage("Subtitle translated.", 4000)
        except Exception as e:
            msg = str(e)
            if self._try_handle_translate_config_error(msg):
                return
            QMessageBox.critical(self, "Translate subtitle failed", msg)

    def _toggle_maximize(self) -> None:
        snap = self._snapshot_window_toggle_state()
        self._suspend_timeline_selection_sync = True
        self._suspend_text_autoselect = True
        state = self.windowState()
        if state & Qt.WindowState.WindowMaximized:
            self.setWindowState(state & ~Qt.WindowState.WindowMaximized)
            self.topbar.max_btn.setText("\uE922")  # Maximize icon
        else:
            self.setWindowState(state | Qt.WindowState.WindowMaximized)
            self.topbar.max_btn.setText("\uE923")  # Restore icon

        def _restore_after_toggle(pass_index: int) -> None:
            try:
                self._restore_window_toggle_state(snap)
            finally:
                if pass_index >= 2:
                    self._suspend_timeline_selection_sync = False
                    self._suspend_text_autoselect = False
                else:
                    QTimer.singleShot(80, lambda: _restore_after_toggle(pass_index + 1))

        QTimer.singleShot(0, lambda: _restore_after_toggle(0))

    def _show_topbar_menu(self) -> None:
        menu = getattr(self, "_topbar_menu", None)
        if menu is None:
            return
        if self._menu_just_closed:
            return
        if menu.isVisible():
            menu.hide()
            return
        btn = self.topbar.menu_btn
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        self.topbar.set_menu_opened(True)
        menu.popup(pos)

    def _build_menu(self) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background: #1f232b;
                border: 1px solid #3b4454;
                border-radius: 6px;
                padding: 6px;
                color: #e6e8ec;
            }
            QMenu::item {
                padding: 6px 26px 6px 10px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #2d3442;
                color: #22d3c5;
            }
            QMenu::separator {
                height: 1px;
                background: #353d4b;
                margin: 4px 8px;
            }
            """
        )
        menu.aboutToShow.connect(lambda: self.topbar.set_menu_opened(True))
        def _on_menu_hide() -> None:
            self.topbar.set_menu_opened(False)
            self._menu_just_closed = True
            QTimer.singleShot(180, lambda: setattr(self, "_menu_just_closed", False))
        menu.aboutToHide.connect(_on_menu_hide)
        
        # We still build the native menu bar but hide it, 
        # and also populate the TopBar's custom menu button.
        self.menuBar().hide()
        
        # File Menu
        file_menu = menu.addMenu(t("menu.file"))
        file_menu.addAction(t("menu.file.open"), self._open_project)
        file_menu.addAction(t("menu.file.save_project"), self._save_project)
        file_menu.addAction("Import CapCut Project...", self._on_import_capcut)
        file_menu.addAction("Export to CapCut Format...", self._on_export_capcut)
        file_menu.addSeparator()
        file_menu.addAction(t("action.add_media"), self._add_media)
        file_menu.addAction(t("menu.file.export"), self._export_video)
        file_menu.addAction("Export Still Frame...", self._export_still_frame)
        file_menu.addAction("Export Subtitles...", self._export_subtitles_manual)
        file_menu.addSeparator()
        file_menu.addAction(t("menu.file.quit"), self.close)

        # Edit Menu
        edit_menu = menu.addMenu(t("menu.edit"))
        edit_menu.addAction(t("action.split"), self.timeline_panel.split_at_playhead)
        edit_menu.addAction(
            t("action.ripple_delete"), self.timeline_panel.ripple_delete_selected
        )
        edit_menu.addSeparator()
        edit_menu.addAction("Translate Selected Subtitle...", self._translate_selected_subtitle)
        edit_menu.addAction(
            "Batch Translate Subtitle Track...", self._translate_selected_subtitle_track_batch
        )

        # Templates Menu
        templates_menu = menu.addMenu("Templates")
        templates_menu.addAction(
            "Save Project as Template...",
            self._save_project_as_template,
        )
        templates_menu.addAction(
            "New Project from Template...",
            self._new_project_from_template,
        )

        # Audio Menu
        audio_menu = menu.addMenu("Audio")
        audio_menu.addAction(
            "Auto Duck Music Under Voice",
            self._auto_duck_music_under_voice,
        )
        audio_menu.addSeparator()
        audio_menu.addAction("Add Beat Marker at Playhead", self._add_beat_marker_at_playhead)
        audio_menu.addAction(
            "Remove Beat Marker Near Playhead",
            self._remove_beat_marker_near_playhead,
        )

        # Help Menu
        help_menu = menu.addMenu(t("menu.help"))
        help_menu.addAction("Plugin Manager...", self._open_plugin_manager)
        help_menu.addAction(t("menu.help.about"), self._about)

        self._topbar_menu = menu
        self.topbar.menu_btn.clicked.connect(self._show_topbar_menu)

    def _save_project_as_template(self) -> None:
        default_name = (self.project.name or "Project Template").strip() or "Project Template"
        name, accepted = QInputDialog.getText(
            self,
            "Save project template",
            "Template name:",
            text=default_name,
        )
        name = name.strip()
        if not accepted or not name:
            return
        try:
            path = save_project_template(name, self.project)
        except Exception as exc:
            QMessageBox.warning(self, "Save template failed", str(exc))
            return
        self.statusBar().showMessage(f"Project template saved: {path}", 5000)

    def _new_project_from_template(self) -> None:
        templates = list_project_templates()
        if not templates:
            QMessageBox.information(
                self,
                "Project templates",
                "No project templates found. Save the current project layout as a template first.",
            )
            return
        names = [preset.name for preset in templates]
        selected, accepted = QInputDialog.getItem(
            self,
            "New project from template",
            "Template:",
            names,
            0,
            False,
        )
        if not accepted or not selected:
            return
        has_content = any(track.clips or track.overlays or track.image_overlays for track in self.project.tracks)
        if has_content:
            result = QMessageBox.question(
                self,
                "Replace current project?",
                "This will replace the current timeline with a new empty project from the template. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        try:
            project = new_project_from_template(str(selected), project_name=str(selected))
        except Exception as exc:
            QMessageBox.warning(self, "Load template failed", str(exc))
            return
        self._apply_loaded_project(project)
        self._store_project_id = None
        self.statusBar().showMessage(f"New project created from template: {selected}", 5000)

    def _auto_duck_music_under_voice(self) -> None:
        voice_intervals = collect_role_intervals(self.project.tracks, ("voice",))
        if not voice_intervals:
            QMessageBox.information(
                self,
                "Auto duck",
                "No audible Voice track found. Set an audio track role to Voice first.",
            )
            return

        music_clip_count = sum(
            len(track.clips)
            for track in self.project.tracks
            if track.kind == "audio"
            and str(getattr(track, "role", "other") or "other").strip().lower() == "music"
            and not bool(getattr(track, "hidden", False))
            and not bool(getattr(track, "muted", False))
        )
        if music_clip_count <= 0:
            QMessageBox.information(
                self,
                "Auto duck",
                "No audible Music track found. Set a music track role to Music first.",
            )
            return

        changed = apply_auto_ducking_to_tracks(
            self.project.tracks,
            config=AutoDuckingConfig(),
            replace_existing=True,
        )
        if changed <= 0:
            QMessageBox.information(
                self,
                "Auto duck",
                "No overlapping Music clips were found under the Voice track.",
            )
            return

        self.timeline_panel.refresh()
        self.inspector_panel.refresh()
        self._push_timeline_history()
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        self._on_timeline_seek(current)
        self.statusBar().showMessage(
            f"Auto ducked {changed} music clip(s) under voice.",
            5000,
        )

    def _add_beat_marker_at_playhead(self) -> None:
        seconds = max(0.0, float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)))
        marker = add_beat_marker(
            self.project,
            seconds,
            label=f"Beat {len(self.project.beat_markers) + 1}",
            source="manual",
        )
        self.timeline_panel.refresh()
        self._push_timeline_history()
        self.statusBar().showMessage(
            f"Beat marker added at {format_timecode(float(marker.time))}.",
            4000,
        )

    def _remove_beat_marker_near_playhead(self) -> None:
        seconds = max(0.0, float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)))
        removed = remove_near_beat_marker(self.project, seconds, tolerance=0.08)
        if not removed:
            QMessageBox.information(
                self,
                "Beat marker",
                "No beat marker found near the playhead.",
            )
            return
        self.timeline_panel.refresh()
        self._push_timeline_history()
        self.statusBar().showMessage("Beat marker removed.", 4000)

    def _add_media(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, t("action.add_media"))
        for p in paths:
            self.media_panel.add_media(Path(p))
        if paths:
            self._on_media_files_imported([Path(p) for p in paths])

    def _on_media_files_imported(self, paths: list[Path]) -> None:
        if not paths:
            return
        from ..core.project import LibraryEntry

        existing = {self._norm_lib_path(e.source) for e in self.project.library_media}
        added_count = 0
        for p in paths:
            norm = self._norm_lib_path(p)
            if not norm or norm in existing:
                try:
                    self._media_ingest.enqueue(p)
                except Exception:
                    pass
                continue
            cached = self._cached_media_info_for_path(p)
            duration = cached.duration if cached is not None else None
            try:
                st = Path(p).stat()
                entry = LibraryEntry(
                    source=str(p), name=Path(p).name, size=st.st_size, mtime=st.st_mtime, duration=duration
                )
            except OSError:
                entry = LibraryEntry(source=str(p), name=Path(p).name, duration=duration)
            self.project.library_media.append(entry)
            existing.add(norm)
            added_count += 1
            try:
                self._media_ingest.enqueue(p)
            except Exception:
                pass
        self._save_to_store_safe()
        if added_count:
            self.statusBar().showMessage(
                f"Imported {added_count} file(s). Analyzing in background...",
                4000,
            )

    def _on_ingest_status_changed(self, path_obj: object, status_obj: object) -> None:
        path = Path(str(path_obj))
        status = str(status_obj or "")
        try:
            self.media_panel.update_media_status(path, status)
        except Exception:
            pass
        if status and status != "Ready":
            self.statusBar().showMessage(f"{status}: {path.name}", 2500)

    def _on_ingest_metadata_ready(self, path_obj: object, info_obj: object) -> None:
        path = Path(str(path_obj))
        if isinstance(info_obj, CachedMediaInfo):
            self._pending_ingest_metadata.append((path, info_obj))
        else:
            self._pending_ingest_failures.append(path)
        if not self._ingest_flush_timer.isActive():
            self._ingest_flush_timer.start()

    def _flush_pending_ingest_metadata(self) -> None:
        failures = self._pending_ingest_failures
        items = self._pending_ingest_metadata
        self._pending_ingest_failures = []
        self._pending_ingest_metadata = []

        for path in failures:
            self.media_panel.update_media_status(path, "Analyze failed")

        if not items:
            return

        changed_library = False
        placeholder_updates: dict[int, tuple[Clip, float]] = {}
        for path, info in items:
            source_key = self._source_key_for_path(path)
            self._preview_audio_presence_cache[source_key] = bool(info.has_audio)

            norm = self._norm_lib_path(path)
            for entry in self.project.library_media:
                if self._norm_lib_path(entry.source) != norm:
                    continue
                duration = info.duration if info.duration and info.duration > 0.0 else getattr(entry, "duration", None)
                try:
                    entry.duration = duration
                    entry.size = info.size or getattr(entry, "size", None)
                    if info.mtime_ns:
                        entry.mtime = float(info.mtime_ns) / 1_000_000_000.0
                    changed_library = True
                except Exception:
                    pass
                break

            try:
                new_duration = float(info.duration or 0.0)
            except Exception:
                new_duration = 0.0
            if new_duration > 0.0:
                for clip in self._duration_placeholder_by_source_key.get(source_key, ()):
                    placeholder_updates[id(clip)] = (clip, new_duration)

            self.media_panel.update_media_status(path, "Ready")

        changed_clips: list[Clip] = []
        affected_track_ids: set[int] = set()
        has_video_track_change = False
        if placeholder_updates:
            target_ids = set(placeholder_updates)
            clip_track_by_id: dict[int, Track] = {}
            for track in self.project.tracks:
                for clip in track.clips:
                    clip_id = id(clip)
                    if clip_id in target_ids:
                        clip_track_by_id[clip_id] = track

            for clip_id, (clip, duration) in placeholder_updates.items():
                track = clip_track_by_id.get(clip_id)
                if track is None:
                    self._unregister_placeholder_clip(clip)
                    continue
                clip.out_point = float(clip.in_point) + max(0.001, duration)
                self._unregister_placeholder_clip(clip)
                changed_clips.append(clip)
                affected_track_ids.add(id(track))
                if track.kind == "video":
                    has_video_track_change = True
                elif track.kind == "audio":
                    resolved_track = self._move_audio_clip_to_non_overlapping_track(
                        clip,
                        track,
                    )
                    affected_track_ids.add(id(resolved_track))

        for track in self.project.tracks:
            if id(track) in affected_track_ids:
                track.clips.sort(key=lambda c: float(c.start))

        if not changed_library and not changed_clips:
            return

        if changed_clips:
            self._invalidate_clip_interval_indexes()
        try:
            self.timeline_panel.refresh()
        except Exception:
            pass
        if changed_clips:
            try:
                self._prewarm_timeline_cache_for_clips(changed_clips)
            except Exception:
                pass
        if has_video_track_change:
            try:
                self.timeline_panel.auto_zoom_to_duration(max(1.0, self.project.duration + 5.0))
            except Exception:
                pass
        try:
            self.inspector_panel.refresh()
        except Exception:
            pass
        self._invalidate_timeline_audio_mix(clear_player=False)
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        self._sync_preview_for_timeline_clock(current, playing=False, force_seek=False)
        self._save_to_store_safe()

    def _on_ingest_thumbnail_ready(self, path_obj: object, thumbnail_obj: object) -> None:
        path = Path(str(path_obj))
        thumb = Path(str(thumbnail_obj)) if thumbnail_obj else None
        self.media_panel.update_media_thumbnail(path, thumb)

    def _on_ingest_proxy_ready(self, path_obj: object, proxy_obj: object) -> None:
        path = Path(str(path_obj))
        proxy = Path(str(proxy_obj)) if proxy_obj else None
        if proxy is None or not proxy.exists():
            return
        source_key = self._source_key_for_path(path)
        changed_clips: list[Clip] = []
        for track in self.project.tracks:
            if track.kind != "video":
                continue
            for clip in track.clips:
                if self._source_key_for_path(clip.source) != source_key:
                    continue
                clip.proxy = str(proxy)
                changed_clips.append(clip)
        if not changed_clips:
            return
        self._prewarm_timeline_cache_for_clips(changed_clips)
        self._invalidate_clip_interval_indexes()
        self.timeline_panel.refresh()
        self._save_to_store_safe()
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        active_clip = self._pick_video_clip_for_time(current)
        if active_clip is not None and self._source_key_for_path(active_clip.source) == source_key:
            playing = bool(getattr(self.timeline_panel, "_is_playing", False))
            self._sync_preview_for_timeline_clock(current, playing=playing, force_seek=not playing)
        self.statusBar().showMessage(f"Preview proxy ready: {path.name}", 3000)

    def _on_ingest_audio_proxy_ready(self, path_obj: object, proxy_obj: object) -> None:
        if not self._use_audio_proxies:
            return
        path = Path(str(path_obj))
        proxy = Path(str(proxy_obj)) if proxy_obj else None
        if proxy is None or not proxy.exists():
            return
        source_key = self._source_key_for_path(path)
        self._audio_proxy_by_source[source_key] = str(proxy)
        self._audio_proxy_by_source[str(path)] = str(proxy)
        self._audio_proxy_path_cache.clear()
        self._clip_audio_preview_path_cache.clear()
        self._clip_deferred_audio_proxy_cache.clear()
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        self._ensure_clip_interval_indexes()
        active_clip = pick_timeline_audio_clip(
            self.project.tracks,
            current,
            fallback_to_first=False,
            index=self._audio_clip_index,
        )
        if (
            bool(getattr(self.timeline_panel, "_is_playing", False))
            and active_clip is not None
            and self._source_key_for_path(active_clip.source) == source_key
        ):
            self._sync_preview_for_timeline_clock(current, playing=True, force_seek=False)
        self.statusBar().showMessage(f"Audio proxy ready: {path.name}", 3000)

    def _voice_target_subtitle_clips(self) -> list[Clip]:
        clips: list[Clip] = []
        for track in self.project.tracks:
            if track.kind != "text" or self._is_track_hidden(track) or self._is_track_muted(track):
                continue
            for clip in track.clips:
                if not clip.is_text_clip:
                    continue
                duration = clip.timeline_duration or 0.0
                if duration <= 0.0:
                    continue
                text = (clip.text_main or clip.text_second or "").strip()
                if not text:
                    continue
                clips.append(clip)
        clips.sort(key=lambda c: (float(c.start), float(c.timeline_duration or 0.0)))
        return clips

    @staticmethod
    def _natural_voice_sort_key(path: Path) -> list[object]:
        return [
            int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", path.name)
        ]

    def _voice_audio_files_from_folder(self, folder: Path) -> list[Path]:
        folder = Path(folder)
        if not folder.is_dir():
            raise ValueError(f"Folder voice không tồn tại: {folder}")
        files = [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() == ".mp3"
        ]
        files.sort(key=self._natural_voice_sort_key)
        if not files:
            raise ValueError("Folder không có file MP3.")
        return files

    def _add_voice_folder_to_timeline(self, folder: Path) -> list[Clip]:
        subtitle_clips = self._voice_target_subtitle_clips()
        audio_files = self._voice_audio_files_from_folder(folder)
        if subtitle_clips and len(audio_files) != len(subtitle_clips):
            raise ValueError(
                f"Số file audio ({len(audio_files)}) không khớp số khối phụ đ "
                f"({len(subtitle_clips)})."
            )

        primary = self._get_or_create_track("audio", None)
        touched_tracks: list[Track] = []
        track_end: dict[int, float] = {}

        def _register_touched(target: Track) -> None:
            for existing in touched_tracks:
                if existing is target:
                    return
            touched_tracks.append(target)

        def _track_end(target: Track) -> float:
            cached = track_end.get(id(target))
            if cached is not None:
                return cached
            max_end = 0.0
            for existing in target.clips:
                existing_duration = float(existing.timeline_duration or 0.0)
                if existing_duration <= 0.0:
                    continue
                existing_start = float(existing.start)
                max_end = max(max_end, existing_start + existing_duration)
            track_end[id(target)] = max_end
            return max_end

        def _candidate_tracks() -> list[Track]:
            candidates: list[Track] = []
            if not self._is_track_locked(primary):
                candidates.append(primary)
            for existing_track in self.project.tracks:
                if existing_track.kind != "audio":
                    continue
                if existing_track is primary:
                    continue
                if self._is_track_locked(existing_track):
                    continue
                candidates.append(existing_track)
            return candidates

        def _new_audio_track() -> Track:
            return self._get_or_create_track(
                "audio",
                self._audio_insert_index_after_last_audio(),
                insert_new_track=True,
            )

        def _pick_target_track(start: float, duration: float) -> Track:
            for candidate in _candidate_tracks():
                if float(start) >= _track_end(candidate):
                    return candidate
            new_track = _new_audio_track()
            track_end[id(new_track)] = 0.0
            return new_track

        created: list[Clip] = []
        sequential_start = 0.0
        if not subtitle_clips:
            sequential_start = _track_end(primary)

        for index, audio_path in enumerate(audio_files):
            target_start = sequential_start
            fallback_duration = 0.05
            if subtitle_clips:
                subtitle_clip = subtitle_clips[index]
                target_start = float(subtitle_clip.start)
                fallback_duration = max(0.05, float(subtitle_clip.timeline_duration or 0.05))
            duration, duration_is_placeholder = self._duration_for_insert(
                audio_path,
                fallback=fallback_duration,
            )

            target_track = _pick_target_track(target_start, duration)
            clip = Clip(
                source=str(audio_path),
                start=float(target_start),
                in_point=0.0,
                out_point=float(duration),
            )
            target_track.clips.append(clip)
            track_end[id(target_track)] = max(
                _track_end(target_track),
                float(target_start) + float(duration),
            )
            if duration_is_placeholder:
                self._register_placeholder_clip(clip)
            _register_touched(target_track)
            created.append(clip)
            if not subtitle_clips:
                sequential_start = float(target_start) + float(clip.timeline_duration or duration)

        for touched in touched_tracks:
            touched.clips.sort(key=lambda c: float(c.start))
        try:
            enqueue_many = getattr(self._media_ingest, "enqueue_many")
            enqueue_many(audio_files)
        except Exception:
            for audio_path in audio_files:
                try:
                    self._media_ingest.enqueue(audio_path)
                except Exception:
                    pass
        return created

    def _open_voice_folder_picker(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chn folder voice")
        if folder:
            self._on_add_voice_folder_requested(Path(folder))

    def _on_add_voice_folder_requested(self, folder: Path) -> None:
        try:
            created = self._add_voice_folder_to_timeline(Path(folder))
        except ValueError as exc:
            QMessageBox.warning(self, "Thêm Voice", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Thêm Voice thất bại", str(exc))
            return

        self._invalidate_clip_interval_indexes()
        self.timeline_panel.refresh()
        if created:
            large_import = len(created) > 250
            if large_import:
                self.timeline_panel.select_clip(created[0])
            else:
                self.timeline_panel.select_clips(created)
            ready_created = [
                clip for clip in created
                if id(clip) not in self._duration_placeholder_clip_ids
            ]
            try:
                if ready_created:
                    self.timeline_panel.prewarm_track_clips(ready_created)
            except Exception:
                pass
        self.inspector_panel.refresh()
        self._preview_sync_mode = "timeline"
        self._push_timeline_history()
        self._refresh_auto_speed_issue_overlays()
        self._save_to_store_safe()
        mode_text = "theo phụ đ" if self._voice_target_subtitle_clips() else "tuần tự"
        self.statusBar().showMessage(
            f"ã thêm {len(created)} voice clip vào timeline {mode_text}.",
            5000,
        )

    def _on_media_files_removed(self, paths: list[Path]) -> None:
        if not paths:
            return
        targets = {self._norm_lib_path(p) for p in paths if p}
        if not targets:
            return
        self.project.library_media = [
            e for e in self.project.library_media
            if self._norm_lib_path(e.source) not in targets
        ]
        self._save_to_store_safe()

    def _on_subtitle_files_imported(self, paths: list[Path]) -> None:
        if not paths:
            return
        from ..core.project import LibraryEntry
        existing = {self._norm_lib_path(e.source) for e in self.project.library_subtitles}
        for p in paths:
            norm = self._norm_lib_path(p)
            if not norm or norm in existing:
                continue
            try:
                st = Path(p).stat()
                entry = LibraryEntry(
                    source=str(p), name=Path(p).name, size=st.st_size, mtime=st.st_mtime, duration=None
                )
            except OSError:
                entry = LibraryEntry(source=str(p), name=Path(p).name, duration=None)
            self.project.library_subtitles.append(entry)
            existing.add(norm)
        self._save_to_store_safe()

    def _on_subtitle_files_removed(self, paths: list[Path]) -> None:
        if not paths:
            return
        targets = {self._norm_lib_path(p) for p in paths if p}
        if not targets:
            return
        self.project.library_subtitles = [
            e for e in self.project.library_subtitles
            if self._norm_lib_path(e.source) not in targets
        ]
        self._save_to_store_safe()

    @staticmethod
    def _norm_lib_path(p) -> str:
        try:
            return str(Path(p).resolve()).lower()
        except Exception:
            return str(p).lower() if p else ""

    def _save_to_store_safe(self) -> None:
        """Write project to store, swallowing transient I/O errors silently."""
        try:
            self.save_to_store()
        except Exception:
            pass

    def _on_media_selection_changed(self, path_obj: object) -> None:
        if self._preview_sync_mode == "timeline" and path_obj is None:
            # Avoid flicker: if we are switching to timeline mode (e.g. after a drop),
            # don't clear the preview just because the library card was deselected.
            return
        self._preview_sync_mode = "library"
        self.preview_panel.clear_timeline_time_display()
        self.preview_panel.set_timeline_playing_override(None)
        self.preview_panel.clear_video_transform()
        self.preview_panel.clear_timeline_audio()
        if not isinstance(path_obj, Path):
            self.preview_panel.set_audio_muted(False)
            self.preview_panel.clear()
            self._preview_source_path = None
            return
        kind = self._track_kind_for_path(path_obj)
        if kind != "video":
            self.preview_panel.set_audio_muted(False)
            self.preview_panel.clear()
            self._preview_source_path = None
            return
        self.preview_panel.set_audio_muted(False)
        self._set_preview_source(path_obj, force=True)
        self.preview_panel.seek(0)

    def _on_relink_media(self, old_path: Path) -> None:
        from ..core.library_resolver import resolve_project_library
        res = resolve_project_library(self.project)
        self._show_relink_dialog(res["media"], res["subtitles"], highlight_path=old_path)

    def _on_relink_subtitle(self, old_path: Path) -> None:
        from ..core.library_resolver import resolve_project_library
        res = resolve_project_library(self.project)
        self._show_relink_dialog(res["media"], res["subtitles"], highlight_path=old_path)

    def _refresh_library_panels_from_project(self) -> None:
        from ..core.library_resolver import resolve_project_library
        missing_flags = resolve_project_library(self.project)
        self.media_panel.set_imported_entries(
            list(self.project.library_media),
            missing_flags["media"],
        )
        self.text_panel.set_imported_subtitles_with_missing(
            list(self.project.library_subtitles),
            missing_flags["subtitles"],
        )
        self._update_media_library_added_states()

    def _on_add_clip(self, path: Path) -> None:
        self._insert_clip(path)

    def _on_add_clip_from_card(self, path: Path) -> None:
        # Adding from the library should place/select the clip, not inherit a
        # previous preview playback state after the timeline clip was deleted.
        self.preview_panel.pause()
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        self._insert_clip(path, start=self._clamp_timeline_seconds(current))
        self.preview_panel.pause()

    def _on_drop_add_clip(
        self, path: str, start: float, track_index: int, insert_new_track: bool
    ) -> None:
        self._insert_clip(
            Path(path),
            start=start,
            track_index=track_index,
            insert_new_track=insert_new_track,
        )

    @staticmethod
    def _track_kind_for_path(path: Path) -> str:
        ext = path.suffix.lower()
        if ext in MainWindow._AUDIO_EXTS:
            return "audio"
        if ext in MainWindow._SUBTITLE_EXTS:
            return "text"
        return "video"

    def _main_video_track(self) -> Track | None:
        for track in self.project.tracks:
            if (
                track.kind == "video"
                and track.name.strip().lower() == "main"
                and not self._is_track_hidden(track)
            ):
                return track
        return next(
            (
                tr for tr in self.project.tracks
                if tr.kind == "video" and not self._is_track_hidden(tr)
            ),
            None,
        )

    def _is_main_video_track(self, track: Track) -> bool:
        main = self._main_video_track()
        return main is not None and track is main

    @staticmethod
    def _is_track_locked(track: Track) -> bool:
        return bool(getattr(track, "locked", False))

    @staticmethod
    def _is_track_hidden(track: Track) -> bool:
        return bool(getattr(track, "hidden", False))

    @staticmethod
    def _is_track_muted(track: Track) -> bool:
        return bool(getattr(track, "muted", False))

    @staticmethod
    def _resolve_non_overlapping_start(track: Track, desired_start: float, duration: float) -> float:
        """Avoid clip overlap on the same track by pushing to the right when needed."""
        resolved = max(0.0, desired_start)
        if duration <= 0.0:
            return resolved

        clips = sorted(track.clips, key=lambda c: c.start)
        for clip in clips:
            clip_dur = clip.timeline_duration or 0.0
            if clip_dur <= 0.0:
                continue
            clip_start = clip.start
            clip_end = clip_start + clip_dur
            if resolved + duration <= clip_start:
                break
            if resolved < clip_end and resolved + duration > clip_start:
                resolved = clip_end
        return resolved

    @staticmethod
    def _clip_overlaps_track(
        track: Track,
        clip: Clip,
        *,
        start: float | None = None,
        duration: float | None = None,
    ) -> bool:
        clip_start = float(clip.start if start is None else start)
        clip_duration = float(
            (clip.timeline_duration or 0.0) if duration is None else duration
        )
        if clip_duration <= 0.0:
            return False
        clip_end = clip_start + clip_duration
        eps = 1e-6
        for existing in track.clips:
            if existing is clip:
                continue
            existing_duration = float(existing.timeline_duration or 0.0)
            if existing_duration <= 0.0:
                continue
            existing_start = float(existing.start)
            existing_end = existing_start + existing_duration
            if clip_start < existing_end - eps and clip_end > existing_start + eps:
                return True
        return False

    def _audio_insert_index_after_last_audio(self) -> int:
        insert_idx = len(self.project.tracks)
        for idx, existing_track in enumerate(self.project.tracks):
            if existing_track.kind == "audio":
                insert_idx = idx + 1
        return insert_idx

    def _move_audio_clip_to_non_overlapping_track(
        self,
        clip: Clip,
        current_track: Track,
    ) -> Track:
        if current_track.kind != "audio":
            return current_track
        duration = float(clip.timeline_duration or 0.0)
        if duration <= 0.0:
            return current_track
        if not self._clip_overlaps_track(current_track, clip, duration=duration):
            return current_track

        for candidate in self.project.tracks:
            if candidate.kind != "audio" or candidate is current_track:
                continue
            if self._is_track_locked(candidate):
                continue
            if self._clip_overlaps_track(candidate, clip, duration=duration):
                continue
            try:
                current_track.clips.remove(clip)
            except ValueError:
                pass
            candidate.clips.append(clip)
            current_track.clips.sort(key=lambda c: float(c.start))
            candidate.clips.sort(key=lambda c: float(c.start))
            return candidate

        new_track = self._get_or_create_track(
            "audio",
            self._audio_insert_index_after_last_audio(),
            insert_new_track=True,
        )
        try:
            current_track.clips.remove(clip)
        except ValueError:
            pass
        new_track.clips.append(clip)
        current_track.clips.sort(key=lambda c: float(c.start))
        new_track.clips.sort(key=lambda c: float(c.start))
        return new_track

    def _main_track_insert_start(self, track: Track, requested_start: float, duration: float) -> float:
        if not self._is_main_video_track(track):
            return self._resolve_non_overlapping_start(track, requested_start, duration)
        magnet_enabled = bool(
            getattr(self.timeline_panel, "is_main_track_magnet_enabled", lambda: True)()
        )
        if not magnet_enabled:
            return self._resolve_non_overlapping_start(track, requested_start, duration)
        clips = [c for c in track.clips if (c.timeline_duration or 0.0) > 0.0]
        if not clips:
            return 0.0
        return self._resolve_non_overlapping_start(track, requested_start, duration)

    def _get_or_create_track(
        self,
        kind: str,
        preferred_index: int | None,
        insert_new_track: bool = False,
    ) -> Track:
        if insert_new_track and preferred_index is not None:
            idx = max(0, min(preferred_index, len(self.project.tracks)))
            track = Track(kind=kind, name=f"{kind.title()} {len(self.project.tracks) + 1}")
            self.project.tracks.insert(idx, track)
            return track

        if (
            preferred_index is not None
            and 0 <= preferred_index < len(self.project.tracks)
            and self.project.tracks[preferred_index].kind == kind
            and not self._is_track_locked(self.project.tracks[preferred_index])
        ):
            return self.project.tracks[preferred_index]

        existing = next(
            (
                tr
                for tr in self.project.tracks
                if tr.kind == kind and not self._is_track_locked(tr)
            ),
            None,
        )
        if existing is not None:
            return existing

        track = Track(kind=kind, name=f"{kind.title()} {len(self.project.tracks) + 1}")
        if preferred_index is not None:
            idx = max(0, min(preferred_index, len(self.project.tracks)))
            self.project.tracks.insert(idx, track)
        elif kind == "text":
            main = self._main_video_track()
            if main is not None:
                main_idx = self.project.tracks.index(main)
                self.project.tracks.insert(main_idx, track)
            else:
                self.project.tracks.append(track)
        else:
            self.project.tracks.append(track)
        return track

    @staticmethod
    def _read_subtitle_text(path: Path) -> str:
        for enc in ("utf-8-sig", "utf-8", "gb18030", "cp1252", "latin-1"):
            try:
                return path.read_text(encoding=enc)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="ignore")

    @staticmethod
    def _split_subtitle_lines(raw: str) -> tuple[str, str]:
        lines = [ln.strip() for ln in raw.replace("\r\n", "\n").split("\n") if ln.strip()]
        if not lines:
            return "", ""
        if len(lines) == 1:
            return lines[0], ""
        return lines[0], " ".join(lines[1:])

    def _parse_subtitle_items(self, path: Path) -> list[tuple[float, float, str, str]]:
        ext = path.suffix.lower()
        text = self._read_subtitle_text(path)
        cues: list[tuple[float, float, str, str]] = []
        if ext == ".srt":
            parsed = parse_srt(text)
            for cue in parsed:
                main, second = self._split_subtitle_lines(cue.text)
                if main or second:
                    cues.append((cue.start, cue.end, main, second))
            return cues
        if ext == ".vtt":
            parsed = parse_vtt(text)
            for cue in parsed:
                main, second = self._split_subtitle_lines(cue.text)
                if main or second:
                    cues.append((cue.start, cue.end, main, second))
            return cues
        if ext == ".lrc":
            parsed, _meta = parse_lrc(text)
            for cue in parsed:
                main, second = self._split_subtitle_lines(cue.text)
                if main or second:
                    cues.append((cue.start, cue.end, main, second))
            return cues
        if ext in {".ass", ".ssa"}:
            parsed = parse_ass(text)
            for cue in parsed:
                main, second = self._split_subtitle_lines(cue.text)
                if main or second:
                    cues.append((cue.start, cue.end, main, second))
            return cues

        # Plain TXT fallback: one line = one cue, 3 seconds each.
        now = 0.0
        for line in text.replace("\r\n", "\n").split("\n"):
            main, second = self._split_subtitle_lines(line)
            if not main and not second:
                continue
            cues.append((now, now + 3.0, main, second))
            now += 3.0
        return cues

    def _insert_subtitle_clips(
        self,
        path: Path,
        *,
        start: float | None = None,
        track_index: int | None = None,
        insert_new_track: bool = False,
    ) -> list[Clip]:
        items = self._parse_subtitle_items(path)
        if not items:
            return []

        requested_track = self._get_or_create_track(
            "text",
            track_index,
            insert_new_track=insert_new_track,
        )

        offset = max(0.0, start or 0.0)
        # Keep source subtitle timing intact. If target text track already has
        # overlapping clips, create a new text track instead of shifting cues.
        track = requested_track
        if not insert_new_track:
            has_overlap = False
            for cue_start, cue_end, _main, _second in items:
                dur = max(0.05, cue_end - cue_start)
                cue_abs_start = max(0.0, offset + cue_start)
                resolved = self._resolve_non_overlapping_start(track, cue_abs_start, dur)
                if abs(resolved - cue_abs_start) > 1e-6:
                    has_overlap = True
                    break
            if has_overlap:
                try:
                    preferred_idx = self.project.tracks.index(requested_track)
                except ValueError:
                    preferred_idx = track_index
                track = self._get_or_create_track(
                    "text",
                    preferred_idx,
                    insert_new_track=True,
                )

        created: list[Clip] = []
        for cue_start, cue_end, main, second in items:
            dur = max(0.05, cue_end - cue_start)
            clip = Clip(
                clip_type="text",
                source=str(path),
                start=max(0.0, offset + cue_start),
                in_point=0.0,
                out_point=dur,
                text_main=main,
                text_second=second,
                text_display="bilingual" if second else "main",
            )
            track.clips.append(clip)
            created.append(clip)
        track.clips.sort(key=lambda c: c.start)
        return created

    def _insert_clip(
        self,
        path: Path,
        start: float | None = None,
        track_index: int | None = None,
        insert_new_track: bool = False,
    ) -> None:
        kind = self._track_kind_for_path(path)
        was_timeline_empty = not any(track.clips for track in self.project.tracks)
        if kind == "text":
            created = self._insert_subtitle_clips(
                path,
                start=start,
                track_index=track_index,
                insert_new_track=insert_new_track,
            )
            if not created:
                QMessageBox.warning(
                    self,
                    "Subtitle import",
                    f"No valid subtitle cues found in {path.name}.",
                )
                return
            self.timeline_panel.refresh()
            self._suspend_timeline_selection_sync = True
            try:
                if len(created) > 250:
                    self.timeline_panel.select_clip(created[0])
                else:
                    self.timeline_panel.select_clips(created)
            finally:
                self._suspend_timeline_selection_sync = False
            self._preview_sync_mode = "timeline"
            self._invalidate_subtitle_lookup_cache()
            current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
            self._sync_preview_for_timeline_clock(
                current,
                playing=False,
                force_seek=True,
            )

            large_import = len(created) >= self._LARGE_SUBTITLE_IMPORT_CUE_COUNT

            def _finish_subtitle_import() -> None:
                if not large_import:
                    self.inspector_panel.show_caption_list_neutral()
                self.text_panel.add_imported_subtitle(path)
                self.statusBar().showMessage(
                    f"Imported subtitle: {path.name} ({len(created)} cues)",
                    5000,
                )
                self.media_panel.list_widget.clearSelection()
                self._update_media_library_added_states()
                self._sync_preview_for_timeline_clock(
                    float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)),
                    playing=False,
                    force_seek=False,
                )

                def _record_subtitle_import_state() -> None:
                    self._push_timeline_history()
                    self._refresh_auto_speed_issue_overlays()
                    self._sync_preview_for_timeline_clock(
                        float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)),
                        playing=False,
                        force_seek=False,
                    )

                if large_import:
                    QTimer.singleShot(120, _record_subtitle_import_state)
                else:
                    _record_subtitle_import_state()

            if large_import:
                self.statusBar().showMessage(
                    f"Imported subtitle: {path.name} ({len(created)} cues). Finalizing...",
                    3000,
                )
                QTimer.singleShot(0, _finish_subtitle_import)
            else:
                _finish_subtitle_import()
            return

        track = self._get_or_create_track(
            kind,
            track_index,
            insert_new_track=insert_new_track,
        )

        dur, duration_is_placeholder = self._duration_for_insert(path, fallback=5.0)

        if start is None:
            # Add button/no explicit drop position: append after the target track.
            start = 0.0
            for c in track.clips:
                d = c.timeline_duration or 0.0
                start = max(start, c.start + d)
        else:
            start = max(0.0, start)

        if kind == "video":
            start = self._main_track_insert_start(track, start, dur)
        else:
            start = self._resolve_non_overlapping_start(track, start, dur)
        clip = Clip(source=str(path), start=start, in_point=0.0, out_point=dur)
        if duration_is_placeholder:
            self._register_placeholder_clip(clip)
        try:
            self._media_ingest.enqueue(path)
        except Exception:
            pass
        track.clips.append(clip)
        track.clips.sort(key=lambda c: c.start)
        if kind == "video":
            try:
                self.timeline_panel.normalize_main_track_magnetic()
            except Exception:
                pass
        if not duration_is_placeholder:
            try:
                self.timeline_panel.prewarm_track_clips([clip])
            except Exception:
                pass
        self.timeline_panel.refresh()
        self.timeline_panel.select_clip(clip)
        if was_timeline_empty and kind == "video" and not duration_is_placeholder:
            # Auto-fit first imported visual clip so ruler range reflects media length.
            self.timeline_panel.auto_zoom_to_duration(max(1.0, dur + 5.0))
            self.timeline_panel.set_playhead(0.0)
            QTimer.singleShot(0, self.timeline_panel.scroll_to_start)
        self.inspector_panel.refresh()

        self._preview_sync_mode = "timeline"
        self.media_panel.list_widget.clearSelection()
        self._update_media_library_added_states()
        # Match HTML behavior: immediately show the timeline frame at the current playhead.
        self._on_timeline_seek(self.timeline_panel._playhead_seconds)
        self._push_timeline_history()
        self._refresh_auto_speed_issue_overlays()

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Undo):
            self._undo_timeline()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self._redo_timeline()
            event.accept()
            return

        if event.matches(QKeySequence.StandardKey.Find):
            try:
                info = self.inspector_panel._info
                info._btn_text_tab_caption.setChecked(True)
                info._caption_list._search_input.setFocus()
                info._caption_list._search_input.selectAll()
            except Exception:
                pass
            event.accept()
            return

        if (
            event.modifiers() == Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_H
        ):
            self._on_caption_find_replace()
            event.accept()
            return

        if event.key() == Qt.Key.Key_Delete:
            fw = QApplication.focusWidget()
            try:
                info = self.inspector_panel._info
                tbl = info._caption_list._table
            except Exception:
                tbl = None
            if (
                tbl is not None
                and tbl.state() != QAbstractItemView.State.EditingState
                and fw is not None
                and (fw is tbl or tbl.isAncestorOf(fw))
            ):
                sel = info._caption_list._selected_clip()
                if sel is not None:
                    self._on_caption_delete(sel)
                    event.accept()
                    return

        if event.key() == Qt.Key.Key_F3:
            try:
                info = self.inspector_panel._info
                cap = info._caption_list
                if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                    cap._on_find_prev()
                else:
                    cap._on_find_next()
            except Exception:
                pass
            event.accept()
            return

        if (
            event.key() == Qt.Key.Key_S
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            fw = QApplication.focusWidget()
            if not self._is_text_entry_focus_widget(fw):
                btn = getattr(self.timeline_panel, "_btn_hover_scrub", None)
                if btn is not None:
                    btn.toggle()
                event.accept()
                return

        if (
            event.key() == Qt.Key.Key_A
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            fw = QApplication.focusWidget()
            if not self._is_text_entry_focus_widget(fw):
                self._on_caption_add()
                event.accept()
                return

        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            if self._handle_space_play_pause_shortcut():
                event.accept()
                return
        super().keyPressEvent(event)

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("menu.file.open"), filter="*.json")
        if not path:
            return
        self._apply_loaded_project(Project.from_json(path))
        self._store_project_id = None

    def _on_import_capcut(self) -> None:
        """File -> Import CapCut Project menu handler."""
        from ..core.capcut_importer import import_capcut_draft

        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Select a CapCut draft_content.json",
            str(Path.home()),
            "CapCut Draft (draft_content.json);;JSON Files (*.json);;All Files (*)",
        )
        if not path_str:
            return

        path = Path(path_str)
        try:
            project = import_capcut_draft(path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "CapCut Import Failed",
                f"Could not import {path.name}:\n\n{exc}",
            )
            return

        try:
            meta = store_save_project(project)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Saved With Warnings",
                f"Imported but failed to save: {exc}",
            )
            self._apply_loaded_project(project)
            self._store_project_id = None
            return

        self.load_project_from_store(meta.project_id)

        QMessageBox.information(
            self,
            "CapCut Import Complete",
            f"Imported {len(project.tracks)} tracks and "
            f"{sum(len(t.clips) for t in project.tracks)} clips from "
            f"{path.name}.",
        )

    def _should_warn_capcut_main_gap(self) -> bool:
        magnet_enabled = bool(
            getattr(self.timeline_panel, "is_main_track_magnet_enabled", lambda: True)()
        )
        if magnet_enabled:
            return False
        main = self._main_video_track()
        if main is None:
            return False
        clips = [
            clip
            for clip in main.clips
            if (clip.timeline_duration or 0.0) > 0.0
        ]
        if not clips:
            return False
        first = min(clips, key=lambda c: float(c.start))
        return float(first.start) > 1e-3

    def _on_export_capcut(self) -> None:
        """File -> Export to CapCut format menu handler."""
        from ..core.capcut_exporter import export_to_capcut

        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Export project to CapCut format",
            str(Path.home() / "draft_content.json"),
            "CapCut Draft (draft_content.json);;JSON Files (*.json);;All Files (*)",
        )
        if not path_str:
            return

        if self._should_warn_capcut_main_gap():
            QMessageBox.warning(
                self,
                "CapCut Export Warning",
                "Main Track Magnet đang tắt và clip đầu trên Main không bắt đầu ở 00:00.\n\n"
                "JianYing/CapCut có thể tự hút đoạn chính v 0s khi mở draft. "
                "ComeCut sẽ giữ nguyên timeline local của bạn và không tự sửa project.",
            )

        path = Path(path_str)
        try:
            dest = export_to_capcut(self.project, path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Could not export to CapCut format:\n\n{exc}",
            )
            return

        QMessageBox.information(
            self,
            "Export Complete",
            f"Exported as CapCut draft:\n{dest}\n\n"
            f"To open in CapCut:\n"
            f"1. Create a new folder under %LOCALAPPDATA%\\CapCut\\User Data\\Projects\\com.lveditor.draft\\<UUID>\\\n"
            f"2. Place this file there as draft_content.json\n"
            f"3. Reopen CapCut and check Drafts",
        )

    def load_project_from_store(self, project_id: str) -> None:
        self._store_project_id = project_id
        self._apply_loaded_project(store_load_project(project_id))

    def save_to_store(self) -> None:
        meta = store_save_project(self.project, project_id=self._store_project_id)
        self._store_project_id = meta.project_id

    def _stop_preview_playback(self) -> None:
        """Stop all preview media immediately (video + timeline audio)."""
        self._stop_gap_playback()
        self._timeline_audio_active_clip_id = None
        self.timeline_panel.set_playing_state(False)
        self.preview_panel.set_timeline_playing_override(False)
        try:
            self.preview_panel.clear()
        except Exception:
            try:
                self.preview_panel.pause()
            except Exception:
                pass
            try:
                self.preview_panel.clear_timeline_audio()
            except Exception:
                pass
        self._preview_source_path = None
        self._preview_active_media_clip = None

    def _apply_loaded_project(self, project: Project) -> None:
        from ..core.library_resolver import resolve_project_library
        self._stop_preview_playback()
        res = resolve_project_library(project)
        missing_flags = res

        # Sync resolved paths to timeline clips
        path_map = res.get("path_map", {})
        if path_map:
            for track in project.tracks:
                for clip in track.clips:
                    norm = self._norm_lib_path(clip.source)
                    if norm in path_map:
                        clip.source = path_map[norm]

        self.project = project
        self._preview_source_path = None
        self._invalidate_clip_interval_indexes()
        self._invalidate_timeline_audio_mix(clear_player=True)
        self.timeline_panel.set_project(self.project)
        self.inspector_panel.set_project(self.project)
        self.topbar.set_project_title(self.project.name)
        self._start_project_proxy_generation()
        QTimer.singleShot(0, self._start_project_audio_proxy_generation)
        self.timeline_panel.refresh()
        self._sync_preview_play_availability()
        all_clips = [clip for track in self.project.tracks for clip in track.clips]
        self._schedule_timeline_cache_prewarm(all_clips)
        self._preview_sync_mode = "timeline"
        current = float(getattr(self.timeline_panel, "_playhead_seconds", 0.0))
        seek_to = min(max(0.0, current), max(0.0, self.project.duration))
        self.timeline_panel.set_playhead(seek_to)
        self._schedule_timeline_preview_prime(seek_to)
        
        # Repopulate library panels with missing state awareness
        self.media_panel.set_imported_entries(
            list(self.project.library_media),
            missing_flags["media"],
        )
        self.text_panel.set_imported_subtitles_with_missing(
            list(self.project.library_subtitles),
            missing_flags["subtitles"],
        )
        self._update_media_library_added_states()
        self._reset_timeline_history()
        self._refresh_auto_speed_issue_overlays()
        QTimer.singleShot(0, self._ensure_project_overview_panel)

        if any(missing_flags["media"]) or any(missing_flags["subtitles"]):
            QTimer.singleShot(0, lambda: self._show_relink_dialog(missing_flags["media"], missing_flags["subtitles"]))
        
        # If resolver updated any paths, persist them
        self._save_to_store_safe()

    def _show_relink_dialog(
        self, 
        media_missing: list[bool], 
        sub_missing: list[bool],
        highlight_path: Path | None = None
    ) -> None:
        from .widgets.relink_dialog import RelinkMediaDialog, RelinkRow

        rows: list[RelinkRow] = []
        highlight_idx = -1
        highlight_norm = self._norm_lib_path(highlight_path) if highlight_path else ""

        for i, missing in enumerate(media_missing):
            if not missing:
                continue
            e = self.project.library_media[i]
            if highlight_norm and self._norm_lib_path(e.source) == highlight_norm:
                highlight_idx = len(rows)
            rows.append(RelinkRow(
                index=i, kind="media",
                name=e.name or Path(e.source).name,
                old_path=e.source,
                duration=e.duration,
                size=e.size,
            ))
        for i, missing in enumerate(sub_missing):
            if not missing:
                continue
            e = self.project.library_subtitles[i]
            if highlight_norm and self._norm_lib_path(e.source) == highlight_norm:
                highlight_idx = len(rows)
            rows.append(RelinkRow(
                index=i, kind="subtitle",
                name=e.name or Path(e.source).name,
                old_path=e.source,
                duration=e.duration,
                size=e.size,
            ))

        if not rows:
            return

        dialog = RelinkMediaDialog(rows, parent=self)
        if highlight_idx >= 0:
            dialog.table.selectRow(highlight_idx)
            dialog.table.scrollToItem(dialog.table.item(highlight_idx, 0))
        dialog.relinks_applied.connect(self._apply_relinks)
        dialog.exec()

    def _apply_relinks(self, rows: list["RelinkRow"]) -> None:
        """Apply relinked paths from the dialog back into the project and sync Timeline."""
        from ..core.media_probe import probe
        changed = False
        for row in rows:
            if row.new_path is None:
                continue
            new_path = Path(row.new_path)
            old_norm = self._norm_lib_path(row.old_path)
            
            # Update Library entry
            try:
                st = new_path.stat()
                duration = None
                try:
                    info = probe(new_path)
                    duration = info.duration
                except Exception:
                    pass
                update = {
                    "source": str(new_path),
                    "name": new_path.name,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                }
                # Keep old duration if probe fails
                if duration is not None:
                    update["duration"] = duration
            except OSError:
                update = {"source": str(new_path), "name": new_path.name}
            
            target_list = (
                self.project.library_media if row.kind == "media"
                else self.project.library_subtitles
            )
            if 0 <= row.index < len(target_list):
                target_list[row.index] = target_list[row.index].model_copy(update=update)
                changed = True
            
            # Sync to Timeline clips
            for track in self.project.tracks:
                for clip in track.clips:
                    if self._norm_lib_path(clip.source) == old_norm:
                        clip.source = str(new_path)

        if changed:
            self._invalidate_clip_interval_indexes()
            self._save_to_store_safe()
            self._refresh_library_panels_from_project()
            self.timeline_panel.refresh()

    def _refresh_library_panels_from_project(self) -> None:
        from ..core.library_resolver import resolve_project_library
        res = resolve_project_library(self.project)
        self.media_panel.set_imported_entries(
            list(self.project.library_media),
            res["media"],
        )
        self.text_panel.set_imported_subtitles_with_missing(
            list(self.project.library_subtitles),
            res["subtitles"],
        )
        self._update_media_library_added_states()

    def _ensure_project_overview_panel(self) -> None:
        """Keep startup state on Project Properties when no clip is selected."""
        try:
            selected = self.timeline_panel.selected_clips()
        except Exception:
            selected = []
        if selected:
            return
        if self.inspector_panel.current_clip() is not None:
            return
        self._set_clip_in_inspector(None)

    def _save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, t("menu.file.save_project"), filter="*.json"
        )
        if not path:
            return
        if not path.endswith(".json"):
            path += ".json"
        self.project.to_json(path)
        try:
            self.save_to_store()
        except Exception:
            pass
        self.statusBar().showMessage(f"Saved: {path}", 5000)

    def _export_video(self) -> None:
        dlg = ExportDialog(self, project_name=self.project.name)
        if dlg.exec() != ExportDialog.Accepted:
            return
        opts = dlg.get_options()
        out_path = opts.video_output_path()
        video_ok = False
        audio_ok = False

        if opts.video_enabled:
            try:
                cmd = render_project(self.project, str(out_path), preset=opts.preset)
            except Exception as e:
                QMessageBox.critical(self, "Export failed", str(e))
                return
            try:
                self.statusBar().showMessage(t("status.rendering"))
                cmd.run(check=True)
                video_ok = True
            except Exception as e:
                QMessageBox.critical(self, "Export failed", str(e))
                return

        audio_path = opts.audio_output_path()
        if opts.audio_enabled:
            try:
                cmd = render_project_audio_only(
                    self.project,
                    str(audio_path),
                    audio_format=opts.audio_format,
                )
            except Exception as e:
                QMessageBox.critical(self, "Audio export failed", str(e))
                return
            try:
                self.statusBar().showMessage("Exporting audio...")
                cmd.run(check=True)
                audio_ok = True
            except Exception as e:
                QMessageBox.critical(self, "Audio export failed", str(e))
                return

        subtitle_msg = ""
        if opts.subs_enabled:
            sub_path = opts.subtitle_output_path()
            try:
                count = self._write_subtitles_file(
                    sub_path,
                    fmt=opts.subs_format,
                    display=opts.subs_display,
                )
                subtitle_msg = f" | subtitles: {sub_path.name} ({count})"
            except Exception as e:
                QMessageBox.critical(self, "Subtitle export failed", str(e))
                return

        if video_ok or audio_ok:
            parts: list[str] = []
            if video_ok:
                parts.append(f"video: {out_path.name}")
            if audio_ok:
                parts.append(f"audio: {audio_path.name}")
            self.statusBar().showMessage(
                f"{t('status.done')} -> {', '.join(parts)}{subtitle_msg}",
                5000,
            )
        elif subtitle_msg:
            self.statusBar().showMessage(f"Subtitle export done{subtitle_msg}", 5000)
        else:
            QMessageBox.information(
                self,
                "Export",
                "Video, Audio and Subtitles are disabled. Nothing to export.",
            )

    def _export_still_frame(self) -> None:
        playhead = max(0.0, float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)))
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", self.project.name or "frame").strip("._")
        safe_name = safe_name or "frame"
        default_path = Path.home() / "Pictures" / f"{safe_name}_{int(playhead * 1000):06d}.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export still frame",
            str(default_path),
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".png")
        try:
            cmd = render_project_still_frame(
                self.project,
                str(target),
                at_seconds=playhead,
            )
            self.statusBar().showMessage("Exporting still frame...")
            cmd.run(check=True)
        except Exception as e:
            QMessageBox.critical(self, "Still frame export failed", str(e))
            return
        self.statusBar().showMessage(f"Still frame exported: {target}", 5000)

    def _open_plugin_manager(self, initial_tab: int = 0, *, modal: bool = True) -> None:
        """Open Plugin Manager.

        Use non-modal when invoked from another modal dialog to avoid the UX
        feeling like a freeze (nested .exec()).
        """
        if not modal:
            dlg = getattr(self, "_plugin_manager_dlg", None)
            if dlg is not None and dlg.isVisible():
                try:
                    dlg._nav.setCurrentRow(max(0, int(initial_tab)))  # type: ignore[attr-defined]
                except Exception:
                    pass
                dlg.raise_()
                dlg.activateWindow()
                return

            dlg = PluginManagerDialog(
                self,
                store=self._plugin_store,
                initial_tab=initial_tab,
            )
            dlg.setModal(False)
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

            def _after_close(_result: int) -> None:
                self._plugin_store.load()

            dlg.finished.connect(_after_close)
            self._plugin_manager_dlg = dlg
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return

        PluginManagerDialog(
            self,
            store=self._plugin_store,
            initial_tab=initial_tab,
        ).exec()
        self._plugin_store.load()

    def _import_subtitles_into_text_panel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select subtitle file",
            filter="Subtitles (*.srt *.vtt *.lrc *.ass *.ssa *.txt)",
        )
        if not path:
            return
        subtitle_path = Path(path)
        # Only add to library, do not auto-insert to timeline.
        self.text_panel.add_imported_subtitle(subtitle_path)
        self.statusBar().showMessage(
            f"Imported subtitle into TEXT library: {subtitle_path.name}", 5000
        )

    def _on_subtitle_template(self, kind: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select subtitle file", filter="Subtitles (*.srt *.vtt *.lrc *.ass *.ssa *.txt)"
        )
        if not path:
            return
        subtitle_path = Path(path)
        # Only add to library, do not auto-insert to timeline.
        self.text_panel.add_imported_subtitle(subtitle_path)
        self.statusBar().showMessage(
            f"Loaded {kind} subtitle into TEXT library: {Path(path).name}", 5000
        )

    def _about(self) -> None:
        QMessageBox.information(
            self,
            t("menu.help.about"),
            "ComeCut-Py\nA pure-Python port of the ComeCut video editor.\nLicensed under AGPL-3.0.",
        )
    
    def _update_media_library_added_states(self) -> None:
        used = set()
        for track in self.project.tracks:
            for clip in track.clips:
                try:
                    norm = str(Path(clip.source).resolve()).lower()
                    used.add(norm)
                except Exception:
                    used.add(clip.source.lower())
        self.media_panel.update_added_states(used)

    # ---------------------------------------------------------------
    # OCR Subtitle Extraction handlers
    # ---------------------------------------------------------------

    def _on_ocr_mode_requested(self) -> None:
        """Kiá»ƒm tra timeline cÃ³ video khÃ´ng, rá»“i báº­t overlay chá»n vÃ¹ng."""
        # Kiá»ƒm tra Ä‘iá»u kiá»‡n: pháº£i cÃ³ Ã­t nháº¥t 1 clip video trÃªn timeline
        has_video = any(
            not getattr(clip, "is_text_clip", False)
            for track in self.project.tracks
            for clip in track.clips
        )
        if not has_video:
            QMessageBox.information(
                self,
                "Trích xuất OCR",
                "Vui lòng thêm video vào Timeline trước khi sử dụng tính năng này.",
            )
            return

        self.statusBar().showMessage(
            "Chế độ OCR: Kéo để di chuyển / Resize vùng chn. [Esc] để hủy.", 0
        )
        self.preview_panel.start_ocr_selection()
        self.text_panel.show_ocr_settings()
        self._update_text_sub_nav_visuals("ocr")

    def _on_show_subtitle_list_requested(self) -> None:
        """Quay láº¡i danh sÃ¡ch phá»¥ Ä‘á»."""
        self.preview_panel.stop_ocr_selection()
        self.text_panel.show_subtitle_list()
        self._update_text_sub_nav_visuals("list")

    def _update_text_sub_nav_visuals(self, mode: str) -> None:
        """Cáº­p nháº­t style cho cÃ¡c nhÃ£n sub-nav dá»±a trÃªn tab Ä‘ang chá»n."""
        active_style = "color: #22d3c5; font-size: 11px; font-weight: normal; padding: 6px 12px; background: #22262d; border-radius: 2px; margin: 4px;"
        inactive_style = "color: #8c93a0; font-size: 11px; font-weight: normal; padding: 6px 12px; background: transparent; border-radius: 2px; margin: 4px;"

        if mode == "list":
            self.text_import_nav_label.setStyleSheet(active_style)
            self.ocr_nav_label.setStyleSheet(inactive_style)
        else:
            self.text_import_nav_label.setStyleSheet(inactive_style)
            self.ocr_nav_label.setStyleSheet(active_style)
    def _on_start_ocr_button_clicked(self) -> None:
        """Khi ngÆ°á»i dÃ¹ng nháº¥n nÃºt 'Báº¯t Ä‘áº§u trÃ­ch xuáº¥t' trong TextPanel."""
        lang, mode = self.text_panel.get_ocr_settings()
        area = self.preview_panel.get_ocr_area()
        self._on_ocr_area_selected(*area)

    def _on_ocr_cancelled(self) -> None:
        """Há»§y cháº¿ Ä‘á»™ OCR."""
        self.preview_panel.stop_ocr_selection()
        self.text_panel.show_subtitle_list()
        self._update_text_sub_nav_visuals("list")
        self.inspector_panel.show_properties()
        self.statusBar().showMessage("ã hủy chế độ OCR.", 3000)

    def _on_ocr_area_selected(self, y1: float, y2: float, x1: float, x2: float) -> None:
        """Nháº­n vÃ¹ng Ä‘Ã£ chá»n vÃ  khá»Ÿi cháº¡y OCR worker."""
        self.statusBar().showMessage("ang chuẩn bị OCR...", 0)

        # Láº¥y video clip Ä‘áº§u tiÃªn tá»« timeline
        video_path: str | None = None
        for track in self.project.tracks:
            for clip in track.clips:
                if not getattr(clip, "is_text_clip", False):
                    video_path = clip.source
                    break
            if video_path:
                break

        if not video_path:
            self.statusBar().showMessage("KhÃ´ng tÃ¬m tháº¥y video trong timeline.", 5000)
            return

        # Láº¥y cÃ i Ä‘áº·t tá»« text_panel
        lang, mode = self.text_panel.get_ocr_settings()

        # Chuyá»ƒn Ä‘á»•i tá»« tá»‰ lá»‡ (0-1) sang pixel tÆ°Æ¡ng á»©ng vá»›i video
        # sub_area: (ymin, ymax, xmin, xmax) - sáº½ Ä‘Æ°á»£c scale trong extractor
        # DÃ¹ng giÃ¡ trá»‹ tÆ°Æ¡ng Ä‘á»‘i, extractor sáº½ nhÃ¢n vá»›i frame_height/width
        from .widgets.ocr_worker import OcrWorker  # type: ignore

        if self._ocr_worker is not None and self._ocr_worker.isRunning():
            self._ocr_worker.cancel()
            self._ocr_worker.wait(3000)

        # Láº¥y kÃ­ch thÆ°á»›c video Ä‘á»ƒ chuyá»ƒn Ä‘á»•i tá»‰ lá»‡ sang pixel
        import cv2  # type: ignore
        try:
            cap = cv2.VideoCapture(video_path)
            frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            cap.release()
        except Exception:
            frame_h, frame_w = 1080, 1920

        sub_area = (
            int(y1 * frame_h),
            int(y2 * frame_h),
            int(x1 * frame_w),
            int(x2 * frame_w),
        )

        self._ocr_worker = OcrWorker(
            video_path=video_path,
            sub_area=sub_area,
            language=lang,
            mode=mode,
        )
        self._ocr_worker.progress_frame.connect(
            lambda p: self.statusBar().showMessage(f"ang trích xuất khung hình... {p}%", 0)
        )
        self._ocr_worker.progress_ocr.connect(
            lambda p: self.statusBar().showMessage(f"ang nhận dạng OCR... {p}%", 0)
        )
        self._ocr_worker.finished.connect(self._on_ocr_result)
        self._ocr_worker.error.connect(self._on_ocr_error)
        self._ocr_worker.start()
        self.statusBar().showMessage("ang chạy OCR... Vui lòng ch.", 0)

    def _on_ocr_result(self, srt_path: str) -> None:
        """Nháº­p file SRT káº¿t quáº£ vÃ o Text Panel."""
        self.preview_panel.stop_ocr_selection()
        self.text_panel.show_subtitle_list()
        self._update_text_sub_nav_visuals("list")

        from pathlib import Path as _Path  # noqa: PLC0415
        p = _Path(srt_path)
        if p.exists():
            # 1) Add to TextPanel + timeline as before
            self.text_panel.add_imported_subtitle(p)
            self._on_add_clip_from_card(p)

            # 2) Display in Inspector (right column)
            # Defer via QTimer so the call lands AFTER the queued
            # ``set_clip`` triggered by timeline selection.
            QTimer.singleShot(0, lambda: self.inspector_panel.show_properties())

            self.statusBar().showMessage(
                f"Trích xuất OCR thành công! ã thêm phụ đ vào Timeline: {p.name}", 8000
            )
        else:
            self.statusBar().showMessage("Không tạo được file phụ đ.", 5000)

    def _on_ocr_cue_double_clicked(self, cue: Cue) -> None:
        """Seek timeline when a cue is double-clicked in the OCR results."""
        self.timeline_panel.set_playhead(cue.start)
        self._on_timeline_seek(cue.start)

    def _on_caption_clip_double_clicked(self, clip: Clip) -> None:
        """Khi user double-click má»™t dÃ²ng phá»¥ Ä‘á» á»Ÿ tab ChÃº thÃ­ch."""
        self.timeline_panel.select_clip(clip)
        self.timeline_panel.set_playhead(clip.start)
        self._on_timeline_seek(clip.start)

    def _on_caption_clip_selected(self, clip_obj: object) -> None:
        clip = clip_obj if isinstance(clip_obj, Clip) else None
        if clip is None:
            return
        try:
            selected = self.timeline_panel.selected_clips()
        except Exception:
            selected = []
        if len(selected) == 1 and selected[0] is clip:
            return
        self._suspend_timeline_selection_sync = True
        try:
            self.timeline_panel.select_clip(clip)
        finally:
            self._suspend_timeline_selection_sync = False

    def _collect_all_text_clips(self) -> list[Clip]:
        clips: list[Clip] = []
        for track in self.project.tracks:
            for clip in track.clips:
                if clip.is_text_clip:
                    clips.append(clip)
        clips.sort(key=lambda c: (c.start, c.in_point))
        return clips

    def _refresh_auto_speed_issue_overlays(self) -> None:
        from ..engine.subtitle_filters import filter_reading_speed_issue_clips

        issues = filter_reading_speed_issue_clips(self._collect_all_text_clips())
        self.timeline_panel.set_speed_issue_clip_ids({id(c) for c in issues})

    def _on_caption_add(self) -> None:
        selected = self.inspector_panel.current_clip()
        target_track: Track | None = None
        if isinstance(selected, Clip) and selected.is_text_clip:
            target_track = self._find_track_for_clip(selected)
        if target_track is None or self._is_track_locked(target_track):
            target_track = self._get_or_create_track("text", preferred_index=None)

        start = max(0.0, float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)))
        duration = 2.0
        start = self._resolve_non_overlapping_start(target_track, start, duration)
        new_clip = Clip(
            source="",
            clip_type="text",
            start=start,
            in_point=0.0,
            out_point=duration,
            text_main="Phụ đ mới",
            text_display="main",
        )
        target_track.clips.append(new_clip)
        target_track.clips.sort(key=lambda c: c.start)

        self.timeline_panel.refresh()
        self.timeline_panel.select_clip(new_clip)
        self._set_clip_in_inspector(new_clip)
        self.inspector_panel.refresh()
        self._on_timeline_seek(float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)))
        self._push_timeline_history()
        self._refresh_auto_speed_issue_overlays()
        self.statusBar().showMessage("ã thêm dòng phụ đ mới.", 3000)

    def _on_caption_delete(self, clip: object) -> None:
        target = clip if isinstance(clip, Clip) else self.inspector_panel.current_clip()
        if target is None or not target.is_text_clip:
            QMessageBox.information(self, "Xóa phụ đ", "Hãy chn một dòng phụ đ để xóa.")
            return

        answer = QMessageBox.question(
            self,
            "Xóa phụ đ",
            f'Xóa dòng: "{(target.text_main or "").strip()[:80]}" ?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        for track in self.project.tracks:
            if target in track.clips:
                track.clips.remove(target)
                break

        self.timeline_panel.select_clip(None)
        self.timeline_panel.refresh()
        self._set_clip_in_inspector(None)
        self.inspector_panel.refresh()
        self._on_timeline_seek(float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)))
        self._push_timeline_history()
        self._refresh_auto_speed_issue_overlays()
        self.statusBar().showMessage("ã xóa dòng phụ đ.", 3000)

    def _on_caption_text_edit(self, clip: object, new_text: str) -> None:
        target = clip if isinstance(clip, Clip) else None
        if target is None or not target.is_text_clip:
            return
        normalized = new_text or ""
        if (target.text_main or "") == normalized:
            return
        target.text_main = normalized
        if not normalized.strip() and (target.text_second or "").strip():
            target.text_display = "second"
        elif normalized.strip() and (target.text_second or "").strip():
            target.text_display = "bilingual"
        else:
            target.text_display = "main"
        update_clip_visuals = getattr(self.timeline_panel, "update_clip_visuals", None)
        if callable(update_clip_visuals):
            update_clip_visuals(target)
        else:
            self.timeline_panel.refresh()
        self.timeline_panel.select_clip(target)
        if self.inspector_panel.current_clip() is target:
            self.inspector_panel.set_clip(target)
        else:
            self.inspector_panel.refresh()
        self._on_timeline_seek(float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)))
        self._push_timeline_history()
        self._refresh_auto_speed_issue_overlays()
        caption_list = self.inspector_panel._info._caption_list
        if caption_list.current_filter_kind() == "ocr":
            caption_list.refresh_filter_styles()

    def _on_caption_find_replace(self) -> None:
        from .dialogs.find_replace_dialog import FindReplaceDialog

        dlg = FindReplaceDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        find_text, replace_text, case_sensitive = dlg.values()
        find_text = (find_text or "").strip()
        if not find_text:
            return

        changed_rows = 0
        for clip in self._collect_all_text_clips():
            old_text = clip.text_main or ""
            if case_sensitive:
                if find_text not in old_text:
                    continue
                new_text = old_text.replace(find_text, replace_text)
            else:
                pattern = re.compile(re.escape(find_text), re.IGNORECASE)
                if not pattern.search(old_text):
                    continue
                new_text = pattern.sub(replace_text, old_text)
            if new_text != old_text:
                clip.text_main = new_text
                changed_rows += 1

        if changed_rows <= 0:
            QMessageBox.information(self, "Tìm & Thay thế", "Không tìm thấy kết quả phù hợp.")
            return

        self.timeline_panel.refresh()
        self.inspector_panel.refresh()
        self._on_timeline_seek(float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)))
        self._push_timeline_history()
        self._refresh_auto_speed_issue_overlays()
        QMessageBox.information(
            self,
            "Tìm & Thay thế",
            f"ã cập nhật {changed_rows} dòng phụ đ.",
        )



    def _on_caption_filter(self, kind: str) -> None:
        from ..engine.subtitle_filters import (
            filter_adjacent_duplicate_clips,
            filter_interjection_clips,
            filter_ocr_error_clips,
            is_ocr_error_text,
        )
        from .dialogs.delete_filter_dialog import DeleteFilterDialog

        all_text = self._collect_all_text_clips()
        caption_list = self.inspector_panel._info._caption_list

        if kind != "interjection" and caption_list.current_filter_kind() == kind:
            caption_list.clear_filter()
            self.statusBar().showMessage("Da tat loc.", 2000)
            return

        if kind == "interjection":
            if caption_list.is_filter_active():
                caption_list.clear_filter()
            candidates = filter_interjection_clips(all_text)
            if not candidates:
                self.statusBar().showMessage("Không có dòng cảm thán.", 4000)
                return
            dlg = DeleteFilterDialog(self, title="Phụ đ cảm thán", candidates=candidates)
            if dlg.exec() != QDialog.Accepted:
                return
            to_delete = dlg.selected_clips()
            if not to_delete:
                return
            to_delete_ids = {id(c) for c in to_delete}
            for track in self.project.tracks:
                if track.clips:
                    track.clips = [c for c in track.clips if id(c) not in to_delete_ids]
            self.timeline_panel.select_clip(None)
            self.timeline_panel.refresh()
            self._set_clip_in_inspector(None)
            self.inspector_panel.refresh()
            self._on_timeline_seek(float(getattr(self.timeline_panel, "_playhead_seconds", 0.0)))
            self._push_timeline_history()
            self._refresh_auto_speed_issue_overlays()
            self.statusBar().showMessage(f"ã xóa {len(to_delete)} dòng cảm thán.", 4000)
            return

        if kind == "ocr":
            candidates = filter_ocr_error_clips(all_text)
            ids = {id(c) for c in candidates}
            if not candidates:
                caption_list.clear_filter()
                self.statusBar().showMessage("Không phát hiện lỗi OCR.", 4000)
                return
            visible = caption_list.apply_filter(
                "ocr",
                ids,
                ocr_error_check=lambda c: is_ocr_error_text(c.text_main or ""),
            )
            self.statusBar().showMessage(f"Lc lỗi OCR: {visible} dòng.", 5000)
            return

        if kind == "duplicate":
            candidates = filter_adjacent_duplicate_clips(all_text)
            ids = {id(c) for c in candidates}
            if not candidates:
                caption_list.clear_filter()
                self.statusBar().showMessage("Không có dòng trùng lặp.", 4000)
                return
            visible = caption_list.apply_filter("duplicate", ids)
            self.statusBar().showMessage(f"Trùng lặp lin k: {visible} dòng.", 5000)
            return

    def _on_text_card_selected(self, path: Path) -> None:
        """Khi user click chá»n 1 card phá»¥ Ä‘á» á»Ÿ panel bÃªn trÃ¡i."""
        self._preview_sync_mode = "timeline"

        # TÃ¬m clip Ä‘áº§u tiÃªn trÃªn timeline dÃ¹ng source nÃ y
        target_clip: Clip | None = None
        path_str = str(path)
        norm_path = str(path.resolve()).lower() if path.exists() else path_str.lower()

        for track in self.project.tracks:
            for clip in track.clips:
                c_norm = str(Path(clip.source).resolve()).lower() if Path(clip.source).exists() else clip.source.lower()
                if c_norm == norm_path or clip.source == path_str:
                    target_clip = clip
                    break
            if target_clip:
                break

        if target_clip:
            self.timeline_panel.select_clip(target_clip)
            self.inspector_panel.set_clip(target_clip)
            self.inspector_panel.switch_to_text_tab()
        else:
            self.inspector_panel.switch_to_text_tab()

    def _on_ocr_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"Lỗi OCR: {msg[:80]}", 8000)
        QMessageBox.warning(self, "Lỗi trích xuất OCR", msg)


    def closeEvent(self, event) -> None:
        self._stop_preview_playback()
        try:
            if self._ingest_flush_timer.isActive():
                self._ingest_flush_timer.stop()
            if self._pending_ingest_metadata or self._pending_ingest_failures:
                self._flush_pending_ingest_metadata()
        except Exception:
            pass
        try:
            self.save_to_store()
        except Exception:
            pass
        try:
            self._proxy_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            self._audio_proxy_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            self._media_ingest.close()
        except Exception:
            pass
        self.closed.emit()
        super().closeEvent(event)


__all__ = ["MainWindow"]

