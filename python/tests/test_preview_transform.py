import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QRect

from comecut_py.engine.audio_levels import AudioLevelStats
from comecut_py.gui.widgets.preview import (
    compute_preview_rects,
    format_audio_meter_summary,
    preview_safe_area_rects,
)


def test_preview_rects_without_transform_fill_by_image_aspect() -> None:
    project_rect, video_rect = compute_preview_rects(
        QRect(0, 0, 1000, 800),
        image_size=(1920, 1080),
        canvas_size=(1920, 1080),
        transform_enabled=False,
        clip_scale=None,
        clip_scale_x=None,
        clip_scale_y=None,
        pos_x=None,
        pos_y=None,
    )

    assert project_rect == video_rect
    assert video_rect.width() == 1000
    assert video_rect.height() == 562


def test_preview_rects_scale_down_from_canvas_center() -> None:
    project_rect, video_rect = compute_preview_rects(
        QRect(0, 0, 1000, 800),
        image_size=(1920, 1080),
        canvas_size=(1920, 1080),
        transform_enabled=True,
        clip_scale=0.5,
        clip_scale_x=None,
        clip_scale_y=None,
        pos_x=None,
        pos_y=None,
    )

    assert project_rect.width() == 1000
    assert project_rect.height() == 562
    assert video_rect.width() == 500
    assert video_rect.height() == 281
    assert abs(video_rect.center().x() - project_rect.center().x()) <= 1
    assert abs(video_rect.center().y() - project_rect.center().y()) <= 1


def test_preview_rects_position_is_mapped_in_canvas_space() -> None:
    project_rect, video_rect = compute_preview_rects(
        QRect(0, 0, 1000, 800),
        image_size=(1920, 1080),
        canvas_size=(1920, 1080),
        transform_enabled=True,
        clip_scale=0.5,
        clip_scale_x=None,
        clip_scale_y=None,
        pos_x=1440,
        pos_y=810,
    )

    assert video_rect.right() <= project_rect.right()
    assert video_rect.bottom() <= project_rect.bottom()
    assert video_rect.center().x() > project_rect.center().x()
    # ComeCut stores positive canvas Y as upward motion from center.
    assert video_rect.center().y() < project_rect.center().y()


def test_preview_rects_non_uniform_scale_uses_independent_axes() -> None:
    project_rect, video_rect = compute_preview_rects(
        QRect(0, 0, 1000, 800),
        image_size=(1920, 1080),
        canvas_size=(1920, 1080),
        transform_enabled=True,
        clip_scale=None,
        clip_scale_x=1.2,
        clip_scale_y=0.8,
        pos_x=None,
        pos_y=None,
    )

    assert project_rect.width() == 1000
    assert project_rect.height() == 562
    assert abs(video_rect.width() - 1200) <= 1
    assert video_rect.height() == 450


def test_preview_safe_area_rects_use_canvas_insets() -> None:
    action_safe, title_safe = preview_safe_area_rects(QRect(100, 50, 1000, 500))

    assert action_safe.left() == 150
    assert action_safe.top() == 75
    assert action_safe.width() == 900
    assert action_safe.height() == 450
    assert title_safe.left() == 200
    assert title_safe.top() == 100
    assert title_safe.width() == 800
    assert title_safe.height() == 400


def test_format_audio_meter_summary_reports_peak_and_rms() -> None:
    stats = AudioLevelStats(
        peak=0.5,
        peak_dbfs=-6.0206,
        rms=0.25,
        rms_dbfs=-12.0412,
        clipped_samples=0,
        total_samples=100,
    )

    short, detail, warning = format_audio_meter_summary("Main", stats)

    assert short == "Main: Pk -6.0 dBFS"
    assert "RMS: -12.0 dBFS" in detail
    assert warning is False


def test_format_audio_meter_summary_warns_on_clipping() -> None:
    stats = AudioLevelStats(
        peak=1.0,
        peak_dbfs=0.0,
        rms=0.8,
        rms_dbfs=-1.9,
        clipped_samples=2,
        total_samples=10,
    )

    short, detail, warning = format_audio_meter_summary("Timeline audio", stats)

    assert short == "Timeline audio: Pk 0.0 dBFS"
    assert "Warning:" in detail
    assert warning is True
