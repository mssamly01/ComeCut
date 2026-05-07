#!/usr/bin/env python3
"""
CapCut Draft JSON Generator - Main Entry Point
Modular version with intelligent subprocess console hiding fix.
"""

import sys
import os
import traceback
import subprocess
import multiprocessing

# --- EARLY INITIALIZATION FOR EXE ---
if __name__ == "__main__":
    # Phải gọi freeze_support() ngay lập tức trên Windows khi dùng PyInstaller
    # để hỗ trợ các thư viện chạy đa luồng/tiến trình như librosa
    multiprocessing.freeze_support()

# Cưỡng ép nạp các module gây lỗi NameError trong bản EXE
try:
    import scipy.stats
    import scipy.signal
    import scipy.special
    import librosa
except Exception:
    pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

# Add current directory to path for relative imports to work consistently
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def resource_path(relative_path):
    """Resolve resource paths for both source runs and PyInstaller bundles."""
    if getattr(sys, "frozen", False):
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base_path = current_dir
    return os.path.join(base_path, relative_path)

# Block 1: Configure PATH to include bundled or local FFmpeg executables
if getattr(sys, 'frozen', False):
    # --- Running as a bundled .exe ---
    # Try multiple possible locations for FFmpeg
    possible_ffmpeg_paths = [
        os.path.join(sys._MEIPASS, "_internal", "bin"),
        sys._MEIPASS,  # Root of temporary directory
        os.path.dirname(sys.executable),  # Same directory as .exe
    ]
    
    ffmpeg_found = False
    for ffmpeg_path in possible_ffmpeg_paths:
        if os.path.isdir(ffmpeg_path):
            # Check if ffmpeg.exe actually exists in this path
            ffmpeg_exe = os.path.join(ffmpeg_path, "ffmpeg.exe")
            if os.path.isfile(ffmpeg_exe):
                os.environ['PATH'] = ffmpeg_path + os.pathsep + os.environ.get('PATH', '')
                print(f"[INFO] FFmpeg found and added to PATH: {ffmpeg_path}")
                ffmpeg_found = True
                break
        elif os.path.isfile(os.path.join(ffmpeg_path, "ffmpeg.exe")):
            os.environ['PATH'] = ffmpeg_path + os.pathsep + os.environ.get('PATH', '')
            print(f"[INFO] FFmpeg found and added to PATH: {ffmpeg_path}")
            ffmpeg_found = True
            break
    
    if not ffmpeg_found:
        print(f"[WARNING] FFmpeg not found in any expected location")
        print(f"[INFO] _MEIPASS contents: {os.listdir(sys._MEIPASS) if os.path.exists(sys._MEIPASS) else 'N/A'}")
        # Fallback: add _MEIPASS anyway
        os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')
else:
    # --- Running as a standard Python script (.py) ---
    internal_bin_path = os.path.join(current_dir, "_internal", "bin")
    if os.path.isdir(internal_bin_path):
        os.environ['PATH'] = internal_bin_path + os.pathsep + os.environ.get('PATH', '')
        print(f"[INFO] FFmpeg path added to PATH: {internal_bin_path}")
    else:
        print(f"[WARNING] FFmpeg directory not found in: {internal_bin_path}")

# Block 2: Prevent console windows from popping up for subprocess calls
if sys.platform == "win32":
    _original_Popen = subprocess.Popen
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = subprocess.SW_HIDE
    class _PatchedPopen(_original_Popen):
        def __init__(self, *args, **kwargs):
            if 'startupinfo' not in kwargs:
                kwargs['startupinfo'] = _si
            super().__init__(*args, **kwargs)
    subprocess.Popen = _PatchedPopen

# --- END: CRITICAL CODE FOR PYINSTALLER ---


try:
    from gui.main_window import MainWindow
    from utils.logger import setup_logger
except ImportError as e:
    print(f"Import Error: {e}")
    print("Please ensure all required modules are in the correct directories")
    sys.exit(1)

def main():
    """Main entry point"""
    try:
        # Setup logging
        logger = setup_logger()
        logger.info("Starting CapCut Draft JSON Generator & Editor")
        
        # Create QApplication
        app = QApplication(sys.argv)
        app.setWindowIcon(QIcon(resource_path("icon.ico")))
        app.setStyle('Fusion')
        
        # Set application metadata
        app.setApplicationName("CapCut Draft Editor")
        app.setApplicationVersion("3.4.0")
        app.setOrganizationName("CapCut Tools")
        
        # Create and show main window
        window = MainWindow()
        window.show()
        
        # Start event loop
        return app.exec()
        
    except Exception as e:
        error_msg = f"Critical Error: {e}\n{traceback.format_exc()}"
        print(error_msg)
        
        try:
            from PyQt6.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Critical Error")
            msg.setText("Application failed to start!")
            msg.setDetailedText(error_msg)
            msg.exec()
        except:
            pass
        
        return 1

if __name__ == "__main__":
    sys.exit(main())