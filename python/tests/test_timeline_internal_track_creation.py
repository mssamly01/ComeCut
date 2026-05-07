import pytest

from comecut_py.core.project import Clip, Project, Track


def _media_clip(source: str, start: float = 0.0, duration: float = 1.0) -> Clip:
    return Clip(source=source, start=start, in_point=0.0, out_point=duration)


def _text_clip(start: float = 0.0, duration: float = 1.0, text: str = "line") -> Clip:
    return Clip(
        clip_type="text",
        source="",
        start=start,
        in_point=0.0,
        out_point=duration,
        text_main=text,
    )


@pytest.fixture()
def timeline_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_internal_audio_drag_can_create_new_track(timeline_app) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    clip_a = _media_clip("a.mp3", duration=2.0)
    clip_b = _media_clip("b.mp3", start=3.0, duration=2.0)
    audio = Track(kind="audio", name="Audio", clips=[clip_a, clip_b])
    project = Project(
        tracks=[
            Track(kind="video", name="Main"),
            audio,
        ]
    )
    panel = TimelinePanel(project)
    panel.resize(1000, 500)

    source_idx = project.tracks.index(audio)
    _top, bottom = panel._track_scene_bounds(source_idx)
    panel.handle_clip_release_by_clip(clip_a, bottom + 20.0, clip_a.start)

    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    assert len(audio_tracks) == 2
    assert any(clip_a in track.clips for track in audio_tracks)
    assert any(clip_b in track.clips for track in audio_tracks)
    assert not any(len(track.clips) > 1 and clip_a in track.clips for track in audio_tracks)
    panel.deleteLater()


def test_internal_text_drag_can_create_new_track(timeline_app) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    clip_a = _text_clip(0.0, 1.0, "first")
    clip_b = _text_clip(2.0, 1.0, "second")
    text = Track(kind="text", name="Text", clips=[clip_a, clip_b])
    project = Project(
        tracks=[
            text,
            Track(kind="video", name="Main"),
        ]
    )
    panel = TimelinePanel(project)
    panel.resize(1000, 500)

    source_idx = project.tracks.index(text)
    top, _bottom = panel._track_scene_bounds(source_idx)
    panel.handle_clip_release_by_clip(clip_a, top - 20.0, clip_a.start)

    text_tracks = [track for track in project.tracks if track.kind == "text"]
    assert len(text_tracks) == 2
    assert any(clip_a in track.clips for track in text_tracks)
    assert any(clip_b in track.clips for track in text_tracks)
    assert not any(len(track.clips) > 1 and clip_a in track.clips for track in text_tracks)
    panel.deleteLater()


def test_internal_drag_replaces_single_clip_track_when_track_limit_reached(
    timeline_app,
) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    clip_a = _media_clip("a.mp3", duration=1.0)
    clip_b = _media_clip("b.mp3", start=2.0, duration=1.0)
    audio_a = Track(kind="audio", name="Audio 1", clips=[clip_a])
    audio_b = Track(kind="audio", name="Audio 2", clips=[clip_b])
    project = Project(
        tracks=[
            Track(kind="video", name="Main"),
            audio_a,
            audio_b,
        ]
    )
    panel = TimelinePanel(project)
    panel.resize(1000, 500)

    source_idx = project.tracks.index(audio_a)
    top, _bottom = panel._track_scene_bounds(source_idx)
    panel.handle_clip_release_by_clip(clip_a, top - 20.0, clip_a.start)

    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    assert len(audio_tracks) == 2
    assert any(clip_a in track.clips for track in audio_tracks)
    assert any(clip_b in track.clips for track in audio_tracks)
    assert all(track.clips for track in audio_tracks)
    panel.deleteLater()


def test_internal_main_video_drag_creates_overlay_track_without_removing_main(
    timeline_app,
) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    clip = _media_clip("main.mp4", duration=2.0)
    main = Track(kind="video", name="Main", clips=[clip])
    project = Project(tracks=[main])
    panel = TimelinePanel(project)
    panel.resize(1000, 500)

    main_idx = project.tracks.index(main)
    top, _bottom = panel._track_scene_bounds(main_idx)
    panel.handle_clip_release_by_clip(clip, top - 20.0, clip.start)

    main_tracks = [
        track
        for track in project.tracks
        if track.kind == "video" and track.name.strip().lower() == "main"
    ]
    overlay_tracks = [
        track
        for track in project.tracks
        if track.kind == "video" and track.name.strip().lower() != "main"
    ]
    assert len(main_tracks) == 1
    assert main_tracks[0].clips == []
    assert len(overlay_tracks) == 1
    assert overlay_tracks[0].clips == [clip]
    panel.deleteLater()


def test_internal_video_track_limit_excludes_main_track(timeline_app) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    clip_a = _media_clip("a.mp4", duration=1.0)
    clip_b = _media_clip("b.mp4", start=2.0, duration=1.0)
    overlay_a = Track(kind="video", name="Video 1", clips=[clip_a])
    overlay_b = Track(kind="video", name="Video 2", clips=[clip_b])
    main = Track(kind="video", name="Main")
    project = Project(tracks=[overlay_a, overlay_b, main])
    panel = TimelinePanel(project)
    panel.resize(1000, 500)

    source_idx = project.tracks.index(overlay_a)
    top, _bottom = panel._track_scene_bounds(source_idx)
    panel.handle_clip_release_by_clip(clip_a, top - 20.0, clip_a.start)

    main_tracks = [
        track
        for track in project.tracks
        if track.kind == "video" and track.name.strip().lower() == "main"
    ]
    overlay_tracks = [
        track
        for track in project.tracks
        if track.kind == "video" and track.name.strip().lower() != "main"
    ]
    assert len(main_tracks) == 1
    assert len(overlay_tracks) == 2
    assert any(clip_a in track.clips for track in overlay_tracks)
    assert any(clip_b in track.clips for track in overlay_tracks)
    assert all(track.clips for track in overlay_tracks)
    panel.deleteLater()
