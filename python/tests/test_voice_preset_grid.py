"""Smoke tests for VoicePresetGrid widget."""
from __future__ import annotations

import pytest

# Skip if no display (CI) unless QT_QPA_PLATFORM=offscreen is set
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from comecut_py.core.voice_presets import PRESETS
from comecut_py.gui.widgets.voice_preset_grid import VoicePresetGrid


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def test_grid_creates_one_card_per_preset(qapp):
    grid = VoicePresetGrid()
    assert len(grid._cards) == len(PRESETS)
    for p in PRESETS:
        assert p.id in grid._cards


def test_set_active_highlights_one_card(qapp):
    grid = VoicePresetGrid()
    grid.set_active("robot")
    for pid, card in grid._cards.items():
        assert card.isChecked() == (pid == "robot")


def test_set_active_empty_string_clears_all(qapp):
    grid = VoicePresetGrid()
    grid.set_active("robot")
    grid.set_active("")
    assert all(not c.isChecked() for c in grid._cards.values())


def test_card_click_emits_preset_clicked_signal(qapp):
    grid = VoicePresetGrid()
    received: list[str] = []
    grid.preset_clicked.connect(received.append)
    grid._cards["helium"].click()
    assert received == ["helium"]


def test_card_click_updates_active_card(qapp):
    grid = VoicePresetGrid()
    grid._cards["lofi"].click()
    assert grid._cards["lofi"].isChecked()
    assert not grid._cards["robot"].isChecked()


def test_set_active_does_not_emit_signal(qapp):
    grid = VoicePresetGrid()
    received: list[str] = []
    grid.preset_clicked.connect(received.append)
    grid.set_active("monster")
    assert received == []
