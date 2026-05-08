from pathlib import Path

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


def test_internal_audio_drag_above_main_still_creates_track_below_main(
    timeline_app,
) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    clip_a = _media_clip("a.mp3", duration=2.0)
    clip_b = _media_clip("b.mp3", start=3.0, duration=2.0)
    audio = Track(kind="audio", name="Audio", clips=[clip_a, clip_b])
    main = Track(kind="video", name="Main")
    project = Project(tracks=[main, audio])
    panel = TimelinePanel(project)
    panel.resize(1000, 500)

    main_idx = project.tracks.index(main)
    top, _bottom = panel._track_scene_bounds(main_idx)
    panel.handle_clip_release_by_clip(clip_a, top - 20.0, clip_a.start)

    main_idx = project.tracks.index(main)
    audio_indices = [idx for idx, track in enumerate(project.tracks) if track.kind == "audio"]
    assert audio_indices
    assert all(idx > main_idx for idx in audio_indices)
    assert any(clip_a in project.tracks[idx].clips for idx in audio_indices)
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


def test_internal_text_drag_below_main_still_creates_track_above_main(
    timeline_app,
) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    clip_a = _text_clip(0.0, 1.0, "first")
    clip_b = _text_clip(2.0, 1.0, "second")
    text = Track(kind="text", name="Text", clips=[clip_a, clip_b])
    main = Track(kind="video", name="Main")
    audio = Track(kind="audio", name="Audio")
    project = Project(tracks=[text, main, audio])
    panel = TimelinePanel(project)
    panel.resize(1000, 500)

    audio_idx = project.tracks.index(audio)
    _top, bottom = panel._track_scene_bounds(audio_idx)
    panel.handle_clip_release_by_clip(clip_a, bottom + 20.0, clip_a.start)

    main_idx = project.tracks.index(main)
    text_indices = [idx for idx, track in enumerate(project.tracks) if track.kind == "text"]
    assert text_indices
    assert all(idx < main_idx for idx in text_indices)
    assert any(clip_a in project.tracks[idx].clips for idx in text_indices)
    panel.deleteLater()


def test_internal_video_drag_below_main_creates_overlay_above_main(
    timeline_app,
) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    clip = _media_clip("main.mp4", duration=2.0)
    main = Track(kind="video", name="Main", clips=[clip])
    audio = Track(kind="audio", name="Audio")
    project = Project(tracks=[main, audio])
    panel = TimelinePanel(project)
    panel.resize(1000, 500)

    audio_idx = project.tracks.index(audio)
    _top, bottom = panel._track_scene_bounds(audio_idx)
    panel.handle_clip_release_by_clip(clip, bottom + 20.0, clip.start)

    main_idx = project.tracks.index(main)
    overlay_indices = [
        idx
        for idx, track in enumerate(project.tracks)
        if track.kind == "video" and track.name.strip().lower() != "main"
    ]
    assert overlay_indices
    assert all(idx < main_idx for idx in overlay_indices)
    assert any(clip in project.tracks[idx].clips for idx in overlay_indices)
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


def test_track_layout_keeps_edge_padding_and_expands_scene_for_scroll(
    timeline_app,
) -> None:
    from comecut_py.gui.widgets.timeline import RULER_HEIGHT, TRACK_EDGE_PADDING, TimelinePanel

    tracks = [Track(kind="video", name="Main")]
    tracks.extend(
        Track(kind="audio", name=f"Audio {idx}", clips=[_media_clip(f"{idx}.mp3")])
        for idx in range(10)
    )
    project = Project(tracks=tracks)
    panel = TimelinePanel(project)
    panel.resize(900, 260)
    panel.refresh()

    _tracks, lane_tops, lane_heights, _main_idx = panel._track_layout_data(project.tracks)

    assert lane_tops[0] >= RULER_HEIGHT + TRACK_EDGE_PADDING - 0.5
    assert panel._scene.sceneRect().height() >= lane_tops[-1] + lane_heights[-1] + TRACK_EDGE_PADDING - 0.5
    assert panel._scene.sceneRect().height() > panel._timeline_viewport_height()
    panel.deleteLater()


def test_prewarm_long_video_queues_full_waveform_left_to_right(
    timeline_app,
    tmp_path,
    monkeypatch,
) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    source = tmp_path / "long.mp4"
    source.write_bytes(b"video")
    clip = _media_clip(str(source), duration=7200.0)
    project = Project(tracks=[Track(kind="video", name="Main", clips=[clip])])
    panel = TimelinePanel(project)
    panel.resize(1000, 500)
    monkeypatch.setattr(panel, "_visible_timeline_seconds", lambda: (0.0, 120.0))

    full_waveform_requests: list[object] = []
    range_waveform_requests: list[tuple[float, float, int]] = []
    chunk_requests: list[int] = []

    monkeypatch.setattr(
        panel,
        "_submit_waveform_extract",
        lambda key, source, num_peaks: full_waveform_requests.append(key),
    )

    def fake_submit_range(key, source, *, start, duration, num_peaks):
        del key, source
        range_waveform_requests.append((float(start), float(duration), int(num_peaks)))

    monkeypatch.setattr(panel, "_submit_waveform_range_extract", fake_submit_range)
    monkeypatch.setattr(
        panel,
        "_submit_filmstrip_chunk_extract",
        lambda key, source, chunk_idx: chunk_requests.append(int(chunk_idx)),
    )

    panel.prewarm_track_clips([clip])

    assert full_waveform_requests == []
    assert range_waveform_requests == [(0.0, 300.0, 256)]
    assert chunk_requests == [0, 1]
    wave_tasks = [
        task
        for task in panel._progressive_media_cache_tasks
        if task and task[0] == "wave_range"
    ]
    assert len(wave_tasks) == 48
    assert [(task[3], task[4], task[5]) for task in wave_tasks[:4]] == [
        (0.0, 300.0, 256),
        (0.0, 300.0, 2048),
        (300.0, 300.0, 256),
        (300.0, 300.0, 2048),
    ]
    assert (wave_tasks[-1][3], wave_tasks[-1][4], wave_tasks[-1][5]) == (
        6900.0,
        300.0,
        2048,
    )
    panel.deleteLater()


def test_prewarm_audio_clips_queues_waveforms_by_timeline_start(
    timeline_app,
    tmp_path,
    monkeypatch,
) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    early_source = tmp_path / "early.mp3"
    late_source = tmp_path / "late.mp3"
    early_source.write_bytes(b"audio")
    late_source.write_bytes(b"audio")
    early = _media_clip(str(early_source), start=0.5, duration=2.0)
    late = _media_clip(str(late_source), start=10.0, duration=2.0)
    project = Project(tracks=[Track(kind="audio", name="Voice", clips=[late, early])])
    panel = TimelinePanel(project)

    monkeypatch.setattr(panel, "_submit_waveform_extract", lambda *args, **kwargs: None)
    monkeypatch.setattr(panel, "_submit_waveform_range_extract", lambda *args, **kwargs: None)

    panel.prewarm_track_clips([late, early])

    wave_tasks = [
        task
        for task in panel._progressive_media_cache_tasks
        if task and task[0] == "wave"
    ]
    assert [(Path(task[2]).name, task[3]) for task in wave_tasks] == [
        ("early.mp3", 256),
        ("early.mp3", 2048),
        ("late.mp3", 256),
        ("late.mp3", 2048),
    ]
    panel.deleteLater()


def test_short_segment_of_long_video_uses_range_waveform(
    timeline_app,
    tmp_path,
    monkeypatch,
) -> None:
    from comecut_py.gui.widgets.timeline import TimelinePanel

    source = tmp_path / "long.mp4"
    source.write_bytes(b"video")
    visible_clip = Clip(source=str(source), start=0.0, in_point=0.0, out_point=2.0)
    later_clip = Clip(source=str(source), start=10.0, in_point=3600.0, out_point=3602.0)
    project = Project(tracks=[Track(kind="video", name="Main", clips=[visible_clip, later_clip])])
    panel = TimelinePanel(project)
    panel.resize(1000, 500)
    monkeypatch.setattr(panel, "_visible_timeline_seconds", lambda: (0.0, 2.0))

    full_waveform_requests: list[object] = []
    range_waveform_requests: list[tuple[float, float, int]] = []
    monkeypatch.setattr(
        panel,
        "_submit_waveform_extract",
        lambda key, source, num_peaks: full_waveform_requests.append(key),
    )

    def fake_submit_range(key, source, *, start, duration, num_peaks):
        del key, source
        range_waveform_requests.append((float(start), float(duration), int(num_peaks)))

    monkeypatch.setattr(panel, "_submit_waveform_range_extract", fake_submit_range)

    peaks = panel.request_visible_waveform_peaks_async(
        visible_clip,
        num_peaks=256,
        media_kind="video",
    )

    assert peaks is None
    assert full_waveform_requests == []
    assert range_waveform_requests == [(0.0, 2.0, 256)]
    panel.deleteLater()
