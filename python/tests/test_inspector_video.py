from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from comecut_py.core.project import Clip, Project, Track
from comecut_py.gui.widgets.inspector import InspectorPanel
from comecut_py.gui.widgets.inspector_video import (
    VideoPropertiesBox,
    clip_visible_duration,
    db_to_linear,
    linear_to_db,
    percent_to_scale,
    scale_to_percent,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _video_clip() -> Clip:
    return Clip(
        source="C:/media/video.mp4",
        in_point=1.0,
        out_point=5.0,
        start=2.0,
        speed=1.0,
        volume=1.0,
    )


def _audio_clip() -> Clip:
    return Clip(
        source="C:/media/audio.wav",
        in_point=0.0,
        out_point=4.0,
        start=0.0,
        speed=1.0,
        volume=1.0,
    )


def _text_clip() -> Clip:
    return Clip(
        clip_type="text",
        source="",
        in_point=0.0,
        out_point=2.0,
        start=0.0,
        text_main="Hello",
    )


def test_db_helpers():
    assert linear_to_db(1.0) == pytest.approx(0.0)
    assert linear_to_db(0.0) == -60.0
    assert db_to_linear(0.0) == pytest.approx(1.0)
    assert db_to_linear(-12.0) == pytest.approx(10.0 ** (-12.0 / 20.0))


def test_scale_helpers():
    assert scale_to_percent(None) == 100
    assert scale_to_percent(0.5) == 50
    assert scale_to_percent(3.0) == 300
    assert percent_to_scale(100) is None
    assert percent_to_scale(50) == pytest.approx(0.5)
    assert percent_to_scale(500) == pytest.approx(5.0)
    assert percent_to_scale(0) == pytest.approx(0.01)


def test_clip_visible_duration():
    clip = _video_clip()
    clip.speed = 2.0
    assert clip_visible_duration(clip) == pytest.approx(2.0)


def test_video_properties_box_updates_clip(qapp):
    clip = _video_clip()
    box = VideoPropertiesBox()
    box.set_clip(clip, track_kind="video")

    box._scale_slider.setValue(50)
    assert clip.scale == pytest.approx(0.5)

    box._scale_slider.setValue(100)
    assert clip.scale is None

    box._scale_slider.setValue(250)
    assert clip.scale == pytest.approx(2.5)
    assert box._scale_chip.value() == 250

    box._scale_chip.setValue(125)
    assert box._scale_slider.value() == 125
    assert clip.scale == pytest.approx(1.25)

    box._scale_inc.click()
    assert box._scale_slider.value() == 126
    box._scale_dec.click()
    assert box._scale_slider.value() == 125

    box._uniform_cb.setChecked(False)
    assert clip.scale is None
    assert clip.scale_x == pytest.approx(1.25)
    assert clip.scale_y == pytest.approx(1.25)

    box._scale_x_slider.setValue(130)
    assert clip.scale_x == pytest.approx(1.3)
    assert clip.scale_y == pytest.approx(1.25)
    box._scale_y_slider.setValue(70)
    assert clip.scale_x == pytest.approx(1.3)
    assert clip.scale_y == pytest.approx(0.7)

    box._uniform_cb.setChecked(True)
    assert clip.scale == pytest.approx(1.3)
    assert clip.scale_x is None
    assert clip.scale_y is None

    box._x_spin.setValue(120)
    box._y_spin.setValue(-40)
    assert clip.pos_x == 120
    assert clip.pos_y == -40

    box._rotate_spin.setValue(10)
    assert clip.effects.rotate == pytest.approx(10.0)
    box._rotate_inc.click()
    assert box._rotate_spin.value() == 11
    box._rotate_dec.click()
    assert box._rotate_spin.value() == 10

    box._speed_slider.setValue(250)
    assert clip.speed == pytest.approx(2.5)
    box._speed_inc.click()
    assert box._speed_slider.value() == 260
    box._speed_dec.click()
    assert box._speed_slider.value() == 250

    box._volume_slider.setValue(-12)
    assert clip.volume == pytest.approx(db_to_linear(-12.0))

    box._pitch_spin.setValue(5.0)
    assert clip.audio_effects.pitch_semitones == pytest.approx(5.0)


def test_inspector_routes_video_track_to_video_box(qapp):
    clip = _video_clip()
    panel = InspectorPanel()
    panel.set_project(Project(tracks=[Track(kind="video", clips=[clip])]))
    panel.set_clip(clip, track_kind="video")

    assert panel._info.current_title() == "VIDEO PROPERTIES"
    assert panel._info._clip_box_video.isHidden() is False
    assert panel._info._clip_box_legacy.isHidden() is True


def test_inspector_routes_audio_track_to_audio_box(qapp):
    clip = _audio_clip()
    panel = InspectorPanel()
    panel.set_project(Project(tracks=[Track(kind="audio", clips=[clip])]))
    panel.set_clip(clip, track_kind="audio")

    assert panel._info.current_title() == "AUDIO PROPERTIES"
    assert panel._info._clip_box_video.isHidden() is True
    assert panel._info._clip_box_audio.isHidden() is False
    assert panel._info._clip_box_legacy.isHidden() is True


def test_inspector_infers_audio_track_kind_from_project(qapp):
    clip = _audio_clip()
    panel = InspectorPanel()
    panel.set_project(Project(tracks=[Track(kind="audio", clips=[clip])]))
    panel.set_clip(clip)

    assert panel._info.current_title() == "AUDIO PROPERTIES"
    assert panel._info._clip_box_audio.isHidden() is False
    assert panel._info._clip_box_legacy.isHidden() is True


def test_inspector_keeps_text_panel_flow(qapp):
    clip = _text_clip()
    panel = InspectorPanel()
    panel.set_project(Project(tracks=[Track(kind="text", clips=[clip])]))
    panel.set_clip(clip, track_kind="text")

    assert panel._info.current_title() == "TEXT PROPERTIES"
    assert panel._info._text_box.isHidden() is False


def test_inspector_none_selection_shows_project_properties(qapp):
    panel = InspectorPanel()
    panel.set_project(Project(name="Demo"))
    panel.set_clip(None)

    assert panel._info.current_title() == "PROJECT PROPERTIES"
    assert panel._info._meta_container.isHidden() is False
    assert panel._info._clip_box_video.isHidden() is True
    assert panel._info._clip_box_audio.isHidden() is True
    assert panel._info._clip_box_legacy.isHidden() is True
