"""Tests for server/config.py — Pydantic Settings env loading.

Covers the 3 cases required by spec 01 / REVIEW-02 #3:
  Case 1: AIFLOW_GEMINI_API_KEY (single underscore) loads correctly
  Case 2: .env file values are loaded (dotenv integration)
  Case 3: Missing key raises ConfigError clearly
"""

import os
import tempfile
from pathlib import Path

import pytest

# Ensure we can import from the server package regardless of cwd
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _clean_env(*keys: str) -> None:
    """Remove env vars so tests start from a clean state."""
    for k in keys:
        os.environ.pop(k, None)


# ─── Case 1: Single-underscore env var loads into nested settings ─────────────

def test_flat_env_key_loads(tmp_path, monkeypatch):
    """AIFLOW_GEMINI_API_KEY (1 underscore) must load into settings.gemini.api_key."""
    monkeypatch.setenv("AIFLOW_GEMINI_API_KEY", "AIzaTestKey123")
    # Point data_dir to tmp so mkdir doesn't pollute cwd
    monkeypatch.setenv("AIFLOW_DATA_DIR", str(tmp_path / "storage"))

    from server.config import load_settings
    s = load_settings()

    assert s.gemini.api_key.get_secret_value() == "AIzaTestKey123"


def test_flat_env_nested_default_preserved(tmp_path, monkeypatch):
    """Sub-settings fields not in env should keep their defaults."""
    monkeypatch.setenv("AIFLOW_GEMINI_API_KEY", "AIzaTestKey123")
    monkeypatch.setenv("AIFLOW_DATA_DIR", str(tmp_path / "storage"))

    from server.config import load_settings
    s = load_settings()

    assert s.gemini.model == "gemini-2.5-flash"
    assert s.gemini.timeout == 60


def test_top_level_field_loads(tmp_path, monkeypatch):
    """Top-level AIFLOW_PORT must still load correctly alongside nested settings."""
    monkeypatch.setenv("AIFLOW_GEMINI_API_KEY", "AIzaTestKey123")
    monkeypatch.setenv("AIFLOW_PORT", "9000")
    monkeypatch.setenv("AIFLOW_DATA_DIR", str(tmp_path / "storage"))

    from server.config import load_settings
    s = load_settings()

    assert s.port == 9000


def test_flow_settings_load(tmp_path, monkeypatch):
    """AIFLOW_FLOW_PLAN must load into settings.flow.plan."""
    monkeypatch.setenv("AIFLOW_GEMINI_API_KEY", "AIzaTestKey123")
    monkeypatch.setenv("AIFLOW_FLOW_PLAN", "Ultra")
    monkeypatch.setenv("AIFLOW_DATA_DIR", str(tmp_path / "storage"))

    from server.config import load_settings
    s = load_settings()

    assert s.flow.plan == "Ultra"


# ─── Case 2: .env file is loaded ─────────────────────────────────────────────

def test_dotenv_file_is_loaded(tmp_path, monkeypatch):
    """.env file values must be loaded by Pydantic Settings."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"AIFLOW_GEMINI_API_KEY=AIzaFromDotEnv\n"
        f"AIFLOW_DATA_DIR={tmp_path / 'storage'}\n"
    )

    # Remove any existing env var so .env file is the only source
    monkeypatch.delenv("AIFLOW_GEMINI_API_KEY", raising=False)

    # load_settings(env_file=...) loads the dotenv file into os.environ first,
    # then instantiates Settings — this is the correct way to test dotenv loading.
    from server.config import load_settings
    s = load_settings(env_file=env_file)
    assert s.gemini.api_key.get_secret_value() == "AIzaFromDotEnv"


def test_dotenv_file_port_override(tmp_path, monkeypatch):
    """.env file port value must override the default."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"AIFLOW_GEMINI_API_KEY=AIzaFromDotEnv\n"
        f"AIFLOW_PORT=7777\n"
        f"AIFLOW_DATA_DIR={tmp_path / 'storage'}\n"
    )

    monkeypatch.delenv("AIFLOW_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AIFLOW_PORT", raising=False)

    from server.config import load_settings
    s = load_settings(env_file=env_file)
    assert s.port == 7777


# ─── Case 3: Missing key raises ConfigError ───────────────────────────────────

def test_missing_api_key_raises_config_error(tmp_path, monkeypatch):
    """Missing AIFLOW_GEMINI_API_KEY must raise ConfigError with a clear message."""
    monkeypatch.delenv("AIFLOW_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("AIFLOW_DATA_DIR", str(tmp_path / "storage"))

    from server.config import load_settings, ConfigError

    with pytest.raises(ConfigError) as exc_info:
        load_settings()

    error_msg = str(exc_info.value)
    assert "AIFLOW_GEMINI_API_KEY" in error_msg


def test_empty_api_key_raises_config_error(tmp_path, monkeypatch):
    """Empty AIFLOW_GEMINI_API_KEY must raise ConfigError."""
    monkeypatch.setenv("AIFLOW_GEMINI_API_KEY", "")
    monkeypatch.setenv("AIFLOW_DATA_DIR", str(tmp_path / "storage"))

    from server.config import load_settings, ConfigError

    with pytest.raises(ConfigError):
        load_settings()


def test_config_error_message_is_helpful(tmp_path, monkeypatch):
    """ConfigError message must mention where to get an API key."""
    monkeypatch.delenv("AIFLOW_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("AIFLOW_DATA_DIR", str(tmp_path / "storage"))

    from server.config import load_settings, ConfigError

    with pytest.raises(ConfigError) as exc_info:
        load_settings()

    error_msg = str(exc_info.value)
    # Should guide the user to get a key
    assert "aistudio.google.com" in error_msg or ".env" in error_msg


# ─── data_dir auto-creation ───────────────────────────────────────────────────

def test_data_dir_is_created_if_missing(tmp_path, monkeypatch):
    """Settings must auto-create data_dir if it doesn't exist."""
    new_dir = tmp_path / "new_storage_dir"
    assert not new_dir.exists()

    monkeypatch.setenv("AIFLOW_GEMINI_API_KEY", "AIzaTestKey123")
    monkeypatch.setenv("AIFLOW_DATA_DIR", str(new_dir))

    from server.config import load_settings
    s = load_settings()

    assert new_dir.exists()
    assert s.data_dir == new_dir
