"""OCR Worker - chạy SubtitleExtractor trong QThread để không block UI."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal  # type: ignore


class OcrWorker(QThread):
    """Chạy quá trình trích xuất phụ đề OCR trong background thread."""

    progress_frame = Signal(int)   # % frame extraction
    progress_ocr = Signal(int)     # % ocr recognition
    finished = Signal(str)         # đường dẫn file .srt kết quả
    error = Signal(str)            # thông báo lỗi

    def __init__(
        self,
        video_path: str,
        sub_area: tuple[int, int, int, int],   # (ymin, ymax, xmin, xmax)
        language: str = "ch",
        mode: str = "fast",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.video_path = video_path
        self.sub_area = sub_area
        self.language = language
        self.mode = mode
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self.requestInterruption()

    def run(self) -> None:
        """Entry point của thread."""
        try:
            # Thêm engine vào sys.path
            engine_dir = Path(__file__).resolve().parents[2] / "engine" / "ocr_extractor" / "VSE_MODULE" / "backend"
            if str(engine_dir.parent) not in sys.path:
                sys.path.insert(0, str(engine_dir.parent))

            # Import và cấu hình
            from comecut_py.engine.ocr_extractor.VSE_MODULE.backend import config  # type: ignore

            # Ánh xạ ngôn ngữ
            lang_map = {
                "vi": "vi",
                "zh": "ch",
                "en": "en",
            }
            config.REC_CHAR_TYPE = lang_map.get(self.language, "ch")

            # Ánh xạ chế độ
            if self.mode == "fast":
                config.MODE_TYPE = "fast"
            else:
                config.MODE_TYPE = "accurate"

            from comecut_py.engine.ocr_extractor.VSE_MODULE.backend.main import SubtitleExtractor  # type: ignore

            extractor = SubtitleExtractor(
                vd_path=self.video_path,
                sub_area=self.sub_area,
            )

            # Kết nối callback tiến độ
            original_update = extractor.update_progress

            def _progress_hook(ocr=None, frame_extract=None, **kwargs):
                if self._cancelled:
                    return
                if frame_extract is not None:
                    self.progress_frame.emit(int(frame_extract))
                if ocr is not None:
                    self.progress_ocr.emit(int(ocr))
                original_update(ocr=ocr, frame_extract=frame_extract, **kwargs)

            extractor.update_progress = _progress_hook

            if self._cancelled:
                return

            extractor.run()

            if self._cancelled:
                return

            # Tìm file SRT kết quả
            srt_path = str(Path(self.video_path).with_suffix(".srt"))
            if os.path.exists(srt_path):
                self.finished.emit(srt_path)
            else:
                self.error.emit("Không tạo được file SRT. Vui lòng kiểm tra lại video và vùng đã chọn.")

        except ImportError as e:
            self.error.emit(
                f"Thiếu thư viện OCR: {e}\n\n"
                "Vui lòng cài đặt:\npip install paddlepaddle paddleocr"
            )
        except Exception as e:
            self.error.emit(f"Lỗi OCR: {e}")
