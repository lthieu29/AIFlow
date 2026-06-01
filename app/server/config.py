"""AIFlow configuration — Pydantic Settings v2.

Env prefix: AIFLOW_
Sub-settings use BaseModel (not BaseSettings) per REVIEW-02 #3.
Root Settings uses a model_validator to manually parse env vars for nested groups.

Usage:
    from server.config import load_settings, Settings, ConfigError
    settings = load_settings()
"""

import os
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Friendly config error raised on startup when required settings are missing or invalid."""
    pass


# ─── Sub-settings: BaseModel (NOT BaseSettings) per REVIEW-02 #3 ─────────────
# Using BaseModel lets the root Settings manually parse env vars with single-underscore
# convention (AIFLOW_GEMINI_API_KEY) instead of double-underscore (AIFLOW_GEMINI__API_KEY).


class GeminiSettings(BaseModel):
    api_key: SecretStr
    model: str = "gemini-2.5-flash"
    vision_model: str = "gemini-2.5-flash"
    timeout: int = 60
    max_retries: int = 3

    @model_validator(mode="after")
    def check_api_key(self) -> "GeminiSettings":
        key = self.api_key.get_secret_value().strip()
        if not key:
            raise ConfigError(
                "AIFLOW_GEMINI_API_KEY is required.\n"
                "Get one (free) at: https://aistudio.google.com/app/apikey\n"
                "Then add to your .env file:\n"
                "    AIFLOW_GEMINI_API_KEY=AIzaSy...\n"
            )
        return self


class FlowSettings(BaseModel):
    plan: Literal["Pro", "Ultra"] = "Pro"
    default_quality: Literal["lite", "fast", "quality"] = "fast"
    default_aspect: Literal["9:16", "16:9"] = "9:16"
    default_duration: int = 8


class WhisperSettings(BaseModel):
    model: Literal["tiny", "base", "small", "medium", "large-v3"] = "medium"
    device: Literal["cpu", "cuda"] = "cpu"
    compute_type: Literal["int8", "float16", "float32"] = "int8"
    model_dir: Path = Path("./storage/models/whisper")


class CookieSettings(BaseModel):
    source: Literal["auto", "manual_file"] = "auto"
    browser: Literal["chrome", "firefox", "edge", "brave"] = "chrome"
    bilibili_file: Path = Path("./storage/cookies/bilibili.txt")
    douyin_file: Path = Path("./storage/cookies/douyin.txt")


class TTSSettings(BaseModel):
    primary: Literal["vieneu", "edge_tts"] = "vieneu"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    quality: Literal["high", "fast"] = "high"

    vieneu_backbone_repo: str = "pnnbao-ump/VieNeu-TTS-v2"
    vieneu_codec_repo: str = "neuphonic/neucodec-onnx-decoder-int8"
    vieneu_default_voice: str = "Binh"
    vieneu_emotion: Literal["natural", "storytelling"] = "natural"
    vieneu_temperature: float = 1.0
    vieneu_use_lmdeploy: bool = True
    vieneu_models_dir: Path = Path("./storage/models/vieneu")

    edge_default_voice: str = "vi-VN-HoaiMyNeural"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_env_for_subsettings(prefix: str) -> dict[str, Any]:
    """Read os.environ entries with AIFLOW_{prefix}_* and return a flat dict.

    Example: prefix='GEMINI' reads AIFLOW_GEMINI_API_KEY → {'api_key': '...'}
    """
    result: dict[str, Any] = {}
    full_prefix = f"AIFLOW_{prefix}_"
    for key, val in os.environ.items():
        if key.upper().startswith(full_prefix):
            field_name = key[len(full_prefix):].lower()
            result[field_name] = val
    return result


def _load_dotenv_into_environ(env_file: str | Path | None = None) -> None:
    """Load a .env file into os.environ using python-dotenv.

    This ensures our model_validator can read all env vars from os.environ,
    regardless of whether they came from the .env file or the shell.

    Args:
        env_file: Path to .env file. Defaults to '.env' in current directory.
    """
    try:
        from dotenv import load_dotenv
        if env_file is not None:
            load_dotenv(dotenv_path=str(env_file), override=False)
        else:
            load_dotenv(override=False)
    except ImportError:
        pass  # python-dotenv not installed; rely on os.environ only


# ─── Root Settings ────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    """Top-level AIFlow configuration.

    Sub-settings (gemini, flow, etc.) are populated via a model_validator that
    manually reads env vars with single-underscore convention (REVIEW-02 #3).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AIFLOW_",
        case_sensitive=False,
        extra="ignore",
    )

    # Server
    host: str = "127.0.0.1"
    port: int = 8101
    ws_port: int = 9223
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    data_dir: Path = Path("./storage")
    debug: bool = False

    # Sub-settings — populated by _build_subsettings validator below
    # Optional so the validator can raise a friendly ConfigError instead of a
    # cryptic pydantic ValidationError when the key is missing.
    gemini: Optional[GeminiSettings] = None
    flow: FlowSettings = Field(default_factory=FlowSettings)
    whisper: WhisperSettings = Field(default_factory=WhisperSettings)
    cookies: CookieSettings = Field(default_factory=CookieSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)

    # Binaries
    ffmpeg_path: Optional[Path] = None
    ffprobe_path: Optional[Path] = None
    aria2c_path: Optional[Path] = None

    # Limits
    max_scenes_per_project: int = 50
    max_video_duration_sec: int = 600
    veo3_daily_budget_credits: int = 100
    max_cascade_per_scene: int = 2
    max_cascade_per_project: int = 5
    gate_user_timeout_hours: int = 24

    # Privacy
    telemetry_enabled: bool = False
    crash_reporting: bool = False

    @model_validator(mode="before")
    @classmethod
    def _build_subsettings(cls, data: Any) -> Any:
        """Build sub-settings dicts from env vars before Pydantic validation.

        Pydantic-settings strips the AIFLOW_ prefix and drops unknown fields
        before calling this validator, so we cannot rely on the data dict for
        sub-settings keys. Instead, we read directly from os.environ (which
        has already been populated by pydantic-settings' dotenv loading).

        REVIEW-02 #3: single-underscore convention (AIFLOW_GEMINI_API_KEY).
        """
        if not isinstance(data, dict):
            return data

        if "gemini" not in data:
            env_data = _parse_env_for_subsettings("GEMINI")
            if env_data:
                data["gemini"] = env_data

        for prefix, attr_name in [
            ("FLOW", "flow"),
            ("WHISPER", "whisper"),
            ("COOKIES", "cookies"),
            ("TTS", "tts"),
        ]:
            if attr_name not in data:
                env_data = _parse_env_for_subsettings(prefix)
                if env_data:
                    data[attr_name] = env_data

        return data

    @model_validator(mode="after")
    def _ensure_data_dir(self) -> "Settings":
        """Auto mkdir -p data_dir if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self

    @model_validator(mode="after")
    def _validate_gemini_required(self) -> "Settings":
        """Fail fast if gemini settings were not provided at all."""
        if self.gemini is None:
            raise ConfigError(
                "AIFLOW_GEMINI_API_KEY is required.\n"
                "Get one (free) at: https://aistudio.google.com/app/apikey\n"
                "Then add to your .env file:\n"
                "    AIFLOW_GEMINI_API_KEY=AIzaSy...\n"
            )
        return self

    @field_validator("ffmpeg_path", "ffprobe_path", "aria2c_path", mode="before")
    @classmethod
    def resolve_binary_path(cls, v: Optional[str]) -> Optional[Path]:
        """Pass-through: auto-resolve vendor/ paths deferred to Phase 1+."""
        if v is None or v == "":
            return None
        return Path(v)


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load settings with friendly error wrapping.

    Loads the .env file into os.environ first (so the model_validator can read
    sub-settings keys), then instantiates Settings.

    Args:
        env_file: Optional path to a .env file. Defaults to '.env'.

    Raises:
        ConfigError: With a human-readable message on missing/invalid config.
    """
    # Load dotenv into os.environ so _build_subsettings can read AIFLOW_GEMINI_* etc.
    _load_dotenv_into_environ(env_file)

    try:
        if env_file is not None:
            return Settings(_env_file=str(env_file))
        return Settings()
    except ConfigError:
        raise
    except Exception as e:
        msg = str(e)
        if "gemini" in msg.lower() or "AIFLOW_GEMINI" in msg.upper():
            raise ConfigError(
                "AIFLOW_GEMINI_API_KEY is required.\n"
                "Get one (free) at: https://aistudio.google.com/app/apikey\n"
                "Then add to your .env file:\n"
                "    AIFLOW_GEMINI_API_KEY=AIzaSy...\n"
            ) from e
        raise ConfigError(f"Config invalid: {msg}") from e
