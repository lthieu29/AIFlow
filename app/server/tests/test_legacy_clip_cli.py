"""Legacy standalone commands fail before creating misleading jobs or fixtures."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from server.cli import aiflow
from server.flow.client import FlowClient


def test_standalone_cli_fails_before_settings_or_database_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(FlowClient, "_instance", None)
    load = MagicMock(side_effect=AssertionError("settings must not be loaded"))
    bootstrap = MagicMock(side_effect=AssertionError("database must not be changed"))
    monkeypatch.setattr("server.config.load_settings", load)
    monkeypatch.setattr("server.db.session.bootstrap_schema", bootstrap)
    image = tmp_path / "start.png"
    image.write_bytes(b"fixture")
    output = tmp_path / "output"
    result = CliRunner().invoke(aiflow, ["gen-clip", "--prompt", "Fixture", "--start-image", str(image),
                                       "--output", str(output)])
    assert result.exit_code == 1
    assert "standalone gen-clip" in result.output
    assert "/production" in result.output
    load.assert_not_called()
    bootstrap.assert_not_called()
    assert not output.exists()


async def test_standalone_smoke_script_fails_before_media_or_remote_calls(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(FlowClient, "_instance", None)
    path = Path(__file__).resolve().parents[2] / "scripts" / "test_gen_clip.py"
    spec = importlib.util.spec_from_file_location("legacy_clip_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(module, "TEMP_IMAGE_PATH", tmp_path / "start.png")
    with pytest.raises(SystemExit) as error:
        await module.main()
    assert error.value.code == 1
    assert "standalone legacy script" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []
