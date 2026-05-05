import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QRect

from comecut_py.gui.widgets.preview import compute_preview_rects


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
    assert video_rect.center().y() > project_rect.center().y()


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
    assert video_rect.width() == 1200
    assert video_rect.height() == 450
