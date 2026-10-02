"""Security tests for server/api/safe_files.py — path-traversal prevention.

These tests prove the file-serving guard blocks any attempt to read files
outside the allowed base directory (the core requirement: a client must never
be able to read unauthorised files such as cookies or the DB).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import HTTPException

from server.api.safe_files import safe_file_or_404, safe_resolve


class TestSafeResolve:
    def test_allows_path_inside_base(self, tmp_path):
        base = tmp_path / "output"
        base.mkdir()
        result = safe_resolve(base, "proj1", "final.mp4")
        assert result == (base / "proj1" / "final.mp4").resolve()

    def test_blocks_parent_traversal(self, tmp_path):
        base = tmp_path / "output"
        base.mkdir()
        (tmp_path / "secret.txt").write_text("cookies!")
        with pytest.raises(HTTPException) as exc:
            safe_resolve(base, "..", "secret.txt")
        assert exc.value.status_code == 403

    def test_blocks_deep_traversal(self, tmp_path):
        base = tmp_path / "voice_gallery"
        base.mkdir()
        with pytest.raises(HTTPException) as exc:
            safe_resolve(base, "../../cookies/bilibili.txt")
        assert exc.value.status_code == 403

    def test_blocks_absolute_escape(self, tmp_path):
        base = tmp_path / "output"
        base.mkdir()
        # An absolute-looking segment must not escape the base.
        with pytest.raises(HTTPException) as exc:
            safe_resolve(base, "C:\\Windows\\System32\\drivers\\etc\\hosts")
        assert exc.value.status_code == 403

    def test_blocks_nul_byte(self, tmp_path):
        base = tmp_path / "output"
        base.mkdir()
        with pytest.raises(HTTPException) as exc:
            safe_resolve(base, "proj\x00.mp4")
        assert exc.value.status_code == 403

    def test_nested_subdir_allowed(self, tmp_path):
        base = tmp_path / "gallery"
        base.mkdir()
        result = safe_resolve(base, "voice1", "demo.mp3")
        assert result.is_relative_to(base.resolve())


class TestSafeFileOr404:
    def test_returns_existing_file(self, tmp_path):
        base = tmp_path / "output"
        (base / "p1").mkdir(parents=True)
        f = base / "p1" / "final.mp4"
        f.write_bytes(b"data")
        assert safe_file_or_404(base, "p1", "final.mp4") == f.resolve()

    def test_404_when_missing(self, tmp_path):
        base = tmp_path / "output"
        base.mkdir()
        with pytest.raises(HTTPException) as exc:
            safe_file_or_404(base, "p1", "final.mp4")
        assert exc.value.status_code == 404

    def test_403_on_traversal_even_if_target_exists(self, tmp_path):
        base = tmp_path / "output"
        base.mkdir()
        secret = tmp_path / "cookies.txt"
        secret.write_text("SESSDATA=secret")
        # Target exists but is outside base → must be 403, never served.
        with pytest.raises(HTTPException) as exc:
            safe_file_or_404(base, "..", "cookies.txt")
        assert exc.value.status_code == 403
