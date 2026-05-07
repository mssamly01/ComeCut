"""Lightweight smoke tests for the GUI module surface.

We don't instantiate Qt widgets here — tests that need a ``QApplication``
are heavy and the existing test suite avoids them. These tests just make
sure the redesigned GUI tree imports cleanly when PySide6 is available
(the ``[gui]`` extra) and that public exports stay stable so other
code can import them without surprise.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def test_main_window_imports() -> None:
    from comecut_py.gui import app, main_window, theme

    assert callable(app.run)
    assert callable(theme.apply_theme)
    assert main_window.MainWindow is not None
    assert hasattr(main_window.MainWindow, "_auto_duck_music_under_voice")
    assert hasattr(main_window.MainWindow, "_add_beat_marker_at_playhead")
    assert hasattr(main_window.MainWindow, "_remove_beat_marker_near_playhead")
    assert hasattr(main_window.MainWindow, "_save_project_as_template")
    assert hasattr(main_window.MainWindow, "_new_project_from_template")
    assert hasattr(main_window.MainWindow, "_export_still_frame")


def test_widget_modules_import() -> None:
    from comecut_py.gui.widgets import (
        inspector,
        left_rail,
        media_library,
        preview,
        text_panel,
        timeline,
        topbar,
        voice_match_panel,
    )

    # Public classes referenced by main_window must exist.
    assert inspector.InspectorPanel is not None
    assert left_rail.LeftRail is not None
    assert media_library.MediaLibraryPanel is not None
    assert preview.PreviewPanel is not None
    assert hasattr(preview.PreviewPanel, "set_timeline_time_display")
    assert hasattr(preview.PreviewPanel, "clear_timeline_time_display")
    assert hasattr(preview.PreviewPanel, "clear_video_preview")
    assert hasattr(preview.PreviewPanel, "main_player_is_playing")
    assert text_panel.TextPanel is not None
    assert timeline.TimelinePanel is not None
    assert topbar.TopBar is not None
    assert voice_match_panel.VoiceMatchPanel is not None

    # Tab keys are part of the public API.
    assert {left_rail.TAB_MEDIA, left_rail.TAB_TEXT, left_rail.TAB_VOICE_MATCH} == {
        "media",
        "text",
        "voice_match",
    }


def test_dialog_modules_import() -> None:
    from comecut_py.gui.dialogs import export_dialog, plugin_manager

    assert export_dialog.ExportDialog is not None
    assert export_dialog.ExportOptions is not None
    assert plugin_manager.PluginManagerDialog is not None
    assert plugin_manager.SECTIONS  # non-empty section map


def test_theme_palette_constants() -> None:
    from comecut_py.gui import theme

    # Core palette tokens used by widgets/dialogs are all 7-char hex.
    for token in (theme.BG, theme.PANEL, theme.PANEL_ALT, theme.BORDER,
                  theme.TEXT, theme.TEXT_MUTED, theme.ACCENT, theme.ACCENT_HOVER,
                  theme.DANGER):
        assert isinstance(token, str)
        assert token.startswith("#") and len(token) == 7
