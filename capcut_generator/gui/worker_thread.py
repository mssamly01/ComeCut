"""
Background worker threads for CapCut draft operations.
Includes a universal worker for running any function with progress reporting.
"""

import sys
import traceback
from typing import List, Optional
from PyQt6.QtCore import QThread, pyqtSignal, QObject

from core.capcut_generator import CapCutDraftGenerator
from utils.logger import get_logger

logger = get_logger(__name__)


# ==============================================================================
#  NEW UNIVERSAL WORKER (For Progress Bar Integration)
# ==============================================================================

class ProgressSignals(QObject):
    """
    Defines signals for reporting progress from a worker thread.
    - progress_update: Reports percentage (int) and message (str).
    - finished: Reports success (bool) and result/error message (str).
    """
    progress_update = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

class UniversalWorker(QThread):
    """A universal worker thread that can run any function and report progress."""
    def __init__(self, target_func, *args, **kwargs):
        super().__init__()
        self.target_func = target_func
        self.args = args
        self.kwargs = kwargs
        self.signals = ProgressSignals()

    def run(self):
        """Executes the target function and emits signals."""
        try:
            # --- THAY ĐỔI QUAN TRỌNG ---
            # Chỉ cần gọi hàm mục tiêu với các tham số đã được cung cấp.
            # Việc truyền callback sẽ được thực hiện ở nơi gọi (main_window.py).
            result = self.target_func(*self.args, **self.kwargs)
            
            if result:
                self.signals.finished.emit(True, str(result)) # Đảm bảo kết quả là string
            else:
                self.signals.finished.emit(False, "Operation failed: The function returned no result. Check logs for details.")
        except Exception as e:
            error_details = f"An unhandled error occurred:\n\n{traceback.format_exc()}"
            self.signals.finished.emit(False, error_details)

# ==============================================================================
#  LEGACY WORKERS (Can be removed if no longer used, kept for reference)
# ==============================================================================

class GeneratorWorker(QThread):
    """DEPRECATED: Background worker thread for generation process. Use UniversalWorker instead."""
    
    # Signals
    progress = pyqtSignal(str)  # Progress messages
    error = pyqtSignal(str)     # Error messages  
    success = pyqtSignal(str)   # Success with result path
    finished = pyqtSignal()     # Thread finished
    
    def __init__(self, video_path: str, audio_files: List[str], srt_path: str,
                 output_json_path: str, gap_aware_mode: bool = False):
        super().__init__()
        
        self.video_path = video_path
        self.audio_files = audio_files
        self.srt_path = srt_path  
        self.output_json_path = output_json_path
        self.gap_aware_mode = gap_aware_mode
        self.result_path = None
        
        # Thread settings
        self.setTerminationEnabled(True)
        
        logger.warning("Legacy GeneratorWorker is being used. Consider switching to UniversalWorker.")
    
    def run(self):
        """Main thread execution"""
        original_stdout = sys.stdout
        try:
            logger.info("Legacy worker thread started")
            sys.stdout = ThreadOutputCapture(self.progress)
            
            generator = CapCutDraftGenerator(
                max_segments=500,
                memory_limit_mb=2500,
                batch_size=2
            )
            
            result = generator.generate_single_json(
                self.video_path,
                self.audio_files,
                self.srt_path,
                self.output_json_path,
                self.gap_aware_mode
            )
            
            sys.stdout = original_stdout
            
            if result:
                self.result_path = result
                self.success.emit(result)
            else:
                error_msg = "Generation failed. The process completed but returned no result.\n\nPlease check the console or log file for the specific error details."
                self.error.emit(error_msg)
                
        except Exception as e:
            sys.stdout = original_stdout if 'original_stdout' in locals() else sys.__stdout__
            error_details = f"An unhandled error occurred:\n\nError: {e}\n\nTraceback:\n{traceback.format_exc()}"
            self.error.emit(error_details)
            
        finally:
            sys.stdout = sys.__stdout__
            self.finished.emit()
    
    def terminate(self):
        """Terminate the thread safely"""
        self.requestInterruption()
        super().terminate()
    
    def stop(self):
        """Request thread to stop gracefully"""
        self.requestInterruption()

class ThreadOutputCapture:
    """Capture stdout/stderr from background thread and emit as signals"""
    def __init__(self, signal):
        self.signal = signal
        
    def write(self, text: str):
        if text.strip():
            self.signal.emit(str(text.rstrip()))
            
    def flush(self):
        pass
    
    def fileno(self):
        return -1

class ProgressWorker(QThread):
    """Specialized worker for progress tracking operations"""
    
    progress_update = pyqtSignal(int, str)
    status_update = pyqtSignal(str)
    completed = pyqtSignal(bool, str)
    
    def __init__(self, operation_func, *args, **kwargs):
        super().__init__()
        self.operation_func = operation_func
        self.args = args
        self.kwargs = kwargs
        self.is_cancelled = False
        
    def run(self):
        try:
            result = self.operation_func(*self.args, **self.kwargs)
            if not self.is_cancelled:
                self.completed.emit(True, "Operation completed successfully")
        except Exception as e:
            error_msg = f"Operation failed: {e}"
            self.completed.emit(False, error_msg)
    
    def cancel(self):
        self.is_cancelled = True
        self.requestInterruption()
    
    def emit_progress(self, percentage: int, message: str = ""):
        if not self.is_cancelled:
            self.progress_update.emit(percentage, message)
    
    def emit_status(self, message: str):
        if not self.is_cancelled:
            self.status_update.emit(message)

class BatchProcessor(QThread):
    """Worker for processing items in batches with memory management"""
    
    batch_completed = pyqtSignal(int, int, str)
    item_processed = pyqtSignal(int, str)
    processing_finished = pyqtSignal(bool, str)
    memory_warning = pyqtSignal(float, str)
    
    def __init__(self, items: List, process_func: callable, batch_size: int = 10):
        super().__init__()
        self.items = items
        self.process_func = process_func
        self.batch_size = batch_size
        self.is_cancelled = False
        self.results = []
        
    def run(self):
        try:
            total_batches = (len(self.items) + self.batch_size - 1) // self.batch_size
            for batch_num in range(total_batches):
                if self.is_cancelled: break
                start_idx = batch_num * self.batch_size
                end_idx = min(start_idx + self.batch_size, len(self.items))
                batch_items = self.items[start_idx:end_idx]
                batch_results = []
                for i, item in enumerate(batch_items):
                    if self.is_cancelled: break
                    try:
                        result = self.process_func(item)
                        batch_results.append(result)
                        item_name = getattr(item, 'name', str(item))
                        self.item_processed.emit(start_idx + i, item_name)
                    except Exception as e:
                        logger.error(f"Error processing item {start_idx + i}: {e}")
                        continue
                self.results.extend(batch_results)
                batch_msg = f"Batch {batch_num + 1}/{total_batches} completed"
                self.batch_completed.emit(batch_num + 1, total_batches, batch_msg)
            
            if not self.is_cancelled:
                self.processing_finished.emit(True, f"Processing completed: {len(self.results)} items processed")
            else:
                self.processing_finished.emit(False, "Processing cancelled by user")
        except Exception as e:
            self.processing_finished.emit(False, f"Batch processing failed: {e}")
    
    def cancel(self):
        self.is_cancelled = True
        self.requestInterruption()
    
    def get_results(self):
        return self.results

class FileValidator(QThread):
    """Background thread for file validation"""
    
    file_validated = pyqtSignal(str, bool, str)
    validation_completed = pyqtSignal(int, int)
    
    def __init__(self, file_paths: List[str]):
        super().__init__()
        self.file_paths = file_paths
        self.valid_files = []
        self.invalid_files = []
        
    def run(self):
        for file_path in self.file_paths:
            if self.isInterruptionRequested(): break
            is_valid, message = self._validate_file(file_path)
            if is_valid: self.valid_files.append(file_path)
            else: self.invalid_files.append(file_path)
            self.file_validated.emit(file_path, is_valid, message)
        self.validation_completed.emit(len(self.valid_files), len(self.file_paths))
    
    def _validate_file(self, file_path: str) -> tuple:
        try:
            import os
            if not os.path.exists(file_path): return False, "File does not exist"
            if not os.path.isfile(file_path): return False, "Path is not a file"
            if os.path.getsize(file_path) == 0: return False, "File is empty"
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.mp4', '.mov', '.avi', '.mkv', '.wmv']: return self._validate_video_file(file_path)
            elif ext in ['.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg']: return self._validate_audio_file(file_path)
            elif ext == '.srt': return self._validate_srt_file(file_path)
            else: return True, "File type not specifically validated"
        except Exception as e:
            return False, f"Validation error: {e}"
    
    def _validate_video_file(self, file_path: str) -> tuple:
        try:
            import ffmpeg
            probe = ffmpeg.probe(file_path)
            if not any(stream['codec_type'] == 'video' for stream in probe['streams']): return False, "No video streams found"
            return True, "Valid video file"
        except Exception as e:
            return False, f"Invalid video file: {e}"
    
    def _validate_audio_file(self, file_path: str) -> tuple:
        try:
            import ffmpeg
            probe = ffmpeg.probe(file_path)
            if not any(stream['codec_type'] == 'audio' for stream in probe['streams']): return False, "No audio streams found"
            return True, "Valid audio file"
        except Exception as e:
            return False, f"Invalid audio file: {e}"
    
    def _validate_srt_file(self, file_path: str) -> tuple:
        try:
            import pysrt
            subs = pysrt.open(file_path, encoding='utf-8')
            if len(subs) == 0: return False, "SRT file contains no subtitles"
            for sub in subs[:3]:
                if sub.start >= sub.end: return False, "Invalid time ranges in SRT"
            return True, f"Valid SRT file ({len(subs)} subtitles)"
        except Exception as e:
            return False, f"Invalid SRT file: {e}"
    
    def get_valid_files(self): return self.valid_files
    def get_invalid_files(self): return self.invalid_files


class StreamRedirector:
    """Redirect stream output to Qt signals"""
    
    def __init__(self, signal):
        self.signal = signal
        self.buffer = []
        
    def write(self, text):
        if text.strip():
            self.buffer.append(text.rstrip())
            if len(self.buffer) >= 5 or text.endswith('\n'):
                self.flush()
    
    def flush(self):
        if self.buffer:
            self.signal.emit('\n'.join(self.buffer))
            self.buffer.clear()
    
    def fileno(self):
        return -1