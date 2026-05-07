"""
Main GUI Window - Modularized with Tabbed Interface.
FINAL VERSION with pitch control option.
"""
import sys
import os
import re
import json
import traceback
import logging 
from datetime import datetime
from typing import List, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QLabel, QFileDialog, QGroupBox, QFormLayout,
    QMessageBox, QTextEdit, QSplitter, QListWidget, QAbstractItemView,
    QCheckBox, QApplication, QTabWidget, QRadioButton, QDoubleSpinBox,
    QProgressBar, QStackedWidget, QSizePolicy, QFrame
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QScreen, QIcon

import pysrt

from utils.logger import get_logger, LogCapture
from gui.worker_thread import UniversalWorker
from gui.styles import APP_STYLES
from core.json_splicer import splice_video_track
from core.capcut_generator import CapCutDraftGenerator

logger = get_logger(__name__)

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- Helpers: Extract screen timestamps from Timetamp SRT file ---
def _timecode_to_seconds(raw_value: str) -> Optional[float]:
    """Convert HH:MM:SS,mmm / HH:MM:SS.mmm or decimal seconds to float seconds."""
    text = (raw_value or "").strip()
    if not text:
        return None

    normalized = text.replace(',', '.')

    if re.fullmatch(r'\d+(\.\d+)?', normalized):
        return float(normalized)

    if not re.fullmatch(r'\d{1,2}:\d{2}:\d{2}(\.\d{1,3})?', normalized):
        return None

    hh, mm, sec_part = normalized.split(':')
    if '.' in sec_part:
        ss, ms = sec_part.split('.', 1)
    else:
        ss, ms = sec_part, '0'

    ms_value = int(ms.ljust(3, '0')[:3])
    return (int(hh) * 3600) + (int(mm) * 60) + int(ss) + (ms_value / 1000.0)


def _extract_timestamp_screen_from_srt(timetamp_path: str) -> Optional[List[float]]:
    """Extract screen boundaries from SRT-like files, including STT + timestamp format."""
    timestamps_us = set()

    # Try standard SRT parser first.
    try:
        subs = pysrt.open(timetamp_path, encoding='utf-8')
        for sub in subs:
            start_s = (
                sub.start.hours * 3600
                + sub.start.minutes * 60
                + sub.start.seconds
                + sub.start.milliseconds / 1000.0
            )
            start_us = int(round(start_s * 1_000_000))
            if start_us > 0:
                timestamps_us.add(start_us)

        if timestamps_us:
            result = [ts / 1_000_000.0 for ts in sorted(timestamps_us)]
            logger.info(f"[Timetamp] Đọc {len(result)} mốc Screen từ file SRT chuẩn.")
            return result
    except Exception as e:
        logger.info(f"[Timetamp] pysrt parse fallback: {e}")

    # Fallback for custom SRT-like formats: STT + timestamp lines.
    try:
        with open(timetamp_path, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()

        waiting_for_timestamp = False
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            if re.fullmatch(r'\d+', line):
                waiting_for_timestamp = True
                continue

            seconds = None
            # Handle normal SRT timeline lines: 00:00:01,000 --> 00:00:02,500
            time_match = re.search(r'(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})', line)
            if time_match:
                seconds = _timecode_to_seconds(time_match.group(1))
            elif waiting_for_timestamp:
                # Handle custom format:
                # 1
                # 00:00:12,300
                seconds = _timecode_to_seconds(line)

            if seconds is not None:
                start_us = int(round(seconds * 1_000_000))
                if start_us > 0:
                    timestamps_us.add(start_us)

            waiting_for_timestamp = False

        if not timestamps_us:
            logger.warning("[Timetamp] Không tìm thấy timestamp hợp lệ trong file SRT.")
            return None

        result = [ts / 1_000_000.0 for ts in sorted(timestamps_us)]
        logger.info(f"[Timetamp] Trích xuất {len(result)} mốc Screen từ file SRT tùy chỉnh.")
        return result
    except Exception as e:
        logger.warning(f"[Timetamp] Không thể đọc file SRT Timetamp: {e}")
        return None


def extract_timestamp_screen_from_timetamp_file(timetamp_path: str) -> Optional[List[float]]:
    """Extract screen timestamps from timetamp SRT file only."""
    ext = os.path.splitext(timetamp_path)[1].lower()
    if ext != '.srt':
        logger.warning("[Timetamp] Chỉ hỗ trợ file SRT cho import timetamp.")
        return None

    return _extract_timestamp_screen_from_srt(timetamp_path)

# --- Wrapper Functions for Workers ---
def run_splicing_task(progress_callback: pyqtSignal, input_path: str, output_path: str, target_speed: float, mode: str, keep_pitch: bool, video_speed_enabled: bool = False, target_video_speed: float = 1.0, remove_silence: bool = False, waveform_sync: bool = False, timestamp_screen: List[int] = None, skip_stretch_shorter: bool = False) -> str:
    progress_callback.emit(5, f"Reading input file: {os.path.basename(input_path)}")
    logger.info(f"Reading input JSON: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        draft_data = json.load(f)
    project_dir = os.path.dirname(input_path)
    modified_data = splice_video_track(draft_data, target_speed, mode, keep_pitch, progress_callback, video_speed_enabled, target_video_speed, remove_silence, project_dir=project_dir, waveform_sync=waveform_sync, timestamp_screen=timestamp_screen, skip_stretch_shorter=skip_stretch_shorter)
    if modified_data:
        modified_data = _normalize_audio_follow_video(modified_data)
        progress_callback.emit(98, f"Saving processed file: {os.path.basename(output_path)}")
        logger.info(f"Saving processed JSON to: {output_path}")
        # Đổi tên file cũ thành backup nếu trùng tên
        try:
            if os.path.exists(output_path):
                backup_dir = os.path.dirname(output_path)
                base_backup = os.path.join(backup_dir, "draft_content_backup.json")
                backup_path = base_backup
                count = 1
                while os.path.exists(backup_path):
                    backup_path = os.path.join(backup_dir, f"draft_content_backup_{count}.json")
                    count += 1
                os.rename(output_path, backup_path)
        except Exception as e:
            logger.warning(f"Không thể đổi tên file cũ thành backup: {e}")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(modified_data, f, ensure_ascii=False, indent=2)
        _sync_timeline_draft_if_needed(output_path, modified_data)
        return output_path
    else:
        raise Exception("Splicing function failed to return data.")

def run_generation_task(progress_callback: pyqtSignal, video_path: str, audio_files: List[str], srt_path: str, output_json_path: str, gap_aware_mode: bool, target_audio_speed: float, keep_pitch: bool, sync_mode: str, video_speed_enabled: bool = False, target_video_speed: float = 1.0, remove_silence: bool = False, waveform_sync: bool = False, timestamp_screen: List[int] = None, skip_stretch_shorter: bool = False, export_lt8: bool = False) -> str:
    try:
        generator = CapCutDraftGenerator()
        result = generator.generate_single_json(
            progress_callback=progress_callback,
            video_path=video_path, 
            audio_files=audio_files, 
            srt_path=srt_path, 
            output_json_path=output_json_path, 
            gap_aware_mode=gap_aware_mode,
            target_audio_speed=target_audio_speed,
            keep_pitch=keep_pitch,
            sync_mode=sync_mode,
            video_speed_enabled=video_speed_enabled,
            target_video_speed=target_video_speed,
            remove_silence=remove_silence,
            waveform_sync=waveform_sync,
            timestamp_screen=timestamp_screen,
            skip_stretch_shorter=skip_stretch_shorter,
            export_lt8=export_lt8
        )
        if not result:
            raise Exception("Generation function failed to return a result path. Check the logs for detailed error information.")
        _repair_saved_draft_files(result)
        return result
    except Exception as e:
        logger.error(f"Generation task failed: {str(e)}")
        raise Exception(f"Generation task failed: {str(e)}")

def _normalize_audio_follow_video(draft_data: dict) -> dict:
    tracks = draft_data.get("tracks", [])
    track_by_type = {t.get("type"): t for t in tracks}
    video_track = track_by_type.get("video")
    text_track = track_by_type.get("text")
    
    # Lấy danh sách audio tracks và toàn bộ segments của chúng
    audio_tracks = [t for t in tracks if t.get("type") == "audio"]
    if not video_track or not audio_tracks:
        return draft_data
        
    all_audio_segments = []
    for track in audio_tracks:
        all_audio_segments.extend(track.get("segments", []))
    
    # Lọc bỏ các segment "câm" (gap) cũ nếu có
    all_audio_segments = [s for s in all_audio_segments if s.get("volume", 1.0) > 0 or s.get("material_id")]
    
    if "config" not in draft_data:
        draft_data["config"] = {}
    draft_data["config"]["maintrack_adsorb"] = True
    
    video_segments = video_track.get("segments", [])
    text_segments = text_track.get("segments", []) if text_track else []
    
    import uuid
    
    # Map video/text by render_index and start time for robust matching
    video_by_index = {}
    video_by_start = {}
    video_ranges = []
    for idx, v_seg in enumerate(video_segments):
        start = v_seg.get("target_timerange", {}).get("start")
        duration = v_seg.get("target_timerange", {}).get("duration", 0)
        end = (start + duration) if start is not None else None
        v_idx = v_seg.get("render_index")
        
        # Luôn gán render_index nếu chưa có để đồng bộ
        if v_idx is None:
            v_idx = idx
            v_seg["render_index"] = v_idx
            
        group_id = v_seg.get("group_id") or str(uuid.uuid4()).upper()
        bundle_id = v_seg.get("raw_segment_id") or str(uuid.uuid4()).upper()
        v_seg["group_id"] = group_id
        v_seg["raw_segment_id"] = bundle_id
        
        video_by_index.setdefault(v_idx, []).append(v_seg)
        if start is not None:
            video_by_start[start] = v_seg
            video_ranges.append((int(start), int(end if end is not None else start), v_seg))

    video_ranges.sort(key=lambda x: x[0])
            
    text_by_index = {}
    text_by_start = {}
    text_by_material_id = {}
    text_ranges = []
    text_start_by_material_id = {}
    for t_seg in text_segments:
        start = t_seg.get("target_timerange", {}).get("start")
        duration = t_seg.get("target_timerange", {}).get("duration", 0)
        end = (start + duration) if start is not None else None
        mat_id = t_seg.get("material_id")
        t_idx = t_seg.get("render_index")
        if t_idx is not None:
            text_by_index[t_idx] = t_seg
        if start is not None:
            text_by_start[start] = t_seg
            text_ranges.append((int(start), int(end if end is not None else start), t_seg))
            if mat_id:
                text_by_material_id[mat_id] = t_seg
                text_start_by_material_id[mat_id] = int(start)

    timeline_fps = draft_data.get("fps", 30.0)
    try:
        timeline_fps = float(timeline_fps)
    except (TypeError, ValueError):
        timeline_fps = 30.0
    if timeline_fps <= 0:
        timeline_fps = 30.0
    one_frame_us = max(1, int(round(1_000_000 / timeline_fps)))

    def _pick_video_by_time(candidates: list, aud_start: Optional[int]):
        if not candidates:
            return None
        if aud_start is None:
            return candidates[0]

        # Prefer segment that contains audio start.
        containing = []
        for seg in candidates:
            tr = seg.get("target_timerange", {})
            v_start = tr.get("start")
            v_dur = tr.get("duration", 0)
            if v_start is None:
                continue
            v_end = v_start + v_dur
            if int(v_start) <= int(aud_start) < int(v_end):
                containing.append(seg)

        if containing:
            return min(
                containing,
                key=lambda s: abs(int((s.get("target_timerange", {}) or {}).get("start", 0)) - int(aud_start)),
            )

        # Fallback: nearest by start time.
        return min(
            candidates,
            key=lambda s: abs(int((s.get("target_timerange", {}) or {}).get("start", 0)) - int(aud_start)),
        )

    def _find_video_for_audio(aud_idx, aud_start):
        idx_candidates = video_by_index.get(aud_idx, []) if aud_idx is not None else []
        ambiguous_index = len(idx_candidates) > 1

        if len(idx_candidates) == 1:
            return idx_candidates[0], False

        if idx_candidates:
            return _pick_video_by_time(idx_candidates, aud_start), True

        if aud_start is not None:
            exact = video_by_start.get(aud_start)
            if exact is not None:
                return exact, False

            for v_start, v_end, v_seg in video_ranges:
                if v_start <= int(aud_start) < v_end:
                    return v_seg, False

            if video_ranges:
                nearest = min(video_ranges, key=lambda item: abs(item[0] - int(aud_start)))[2]
                return nearest, False

        return None, ambiguous_index

    def _find_text_for_alignment(v_start, aud_start):
        if aud_start is not None and aud_start in text_by_start:
            return text_by_start[aud_start]
        if v_start in text_by_start:
            return text_by_start[v_start]
        if aud_start is None:
            return None
        for t_start, t_end, t_seg in text_ranges:
            if t_start <= int(aud_start) < t_end:
                return t_seg
        return None
            
    audio_mats = {m["id"]: m for m in draft_data.get("materials", {}).get("audios", [])}
    text_mats = {m["id"]: m for m in draft_data.get("materials", {}).get("texts", [])}
    
    # Cập nhật thông tin cho từng audio segment dựa trên video segment tương ứng
    updated_audio_segments = []
    for aud_seg in all_audio_segments:
        aud_idx = aud_seg.get("render_index")
        aud_start = aud_seg.get("target_timerange", {}).get("start")

        # If audio material already links to a text material, keep audio start in sync with that text.
        a_mat_id = aud_seg.get("material_id")
        linked_text_id = (audio_mats.get(a_mat_id) or {}).get("text_id")
        if linked_text_id in text_start_by_material_id:
            linked_start = text_start_by_material_id[linked_text_id]
            if aud_start is None or abs(int(aud_start) - int(linked_start)) > one_frame_us:
                aud_seg.setdefault("target_timerange", {})["start"] = int(linked_start)
                aud_start = int(linked_start)
        
        # Tìm video segment tương ứng, xử lý an toàn khi render_index bị trùng.
        target_v_seg, ambiguous_index = _find_video_for_audio(aud_idx, aud_start)
            
        if target_v_seg:
            v_start = target_v_seg.get("target_timerange", {}).get("start")
            v_group_id = target_v_seg.get("group_id")
            v_bundle_id = target_v_seg.get("raw_segment_id")
            v_render_index = target_v_seg.get("render_index")
            
            # CẬP NHẬT VỊ TRÍ:
            # Chỉ snap về đầu video nếu KHÔNG có text link tin cậy.
            current_offset = abs(aud_start - v_start) if aud_start is not None else 9999999
            has_linked_text = linked_text_id in text_start_by_material_id
            if (not has_linked_text) and (not ambiguous_index) and current_offset > one_frame_us:
                aud_seg.setdefault("target_timerange", {})["start"] = v_start
                aud_start = v_start
            
            aud_seg["group_id"] = v_group_id
            aud_seg["raw_segment_id"] = v_bundle_id
            aud_seg["render_index"] = v_render_index
            
            # Cập nhật text_to_audio link
            preferred_text_seg = text_by_material_id.get(linked_text_id) if linked_text_id else None
            text_seg = preferred_text_seg or text_by_index.get(v_render_index) or _find_text_for_alignment(v_start, aud_start)
            if text_seg:
                a_mat_id = aud_seg.get("material_id")
                t_mat_id = text_seg.get("material_id")
                if a_mat_id in audio_mats and t_mat_id in text_mats:
                    a_mat = audio_mats[a_mat_id]
                    t_mat = text_mats[t_mat_id]
                    a_mat["type"] = "text_to_audio"
                    a_mat["text_id"] = t_mat_id
                    if "text_to_audio_ids" not in t_mat:
                        t_mat["text_to_audio_ids"] = []
                    if aud_seg["id"] not in t_mat["text_to_audio_ids"]:
                        t_mat["text_to_audio_ids"].append(aud_seg["id"])

                desired_text_start = (text_seg.get("target_timerange") or {}).get("start")
                current_start = (aud_seg.get("target_timerange") or {}).get("start")
                if desired_text_start is not None and (current_start is None or abs(int(current_start) - int(desired_text_start)) > one_frame_us):
                    aud_seg.setdefault("target_timerange", {})["start"] = int(desired_text_start)
                    aud_start = int(desired_text_start)
                        
        updated_audio_segments.append(aud_seg)
        
    # Phân bổ lại vào các track để tránh đè vấp (Overlap Protection)
    audio_tracks_list = []
    sorted_audio = sorted(updated_audio_segments, key=lambda s: s.get("target_timerange", {}).get("start", 0))
    for aud_seg in sorted_audio:
        seg_start = aud_seg.get("target_timerange", {}).get("start", 0)
        seg_duration = aud_seg.get("target_timerange", {}).get("duration", 0)
        
        placed = False
        for track_segs in audio_tracks_list:
            if not track_segs: continue
            last_seg = track_segs[-1]
            last_end = last_seg.get("target_timerange", {}).get("start", 0) + last_seg.get("target_timerange", {}).get("duration", 0)
            if seg_start >= last_end:
                track_segs.append(aud_seg)
                placed = True
                break
        if not placed:
            audio_tracks_list.append([aud_seg])
            
    # Xây dựng lại danh sách tracks (Giữ video, text, và thay thế audio)
    new_tracks = []
    for t in tracks:
        if t.get("type") != "audio":
            new_tracks.append(t)
            
    for track_segs in audio_tracks_list:
        new_tracks.append({
            "attribute": 0,
            "flag": 0,
            "id": str(uuid.uuid4()).upper(),
            "is_default_name": True,
            "name": "",
            "segments": track_segs,
            "type": "audio"
        })
        
    if not audio_tracks_list:
        new_tracks.append({
            "attribute": 0,
            "flag": 0,
            "id": str(uuid.uuid4()).upper(),
            "is_default_name": True,
            "name": "",
            "segments": [],
            "type": "audio"
        })
        
    draft_data["tracks"] = new_tracks
    return draft_data

def _sync_timeline_draft_if_needed(output_json_path: str, draft_data: dict):
    try:
        project_root = os.path.dirname(output_json_path)
        timelines_dir = os.path.join(project_root, "Timelines")
        project_json = os.path.join(timelines_dir, "project.json")
        if not os.path.exists(project_json):
            return
        with open(project_json, 'r', encoding='utf-8') as f:
            project_info = json.load(f)
        timeline_id = project_info.get("main_timeline_id")
        if not timeline_id:
            return
        timeline_dir = os.path.join(timelines_dir, timeline_id)
        os.makedirs(timeline_dir, exist_ok=True)
        timeline_extra_path = os.path.join(timeline_dir, "draft.extra")
        if os.path.exists(timeline_extra_path):
            os.remove(timeline_extra_path)
        timeline_draft_path = os.path.join(timeline_dir, "draft_content.json")
        with open(timeline_draft_path, 'w', encoding='utf-8') as f:
            json.dump(draft_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Không thể đồng bộ draft timeline: {e}")

def _repair_saved_draft_files(output_json_path: str):
    try:
        with open(output_json_path, 'r', encoding='utf-8') as f:
            draft_data = json.load(f)
        repaired = _normalize_audio_follow_video(draft_data)
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(repaired, f, ensure_ascii=False, indent=2)
        _sync_timeline_draft_if_needed(output_json_path, repaired)
    except Exception as e:
        logger.warning(f"Không thể sửa hậu kỳ draft đã sinh: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Initialize logging first to prevent AttributeErrors in update_logs
        root_logger = logging.getLogger("CapCutGenerator")
        self.log_capture = LogCapture(root_logger)
        self.log_capture.start_capture()
        
        self.setWindowTitle("CapCut Draft Generator & Editor v3.4.0")
        self.setGeometry(100, 100, 1000, 850) 
        self.setMinimumSize(950, 800)
        
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        
        # Resolve absolute paths for arrow icons in stylesheet
        up_path = resource_path("gui/up_arrow.svg").replace("\\", "/")
        down_path = resource_path("gui/down_arrow.svg").replace("\\", "/")
        dynamic_styles = APP_STYLES.replace("gui/up_arrow.svg", up_path).replace("gui/down_arrow.svg", down_path)
        
        self.setStyleSheet(dynamic_styles)
        self._syncing_ui = False
        self.worker = None
        self.initUI()
        self.center_window()
        
        # Call the visibility update function once at startup
        self._update_pitch_checkbox_visibility()
        self._update_gen_speed_locks()
        self._update_splicer_speed_locks()
        
        logger.info("Main window initialized with Tabbed UI.")

    def center_window(self):
        """Centers the main window on the primary screen."""
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        window_geometry = self.frameGeometry()
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        header_label = QLabel("🎬 CapCut Draft Generator & Editor")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter); header_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #00d4ff; margin: 10px;")
        main_layout.addWidget(header_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_generator_tab(), "🚀 Tạo Project Mới")
        self.tabs.addTab(self._create_splicer_tab(), "✂️ Chỉnh Sửa JSON")
        main_layout.addWidget(self.tabs)
        
        self.progress_stack = QStackedWidget()
        self.gen_progress_widget = self._create_progress_widget()
        self.splicer_progress_widget = self._create_progress_widget()
        self.progress_stack.addWidget(self.gen_progress_widget)
        self.progress_stack.addWidget(self.splicer_progress_widget)
        self.progress_stack.setVisible(False)
        main_layout.addWidget(self.progress_stack)
        
        self.tabs.currentChanged.connect(self.progress_stack.setCurrentIndex)

        # Setup UI Synchronization between tabs
        self._setup_ui_sync()

        main_layout.addWidget(self._create_log_section())

    def _create_progress_widget(self) -> QWidget:
        """Creates a reusable progress display widget."""
        progress_widget = QWidget()
        layout = QVBoxLayout(progress_widget)
        layout.setContentsMargins(0, 5, 0, 5)
        
        label = QLabel("")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        bar = QProgressBar()
        bar.setTextVisible(False)
        
        layout.addWidget(label)
        layout.addWidget(bar)
        
        progress_widget.label = label
        progress_widget.bar = bar
        return progress_widget

    def _create_generator_tab(self) -> QWidget:
        tab_widget = QWidget()
        main_layout = QHBoxLayout(tab_widget)
        left_column_widget = QWidget()
        left_layout = QVBoxLayout(left_column_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)

        input_groupbox = QGroupBox("📂 Files Đầu Vào")
        form_layout = QFormLayout(input_groupbox)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form_layout.setSpacing(10) # Tăng khoảng cách giữa các dòng
        self.video_path_edit = QLineEdit(); self.video_path_edit.setPlaceholderText("Chọn file video .mp4, .mov...")
        self.video_path_edit.setMinimumHeight(35)
        btn_browse_video = QPushButton("🎬 Chọn Video"); btn_browse_video.clicked.connect(self.browse_video)
        btn_browse_video.setMinimumHeight(35)
        video_layout = QHBoxLayout(); video_layout.addWidget(self.video_path_edit); video_layout.addWidget(btn_browse_video)
        form_layout.addRow("📹 Video Gốc:", video_layout)
        self.audio_folder_edit = QLineEdit(); self.audio_folder_edit.setPlaceholderText("Chọn thư mục chứa file audio")
        self.audio_folder_edit.setMinimumHeight(35)
        btn_browse_audio = QPushButton("🎵 Chọn Folder"); btn_browse_audio.clicked.connect(self.browse_audio_folder)
        btn_browse_audio.setMinimumHeight(35)
        audio_layout = QHBoxLayout(); audio_layout.addWidget(self.audio_folder_edit); audio_layout.addWidget(btn_browse_audio)
        form_layout.addRow("🎶 Thư Mục Audio:", audio_layout)

        # Timetamp row (Hidden by default, shown for Priority mode)
        self.timetamp_row = QWidget()
        timetamp_row_layout = QHBoxLayout(self.timetamp_row)
        timetamp_row_layout.setContentsMargins(0, 0, 0, 0)
        self.timetamp_edit = QLineEdit(); self.timetamp_edit.setPlaceholderText("File SRT chứa timestamp_screen (Tùy chọn)")
        self.timetamp_edit.setMinimumHeight(35)
        self.btn_browse_timetamp = QPushButton("⚙️ Nhập Timetamp"); self.btn_browse_timetamp.clicked.connect(self.browse_timetamp_file)
        self.btn_browse_timetamp.setMinimumHeight(35)
        timetamp_row_layout.addWidget(self.timetamp_edit)
        timetamp_row_layout.addWidget(self.btn_browse_timetamp)
        self.timetamp_label = QLabel("📄 Timetamp:")
        form_layout.addRow(self.timetamp_label, self.timetamp_row)

        self.srt_path_edit = QLineEdit(); self.srt_path_edit.setPlaceholderText("File phụ đề .srt")
        self.srt_path_edit.setMinimumHeight(35)
        btn_browse_srt = QPushButton("📝 Chọn SRT"); btn_browse_srt.clicked.connect(self.browse_srt)
        btn_browse_srt.setMinimumHeight(35)
        srt_layout = QHBoxLayout(); srt_layout.addWidget(self.srt_path_edit); srt_layout.addWidget(btn_browse_srt)
        form_layout.addRow("📄 File Phụ Đề:", srt_layout)
        self.output_json_edit_gen = QLineEdit(); self.output_json_edit_gen.setPlaceholderText("Chọn thư mục lưu draft_content.json")
        self.output_json_edit_gen.setMinimumHeight(35)
        btn_browse_output_gen = QPushButton("📁 Chọn Vị Trí"); btn_browse_output_gen.clicked.connect(self.browse_output_json_for_generator)
        btn_browse_output_gen.setMinimumHeight(35)
        output_layout_gen = QHBoxLayout(); output_layout_gen.addWidget(self.output_json_edit_gen); output_layout_gen.addWidget(btn_browse_output_gen)
        form_layout.addRow("💾 File JSON:", output_layout_gen)
        
        input_groupbox.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        
        # Initial visibility update
        QTimer.singleShot(0, self._update_timetamp_visibility)

        left_layout.addWidget(input_groupbox)
        
        mode_groupbox = QGroupBox("⚙️ Tùy Chỉnh Xử Lý")
        mode_groupbox.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        mode_layout = QVBoxLayout(mode_groupbox)
        
        # Main layout for the groupbox: 2 columns
        mode_columns_layout = QHBoxLayout()
        mode_columns_layout.setSpacing(15)
        
        # COLUMN 1: Speeds and Modes (Wrapped in a styled Frame)
        col1_frame = QFrame(); col1_frame.setFrameShape(QFrame.Shape.StyledPanel)
        col1_frame.setStyleSheet("QFrame { border: 1px solid #444; border-radius: 8px; background-color: #2b2b2b; } QLabel { border: none; background: none; } QRadioButton { border: none; background: none; padding: 2px; }")
        col1_layout = QVBoxLayout(col1_frame)
        col1_layout.setContentsMargins(15, 15, 15, 15)
        col1_layout.setSpacing(15)
        
        # Combined Speed Row
        speed_row_layout = QHBoxLayout()
        audio_label = QLabel("🔊 Audio:"); audio_label.setMinimumHeight(30)
        speed_row_layout.addWidget(audio_label)
        self.gen_speed_spinbox = QDoubleSpinBox(); self.gen_speed_spinbox.setRange(0.5, 3.0); self.gen_speed_spinbox.setSingleStep(0.05); self.gen_speed_spinbox.setValue(1.00) 
        self.gen_speed_spinbox.valueChanged.connect(self._update_pitch_checkbox_visibility); self.gen_speed_spinbox.setMaximumWidth(70); self.gen_speed_spinbox.setMinimumHeight(30)
        speed_row_layout.addWidget(self.gen_speed_spinbox)
        
        speed_row_layout.addSpacing(15)
        
        video_label = QLabel("🎬 Video:"); video_label.setMinimumHeight(30)
        speed_row_layout.addWidget(video_label)
        self.gen_video_speed_spinbox = QDoubleSpinBox(); self.gen_video_speed_spinbox.setRange(0.5, 3.0); self.gen_video_speed_spinbox.setSingleStep(0.05); self.gen_video_speed_spinbox.setValue(1.0)
        self.gen_video_speed_spinbox.valueChanged.connect(self._on_video_speed_changed); self.gen_video_speed_spinbox.setMaximumWidth(70); self.gen_video_speed_spinbox.setMinimumHeight(30)
        speed_row_layout.addWidget(self.gen_video_speed_spinbox)
        speed_row_layout.addStretch()
        col1_layout.addLayout(speed_row_layout)
        
        # Sync Modes
        self.gen_mode_sync_rb = QRadioButton("Đồng bộ Video theo Audio (Co giãn video)")
        self.gen_mode_sync_rb.setChecked(True)
        self.gen_mode_sync_rb.setToolTip("Video sẽ được co giãn (tăng/giảm speed) để khớp chính xác với thời lượng của từng đoạn audio tương ứng.")
        self.gen_mode_sync_rb.toggled.connect(self._update_gen_speed_locks)
        col1_layout.addWidget(self.gen_mode_sync_rb)
        
        self.gen_mode_priority_rb = QRadioButton("Đồng bộ Video theo Audio (Giữ nguyên video)")
        self.gen_mode_priority_rb.setToolTip("Giữ nguyên speed video, nếu thời lượng video dài hơn audio.")
        self.gen_mode_priority_rb.toggled.connect(self._update_gen_speed_locks)
        col1_layout.addWidget(self.gen_mode_priority_rb)
        
        self.gen_mode_audio_sync_rb = QRadioButton("Đồng bộ Audio theo Video (Co giãn audio)")
        self.gen_mode_audio_sync_rb.setToolTip("Audio sẽ được co giãn (tăng/giảm speed) để khớp chính xác với thời lượng của từng đoạn audio tương ứng.")
        self.gen_mode_audio_sync_rb.toggled.connect(self._update_gen_speed_locks)
        col1_layout.addWidget(self.gen_mode_audio_sync_rb)
        
        self.gen_mode_audio_sync_priority_rb = QRadioButton("Đồng bộ Audio theo Video (Giữ nguyên audio)")
        self.gen_mode_audio_sync_priority_rb.setToolTip("Giữ nguyên speed audio, nếu thời lượng audio ngắn hơn video.")
        self.gen_mode_audio_sync_priority_rb.toggled.connect(self._update_gen_speed_locks)
        self.gen_mode_audio_sync_priority_rb.toggled.connect(self._update_timetamp_visibility)
        col1_layout.addWidget(self.gen_mode_audio_sync_priority_rb)
        
        # COLUMN 2: Additional Options (Wrapped in a styled Frame)
        col2_frame = QFrame(); col2_frame.setFrameShape(QFrame.Shape.StyledPanel)
        col2_frame.setStyleSheet("QFrame { border: 1px solid #444; border-radius: 8px; background-color: #2b2b2b; } QLabel { border: none; background: none; } QCheckBox { border: none; background: none; padding: 2px; }")
        col2_layout = QVBoxLayout(col2_frame)
        col2_layout.setContentsMargins(15, 15, 15, 15)
        col2_layout.setSpacing(15)
        
        self.gen_remove_silence_checkbox = QCheckBox("Xoá khoản lặng")
        self.gen_remove_silence_checkbox.setChecked(False)
        self.gen_remove_silence_checkbox.setToolTip("Tự động xoá các đoạn im lặng trong file audio để video liền mạch hơn.")
        col2_layout.addWidget(self.gen_remove_silence_checkbox)
        
        self.gen_waveform_sync_checkbox = QCheckBox("Đồng bộ âm thanh")
        self.gen_waveform_sync_checkbox.setChecked(False)
        self.gen_waveform_sync_checkbox.setToolTip("Khớp âm thanh MP3 chính xác với sóng âm lời thoại của video (Waveform Sync).")
        col2_layout.addWidget(self.gen_waveform_sync_checkbox)
        
        self.gen_pitch_checkbox = QCheckBox("Thay đổi cao độ")
        self.gen_pitch_checkbox.setChecked(True)
        col2_layout.addWidget(self.gen_pitch_checkbox)
        
        self.gen_skip_stretch_checkbox = QCheckBox("Không co giãn nếu ngắn hơn")
        self.gen_skip_stretch_checkbox.setChecked(False)
        self.gen_skip_stretch_checkbox.setToolTip("Giữ nguyên tốc độ (không làm chậm) nếu video hoặc audio của đoạn đó đang ngắn hơn thành phần còn lại.")
        col2_layout.addWidget(self.gen_skip_stretch_checkbox)

        self.gen_export_lt8_checkbox = QCheckBox("Xuat JSON CapCut <8.0")
        self.gen_export_lt8_checkbox.setChecked(False)
        self.gen_export_lt8_checkbox.setToolTip("Bat de xuat profile JSON legacy CapCut <8.0 (vi du 7.8.0).")
        col2_layout.addWidget(self.gen_export_lt8_checkbox)
        
        col2_layout.addStretch()
        
        mode_columns_layout.addWidget(col1_frame, 1)
        mode_columns_layout.addWidget(col2_frame, 1)
        
        mode_layout.addLayout(mode_columns_layout)
        
        # Connect all radio buttons to visibility update
        self.gen_mode_sync_rb.toggled.connect(self._update_timetamp_visibility)
        self.gen_mode_priority_rb.toggled.connect(self._update_timetamp_visibility)
        self.gen_mode_audio_sync_rb.toggled.connect(self._update_timetamp_visibility)

        left_layout.addWidget(mode_groupbox)

        self.gen_progress_label = QLabel(""); self.gen_progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.gen_progress_label.setVisible(False)
        left_layout.addWidget(self.gen_progress_label)
        self.gen_progress_bar = QProgressBar(); self.gen_progress_bar.setTextVisible(False); self.gen_progress_bar.setVisible(False)
        left_layout.addWidget(self.gen_progress_bar)
        
        left_layout.addStretch(1)
        
        right_column_widget = QWidget()
        right_layout = QVBoxLayout(right_column_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.audio_list_groupbox = QGroupBox("🎵 Thứ Tự File Audio")
        audio_list_layout = QVBoxLayout(self.audio_list_groupbox)
        self.audio_list_widget = QListWidget()
        self.audio_list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        audio_list_layout.addWidget(self.audio_list_widget)
        right_layout.addWidget(self.audio_list_groupbox)
        
        right_column_widget.setVisible(False)
        self.generator_right_column = right_column_widget
        
        main_layout.addWidget(left_column_widget, 1)
        main_layout.addWidget(right_column_widget, 1)
        
        # Initialize UI state
        self._update_gen_speed_locks()
        
        return tab_widget
    
    def _create_splicer_tab(self) -> QWidget:
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)
        
        files_groupbox = QGroupBox("📂 File Đầu Vào & Đầu Ra"); form_layout = QFormLayout(files_groupbox)
        self.splicer_input_edit = QLineEdit(); self.splicer_input_edit.setPlaceholderText("Chọn file draft_content.json cần xử lý"); btn_browse_splicer_in = QPushButton("📁 Chọn JSON Gốc"); btn_browse_splicer_in.clicked.connect(self.browse_splicer_input); in_layout = QHBoxLayout(); in_layout.addWidget(self.splicer_input_edit); in_layout.addWidget(btn_browse_splicer_in); form_layout.addRow("File JSON Gốc:", in_layout)
        
        # Splicer Timetamp row
        self.splicer_timetamp_row_widget = QWidget()
        splicer_timetamp_row_layout = QHBoxLayout(self.splicer_timetamp_row_widget); splicer_timetamp_row_layout.setContentsMargins(0, 0, 0, 0)
        self.splicer_timetamp_edit = QLineEdit(); self.splicer_timetamp_edit.setPlaceholderText("File SRT chứa timestamp_screen (Tùy chọn)")
        btn_browse_splicer_timetamp = QPushButton("⚙️ Nhập Timetamp"); btn_browse_splicer_timetamp.clicked.connect(self.browse_splicer_timetamp_file)
        splicer_timetamp_row_layout.addWidget(self.splicer_timetamp_edit); splicer_timetamp_row_layout.addWidget(btn_browse_splicer_timetamp)
        self.splicer_timetamp_label = QLabel("📄 Timetamp:")
        form_layout.addRow(self.splicer_timetamp_label, self.splicer_timetamp_row_widget)

        self.splicer_output_edit = QLineEdit(); self.splicer_output_edit.setPlaceholderText("Nơi lưu file JSON đã xử lý"); btn_browse_splicer_out = QPushButton("📁 Chọn Vị Trí Lưu"); btn_browse_splicer_out.clicked.connect(self.browse_splicer_output); out_layout = QHBoxLayout(); out_layout.addWidget(self.splicer_output_edit); out_layout.addWidget(btn_browse_splicer_out); form_layout.addRow("File JSON Mới:", out_layout)
        layout.addWidget(files_groupbox)

        options_groupbox = QGroupBox("⚙️ Tùy Chỉnh Xử Lý")
        options_layout = QVBoxLayout(options_groupbox)
        
        # Main layout for the groupbox: 2 columns
        splicer_mode_columns_layout = QHBoxLayout()
        splicer_mode_columns_layout.setSpacing(15)
        
        # COLUMN 1: Speeds and Modes (Wrapped in a styled Frame)
        s_col1_frame = QFrame(); s_col1_frame.setFrameShape(QFrame.Shape.StyledPanel)
        s_col1_frame.setStyleSheet("QFrame { border: 1px solid #444; border-radius: 8px; background-color: #2b2b2b; } QLabel { border: none; background: none; } QRadioButton { border: none; background: none; padding: 2px; }")
        s_col1_layout = QVBoxLayout(s_col1_frame)
        s_col1_layout.setContentsMargins(15, 15, 15, 15)
        s_col1_layout.setSpacing(15)
        
        # Combined Speed Row
        s_speed_row_layout = QHBoxLayout()
        s_audio_label = QLabel("🔊 Audio:"); s_audio_label.setMinimumHeight(30)
        s_speed_row_layout.addWidget(s_audio_label)
        self.splicer_speed_spinbox = QDoubleSpinBox(); self.splicer_speed_spinbox.setRange(0.5, 3.0); self.splicer_speed_spinbox.setSingleStep(0.05); self.splicer_speed_spinbox.setValue(1.00) 
        self.splicer_speed_spinbox.valueChanged.connect(self._update_pitch_checkbox_visibility); self.splicer_speed_spinbox.setMaximumWidth(70); self.splicer_speed_spinbox.setMinimumHeight(30)
        s_speed_row_layout.addWidget(self.splicer_speed_spinbox)
        
        s_speed_row_layout.addSpacing(15)
        
        s_video_label = QLabel("🎬 Video:"); s_video_label.setMinimumHeight(30)
        s_speed_row_layout.addWidget(s_video_label)
        self.splicer_video_speed_spinbox = QDoubleSpinBox(); self.splicer_video_speed_spinbox.setRange(0.5, 3.0); self.splicer_video_speed_spinbox.setSingleStep(0.05); self.splicer_video_speed_spinbox.setValue(1.0)
        self.splicer_video_speed_spinbox.valueChanged.connect(self._on_splicer_video_speed_changed); self.splicer_video_speed_spinbox.setMaximumWidth(70); self.splicer_video_speed_spinbox.setMinimumHeight(30)
        s_speed_row_layout.addWidget(self.splicer_video_speed_spinbox)
        s_speed_row_layout.addStretch()
        s_col1_layout.addLayout(s_speed_row_layout)
        
        # Sync Modes
        self.splicer_mode_sync_rb = QRadioButton("Đồng bộ tuyệt đối (Co giãn video theo audio)")
        self.splicer_mode_sync_rb.setChecked(True)
        self.splicer_mode_sync_rb.setToolTip("Video sẽ được co giãn (tăng/giảm tốc) để khớp chính xác với thời lượng của từng đoạn audio tương ứng.")
        self.splicer_mode_sync_rb.toggled.connect(self._update_splicer_speed_locks)
        s_col1_layout.addWidget(self.splicer_mode_sync_rb)
        
        self.splicer_mode_priority_rb = QRadioButton("Ưu tiên Video")
        self.splicer_mode_priority_rb.setToolTip("Giữ nguyên tốc độ video gốc, audio được đặt theo thứ tự nhưng video không bị co giãn. Hỗ trợ đồng bộ sóng âm.")
        self.splicer_mode_priority_rb.toggled.connect(self._update_splicer_speed_locks)
        s_col1_layout.addWidget(self.splicer_mode_priority_rb)
        
        self.splicer_mode_audio_sync_rb = QRadioButton("Đồng bộ Audio theo Video (Co giãn audio)")
        self.splicer_mode_audio_sync_rb.setToolTip("Audio sẽ được co giãn (tăng/giảm tốc) để khớp chính xác với thời lượng của từng đoạn video tương ứng.")
        self.splicer_mode_audio_sync_rb.toggled.connect(self._update_splicer_speed_locks)
        s_col1_layout.addWidget(self.splicer_mode_audio_sync_rb)
        
        self.splicer_mode_audio_sync_priority_rb = QRadioButton("Đồng bộ Audio theo Video - Ưu tiên")
        self.splicer_mode_audio_sync_priority_rb.setToolTip("Giữ nguyên tốc độ audio gốc, video được cắt/ghép theo ranh giới screen nhưng audio không bị co giãn.")
        self.splicer_mode_audio_sync_priority_rb.toggled.connect(self._update_splicer_speed_locks)
        s_col1_layout.addWidget(self.splicer_mode_audio_sync_priority_rb)
        
        # COLUMN 2: Additional Options (Wrapped in a styled Frame)
        s_col2_frame = QFrame(); s_col2_frame.setFrameShape(QFrame.Shape.StyledPanel)
        s_col2_frame.setStyleSheet("QFrame { border: 1px solid #444; border-radius: 8px; background-color: #2b2b2b; } QLabel { border: none; background: none; } QCheckBox { border: none; background: none; padding: 2px; }")
        s_col2_layout = QVBoxLayout(s_col2_frame)
        s_col2_layout.setContentsMargins(15, 15, 15, 15)
        s_col2_layout.setSpacing(15)
        
        self.splicer_remove_silence_checkbox = QCheckBox("Xoá khoản lặng")
        self.splicer_remove_silence_checkbox.setChecked(False)
        self.splicer_remove_silence_checkbox.setToolTip("Tự động xoá các đoạn im lặng trong file audio của project cũ.")
        s_col2_layout.addWidget(self.splicer_remove_silence_checkbox)
        
        self.splicer_waveform_sync_checkbox = QCheckBox("Đồng bộ âm thanh")
        self.splicer_waveform_sync_checkbox.setChecked(False)
        self.splicer_waveform_sync_checkbox.setToolTip("Khớp âm thanh MP3 chính xác với sóng âm lời thoại của video (Waveform Sync).")
        s_col2_layout.addWidget(self.splicer_waveform_sync_checkbox)
        
        self.splicer_pitch_checkbox = QCheckBox("Thay đổi cao độ")
        self.splicer_pitch_checkbox.setChecked(True)
        s_col2_layout.addWidget(self.splicer_pitch_checkbox)
        
        self.splicer_skip_stretch_checkbox = QCheckBox("Không co giãn nếu ngắn hơn")
        self.splicer_skip_stretch_checkbox.setChecked(False)
        self.splicer_skip_stretch_checkbox.setToolTip("Giữ nguyên tốc độ (không làm chậm) nếu video hoặc audio của đoạn đó đang ngắn hơn thành phần còn lại.")
        s_col2_layout.addWidget(self.splicer_skip_stretch_checkbox)
        
        s_col2_layout.addStretch()
        
        splicer_mode_columns_layout.addWidget(s_col1_frame, 1)
        splicer_mode_columns_layout.addWidget(s_col2_frame, 1)
        
        options_layout.addLayout(splicer_mode_columns_layout)
        layout.addWidget(options_groupbox)

        self.splicer_progress_label = QLabel(""); self.splicer_progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.splicer_progress_label.setVisible(False)
        layout.addWidget(self.splicer_progress_label)
        self.splicer_progress_bar = QProgressBar(); self.splicer_progress_bar.setTextVisible(False); self.splicer_progress_bar.setVisible(False)
        layout.addWidget(self.splicer_progress_bar)
        return tab_widget

    def _setup_ui_sync(self):
        """Connects signals for synchronizing settings between Generator and Splicer tabs."""
        # --- Speed SpinBoxes ---
        self.gen_speed_spinbox.valueChanged.connect(lambda v: self._sync_widget_value(v, self.splicer_speed_spinbox))
        self.splicer_speed_spinbox.valueChanged.connect(lambda v: self._sync_widget_value(v, self.gen_speed_spinbox))
        
        self.gen_video_speed_spinbox.valueChanged.connect(lambda v: self._sync_widget_value(v, self.splicer_video_speed_spinbox))
        self.splicer_video_speed_spinbox.valueChanged.connect(lambda v: self._sync_widget_value(v, self.gen_video_speed_spinbox))
        
        # --- Sync Modes (RadioButtons) ---
        self.gen_mode_sync_rb.toggled.connect(lambda b: self._sync_widget_checked(b, self.splicer_mode_sync_rb))
        self.splicer_mode_sync_rb.toggled.connect(lambda b: self._sync_widget_checked(b, self.gen_mode_sync_rb))
        
        self.gen_mode_priority_rb.toggled.connect(lambda b: self._sync_widget_checked(b, self.splicer_mode_priority_rb))
        self.splicer_mode_priority_rb.toggled.connect(lambda b: self._sync_widget_checked(b, self.gen_mode_priority_rb))
        
        self.gen_mode_audio_sync_rb.toggled.connect(lambda b: self._sync_widget_checked(b, self.splicer_mode_audio_sync_rb))
        self.splicer_mode_audio_sync_rb.toggled.connect(lambda b: self._sync_widget_checked(b, self.gen_mode_audio_sync_rb))
        
        self.gen_mode_audio_sync_priority_rb.toggled.connect(lambda b: self._sync_widget_checked(b, self.splicer_mode_audio_sync_priority_rb))
        self.splicer_mode_audio_sync_priority_rb.toggled.connect(lambda b: self._sync_widget_checked(b, self.gen_mode_audio_sync_priority_rb))
        
        # --- Additional Options (Checkboxes) ---
        self.gen_remove_silence_checkbox.toggled.connect(lambda b: self._sync_widget_checked(b, self.splicer_remove_silence_checkbox))
        self.splicer_remove_silence_checkbox.toggled.connect(lambda b: self._sync_widget_checked(b, self.gen_remove_silence_checkbox))
        
        self.gen_waveform_sync_checkbox.toggled.connect(lambda b: self._sync_widget_checked(b, self.splicer_waveform_sync_checkbox))
        self.splicer_waveform_sync_checkbox.toggled.connect(lambda b: self._sync_widget_checked(b, self.gen_waveform_sync_checkbox))
        
        self.gen_pitch_checkbox.toggled.connect(lambda b: self._sync_widget_checked(b, self.splicer_pitch_checkbox))
        self.splicer_pitch_checkbox.toggled.connect(lambda b: self._sync_widget_checked(b, self.gen_pitch_checkbox))

    def _sync_widget_value(self, value, target_widget):
        if self._syncing_ui: return
        self._syncing_ui = True
        try:
            target_widget.setValue(value)
        finally:
            self._syncing_ui = False

    def _sync_widget_checked(self, checked, target_widget):
        if self._syncing_ui: return
        self._syncing_ui = True
        try:
            target_widget.setChecked(checked)
        finally:
            self._syncing_ui = False

    def _create_log_section(self) -> QWidget:
        log_section_widget = QWidget(); layout = QVBoxLayout(log_section_widget); layout.setContentsMargins(0, 5, 0, 0)
        self.log_text_edit = QTextEdit(); self.log_text_edit.setReadOnly(True); self.log_text_edit.setFont(QFont("Consolas", 10)); self.log_text_edit.setMinimumHeight(150)
        self.log_text_edit.document().setMaximumBlockCount(0) # Unlimited lines
        self.log_timer = QTimer(self); self.log_timer.timeout.connect(self.update_logs); self.log_timer.start(500)
        action_layout = QHBoxLayout()
        self.main_action_button = QPushButton("🚀 BẮT ĐẦU"); self.main_action_button.setFixedHeight(40); self.main_action_button.clicked.connect(self.start_main_action)
        self.stop_button = QPushButton("⛔ DỪNG LẠI"); self.stop_button.setFixedHeight(40); self.stop_button.setEnabled(False); self.stop_button.clicked.connect(self.stop_generation)
        action_layout.addWidget(self.main_action_button, 3); action_layout.addWidget(self.stop_button, 1)
        layout.addWidget(self.log_text_edit); layout.addLayout(action_layout)
        return log_section_widget
        
    def _update_pitch_checkbox_visibility(self):
        """Shows or hides the pitch checkbox based on the current tab's speed value."""
        try:
            # Check for Generator tab widgets
            if hasattr(self, 'gen_speed_spinbox') and hasattr(self, 'gen_pitch_checkbox'):
                # Ensure the C++ objects haven't been deleted
                if self.gen_speed_spinbox and self.gen_pitch_checkbox:
                    gen_speed = self.gen_speed_spinbox.value()
                    self.gen_pitch_checkbox.setVisible(gen_speed != 1.0)
            
            # Check for Splicer tab widgets
            if hasattr(self, 'splicer_speed_spinbox') and hasattr(self, 'splicer_pitch_checkbox'):
                # Ensure the C++ objects haven't been deleted
                if self.splicer_speed_spinbox and self.splicer_pitch_checkbox:
                    splicer_speed = self.splicer_speed_spinbox.value()
                    self.splicer_pitch_checkbox.setVisible(splicer_speed != 1.0)
        except (RuntimeError, AttributeError):
            # Safe to ignore if widgets are being recreated or not yet initialized
            pass
    
    def _update_gen_speed_locks(self):
        """Cập nhật trạng thái khóa tốc độ dựa vào chế độ đồng bộ (Generator tab)."""
        is_priority_mode = self.gen_mode_priority_rb.isChecked() or self.gen_mode_audio_sync_priority_rb.isChecked()
        
        # Hide/Show options based on "Video Priority" mode
        self.gen_waveform_sync_checkbox.setVisible(is_priority_mode)
        
        if not is_priority_mode:
            self.gen_waveform_sync_checkbox.setChecked(False)

        # Chế độ "Co giãn video theo audio": audio tùy chỉnh, video khóa
        if self.gen_mode_sync_rb.isChecked():
            self.gen_speed_spinbox.setEnabled(True)
            self.gen_speed_spinbox.setStyleSheet("")
            self.gen_video_speed_spinbox.setEnabled(True)
            self.gen_video_speed_spinbox.setStyleSheet("")
        # Chế độ "Ưu tiên video": cả 2 đều tùy chỉnh
        elif self.gen_mode_priority_rb.isChecked():
            self.gen_speed_spinbox.setEnabled(True)
            self.gen_speed_spinbox.setStyleSheet("")
            self.gen_video_speed_spinbox.setEnabled(True)
            self.gen_video_speed_spinbox.setStyleSheet("")
        # Chế độ "Co giãn audio theo video": video tùy chỉnh, audio khóa
        elif self.gen_mode_audio_sync_rb.isChecked():
            self.gen_speed_spinbox.setEnabled(False)
            self.gen_speed_spinbox.setValue(1.0)
            self.gen_speed_spinbox.setStyleSheet("QDoubleSpinBox { background-color: #3a3a3a; color: #888; }")
            self.gen_video_speed_spinbox.setEnabled(True)
            self.gen_video_speed_spinbox.setStyleSheet("")
        # Chế độ "Ưu tiên audio": cả 2 đều tùy chỉnh
        elif self.gen_mode_audio_sync_priority_rb.isChecked():
            self.gen_speed_spinbox.setEnabled(True)
            self.gen_speed_spinbox.setStyleSheet("")
            self.gen_video_speed_spinbox.setEnabled(True)
            self.gen_video_speed_spinbox.setStyleSheet("")
    
    def _update_splicer_speed_locks(self):
        """Cập nhật trạng thái khóa tốc độ dựa vào chế độ đồng bộ (Splicer tab)."""
        is_priority_mode = self.splicer_mode_priority_rb.isChecked() or self.splicer_mode_audio_sync_priority_rb.isChecked()
        is_timetamp_mode = self.splicer_mode_priority_rb.isChecked()
        
        # Hide/Show options based on "Video Priority" mode
        self.splicer_waveform_sync_checkbox.setVisible(is_priority_mode)
        self.splicer_timetamp_row_widget.setVisible(is_timetamp_mode)
        self.splicer_timetamp_label.setVisible(is_timetamp_mode)
        
        if not is_priority_mode:
            self.splicer_waveform_sync_checkbox.setChecked(False)

        # Chế độ "Co giãn video theo audio": audio tùy chỉnh, video khóa
        if self.splicer_mode_sync_rb.isChecked():
            self.splicer_speed_spinbox.setEnabled(True)
            self.splicer_speed_spinbox.setStyleSheet("")
            self.splicer_video_speed_spinbox.setEnabled(True)
            self.splicer_video_speed_spinbox.setStyleSheet("")
        # Chế độ "Ưu tiên video": cả 2 đều tùy chỉnh
        elif self.splicer_mode_priority_rb.isChecked():
            self.splicer_speed_spinbox.setEnabled(True)
            self.splicer_speed_spinbox.setStyleSheet("")
            self.splicer_video_speed_spinbox.setEnabled(True)
            self.splicer_video_speed_spinbox.setStyleSheet("")
        # Chế độ "Co giãn audio theo video": video tùy chỉnh, audio khóa
        elif self.splicer_mode_audio_sync_rb.isChecked():
            self.splicer_speed_spinbox.setEnabled(False)
            self.splicer_speed_spinbox.setValue(1.0)
            self.splicer_speed_spinbox.setStyleSheet("QDoubleSpinBox { background-color: #3a3a3a; color: #888; }")
            self.splicer_video_speed_spinbox.setEnabled(True)
            self.splicer_video_speed_spinbox.setStyleSheet("")
        # Chế độ "Ưu tiên audio": cả 2 đều tùy chỉnh
        elif self.splicer_mode_audio_sync_priority_rb.isChecked():
            self.splicer_speed_spinbox.setEnabled(True)
            self.splicer_speed_spinbox.setStyleSheet("")
            self.splicer_video_speed_spinbox.setEnabled(True)
            self.splicer_video_speed_spinbox.setStyleSheet("")
        
    def _on_video_speed_changed(self):
        """Handle video speed value changes."""
        pass  # Không tự động chuyển chế độ
    
    def _on_splicer_video_speed_changed(self):
        """Handle video speed value changes in splicer tab."""
        pass  # Không tự động chuyển chế độ

    def start_main_action(self):
        current_tab_index = self.tabs.currentIndex()
        if current_tab_index == 0: self.start_generation()
        elif current_tab_index == 1: self.start_splicing_from_json()

    def start_generation(self):
        if self.worker and self.worker.isRunning():
            return
            
        if not all([self.video_path_edit.text(), self.audio_folder_edit.text(), self.srt_path_edit.text(), self.output_json_edit_gen.text()]):
            QMessageBox.critical(self, "Lỗi", "Vui lòng chọn tất cả các file đầu vào và đầu ra.")
            return
            
        self.log_text_edit.clear()
        
        audio_folder = self.audio_folder_edit.text()
        audio_files = [os.path.join(audio_folder, self.audio_list_widget.item(i).text()) for i in range(self.audio_list_widget.count())]
        
        target_speed = self.gen_speed_spinbox.value()
        keep_pitch = self.gen_pitch_checkbox.isChecked() and self.gen_pitch_checkbox.isVisible()
        if self.gen_mode_priority_rb.isChecked():
            sync_mode = 'video_priority'
        elif self.gen_mode_audio_sync_rb.isChecked():
            sync_mode = 'audio_sync'
        elif self.gen_mode_audio_sync_priority_rb.isChecked():
            sync_mode = 'audio_sync_priority'
        else:
            sync_mode = 'force_sync'
        
        waveform_sync = self.gen_waveform_sync_checkbox.isChecked()
        
        # Video speed settings - khi speed != 1.0 thì áp dụng logic mới
        target_video_speed = self.gen_video_speed_spinbox.value()
        video_speed_enabled = target_video_speed != 1.0

        # Extract timestamp_screen from Timetamp SRT file.
        # Temporary rule: do not apply timetamp in "audio_sync_priority" mode.
        timestamp_screen = [] if sync_mode == 'audio_sync_priority' else None
        timetamp_path = self.timetamp_edit.text()
        if sync_mode == 'audio_sync_priority':
            if timetamp_path:
                logger.info("Generator: Bỏ qua Timetamp ở mode 'Đồng bộ Audio theo Video (Giữ nguyên audio)'.")
        elif timetamp_path and os.path.exists(timetamp_path):
            timestamp_screen = extract_timestamp_screen_from_timetamp_file(timetamp_path)
            if timestamp_screen:
                logger.info(f"Generator: Đã trích xuất {len(timestamp_screen)} ranh giới Screen từ {os.path.basename(timetamp_path)}")
            else:
                logger.warning(f"Generator: Không thể trích xuất ranh giới Screen từ {os.path.basename(timetamp_path)}")

        self.worker = UniversalWorker(run_generation_task)
        
        args = (
            self.worker.signals.progress_update, 
            self.video_path_edit.text(), 
            audio_files, 
            self.srt_path_edit.text(), 
            self.output_json_edit_gen.text(), 
            True,
            target_speed, 
            keep_pitch,
            sync_mode,
            video_speed_enabled,
            target_video_speed,
            self.gen_remove_silence_checkbox.isChecked(),
            waveform_sync,
            timestamp_screen,
            self.gen_skip_stretch_checkbox.isChecked(),
            self.gen_export_lt8_checkbox.isChecked()
        )
        self.worker.args = args
        
        self.worker.signals.progress_update.connect(self.on_progress_update)
        self.worker.signals.finished.connect(self.on_worker_finished)
        self.worker.start()
        self.set_ui_busy(True)

    def start_splicing_from_json(self):
        if self.worker and self.worker.isRunning(): return
        input_path = self.splicer_input_edit.text(); output_path = self.splicer_output_edit.text()
        if not input_path or not output_path: QMessageBox.critical(self, "Lỗi", "Vui lòng chọn file JSON đầu vào và vị trí lưu đầu ra."); return
        self.log_text_edit.clear()
        target_speed = self.splicer_speed_spinbox.value()
        if self.splicer_mode_priority_rb.isChecked():
            mode = 'video_priority'
        elif self.splicer_mode_audio_sync_rb.isChecked():
            mode = 'audio_sync'
        elif self.splicer_mode_audio_sync_priority_rb.isChecked():
            mode = 'audio_sync_priority'
        else:
            mode = 'force_sync'
        
        waveform_sync = self.splicer_waveform_sync_checkbox.isChecked()
        keep_pitch = self.splicer_pitch_checkbox.isChecked() and self.splicer_pitch_checkbox.isVisible()
        
        # Video speed settings - khi speed != 1.0 thì áp dụng logic mới
        target_video_speed = self.splicer_video_speed_spinbox.value()
        video_speed_enabled = target_video_speed != 1.0
        
        # Extract timestamp_screen for Splicer from Timetamp SRT file.
        # Temporary rule: do not apply timetamp in "audio_sync_priority" mode.
        # Use [] (not None) to avoid fallback to timestamp values embedded in input JSON.
        timestamp_screen = [] if mode == 'audio_sync_priority' else None
        timetamp_path = self.splicer_timetamp_edit.text()
        if mode == 'audio_sync_priority':
            if timetamp_path:
                logger.info("Splicer: Bỏ qua Timetamp ở mode 'Đồng bộ Audio theo Video (Giữ nguyên audio)'.")
        elif timetamp_path and os.path.exists(timetamp_path):
            timestamp_screen = extract_timestamp_screen_from_timetamp_file(timetamp_path)
            if timestamp_screen:
                logger.info(f"Splicer: Đã trích xuất {len(timestamp_screen)} ranh giới Screen từ {os.path.basename(timetamp_path)}")
            else:
                logger.warning(f"Splicer: Không thể trích xuất ranh giới Screen từ {os.path.basename(timetamp_path)}")
        
        self.worker = UniversalWorker(run_splicing_task)
        args = (
            self.worker.signals.progress_update, 
            input_path, 
            output_path, 
            target_speed, 
            mode, 
            keep_pitch, 
            video_speed_enabled, 
            target_video_speed, 
            self.splicer_remove_silence_checkbox.isChecked(),
            waveform_sync,
            timestamp_screen,
            self.splicer_skip_stretch_checkbox.isChecked()
        )
        self.worker.args = args; self.worker.signals.progress_update.connect(self.on_progress_update); self.worker.signals.finished.connect(self.on_worker_finished); self.worker.start(); self.set_ui_busy(True)

    def set_ui_busy(self, busy: bool):
        self.main_action_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.tabs.setEnabled(not busy)
        self.progress_stack.setVisible(busy)
        # Thay đổi chiều cao log khi hiện tiến trình
        if busy:
            self.log_text_edit.setMinimumHeight(60)  # Giảm chiều cao log
        else:
            self.log_text_edit.setMinimumHeight(150)  # Trả lại chiều cao ban đầu
            self.gen_progress_widget.label.setText(""); self.gen_progress_widget.bar.setValue(0)
            self.splicer_progress_widget.label.setText(""); self.splicer_progress_widget.bar.setValue(0)

    def on_progress_update(self, percent: int, message: str):
        current_widget = self.progress_stack.currentWidget()
        current_widget.bar.setValue(percent)
        current_widget.label.setText(f"{message} ({percent}%)")

    def _update_timetamp_visibility(self):
        """Show Timetamp field ONLY when 'Sync Video to Audio (Priority Video)' is active."""
        if not hasattr(self, 'gen_mode_priority_rb') or not self.gen_mode_priority_rb:
            return
            
        is_timetamp_mode = self.gen_mode_priority_rb.isChecked()
        
        self.timetamp_row.setVisible(is_timetamp_mode)
        if hasattr(self, 'timetamp_label'):
            self.timetamp_label.setVisible(is_timetamp_mode)
            
        # Trigger layout refresh
        current_widget = self.tabs.currentWidget()
        if current_widget and current_widget.layout():
            current_widget.layout().activate()
        
        # Adjust window height
        if is_timetamp_mode:
            self.setMinimumHeight(880)
            if self.height() < 880:
                self.resize(self.width(), 880)
        else:
            self.setMinimumHeight(820)
            if self.height() < 820:
                self.resize(self.width(), 820)
        
    def on_worker_finished(self, success: bool, result_or_error: str):
        self.set_ui_busy(False)
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        if success: QMessageBox.information(self, "Thành công", f"Tác vụ hoàn tất!\n\nFile đã được lưu tại:\n{result_or_error}")
        else: QMessageBox.critical(self, "Lỗi", f"Tác vụ thất bại:\n\n{result_or_error}")
    

    def browse_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file video", "", "Video Files (*.mp4 *.mov *.avi);;All Files (*)")
        if path:
            self.video_path_edit.setText(path)
            try:
                video_dir = os.path.dirname(path)
                audio_dir = os.path.join(video_dir, "mp3")
                self.audio_folder_edit.setText(audio_dir)
                if os.path.isdir(audio_dir):
                    self.load_audio_files(audio_dir)
                    logger.info(f"Auto-selected audio folder: {audio_dir}")
                else:
                    logger.warning(f"Auto-selected audio folder does not exist: {audio_dir}")
            except Exception as e:
                logger.error(f"Failed to auto-select audio folder for video {path}: {e}")
    def browse_audio_folder(self): path = QFileDialog.getExistingDirectory(self, "Chọn thư mục audio"); (path and (self.audio_folder_edit.setText(path), self.load_audio_files(path)))
    def browse_timetamp_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file Timetamp (SRT)", "", "SRT Files (*.srt);;All Files (*)")
        if path:
            self.timetamp_edit.setText(path)
    def browse_splicer_timetamp_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file Timetamp cho Splicer (SRT)", "", "SRT Files (*.srt);;All Files (*)")
        if path:
            self.splicer_timetamp_edit.setText(path)
    def browse_srt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file phụ đề", "", "SRT Files (*.srt);;All Files (*)")
        if path:
            self.srt_path_edit.setText(path)

    def browse_splicer_input(self): path, _ = QFileDialog.getOpenFileName(self, "Chọn file draft_content.json gốc", "", "JSON Files (*.json)"); (path and (self.splicer_input_edit.setText(path), self.splicer_output_edit.setText(os.path.join(os.path.dirname(path), "draft_content.json"))))
    def browse_splicer_output(self): in_path = self.splicer_input_edit.text(); suggested = os.path.join(os.path.dirname(in_path) if in_path else "", "draft_content.json"); path, _ = QFileDialog.getSaveFileName(self, "Lưu file JSON đã xử lý", suggested, "JSON Files (*.json)"); (path and self.splicer_output_edit.setText(path))
    def browse_output_json_for_generator(self):
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu file JSON")
        if path:
            json_path = os.path.join(path, "draft_content.json")
            backup_dir = path
            base_backup = os.path.join(backup_dir, "draft_content_backup.json")
            backup_path = base_backup
            count = 1
            if os.path.exists(json_path):
                while os.path.exists(backup_path):
                    backup_path = os.path.join(backup_dir, f"draft_content_backup_{count}.json")
                    count += 1
                try:
                    os.rename(json_path, backup_path)
                except Exception as e:
                    QMessageBox.warning(self, "Cảnh báo", f"Không thể đổi tên file draft_content.json thành {os.path.basename(backup_path)}: {e}")
            self.output_json_edit_gen.setText(json_path)
    def load_audio_files(self, folder_path: str):
        try:
            audio_files = sorted([f for f in os.listdir(folder_path) if f.lower().endswith(('.mp3', '.wav', '.m4a'))], key=self.natural_sort_key)
            self.audio_list_widget.clear(); self.audio_list_widget.addItems(audio_files)
            self.generator_right_column.setVisible(True); logger.info(f"Loaded {len(audio_files)} audio files.")
        except Exception as e: QMessageBox.critical(self, "Lỗi", f"Không thể tải file audio: {e}"); logger.error(f"Failed to load audio files: {e}"); self.generator_right_column.setVisible(False)
    def update_logs(self): messages = self.log_capture.get_messages(); (messages and (self.log_text_edit.append("\n".join(messages)), self.log_capture.clear_messages(), self.log_text_edit.verticalScrollBar().setValue(self.log_text_edit.verticalScrollBar().maximum())))
    def stop_generation(self):
        if self.worker and self.worker.isRunning():
            # Disconnect signals to prevent double handling
            try:
                self.worker.signals.progress_update.disconnect()
                self.worker.signals.finished.disconnect()
            except:
                pass
                
            self.worker.terminate()
            self.worker.wait()  # Wait for thread to actually finish
            logger.warning("Process terminated by user.")
            self.on_worker_finished(False, "Tác vụ đã bị người dùng dừng lại.")

    def closeEvent(self, event):
        """Handle application closure to ensure threads are cleaned up."""
        if self.worker and self.worker.isRunning():
            try:
                self.worker.terminate()
                self.worker.wait()
            except:
                pass
        event.accept()

    def natural_sort_key(self, s: str) -> List[str]: return [int(text) if text.isdigit() else text.lower() for text in re.split(r'([0-9]+)', s)]
