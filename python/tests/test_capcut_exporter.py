from __future__ import annotations

import json
from pathlib import Path

from comecut_py.core import export_to_capcut, import_capcut_draft, is_capcut_format
from comecut_py.core.project import Clip, ImageOverlay, Project, Track


def _sample_video_clip() -> Clip:
    return Clip(
        source="C:/media/video.mp4",
        in_point=1.0,
        out_point=5.0,
        start=2.5,
        speed=1.25,
        volume=0.75,
    )


def _sample_audio_clip() -> Clip:
    return Clip(
        source="C:/media/audio.wav",
        in_point=0.5,
        out_point=3.0,
        start=1.0,
        speed=0.5,
        volume=0.6,
    )


def _sample_text_clip() -> Clip:
    return Clip(
        clip_type="text",
        source="",
        in_point=0.0,
        out_point=3.0,
        start=4.0,
        text_main="Hello",
        text_color="#ffffff",
        text_font_family="Arial",
        text_font_size=30,
        text_stroke_color="#000000",
        text_stroke_width=2,
    )


def test_exported_file_is_capcut_format(tmp_path: Path):
    project = Project(name="Exported", tracks=[Track(kind="video", clips=[_sample_video_clip()])])

    out = tmp_path / "draft_content.json"
    dest = export_to_capcut(project, out)
    data = json.loads(dest.read_text(encoding="utf-8"))

    assert dest == out
    assert data["version"] == 360000
    assert data["new_version"] == "153.0.0"
    assert is_capcut_format(data) is True


def test_exported_skeleton_has_all_54_material_categories(tmp_path: Path):
    project = Project(name="Materials", tracks=[Track(kind="video", clips=[_sample_video_clip()])])

    out = tmp_path / "draft_content.json"
    data = json.loads(export_to_capcut(project, out).read_text(encoding="utf-8"))

    assert len(data["materials"]) == 54
    assert "videos" in data["materials"]
    assert "audios" in data["materials"]
    assert "texts" in data["materials"]
    assert "speeds" in data["materials"]
    assert "material_animations" in data["materials"]


def test_exported_video_segment_has_6_extra_material_refs(tmp_path: Path):
    project = Project(name="Video", tracks=[Track(kind="video", clips=[_sample_video_clip()])])

    out = tmp_path / "draft_content.json"
    data = json.loads(export_to_capcut(project, out).read_text(encoding="utf-8"))

    segment = data["tracks"][0]["segments"][0]
    assert len(segment["extra_material_refs"]) == 6


def test_exported_audio_segment_has_5_extra_material_refs(tmp_path: Path):
    project = Project(name="Audio", tracks=[Track(kind="audio", clips=[_sample_audio_clip()])])

    out = tmp_path / "draft_content.json"
    data = json.loads(export_to_capcut(project, out).read_text(encoding="utf-8"))

    segment = data["tracks"][0]["segments"][0]
    assert len(segment["extra_material_refs"]) == 5


def test_exported_audio_segment_with_fade_has_fade_pool_and_extra_ref(tmp_path: Path):
    clip = _sample_audio_clip()
    clip.audio_effects.fade_in = 1.5
    clip.audio_effects.fade_out = 2.0
    project = Project(name="AudioFade", tracks=[Track(kind="audio", clips=[clip])])

    out = tmp_path / "draft_content.json"
    data = json.loads(export_to_capcut(project, out).read_text(encoding="utf-8"))

    segment = data["tracks"][0]["segments"][0]
    assert len(segment["extra_material_refs"]) == 6

    pool = data["materials"]["audio_fades"]
    assert len(pool) == 1
    assert pool[0]["fade_in_duration"] == 1_500_000
    assert pool[0]["fade_out_duration"] == 2_000_000
    assert pool[0]["id"] in segment["extra_material_refs"]


def test_exported_text_segment_has_1_extra_material_ref(tmp_path: Path):
    project = Project(name="Text", tracks=[Track(kind="text", clips=[_sample_text_clip()])])

    out = tmp_path / "draft_content.json"
    data = json.loads(export_to_capcut(project, out).read_text(encoding="utf-8"))

    segment = data["tracks"][0]["segments"][0]
    assert len(segment["extra_material_refs"]) == 1


def test_export_then_import_roundtrip_preserves_basic_fields(tmp_path: Path):
    project = Project(
        name="Roundtrip",
        width=1280,
        height=720,
        fps=30.0,
        tracks=[
            Track(kind="video", clips=[_sample_video_clip()]),
            Track(kind="text", clips=[_sample_text_clip()]),
        ],
    )

    out = tmp_path / "draft_content.json"
    imported = import_capcut_draft(export_to_capcut(project, out))

    assert len(imported.tracks) == 2
    assert imported.width == 1280
    assert imported.height == 720
    assert imported.fps == 30.0

    video_clip = imported.tracks[0].clips[0]
    assert video_clip.start == 2.5
    assert video_clip.in_point == 1.0
    assert video_clip.out_point == 5.0
    assert video_clip.speed == 1.25
    assert video_clip.volume == 0.75

    text_clip = imported.tracks[1].clips[0]
    assert text_clip.text_main == "Hello"
    assert text_clip.text_color == "#ffffff"
    assert text_clip.text_font_size == 30


def test_function_assistant_info_keeps_capcut_typo(tmp_path: Path):
    project = Project(name="Typo", tracks=[Track(kind="video", clips=[_sample_video_clip()])])

    out = tmp_path / "draft_content.json"
    data = json.loads(export_to_capcut(project, out).read_text(encoding="utf-8"))

    assert "enhande_voice" in data["function_assistant_info"]
    assert "enhande_voice_fixed" in data["function_assistant_info"]


def test_image_track_is_skipped_safely(tmp_path: Path):
    project = Project(
        name="Mixed",
        tracks=[
            Track(
                kind="video",
                clips=[_sample_video_clip()],
                image_overlays=[
                    ImageOverlay(
                        source="C:/media/overlay.png",
                        start=0.0,
                        end=2.0,
                    )
                ],
            )
        ],
    )

    out = tmp_path / "draft_content.json"
    data = json.loads(export_to_capcut(project, out).read_text(encoding="utf-8"))

    track_types = {track["type"] for track in data["tracks"]}
    assert "image" not in track_types
    assert "video" in track_types


def test_bilingual_text_exports_both_lines(tmp_path: Path):
    project = Project(
        name="Bilingual",
        tracks=[
            Track(
                kind="text",
                clips=[
                    Clip(
                        clip_type="text",
                        source="",
                        in_point=0.0,
                        out_point=3.0,
                        start=0.0,
                        text_main="Hello",
                        text_second="Xin chao",
                        text_display="bilingual",
                        text_color="#ffffff",
                        text_second_color="#00ff00",
                        text_font_size=30,
                        text_second_font_size=24,
                    )
                ],
            )
        ],
    )

    out = tmp_path / "draft_content.json"
    data = json.loads(export_to_capcut(project, out).read_text(encoding="utf-8"))

    text_material = data["materials"]["texts"][0]
    parsed = json.loads(text_material["content"])

    assert parsed["text"] == "Hello\nXin chao"
    assert len(parsed["styles"]) == 2
    assert parsed["styles"][0]["range"] == [0, len("Hello")]
    assert parsed["styles"][1]["range"] == [len("Hello") + 1, len("Hello\nXin chao")]


def test_font_family_round_trips_through_export_then_import(tmp_path: Path):
    project = Project(name="Font", tracks=[Track(kind="text", clips=[_sample_text_clip()])])

    out = tmp_path / "draft_content.json"
    imported = import_capcut_draft(export_to_capcut(project, out))

    assert imported.tracks[0].clips[0].text_font_family == "Arial"
