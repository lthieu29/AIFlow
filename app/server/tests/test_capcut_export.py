"""Tests for server/export/capcut — CapCut / JianYing draft builder.

These tests are pure-Python and do not require any external tools (ffprobe,
CapCut, etc.).  They verify that the JSON structure produced by
:class:`~server.export.capcut.JianYingDraft` is well-formed and contains
the expected fields.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from server.export.capcut import (
    AudioMaterial,
    AudioSegment,
    DraftWriter,
    JianYingDraft,
    TextBorder,
    TextSegment,
    TextStyle,
    Timerange,
    VideoMaterial,
    VideoSegment,
)
from server.export.capcut.models import SEC, ClipSettings, trange, tim


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_video(name: str = "clip.mp4", duration_s: float = 8.0) -> VideoMaterial:
    return VideoMaterial(
        path=f"/fake/{name}",
        material_type="video",
        duration_us=int(duration_s * SEC),
        width=1080,
        height=1920,
        material_name=name,
    )


def _make_audio(name: str = "narration.mp3", duration_s: float = 8.0) -> AudioMaterial:
    return AudioMaterial(
        path=f"/fake/{name}",
        duration_us=int(duration_s * SEC),
        material_name=name,
    )


# ---------------------------------------------------------------------------
# Unit tests — time utilities
# ---------------------------------------------------------------------------

class TestTimeUtils:
    def test_tim_int_passthrough(self):
        assert tim(5_000_000) == 5_000_000

    def test_tim_float_rounds(self):
        assert tim(1.5) == 2  # rounds to nearest int

    def test_tim_string_seconds(self):
        assert tim("3s") == 3 * SEC

    def test_tim_string_minutes(self):
        assert tim("1m30s") == 90 * SEC

    def test_tim_string_hours(self):
        assert tim("1h") == 3600 * SEC

    def test_trange_helper(self):
        tr = trange("2s", "5s")
        assert tr.start == 2 * SEC
        assert tr.duration == 5 * SEC
        assert tr.end == 7 * SEC

    def test_timerange_no_overlap(self):
        a = Timerange(0, 3 * SEC)
        b = Timerange(3 * SEC, 3 * SEC)
        assert not a.overlaps(b)

    def test_timerange_overlap(self):
        a = Timerange(0, 5 * SEC)
        b = Timerange(3 * SEC, 5 * SEC)
        assert a.overlaps(b)


# ---------------------------------------------------------------------------
# Unit tests — materials
# ---------------------------------------------------------------------------

class TestVideoMaterial:
    def test_export_json_keys(self):
        mat = _make_video()
        j = mat.export_json()
        assert j["type"] == "video"
        assert j["duration"] == 8 * SEC
        assert j["width"] == 1080
        assert j["height"] == 1920
        assert j["path"] == "/fake/clip.mp4"
        assert "id" in j
        assert "material_id" in j

    def test_stable_id_from_name(self):
        a = _make_video("same.mp4")
        b = _make_video("same.mp4")
        assert a.material_id == b.material_id

    def test_different_names_different_ids(self):
        a = _make_video("a.mp4")
        b = _make_video("b.mp4")
        assert a.material_id != b.material_id

    def test_photo_type(self):
        mat = VideoMaterial(
            path="/fake/img.jpg",
            material_type="photo",
            duration_us=10_800_000_000,
            width=1080,
            height=1920,
            material_name="img.jpg",
        )
        j = mat.export_json()
        assert j["type"] == "photo"


class TestAudioMaterial:
    def test_export_json_keys(self):
        mat = _make_audio()
        j = mat.export_json()
        assert j["duration"] == 8 * SEC
        assert j["path"] == "/fake/narration.mp3"
        assert j["type"] == "extract_music"
        assert "id" in j

    def test_stable_id_from_name(self):
        a = _make_audio("same.mp3")
        b = _make_audio("same.mp3")
        assert a.material_id == b.material_id


# ---------------------------------------------------------------------------
# Unit tests — segments
# ---------------------------------------------------------------------------

class TestVideoSegment:
    def test_export_json_structure(self):
        mat = _make_video()
        seg = VideoSegment(
            material=mat,
            target_timerange=Timerange(0, 8 * SEC),
        )
        j = seg.export_json()
        assert j["material_id"] == mat.material_id
        assert j["target_timerange"] == {"start": 0, "duration": 8 * SEC}
        assert j["speed"] == 1.0
        assert j["volume"] == 1.0
        assert "clip" in j
        assert "uniform_scale" in j

    def test_source_timerange_defaults_to_full(self):
        mat = _make_video()
        seg = VideoSegment(material=mat, target_timerange=Timerange(0, 5 * SEC))
        assert seg.source_timerange == Timerange(0, 5 * SEC)

    def test_end_property(self):
        mat = _make_video()
        seg = VideoSegment(material=mat, target_timerange=Timerange(2 * SEC, 6 * SEC))
        assert seg.end == 8 * SEC


class TestAudioSegment:
    def test_export_json_structure(self):
        mat = _make_audio()
        seg = AudioSegment(material=mat, target_timerange=Timerange(0, 8 * SEC))
        j = seg.export_json()
        assert j["material_id"] == mat.material_id
        assert j["clip"] is None  # audio has no clip settings

    def test_volume_respected(self):
        mat = _make_audio()
        seg = AudioSegment(material=mat, target_timerange=Timerange(0, 8 * SEC), volume=0.5)
        assert seg.export_json()["volume"] == 0.5


class TestTextSegment:
    def test_export_material_keys(self):
        seg = TextSegment(
            text="Hello world",
            target_timerange=Timerange(0, 3 * SEC),
        )
        mat = seg.export_material()
        assert mat["type"] == "text"
        content = json.loads(mat["content"])
        assert content["text"] == "Hello world"
        assert len(content["styles"]) == 1

    def test_export_json_structure(self):
        seg = TextSegment(text="Hi", target_timerange=Timerange(0, 2 * SEC))
        j = seg.export_json()
        assert j["material_id"] == seg.material_id
        assert j["target_timerange"]["duration"] == 2 * SEC

    def test_border_sets_check_flag(self):
        seg = TextSegment(
            text="Bordered",
            target_timerange=Timerange(0, 2 * SEC),
            border=TextBorder(),
        )
        mat = seg.export_material()
        # check_flag should have bit 3 set (value 8) in addition to base 7 → 15
        assert mat["check_flag"] & 8

    def test_style_color_in_content(self):
        style = TextStyle(color=(1.0, 0.0, 0.0))
        seg = TextSegment(text="Red", target_timerange=Timerange(0, 1 * SEC), style=style)
        content = json.loads(seg.export_material()["content"])
        color = content["styles"][0]["fill"]["content"]["solid"]["color"]
        assert color == [1.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# Unit tests — JianYingDraft builder
# ---------------------------------------------------------------------------

class TestJianYingDraft:
    def test_empty_draft_dumps_valid_json(self):
        draft = JianYingDraft(name="Empty")
        data = json.loads(draft.dumps())
        assert data["name"] == "Empty"
        assert data["duration"] == 0
        assert data["tracks"] == []

    def test_canvas_config(self):
        draft = JianYingDraft(width=1080, height=1920)
        data = json.loads(draft.dumps())
        assert data["canvas_config"]["width"] == 1080
        assert data["canvas_config"]["height"] == 1920

    def test_fps_stored(self):
        draft = JianYingDraft(fps=60)
        data = json.loads(draft.dumps())
        assert data["fps"] == 60.0

    def test_add_video_clip_creates_track(self):
        draft = JianYingDraft()
        mat = _make_video()
        draft.add_video_clip(mat, Timerange(0, 8 * SEC))
        data = json.loads(draft.dumps())
        assert len(data["tracks"]) == 1
        assert data["tracks"][0]["type"] == "video"
        assert len(data["tracks"][0]["segments"]) == 1

    def test_add_video_clip_updates_duration(self):
        draft = JianYingDraft()
        mat = _make_video()
        draft.add_video_clip(mat, Timerange(0, 8 * SEC))
        assert draft.duration == 8 * SEC

    def test_add_audio_clip_creates_audio_track(self):
        draft = JianYingDraft()
        mat = _make_audio()
        draft.add_audio_clip(mat, Timerange(0, 8 * SEC), track="narration")
        data = json.loads(draft.dumps())
        audio_tracks = [t for t in data["tracks"] if t["type"] == "audio"]
        assert len(audio_tracks) == 1
        assert audio_tracks[0]["name"] == "narration"

    def test_multiple_audio_tracks(self):
        draft = JianYingDraft()
        tts = _make_audio("tts.mp3")
        bgm = _make_audio("bgm.mp3")
        draft.add_audio_clip(tts, Timerange(0, 8 * SEC), track="narration")
        draft.add_audio_clip(bgm, Timerange(0, 8 * SEC), track="bgm")
        data = json.loads(draft.dumps())
        audio_tracks = [t for t in data["tracks"] if t["type"] == "audio"]
        assert len(audio_tracks) == 2

    def test_add_subtitle_creates_text_track(self):
        draft = JianYingDraft()
        draft.add_subtitle("Hello", Timerange(0, 2 * SEC))
        data = json.loads(draft.dumps())
        text_tracks = [t for t in data["tracks"] if t["type"] == "text"]
        assert len(text_tracks) == 1
        assert len(text_tracks[0]["segments"]) == 1

    def test_subtitle_text_in_materials(self):
        draft = JianYingDraft()
        draft.add_subtitle("Test subtitle", Timerange(0, 2 * SEC))
        data = json.loads(draft.dumps())
        texts = data["materials"]["texts"]
        assert len(texts) == 1
        content = json.loads(texts[0]["content"])
        assert content["text"] == "Test subtitle"

    def test_video_material_in_materials(self):
        draft = JianYingDraft()
        mat = _make_video()
        draft.add_video_clip(mat, Timerange(0, 8 * SEC))
        data = json.loads(draft.dumps())
        assert len(data["materials"]["videos"]) == 1
        assert data["materials"]["videos"][0]["path"] == "/fake/clip.mp4"

    def test_audio_material_in_materials(self):
        draft = JianYingDraft()
        mat = _make_audio()
        draft.add_audio_clip(mat, Timerange(0, 8 * SEC))
        data = json.loads(draft.dumps())
        assert len(data["materials"]["audios"]) == 1

    def test_speed_objects_in_materials(self):
        draft = JianYingDraft()
        draft.add_video_clip(_make_video(), Timerange(0, 8 * SEC))
        draft.add_audio_clip(_make_audio(), Timerange(0, 8 * SEC))
        data = json.loads(draft.dumps())
        # One speed object per video/audio segment
        assert len(data["materials"]["speeds"]) == 2

    def test_same_material_not_duplicated(self):
        """Adding the same material twice should not duplicate it in the JSON."""
        draft = JianYingDraft()
        mat = _make_video("clip.mp4")
        draft.add_video_clip(mat, Timerange(0, 4 * SEC))
        draft.add_video_clip(mat, Timerange(4 * SEC, 4 * SEC))
        data = json.loads(draft.dumps())
        assert len(data["materials"]["videos"]) == 1

    def test_duration_is_max_of_all_tracks(self):
        draft = JianYingDraft()
        draft.add_video_clip(_make_video(), Timerange(0, 8 * SEC))
        draft.add_audio_clip(_make_audio("long.mp3", 10.0), Timerange(0, 10 * SEC))
        assert draft.duration == 10 * SEC

    def test_full_draft_structure(self):
        """Integration: video + narration + bgm + subtitle."""
        draft = JianYingDraft(name="Full Test", width=1080, height=1920)
        draft.add_video_clip(_make_video(), Timerange(0, 8 * SEC))
        draft.add_audio_clip(_make_audio("tts.mp3"), Timerange(0, 8 * SEC), track="narration")
        draft.add_audio_clip(_make_audio("bgm.mp3", 30.0), Timerange(0, 8 * SEC), track="bgm", volume=0.3)
        draft.add_subtitle("Scene 1", Timerange(0, 4 * SEC))
        draft.add_subtitle("Scene 2", Timerange(4 * SEC, 4 * SEC))

        data = json.loads(draft.dumps())

        assert data["name"] == "Full Test"
        assert data["duration"] == 8 * SEC
        assert len(data["tracks"]) == 4  # video, narration, bgm, subtitle

        track_types = {t["type"] for t in data["tracks"]}
        assert track_types == {"video", "audio", "text"}

        text_tracks = [t for t in data["tracks"] if t["type"] == "text"]
        assert len(text_tracks[0]["segments"]) == 2

    def test_dump_writes_file(self, tmp_path):
        draft = JianYingDraft(name="File Test")
        out = tmp_path / "draft_info.json"
        draft.dump(str(out))
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["name"] == "File Test"


# ---------------------------------------------------------------------------
# Unit tests — SRT import
# ---------------------------------------------------------------------------

class TestSRTImport:
    SRT_CONTENT = """\
1
00:00:00,000 --> 00:00:02,500
Hello world

2
00:00:02,500 --> 00:00:05,000
Second subtitle
"""

    def test_import_srt_string(self):
        draft = JianYingDraft()
        draft.import_srt(self.SRT_CONTENT)
        data = json.loads(draft.dumps())
        text_tracks = [t for t in data["tracks"] if t["type"] == "text"]
        assert len(text_tracks) == 1
        assert len(text_tracks[0]["segments"]) == 2

    def test_import_srt_timing(self):
        draft = JianYingDraft()
        draft.import_srt(self.SRT_CONTENT)
        data = json.loads(draft.dumps())
        segs = data["tracks"][0]["segments"]
        assert segs[0]["target_timerange"]["start"] == 0
        assert segs[0]["target_timerange"]["duration"] == 2_500_000
        assert segs[1]["target_timerange"]["start"] == 2_500_000

    def test_import_srt_from_file(self, tmp_path):
        srt_file = tmp_path / "subs.srt"
        srt_file.write_text(self.SRT_CONTENT, encoding="utf-8")
        draft = JianYingDraft()
        draft.import_srt(str(srt_file))
        data = json.loads(draft.dumps())
        assert len(data["tracks"][0]["segments"]) == 2

    def test_import_srt_text_content(self):
        draft = JianYingDraft()
        draft.import_srt(self.SRT_CONTENT)
        data = json.loads(draft.dumps())
        texts = data["materials"]["texts"]
        contents = [json.loads(t["content"])["text"] for t in texts]
        assert "Hello world" in contents
        assert "Second subtitle" in contents


# ---------------------------------------------------------------------------
# Unit tests — DraftWriter
# ---------------------------------------------------------------------------

class TestDraftWriter:
    def test_write_creates_folder(self, tmp_path):
        draft = JianYingDraft(name="Writer Test")
        writer = DraftWriter(draft_root=str(tmp_path))
        out = writer.write(draft)
        assert os.path.isdir(out)

    def test_write_creates_required_files(self, tmp_path):
        draft = JianYingDraft(name="Files Test")
        writer = DraftWriter(draft_root=str(tmp_path))
        out = writer.write(draft)
        assert os.path.exists(os.path.join(out, "draft_info.json"))
        assert os.path.exists(os.path.join(out, "draft_meta_info.json"))
        assert os.path.exists(os.path.join(out, "draft_agency_config.json"))
        assert os.path.exists(os.path.join(out, "draft_biz_config.json"))
        assert os.path.exists(os.path.join(out, "draft_settings"))

    def test_write_raises_if_folder_exists(self, tmp_path):
        draft = JianYingDraft(name="Duplicate")
        writer = DraftWriter(draft_root=str(tmp_path))
        writer.write(draft)
        with pytest.raises(FileExistsError):
            writer.write(draft)

    def test_meta_info_has_name(self, tmp_path):
        draft = JianYingDraft(name="Meta Test")
        writer = DraftWriter(draft_root=str(tmp_path))
        out = writer.write(draft)
        meta = json.loads(
            open(os.path.join(out, "draft_meta_info.json"), encoding="utf-8").read()
        )
        assert meta["draft_name"] == "Meta Test"
        assert "tm_draft_create" in meta
        assert "tm_duration" in meta

    def test_write_to_dir(self, tmp_path):
        draft = JianYingDraft(name="Dir Test")
        writer = DraftWriter()
        out = writer.write_to_dir(draft, str(tmp_path))
        assert os.path.exists(os.path.join(out, "draft_info.json"))

    def test_write_to_dir_raises_if_not_exists(self, tmp_path):
        draft = JianYingDraft(name="Missing")
        writer = DraftWriter()
        with pytest.raises(FileNotFoundError):
            writer.write_to_dir(draft, str(tmp_path / "nonexistent"))

    def test_draft_info_json_is_valid(self, tmp_path):
        draft = JianYingDraft(name="Valid JSON")
        draft.add_video_clip(_make_video(), Timerange(0, 5 * SEC))
        writer = DraftWriter(draft_root=str(tmp_path))
        out = writer.write(draft)
        data = json.loads(
            open(os.path.join(out, "draft_info.json"), encoding="utf-8").read()
        )
        assert data["name"] == "Valid JSON"
        assert data["duration"] == 5 * SEC
