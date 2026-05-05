from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from comecut_py.core.project import Clip
from comecut_py.gui.widgets.inspector_audio import AudioPropertiesBox, FADE_MAX_SECONDS
from comecut_py.gui.widgets.inspector_video import db_to_linear, linear_to_db


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def clip() -> Clip:
    return Clip(
        source="C:/media/audio.wav",
        in_point=0.0,
        out_point=10.0,
        start=0.0,
    )


def test_set_clip_populates_speed_and_volume(qapp, clip):
    box = AudioPropertiesBox()
    clip.speed = 1.5
    clip.volume = 0.5
    box.set_clip(clip, track_kind="audio")
    assert box._speed_spin.value() == pytest.approx(1.5)
    assert box._speed_slider.value() == 150
    assert box._volume_spin.value() == pytest.approx(linear_to_db(0.5), abs=0.2)


def test_set_clip_populates_fade_in_out(qapp, clip):
    box = AudioPropertiesBox()
    clip.audio_effects.fade_in = 1.5
    clip.audio_effects.fade_out = 2.0
    box.set_clip(clip, track_kind="audio")
    assert box._fade_in_spin.value() == pytest.approx(1.5)
    assert box._fade_in_slider.value() == 15
    assert box._fade_out_spin.value() == pytest.approx(2.0)
    assert box._fade_out_slider.value() == 20


def test_speed_slider_updates_clip_and_spin(qapp, clip):
    box = AudioPropertiesBox()
    box.set_clip(clip, track_kind="audio")
    box._speed_slider.setValue(200)
    assert clip.speed == pytest.approx(2.0)
    assert box._speed_spin.value() == pytest.approx(2.0)


def test_speed_spin_updates_clip_and_slider(qapp, clip):
    box = AudioPropertiesBox()
    box.set_clip(clip, track_kind="audio")
    box._speed_spin.setValue(0.5)
    assert clip.speed == pytest.approx(0.5)
    assert box._speed_slider.value() == 50


def test_volume_slider_db_to_linear_round_trip(qapp, clip):
    box = AudioPropertiesBox()
    box.set_clip(clip, track_kind="audio")
    box._volume_slider.setValue(-6)
    assert clip.volume == pytest.approx(db_to_linear(-6.0), abs=1e-3)


def test_volume_clamps_above_plus_20_db(qapp, clip):
    box = AudioPropertiesBox()
    box.set_clip(clip, track_kind="audio")
    box._volume_spin.setValue(50.0)
    assert box._volume_spin.value() == pytest.approx(20.0)
    assert box._volume_slider.value() == 20
    assert clip.volume == pytest.approx(db_to_linear(20.0))


def test_fade_in_slider_writes_to_audio_effects(qapp, clip):
    box = AudioPropertiesBox()
    box.set_clip(clip, track_kind="audio")
    box._fade_in_slider.setValue(30)
    assert clip.audio_effects.fade_in == pytest.approx(3.0)
    assert box._fade_in_spin.value() == pytest.approx(3.0)


def test_fade_out_spin_writes_to_audio_effects(qapp, clip):
    box = AudioPropertiesBox()
    box.set_clip(clip, track_kind="audio")
    box._fade_out_spin.setValue(2.5)
    assert clip.audio_effects.fade_out == pytest.approx(2.5)
    assert box._fade_out_slider.value() == 25


def test_fade_in_clamps_to_max(qapp, clip):
    box = AudioPropertiesBox()
    box.set_clip(clip, track_kind="audio")
    box._fade_in_spin.setValue(99.0)
    assert box._fade_in_spin.value() == pytest.approx(FADE_MAX_SECONDS)
    assert clip.audio_effects.fade_in == pytest.approx(FADE_MAX_SECONDS)


def test_set_clip_none_disables_controls(qapp):
    box = AudioPropertiesBox()
    box.set_clip(None)
    assert box._speed_slider.isEnabled() is False
    assert box._fade_in_spin.isEnabled() is False
    assert box._fade_out_slider.isEnabled() is False


def test_clip_changed_signal_fires_on_user_input(qapp, clip):
    box = AudioPropertiesBox()
    fired: list[str] = []
    box.clip_changed.connect(lambda source: fired.append(source))
    box.set_clip(clip, track_kind="audio")
    box._fade_in_spin.setValue(1.0)
    assert len(fired) == 1


def test_set_clip_during_binding_does_not_fire_changed(qapp, clip):
    box = AudioPropertiesBox()
    fired: list[str] = []
    box.clip_changed.connect(lambda source: fired.append(source))
    clip.audio_effects.fade_in = 2.0
    box.set_clip(clip, track_kind="audio")
    assert fired == []
