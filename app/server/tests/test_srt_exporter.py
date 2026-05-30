"""Tests for server/export/srt_exporter.py — SrtExporter.

Covers:
  - Core SRT generation from SubtitleSegment list
  - Writing to file
  - Building segments from scene narrations
  - Building segments from Whisper transcription output
  - API endpoint GET /api/projects/{project_id}/export/srt
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from server.export.srt_exporter import (
    SrtExporter,
    SubtitleSegment,
    generate_srt,
    write_srt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_segments(*items: tuple[str, float, float]) -> list[SubtitleSegment]:
    """Build a list of SubtitleSegment from (text, start, end) tuples."""
    return [SubtitleSegment(text=t, start_sec=s, end_sec=e) for t, s, e in items]


@dataclass
class FakeWhisperSegment:
    """Minimal stand-in for server.audio.transcribe.SRTSegment."""

    index: int
    start_time: float
    end_time: float
    text: str


def _make_project(project_id: int = 1, title: str = "Test") -> SimpleNamespace:
    return SimpleNamespace(id=project_id, title=title, short_id="p_test", aspect="9:16")


def _make_scene(
    order: int = 0,
    project_id: int = 1,
    duration: float = 8.0,
    narration: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=order + 1,
        project_id=project_id,
        order=order,
        duration=duration,
        narration=narration,
    )


# ---------------------------------------------------------------------------
# SubtitleSegment
# ---------------------------------------------------------------------------


class TestSubtitleSegment:
    def test_fields_stored(self):
        seg = SubtitleSegment(text="Hello", start_sec=1.0, end_sec=3.5)
        assert seg.text == "Hello"
        assert seg.start_sec == 1.0
        assert seg.end_sec == 3.5


# ---------------------------------------------------------------------------
# SrtExporter.generate
# ---------------------------------------------------------------------------


class TestSrtExporterGenerate:
    def test_empty_list_returns_empty_string(self):
        exporter = SrtExporter()
        assert exporter.generate([]) == ""

    def test_single_segment(self):
        exporter = SrtExporter()
        segs = _make_segments(("Hello world", 0.0, 2.5))
        result = exporter.generate(segs)
        assert "1\n" in result
        assert "00:00:00,000 --> 00:00:02,500" in result
        assert "Hello world" in result

    def test_multiple_segments_numbered_from_one(self):
        exporter = SrtExporter()
        segs = _make_segments(
            ("First", 0.0, 2.0),
            ("Second", 2.0, 4.0),
            ("Third", 4.0, 6.0),
        )
        result = exporter.generate(segs)
        assert "1\n" in result
        assert "2\n" in result
        assert "3\n" in result

    def test_segments_separated_by_blank_line(self):
        exporter = SrtExporter()
        segs = _make_segments(("A", 0.0, 1.0), ("B", 1.0, 2.0))
        result = exporter.generate(segs)
        # SRT blocks are separated by double newline
        assert "\n\n" in result

    def test_empty_text_segments_skipped(self):
        exporter = SrtExporter()
        segs = [
            SubtitleSegment(text="", start_sec=0.0, end_sec=1.0),
            SubtitleSegment(text="  ", start_sec=1.0, end_sec=2.0),
            SubtitleSegment(text="Real text", start_sec=2.0, end_sec=3.0),
        ]
        result = exporter.generate(segs)
        # Only one segment should appear
        assert result.count(" --> ") == 1
        assert "Real text" in result

    def test_timestamp_format_correct(self):
        exporter = SrtExporter()
        segs = _make_segments(("Test", 3661.5, 3665.0))
        result = exporter.generate(segs)
        assert "01:01:01,500 --> 01:01:05,000" in result

    def test_trailing_newline(self):
        exporter = SrtExporter()
        segs = _make_segments(("Hello", 0.0, 1.0))
        result = exporter.generate(segs)
        assert result.endswith("\n")

    def test_module_level_generate_srt(self):
        segs = _make_segments(("Hello", 0.0, 1.0))
        result = generate_srt(segs)
        assert "Hello" in result
        assert "00:00:00,000 --> 00:00:01,000" in result


# ---------------------------------------------------------------------------
# SrtExporter.write
# ---------------------------------------------------------------------------


class TestSrtExporterWrite:
    def test_writes_file(self, tmp_path: Path):
        exporter = SrtExporter()
        segs = _make_segments(("Hello", 0.0, 2.0))
        out = exporter.write(segs, tmp_path / "output.srt")
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "Hello" in content

    def test_creates_parent_directories(self, tmp_path: Path):
        exporter = SrtExporter()
        segs = _make_segments(("Hello", 0.0, 2.0))
        nested = tmp_path / "a" / "b" / "c" / "output.srt"
        out = exporter.write(segs, nested)
        assert out.exists()

    def test_returns_resolved_path(self, tmp_path: Path):
        exporter = SrtExporter()
        segs = _make_segments(("Hello", 0.0, 2.0))
        out = exporter.write(segs, tmp_path / "output.srt")
        assert out.is_absolute()

    def test_empty_segments_writes_empty_file(self, tmp_path: Path):
        exporter = SrtExporter()
        out = exporter.write([], tmp_path / "empty.srt")
        assert out.exists()
        assert out.read_text(encoding="utf-8") == ""

    def test_module_level_write_srt(self, tmp_path: Path):
        segs = _make_segments(("Hello", 0.0, 1.0))
        out = write_srt(segs, tmp_path / "out.srt")
        assert out.exists()
        assert "Hello" in out.read_text(encoding="utf-8")

    def test_encoding_utf8_default(self, tmp_path: Path):
        exporter = SrtExporter()
        segs = _make_segments(("Xin chào thế giới", 0.0, 2.0))
        out = exporter.write(segs, tmp_path / "vi.srt")
        content = out.read_text(encoding="utf-8")
        assert "Xin chào thế giới" in content


# ---------------------------------------------------------------------------
# SrtExporter.from_scene_narrations
# ---------------------------------------------------------------------------


class TestFromSceneNarrations:
    def test_basic_two_scenes(self):
        segs = SrtExporter.from_scene_narrations(
            ["Scene one", "Scene two"],
            [8.0, 8.0],
        )
        assert len(segs) == 2
        assert segs[0].text == "Scene one"
        assert segs[0].start_sec == 0.0
        assert segs[0].end_sec == 8.0
        assert segs[1].start_sec == 8.0
        assert segs[1].end_sec == 16.0

    def test_gap_trims_end(self):
        segs = SrtExporter.from_scene_narrations(
            ["A", "B"],
            [8.0, 8.0],
            gap_sec=0.5,
        )
        assert segs[0].end_sec == pytest.approx(7.5)
        assert segs[1].end_sec == pytest.approx(15.5)

    def test_empty_narrations_skipped(self):
        segs = SrtExporter.from_scene_narrations(
            ["", "Real text", "  "],
            [8.0, 8.0, 8.0],
        )
        assert len(segs) == 1
        assert segs[0].text == "Real text"
        assert segs[0].start_sec == 8.0

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError, match="same length"):
            SrtExporter.from_scene_narrations(["A", "B"], [8.0])

    def test_single_scene(self):
        segs = SrtExporter.from_scene_narrations(["Only scene"], [5.0])
        assert len(segs) == 1
        assert segs[0].start_sec == 0.0
        assert segs[0].end_sec == 5.0

    def test_empty_inputs(self):
        segs = SrtExporter.from_scene_narrations([], [])
        assert segs == []

    def test_cursor_advances_even_for_empty_narrations(self):
        """Empty narration scenes still advance the timeline cursor."""
        segs = SrtExporter.from_scene_narrations(
            ["", "Second"],
            [5.0, 8.0],
        )
        assert len(segs) == 1
        assert segs[0].start_sec == pytest.approx(5.0)
        assert segs[0].end_sec == pytest.approx(13.0)

    def test_gap_larger_than_duration_clamps_to_duration(self):
        """When gap >= duration, end should not go below start."""
        segs = SrtExporter.from_scene_narrations(
            ["Short"],
            [1.0],
            gap_sec=5.0,  # gap > duration
        )
        assert len(segs) == 1
        assert segs[0].end_sec >= segs[0].start_sec


# ---------------------------------------------------------------------------
# SrtExporter.from_whisper_segments
# ---------------------------------------------------------------------------


class TestFromWhisperSegments:
    def test_basic_conversion(self):
        whisper_segs = [
            FakeWhisperSegment(index=1, start_time=0.0, end_time=2.5, text="Hello"),
            FakeWhisperSegment(index=2, start_time=2.5, end_time=5.0, text="World"),
        ]
        segs = SrtExporter.from_whisper_segments(whisper_segs)  # type: ignore[arg-type]
        assert len(segs) == 2
        assert segs[0].text == "Hello"
        assert segs[0].start_sec == 0.0
        assert segs[0].end_sec == 2.5
        assert segs[1].text == "World"

    def test_empty_text_segments_skipped(self):
        whisper_segs = [
            FakeWhisperSegment(index=1, start_time=0.0, end_time=1.0, text=""),
            FakeWhisperSegment(index=2, start_time=1.0, end_time=2.0, text="  "),
            FakeWhisperSegment(index=3, start_time=2.0, end_time=3.0, text="Real"),
        ]
        segs = SrtExporter.from_whisper_segments(whisper_segs)  # type: ignore[arg-type]
        assert len(segs) == 1
        assert segs[0].text == "Real"

    def test_empty_list(self):
        segs = SrtExporter.from_whisper_segments([])
        assert segs == []

    def test_roundtrip_generate(self):
        """Whisper segments → SubtitleSegments → SRT string should be valid."""
        whisper_segs = [
            FakeWhisperSegment(index=1, start_time=0.0, end_time=3.0, text="Xin chào"),
            FakeWhisperSegment(index=2, start_time=3.0, end_time=6.0, text="Thế giới"),
        ]
        segs = SrtExporter.from_whisper_segments(whisper_segs)  # type: ignore[arg-type]
        exporter = SrtExporter()
        result = exporter.generate(segs)
        assert "Xin chào" in result
        assert "Thế giới" in result
        assert "1\n" in result
        assert "2\n" in result


# ---------------------------------------------------------------------------
# SRT output validity
# ---------------------------------------------------------------------------


class TestSrtOutputValidity:
    """Verify that generated SRT can be round-tripped through the parser."""

    def test_roundtrip_parse(self):
        from server.content.srt_utils import parse_srt

        exporter = SrtExporter()
        segs = _make_segments(
            ("First subtitle", 0.0, 2.0),
            ("Second subtitle", 2.5, 5.0),
            ("Third subtitle", 5.5, 8.0),
        )
        srt_string = exporter.generate(segs)
        parsed = parse_srt(srt_string)

        assert len(parsed) == 3
        assert parsed[0].text == "First subtitle"
        assert parsed[0].start_sec == pytest.approx(0.0)
        assert parsed[0].end_sec == pytest.approx(2.0)
        assert parsed[1].text == "Second subtitle"
        assert parsed[2].text == "Third subtitle"

    def test_indices_sequential(self):
        from server.content.srt_utils import parse_srt

        exporter = SrtExporter()
        segs = _make_segments(
            ("A", 0.0, 1.0),
            ("B", 1.0, 2.0),
            ("C", 2.0, 3.0),
        )
        srt_string = exporter.generate(segs)
        parsed = parse_srt(srt_string)
        assert [p.index for p in parsed] == [1, 2, 3]


# ---------------------------------------------------------------------------
# API route tests — GET /api/projects/{project_id}/export/srt
# ---------------------------------------------------------------------------


class TestExportSrtRoute:
    """Tests for GET /api/projects/{project_id}/export/srt."""

    def _make_app(self, fake_settings: MagicMock):
        from fastapi import FastAPI
        from server.api.routes.export import router, get_settings

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_settings] = lambda: fake_settings
        return app

    @pytest.fixture()
    def fake_settings(self, tmp_path: Path) -> MagicMock:
        settings = MagicMock()
        settings.data_dir = tmp_path / "storage"
        (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
        return settings

    def test_srt_route_registered(self):
        from server.api.routes.export import router

        routes = [r.path for r in router.routes]
        assert any("export/srt" in r for r in routes)

    def test_returns_404_for_missing_project(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        from fastapi.testclient import TestClient

        app = self._make_app(fake_settings)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = None

        with patch("server.db.session.get_engine", return_value=MagicMock()):
            with patch("sqlmodel.Session", return_value=mock_session):
                client = TestClient(app)
                response = client.get("/api/projects/9999/export/srt")

        assert response.status_code == 404

    def test_returns_422_for_no_scenes(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
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
                response = client.get("/api/projects/1/export/srt")

        assert response.status_code == 422

    def test_returns_srt_from_existing_file(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """When an SRT file exists in the audio dir, it is returned directly."""
        from fastapi.testclient import TestClient

        # Create a fake SRT file in the expected location
        audio_dir = Path(fake_settings.data_dir) / "audio" / "1"
        audio_dir.mkdir(parents=True, exist_ok=True)
        srt_file = audio_dir / "subtitles.srt"
        srt_file.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n",
            encoding="utf-8",
        )

        app = self._make_app(fake_settings)
        fake_project = _make_project(project_id=1)
        fake_scene = _make_scene(order=0, project_id=1, narration="Hello world")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = fake_project
        mock_session.exec.return_value.all.return_value = [fake_scene]

        with patch("server.db.session.get_engine", return_value=MagicMock()):
            with patch("sqlmodel.Session", return_value=mock_session):
                client = TestClient(app)
                response = client.get("/api/projects/1/export/srt?inline=true")

        assert response.status_code == 200
        assert "Hello world" in response.text

    def test_generates_srt_from_narrations_when_no_file(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """When no SRT file exists, generate from scene narrations."""
        from fastapi.testclient import TestClient

        app = self._make_app(fake_settings)
        fake_project = _make_project(project_id=2)
        fake_scene = _make_scene(
            order=0, project_id=2, duration=5.0, narration="Generated subtitle"
        )

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = fake_project
        mock_session.exec.return_value.all.return_value = [fake_scene]

        with patch("server.db.session.get_engine", return_value=MagicMock()):
            with patch("sqlmodel.Session", return_value=mock_session):
                client = TestClient(app)
                response = client.get("/api/projects/2/export/srt?inline=true")

        assert response.status_code == 200
        assert "Generated subtitle" in response.text
        assert "00:00:00,000 --> 00:00:05,000" in response.text

    def test_download_response_has_content_disposition(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """Default (non-inline) response should have Content-Disposition attachment."""
        from fastapi.testclient import TestClient

        app = self._make_app(fake_settings)
        fake_project = _make_project(project_id=3)
        fake_scene = _make_scene(
            order=0, project_id=3, duration=8.0, narration="Download me"
        )

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = fake_project
        mock_session.exec.return_value.all.return_value = [fake_scene]

        with patch("server.db.session.get_engine", return_value=MagicMock()):
            with patch("sqlmodel.Session", return_value=mock_session):
                client = TestClient(app)
                response = client.get("/api/projects/3/export/srt")

        assert response.status_code == 200
        content_disp = response.headers.get("content-disposition", "")
        assert "attachment" in content_disp
        assert ".srt" in content_disp

    def test_returns_422_when_scenes_have_no_narrations(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """When scenes exist but have no narration text, return 422."""
        from fastapi.testclient import TestClient

        app = self._make_app(fake_settings)
        fake_project = _make_project(project_id=4)
        # Scenes with empty narration
        fake_scenes = [
            _make_scene(order=0, project_id=4, narration=""),
            _make_scene(order=1, project_id=4, narration="  "),
        ]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = fake_project
        mock_session.exec.return_value.all.return_value = fake_scenes

        with patch("server.db.session.get_engine", return_value=MagicMock()):
            with patch("sqlmodel.Session", return_value=mock_session):
                client = TestClient(app)
                response = client.get("/api/projects/4/export/srt")

        assert response.status_code == 422

    def test_multiple_scenes_generate_multiple_segments(
        self, fake_settings: MagicMock, tmp_path: Path
    ):
        """Multiple scenes with narrations produce multiple SRT segments."""
        from fastapi.testclient import TestClient

        app = self._make_app(fake_settings)
        fake_project = _make_project(project_id=5)
        fake_scenes = [
            _make_scene(order=0, project_id=5, duration=5.0, narration="First scene"),
            _make_scene(order=1, project_id=5, duration=5.0, narration="Second scene"),
        ]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = fake_project
        mock_session.exec.return_value.all.return_value = fake_scenes

        with patch("server.db.session.get_engine", return_value=MagicMock()):
            with patch("sqlmodel.Session", return_value=mock_session):
                client = TestClient(app)
                response = client.get("/api/projects/5/export/srt?inline=true")

        assert response.status_code == 200
        text = response.text
        assert "First scene" in text
        assert "Second scene" in text
        # Two numbered blocks
        assert "1\n" in text
        assert "2\n" in text
