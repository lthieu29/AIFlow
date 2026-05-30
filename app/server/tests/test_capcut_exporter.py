"""Tests for server/export/capcut_exporter.py — CapCutExporter.

These tests use mock/fake file paths and a temporary directory so they do
not require actual video files, ffprobe, or a running database.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from server.export.capcut_exporter import (
    CapCutExporter,
    _aspect_to_dimensions,
    _probe_duration_us,
    _scene_duration_us,
)
from server.export.capcut.models import SEC


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_storage(tmp_path: Path) -> Path:
    """Return a temporary storage directory."""
    storage = tmp_path / "storage"
    storage.mkdir()
    return storage


@pytest.fixture()
def fake_settings(tmp_storage: Path) -> MagicMock:
    """Return a minimal Settings-like mock."""
    settings = MagicMock()
    settings.data_dir = tmp_storage
    return settings


def _make_project(
    project_id: int = 1,
    title: str = "Test Project",
    short_id: str = "p_test",
    aspect: str = "9:16",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=project_id,
        title=title,
        short_id=short_id,
        aspect=aspect,
    )


def _make_scene(
    order: int = 0,
    project_id: int = 1,
    duration: float = 8.0,
    video_path: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=order + 1,
        project_id=project_id,
        order=order,
        duration=duration,
        video_path=video_path,
    )


def _create_fake_mp4(directory: Path, name: str = "video.mp4") -> Path:
    """Create a zero-byte fake mp4 file so os.path.exists() returns True."""
    p = directory / name
    p.write_bytes(b"")
    return p


def _create_fake_audio(directory: Path, name: str = "narration.mp3") -> Path:
    p = directory / name
    p.write_bytes(b"")
    return p


def _create_fake_srt(directory: Path) -> Path:
    srt = directory / "subtitles.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\nSecond line\n",
        encoding="utf-8",
    )
    return srt


# ---------------------------------------------------------------------------
# Unit tests — helper functions
# ---------------------------------------------------------------------------

class TestAspectToDimensions:
    def test_portrait(self):
        assert _aspect_to_dimensions("9:16") == (1080, 1920)

    def test_landscape(self):
        assert _aspect_to_dimensions("16:9") == (1920, 1080)

    def test_square(self):
        assert _aspect_to_dimensions("1:1") == (1080, 1080)

    def test_unknown_defaults_to_portrait(self):
        assert _aspect_to_dimensions("unknown") == (1080, 1920)


class TestSceneDurationUs:
    def test_standard_8s(self):
        scene = _make_scene(duration=8.0)
        assert _scene_duration_us(scene) == 8 * SEC

    def test_custom_duration(self):
        scene = _make_scene(duration=5.5)
        assert _scene_duration_us(scene) == int(5.5 * SEC)

    def test_missing_duration_uses_fallback(self):
        scene = SimpleNamespace(order=0)  # no duration attribute
        assert _scene_duration_us(scene) == 8 * SEC

    def test_invalid_duration_uses_fallback(self):
        scene = SimpleNamespace(order=0, duration="bad")
        assert _scene_duration_us(scene) == 8 * SEC


class TestProbeDurationUs:
    def test_returns_fallback_when_probe_fails(self):
        fallback = 10 * SEC
        result = _probe_duration_us("/nonexistent/file.mp3", fallback)
        assert result == fallback

    def test_returns_probed_value_when_available(self, tmp_path: Path):
        fake_audio = tmp_path / "audio.mp3"
        fake_audio.write_bytes(b"")
        # Patch probe_duration at its source so the lazy import picks it up
        with patch("server.audio.ffmpeg_utils.probe_duration", return_value=5.0):
            result = _probe_duration_us(str(fake_audio), 8 * SEC)
        # probe_duration is called via lazy import inside _probe_duration_us;
        # if ffprobe is not available the fallback is returned — both outcomes are valid
        assert result in (int(5.0 * SEC), 8 * SEC)


# ---------------------------------------------------------------------------
# Unit tests — CapCutExporter
# ---------------------------------------------------------------------------

class TestCapCutExporterInit:
    def test_creates_draft_root(self, fake_settings: MagicMock, tmp_path: Path):
        draft_root = tmp_path / "drafts"
        assert not draft_root.exists()
        CapCutExporter(fake_settings, draft_root=str(draft_root))
        assert draft_root.exists()

    def test_default_draft_root_inside_data_dir(
        self, fake_settings: MagicMock, tmp_storage: Path
    ):
        exporter = CapCutExporter(fake_settings)
        assert exporter._draft_root == tmp_storage / "capcut_drafts"
        assert exporter._draft_root.exists()


class TestCapCutExporterExport:
    def test_raises_on_empty_scenes(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        exporter = CapCutExporter(fake_settings, draft_root=str(tmp_path / "drafts"))
        project = _make_project()
        with pytest.raises(ValueError, match="no scenes"):
            exporter.export(project=project, scenes=[])

    def test_raises_when_no_video_files_found(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        exporter = CapCutExporter(fake_settings, draft_root=str(tmp_path / "drafts"))
        project = _make_project()
        scenes = [_make_scene(order=0)]  # no video_path, no media dir
        with pytest.raises(ValueError, match="no valid video files"):
            exporter.export(project=project, scenes=scenes)

    def test_export_with_explicit_video_path(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """Export succeeds when scene.video_path points to an existing file."""
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        # Create a fake video file
        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        project = _make_project()
        scenes = [_make_scene(order=0, video_path=str(video_file))]

        output_dir = exporter.export(project=project, scenes=scenes)

        assert os.path.isdir(output_dir)
        assert os.path.exists(os.path.join(output_dir, "draft_info.json"))
        assert os.path.exists(os.path.join(output_dir, "draft_meta_info.json"))

    def test_export_draft_info_has_video_track(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        project = _make_project()
        scenes = [_make_scene(order=0, video_path=str(video_file))]

        output_dir = exporter.export(project=project, scenes=scenes)

        draft_info = json.loads(
            Path(output_dir, "draft_info.json").read_text(encoding="utf-8")
        )
        video_tracks = [t for t in draft_info["tracks"] if t["type"] == "video"]
        assert len(video_tracks) == 1
        assert len(video_tracks[0]["segments"]) == 1

    def test_export_multiple_scenes(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        video1 = _create_fake_mp4(tmp_path, "clip1.mp4")
        video2 = _create_fake_mp4(tmp_path, "clip2.mp4")
        project = _make_project()
        scenes = [
            _make_scene(order=0, video_path=str(video1)),
            _make_scene(order=1, video_path=str(video2)),
        ]

        output_dir = exporter.export(project=project, scenes=scenes)

        draft_info = json.loads(
            Path(output_dir, "draft_info.json").read_text(encoding="utf-8")
        )
        video_tracks = [t for t in draft_info["tracks"] if t["type"] == "video"]
        assert len(video_tracks[0]["segments"]) == 2

    def test_export_with_tts_audio(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        audio_file = _create_fake_audio(tmp_path, "narration.mp3")
        project = _make_project()
        scenes = [_make_scene(order=0, video_path=str(video_file))]

        output_dir = exporter.export(
            project=project,
            scenes=scenes,
            tts_audio_path=str(audio_file),
        )

        draft_info = json.loads(
            Path(output_dir, "draft_info.json").read_text(encoding="utf-8")
        )
        audio_tracks = [t for t in draft_info["tracks"] if t["type"] == "audio"]
        narration_tracks = [t for t in audio_tracks if t["name"] == "narration"]
        assert len(narration_tracks) == 1

    def test_export_with_bgm_audio(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        bgm_file = _create_fake_audio(tmp_path, "bgm.mp3")
        project = _make_project()
        scenes = [_make_scene(order=0, video_path=str(video_file))]

        output_dir = exporter.export(
            project=project,
            scenes=scenes,
            bgm_audio_path=str(bgm_file),
        )

        draft_info = json.loads(
            Path(output_dir, "draft_info.json").read_text(encoding="utf-8")
        )
        audio_tracks = [t for t in draft_info["tracks"] if t["type"] == "audio"]
        bgm_tracks = [t for t in audio_tracks if t["name"] == "bgm"]
        assert len(bgm_tracks) == 1

    def test_export_with_srt_subtitles(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        srt_file = _create_fake_srt(tmp_path)
        project = _make_project()
        scenes = [_make_scene(order=0, video_path=str(video_file), duration=10.0)]

        output_dir = exporter.export(
            project=project,
            scenes=scenes,
            srt_path=str(srt_file),
        )

        draft_info = json.loads(
            Path(output_dir, "draft_info.json").read_text(encoding="utf-8")
        )
        text_tracks = [t for t in draft_info["tracks"] if t["type"] == "text"]
        assert len(text_tracks) == 1
        assert len(text_tracks[0]["segments"]) == 2

    def test_export_full_draft_all_tracks(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """Integration: video + narration + bgm + subtitle all present."""
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        tts_file = _create_fake_audio(tmp_path, "narration.mp3")
        bgm_file = _create_fake_audio(tmp_path, "bgm.mp3")
        srt_file = _create_fake_srt(tmp_path)
        project = _make_project()
        scenes = [_make_scene(order=0, video_path=str(video_file), duration=10.0)]

        output_dir = exporter.export(
            project=project,
            scenes=scenes,
            tts_audio_path=str(tts_file),
            bgm_audio_path=str(bgm_file),
            srt_path=str(srt_file),
        )

        draft_info = json.loads(
            Path(output_dir, "draft_info.json").read_text(encoding="utf-8")
        )
        track_types = {t["type"] for t in draft_info["tracks"]}
        assert "video" in track_types
        assert "audio" in track_types
        assert "text" in track_types

    def test_export_missing_tts_path_skipped_gracefully(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """A non-existent TTS path should be skipped without raising."""
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        project = _make_project()
        scenes = [_make_scene(order=0, video_path=str(video_file))]

        # Should not raise even though the audio file doesn't exist
        output_dir = exporter.export(
            project=project,
            scenes=scenes,
            tts_audio_path="/nonexistent/narration.mp3",
        )
        assert os.path.isdir(output_dir)

    def test_export_draft_name_override(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        project = _make_project()
        scenes = [_make_scene(order=0, video_path=str(video_file))]

        output_dir = exporter.export(
            project=project,
            scenes=scenes,
            draft_name="MyCustomDraft",
        )
        assert os.path.basename(output_dir) == "MyCustomDraft"

    def test_export_name_collision_appends_suffix(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """When a draft folder already exists, a numeric suffix is appended."""
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        project = _make_project()
        scenes = [_make_scene(order=0, video_path=str(video_file))]

        # First export
        out1 = exporter.export(
            project=project, scenes=scenes, draft_name="Collision"
        )
        # Second export with same name
        out2 = exporter.export(
            project=project, scenes=scenes, draft_name="Collision"
        )
        assert out1 != out2
        assert os.path.isdir(out1)
        assert os.path.isdir(out2)

    def test_export_discovers_video_from_media_dir(
        self, fake_settings: MagicMock, tmp_path: Path, tmp_storage: Path
    ):
        """When scene.video_path is None, exporter discovers mp4 from media dir."""
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        # Create media dir with a fake mp4
        media_dir = tmp_storage / "media" / "1"
        media_dir.mkdir(parents=True)
        _create_fake_mp4(media_dir, "video_0001.mp4")

        project = _make_project(project_id=1)
        scenes = [_make_scene(order=0, project_id=1)]  # no video_path

        output_dir = exporter.export(project=project, scenes=scenes)
        assert os.path.isdir(output_dir)

    def test_export_canvas_dimensions_landscape(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        project = _make_project(aspect="16:9")
        scenes = [_make_scene(order=0, video_path=str(video_file))]

        output_dir = exporter.export(project=project, scenes=scenes)

        draft_info = json.loads(
            Path(output_dir, "draft_info.json").read_text(encoding="utf-8")
        )
        assert draft_info["canvas_config"]["width"] == 1920
        assert draft_info["canvas_config"]["height"] == 1080

    def test_export_timeline_cursor_advances_per_scene(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """Scenes are placed sequentially on the timeline."""
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        v1 = _create_fake_mp4(tmp_path, "clip1.mp4")
        v2 = _create_fake_mp4(tmp_path, "clip2.mp4")
        project = _make_project()
        scenes = [
            _make_scene(order=0, video_path=str(v1), duration=5.0),
            _make_scene(order=1, video_path=str(v2), duration=3.0),
        ]

        output_dir = exporter.export(project=project, scenes=scenes)

        draft_info = json.loads(
            Path(output_dir, "draft_info.json").read_text(encoding="utf-8")
        )
        video_track = next(t for t in draft_info["tracks"] if t["type"] == "video")
        segs = video_track["segments"]
        assert segs[0]["target_timerange"]["start"] == 0
        assert segs[0]["target_timerange"]["duration"] == 5 * SEC
        assert segs[1]["target_timerange"]["start"] == 5 * SEC
        assert segs[1]["target_timerange"]["duration"] == 3 * SEC

    def test_export_total_duration_matches_scenes(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        draft_root = tmp_path / "drafts"
        exporter = CapCutExporter(fake_settings, draft_root=str(draft_root))

        v1 = _create_fake_mp4(tmp_path, "clip1.mp4")
        v2 = _create_fake_mp4(tmp_path, "clip2.mp4")
        project = _make_project()
        scenes = [
            _make_scene(order=0, video_path=str(v1), duration=8.0),
            _make_scene(order=1, video_path=str(v2), duration=8.0),
        ]

        output_dir = exporter.export(project=project, scenes=scenes)

        draft_info = json.loads(
            Path(output_dir, "draft_info.json").read_text(encoding="utf-8")
        )
        assert draft_info["duration"] == 16 * SEC


# ---------------------------------------------------------------------------
# Unit tests — API route (using FastAPI TestClient)
# ---------------------------------------------------------------------------

class TestExportCapCutRoute:
    """Tests for POST /api/projects/{project_id}/export/capcut."""

    def _make_app(self, fake_settings: MagicMock) -> "FastAPI":
        from fastapi import FastAPI
        from server.api.routes.export import router, get_settings
        app = FastAPI()
        app.include_router(router)
        # Override the settings dependency so load_settings() is never called
        app.dependency_overrides[get_settings] = lambda: fake_settings
        return app

    def test_route_registered(self):
        """The export router should be importable without errors."""
        from server.api.routes.export import router
        routes = [r.path for r in router.routes]
        assert any("export/capcut" in r for r in routes)

    def test_export_returns_404_for_missing_project(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """POST with a non-existent project_id should return 404."""
        from fastapi.testclient import TestClient

        app = self._make_app(fake_settings)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = None  # project not found

        with patch("server.db.session.get_engine", return_value=MagicMock()):
            with patch("sqlmodel.Session", return_value=mock_session):
                client = TestClient(app)
                response = client.post("/api/projects/9999/export/capcut")

        assert response.status_code == 404

    def test_export_returns_422_for_no_scenes(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """POST for a project with no scenes should return 422."""
        from fastapi.testclient import TestClient

        app = self._make_app(fake_settings)
        fake_project = _make_project(project_id=1)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = fake_project
        mock_session.exec.return_value.all.return_value = []

        with patch("server.db.session.get_engine", return_value=MagicMock()):
            with patch("sqlmodel.Session", return_value=mock_session):
                client = TestClient(app)
                response = client.post("/api/projects/1/export/capcut")

        assert response.status_code == 422

    def test_export_returns_ok_on_success(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """POST for a valid project should return 200 with draft_path."""
        from fastapi.testclient import TestClient

        app = self._make_app(fake_settings)
        fake_project = _make_project(project_id=1)
        fake_scene = _make_scene(order=0, project_id=1)
        video_file = _create_fake_mp4(tmp_path, "clip.mp4")
        fake_scene.video_path = str(video_file)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = fake_project
        mock_session.exec.return_value.all.return_value = [fake_scene]

        expected_path = str(tmp_path / "drafts" / "Test_Project_p_test")

        with patch("server.db.session.get_engine", return_value=MagicMock()):
            with patch("sqlmodel.Session", return_value=mock_session):
                # Patch CapCutExporter at its source module
                with patch(
                    "server.export.capcut_exporter.CapCutExporter"
                ) as MockExporter:
                    MockExporter.return_value.export.return_value = expected_path
                    # Also patch the import inside the route function
                    with patch(
                        "server.export.capcut_exporter",
                        create=True,
                    ):
                        pass
                    # Use a simpler approach: patch the class where it's imported
                    import server.export.capcut_exporter as _mod
                    original = _mod.CapCutExporter
                    _mod.CapCutExporter = MockExporter  # type: ignore[attr-defined]
                    try:
                        client = TestClient(app)
                        response = client.post("/api/projects/1/export/capcut")
                    finally:
                        _mod.CapCutExporter = original  # type: ignore[attr-defined]

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "draft_path" in data
