"""PySide6 entry point - constructs the QApplication and the main window."""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from threading import current_thread
from typing import TextIO

_CRASH_LOG_FILE: TextIO | None = None
_OLD_QT_MESSAGE_HANDLER = None


def _crash_debug_enabled() -> bool:
    raw = (os.environ.get("COMECUT_CRASH_DEBUG", "1") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _log_line(message: str) -> None:
    global _CRASH_LOG_FILE
    if _CRASH_LOG_FILE is None:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    _CRASH_LOG_FILE.write(f"[{ts}] {message}\n")
    _CRASH_LOG_FILE.flush()


def _install_crash_debug_hooks() -> Path | None:
    """Enable crash diagnostics for Python + Qt + native faults."""
    global _CRASH_LOG_FILE, _OLD_QT_MESSAGE_HANDLER
    if not _crash_debug_enabled():
        return None
    if _CRASH_LOG_FILE is not None:
        return Path(_CRASH_LOG_FILE.name)

    log_path = Path.cwd() / "comecut_py_crash.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _CRASH_LOG_FILE = log_path.open("a", encoding="utf-8", buffering=1)
    _log_line("=" * 80)
    _log_line("ComeCut-Py crash debug session started")
    _log_line(f"Python: {sys.version}")
    _log_line(f"Platform: {sys.platform}")
    _log_line(f"PID: {os.getpid()}")

    import faulthandler

    faulthandler.enable(file=_CRASH_LOG_FILE, all_threads=True)
    _log_line("faulthandler enabled (all_threads=True)")

    def _python_excepthook(exc_type, exc_value, exc_tb):
        _log_line(
            f"[PYTHON-UNCAUGHT] thread={current_thread().name} "
            f"type={getattr(exc_type, '__name__', str(exc_type))}"
        )
        traceback.print_exception(exc_type, exc_value, exc_tb, file=_CRASH_LOG_FILE)
        _CRASH_LOG_FILE.flush()
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _python_excepthook

    if hasattr(sys, "unraisablehook"):
        def _unraisable_hook(unraisable):
            _log_line(
                f"[PYTHON-UNRAISABLE] {unraisable.exc_type}: "
                f"{unraisable.err_msg or ''}".strip()
            )
            if unraisable.exc_value is not None:
                traceback.print_exception(
                    unraisable.exc_type,
                    unraisable.exc_value,
                    unraisable.exc_traceback,
                    file=_CRASH_LOG_FILE,
                )
                _CRASH_LOG_FILE.flush()

        sys.unraisablehook = _unraisable_hook

    try:
        import threading

        def _thread_excepthook(args):
            _log_line(
                f"[THREAD-UNCAUGHT] thread={getattr(args.thread, 'name', 'unknown')} "
                f"type={getattr(args.exc_type, '__name__', str(args.exc_type))}"
            )
            traceback.print_exception(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
                file=_CRASH_LOG_FILE,
            )
            _CRASH_LOG_FILE.flush()
            if hasattr(threading, "__excepthook__"):
                threading.__excepthook__(args)

        threading.excepthook = _thread_excepthook
    except Exception:
        _log_line("threading.excepthook install skipped")

    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler  # type: ignore

        qt_levels = {
            QtMsgType.QtDebugMsg: "DEBUG",
            QtMsgType.QtInfoMsg: "INFO",
            QtMsgType.QtWarningMsg: "WARNING",
            QtMsgType.QtCriticalMsg: "CRITICAL",
            QtMsgType.QtFatalMsg: "FATAL",
        }

        def _qt_message_handler(msg_type, context, message):
            level = qt_levels.get(msg_type, str(msg_type))
            file_name = getattr(context, "file", "") or ""
            line = getattr(context, "line", 0) or 0
            function = getattr(context, "function", "") or ""
            _log_line(f"[QT-{level}] {file_name}:{line} {function} | {message}")
            if _OLD_QT_MESSAGE_HANDLER is not None:
                _OLD_QT_MESSAGE_HANDLER(msg_type, context, message)

        _OLD_QT_MESSAGE_HANDLER = qInstallMessageHandler(_qt_message_handler)
        _log_line("Qt message handler installed")
    except Exception as e:
        _log_line(f"Qt message handler install failed: {e!r}")

    return log_path


def _shutdown_crash_debug_hooks() -> None:
    global _CRASH_LOG_FILE
    if _CRASH_LOG_FILE is None:
        return
    _log_line("ComeCut-Py shutdown")
    _CRASH_LOG_FILE.close()
    _CRASH_LOG_FILE = None


def run() -> int:
    """Launch the GUI. Returns the Qt exit code."""
    try:
        from PySide6.QtWidgets import QApplication  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "PySide6 is not installed. Install GUI extras: "
            "pip install 'comecut-py[gui]'"
        ) from e

    from .main_window import MainWindow
    from .theme import apply_theme
    from .widgets.home_window import HomeWindow

    crash_log_path = _install_crash_debug_hooks()
    app = QApplication.instance() or QApplication(sys.argv)
    app.aboutToQuit.connect(_shutdown_crash_debug_hooks)

    if crash_log_path is not None:
        _log_line(f"Crash log path: {crash_log_path}")
        print(f"[ComeCut] Crash debug log: {crash_log_path}")

    apply_theme(app)
    home = HomeWindow()
    windows: list[object] = [home]

    def _show_home(closed_editor: object | None = None) -> None:
        if closed_editor is not None:
            try:
                windows.remove(closed_editor)
            except ValueError:
                pass
        home.refresh_projects()
        home.show()
        home.raise_()
        home.activateWindow()

    def open_editor(project_id: str) -> None:
        editor = MainWindow()
        try:
            editor.load_project_from_store(project_id)
        except Exception:
            _log_line(f"Failed to open project id={project_id}")
            _log_line(traceback.format_exc())
            return
        windows.append(editor)
        home.hide()
        editor.closed.connect(lambda e=editor: _show_home(e))
        editor.show()

    home.new_project_requested.connect(open_editor)
    home.open_project_requested.connect(open_editor)
    home.show()
    return app.exec()


__all__ = ["run"]
