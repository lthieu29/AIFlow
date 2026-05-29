# 01 — Config & Secrets Spec

> **Status**: Draft for review
> **Depends on**: 00-folder-structure
> **Used by**: tất cả module trong `server/`

## Mục đích

Định nghĩa toàn bộ env vars + config file của AIFlow. Đảm bảo:
- Không có secret hardcode trong code
- Mọi default value tường minh
- User chỉ cần edit 1 file `.env` để chạy được
- Validation fail-fast khi missing config quan trọng

## Stack

- **Pydantic Settings v2** (`pydantic-settings`) — validate + load `.env` + override từ env
- **python-dotenv** — load `.env` vào `os.environ`
- **YAML** — chỉ cho `skills/*/manifest.yaml` (config dạng data)

## File `.env.example` (commit vào git)

```dotenv
# =====================================================================
# AIFlow Configuration — copy này thành .env và điền giá trị thật
# =====================================================================

# ─── Server ───────────────────────────────────────────────────────────
AIFLOW_HOST=127.0.0.1
AIFLOW_PORT=8101
AIFLOW_WS_PORT=9223
AIFLOW_LOG_LEVEL=INFO              # DEBUG | INFO | WARNING | ERROR
AIFLOW_DATA_DIR=./storage          # Relative tới app/ hoặc absolute
AIFLOW_DEBUG=false                 # true → reload + verbose

# ─── Google Gemini (free tier qua AI Studio) ─────────────────────────
# Lấy tại https://aistudio.google.com/app/apikey
AIFLOW_GEMINI_API_KEY=
AIFLOW_GEMINI_MODEL=gemini-2.5-flash       # Hoặc gemini-2.5-pro nếu có quota
AIFLOW_GEMINI_VISION_MODEL=gemini-2.5-flash
AIFLOW_GEMINI_TIMEOUT=60                   # giây
AIFLOW_GEMINI_MAX_RETRIES=3

# ─── Google Flow (Veo 3.1) ───────────────────────────────────────────
# AIFLOW không có API key Flow — token được extension capture tự động
# Chỉ cần khai báo plan để dispatch model name đúng:
AIFLOW_FLOW_PLAN=Pro                       # Pro | Ultra
AIFLOW_FLOW_DEFAULT_QUALITY=fast           # lite | fast | quality
AIFLOW_FLOW_DEFAULT_ASPECT=9:16            # 9:16 | 16:9
AIFLOW_FLOW_DEFAULT_DURATION=8             # 8 giây cố định Veo3

# ─── Extension callback security ─────────────────────────────────────
# Agent generate runtime, không phải set tay
# (Extension nhận được khi connect WS, gửi lại trong header X-Callback-Secret)

# ─── TTS (Phase 3) ───────────────────────────────────────────────────
AIFLOW_TTS_PROVIDER=edge                   # edge (free) | azure
AIFLOW_TTS_DEFAULT_VOICE=                  # Bỏ trống = chọn theo skill manifest
AIFLOW_AZURE_TTS_KEY=                      # Optional, chỉ khi provider=azure
AIFLOW_AZURE_TTS_REGION=eastasia

# ─── Whisper (Phase 3) ───────────────────────────────────────────────
AIFLOW_WHISPER_MODEL=medium                # tiny | base | small | medium | large-v3
AIFLOW_WHISPER_DEVICE=cpu                  # cpu | cuda
AIFLOW_WHISPER_COMPUTE_TYPE=int8           # int8 | float16 | float32
AIFLOW_WHISPER_MODEL_DIR=./storage/models/whisper

# ─── FFmpeg / Aria2 paths ────────────────────────────────────────────
# Để trống → tự dò vendor/ffmpeg.exe rồi PATH
AIFLOW_FFMPEG_PATH=
AIFLOW_FFPROBE_PATH=
AIFLOW_ARIA2C_PATH=

# ─── Video Remaster (Phase 4.5) ──────────────────────────────────────
AIFLOW_REMASTER_DEFAULT_PRESET=light       # light | aggressive | translate_only
AIFLOW_REMASTER_TARGET_LANG=vi             # ISO 639-1
AIFLOW_BILIBILI_COOKIES_FILE=./storage/cookies/bilibili.txt
AIFLOW_DOUYIN_COOKIES_FILE=./storage/cookies/douyin.txt
AIFLOW_COOKIE_SOURCE=auto                  # auto | manual_file
                                            # auto = browser-cookie3 (Chrome)
                                            # manual_file = đọc cookies.txt
AIFLOW_BROWSER_COOKIE_BROWSER=chrome       # chrome | firefox | edge | brave

# ─── Playwright (Phase 3.5 visual layer) ─────────────────────────────
AIFLOW_PLAYWRIGHT_BROWSERS_PATH=./storage/playwright

# ─── Pipeline limits ─────────────────────────────────────────────────
AIFLOW_MAX_SCENES_PER_PROJECT=50           # Hard limit, ngăn over-spend
AIFLOW_MAX_VIDEO_DURATION_SEC=600          # 10 phút
AIFLOW_VEO3_DAILY_BUDGET_CREDITS=100       # Pro plan = 100 credits/day
AIFLOW_FAL_API_KEY=                        # Optional fallback nếu Flow chết

# ─── Telemetry / Privacy ─────────────────────────────────────────────
AIFLOW_TELEMETRY_ENABLED=false             # KHÔNG gửi telemetry ra ngoài
AIFLOW_CRASH_REPORTING=false
```

## File `.env` thật (KHÔNG commit, gitignore)

User copy `.env.example` thành `.env`, điền 2-3 giá trị bắt buộc:
- `AIFLOW_GEMINI_API_KEY`
- `AIFLOW_FLOW_PLAN` (Pro hoặc Ultra)

Còn lại đều có default hợp lý.

## Pydantic Settings class

> **REVIEW-02 #3 — Pydantic nested `BaseSettings` không load đúng env prefix**.
> Nested `BaseSettings` với `env_nested_delimiter="__"` mong đợi `AIFLOW_GEMINI__API_KEY` (2 gạch),
> nhưng `.env.example` dùng `AIFLOW_GEMINI_API_KEY` (1 gạch) — convention quen thuộc cho user.
>
> **Solution**: sub-settings dùng `BaseModel` (regular Pydantic), KHÔNG `BaseSettings`. Root
> `Settings(BaseSettings)` custom `model_validator(mode='before')` đọc env vars thủ công và build
> nested dict — toàn quyền control prefix mapping.

```python
# server/config.py — SPEC ONLY, KHÔNG implement ở Phase 0
import os
from pathlib import Path
from typing import Literal, Optional, Any
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Friendly config errors (REVIEW-01 #5)."""
    pass


# ─── Sub-settings DÙNG BaseModel, KHÔNG BaseSettings (REVIEW-02 #3) ─────
class FlowSettings(BaseModel):
    plan: Literal["Pro", "Ultra"] = "Pro"
    default_quality: Literal["lite", "fast", "quality"] = "fast"
    default_aspect: Literal["9:16", "16:9"] = "9:16"
    default_duration: int = 8


class GeminiSettings(BaseModel):
    api_key: SecretStr
    model: str = "gemini-2.5-flash"
    vision_model: str = "gemini-2.5-flash"
    timeout: int = 60
    max_retries: int = 3
    
    @model_validator(mode="after")
    def check_api_key(self) -> "GeminiSettings":
        if not self.api_key.get_secret_value().strip():
            raise ConfigError(
                "AIFLOW_GEMINI_API_KEY is required.\n"
                "Get one (free) at: https://aistudio.google.com/app/apikey\n"
                "Then add to your .env file:\n"
                "    AIFLOW_GEMINI_API_KEY=AIzaSy...\n"
            )
        if not self.api_key.get_secret_value().startswith("AIza"):
            import warnings
            warnings.warn(
                "AIFLOW_GEMINI_API_KEY does not start with 'AIza' — "
                "this may not be a valid Google API key. Continuing anyway."
            )
        return self


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
    """REVIEW-02 #1 — Phase 3 TTS config (placeholder Phase 0)."""
    primary: Literal["vieneu", "edge_tts"] = "vieneu"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    quality: Literal["high", "fast"] = "high"
    
    vieneu_backbone_repo: str = "pnnbao-ump/VieNeu-TTS-v2"
    vieneu_codec_repo: str = "neuphonic/neucodec-onnx-decoder-int8"
    vieneu_default_voice: str = "Binh"
    vieneu_emotion: Literal["natural", "storytelling"] = "natural"
    vieneu_temperature: float = 1.0
    vieneu_use_lmdeploy: bool = True              # Python 3.12 mặc định OK
    vieneu_models_dir: Path = Path("./storage/models/vieneu")
    
    edge_default_voice: str = "vi-VN-HoaiMyNeural"


# ─── Root Settings — CHỈ class này dùng BaseSettings ─────────────────
def _parse_env_for_subsettings(prefix: str) -> dict[str, Any]:
    """REVIEW-02 #3 — Đọc os.environ với prefix `AIFLOW_{prefix}_*` thành dict.
    
    VD prefix='GEMINI' → đọc AIFLOW_GEMINI_API_KEY, AIFLOW_GEMINI_MODEL, ...
    Trả về {'api_key': '...', 'model': '...', ...} cho Pydantic build sub-model.
    """
    result = {}
    full_prefix = f"AIFLOW_{prefix}_"
    for key, val in os.environ.items():
        if not key.startswith(full_prefix):
            continue
        field_name = key[len(full_prefix):].lower()
        result[field_name] = val
    return result


class Settings(BaseSettings):
    """Top-level config. Sub-settings là BaseModel build từ env vars thủ công."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AIFLOW_",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Server (top-level — auto load từ AIFLOW_HOST, AIFLOW_PORT, ...)
    host: str = "127.0.0.1"
    port: int = 8101
    ws_port: int = 9223
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    data_dir: Path = Path("./storage")
    debug: bool = False
    
    # Sub-settings — populate qua model_validator dưới đây
    flow: FlowSettings = Field(default_factory=FlowSettings)
    gemini: GeminiSettings = Field(default=None)        # type: ignore[assignment]
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
        """REVIEW-02 #3 — Build sub-settings từ env vars trước khi validate.
        
        Mỗi sub-settings có prefix riêng:
        - AIFLOW_GEMINI_*     → gemini.{field}
        - AIFLOW_FLOW_*       → flow.{field}
        - AIFLOW_WHISPER_*    → whisper.{field}
        - AIFLOW_COOKIES_*    → cookies.{field}
        - AIFLOW_TTS_*        → tts.{field}
        """
        if not isinstance(data, dict):
            return data
        
        # Build từng sub-settings nếu chưa có trong data (chưa pass thủ công)
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
    
    @field_validator("ffmpeg_path", "ffprobe_path", "aria2c_path", mode="before")
    @classmethod
    def resolve_binary_path(cls, v: Optional[str]) -> Optional[Path]:
        """Auto-resolve: nếu None → dò vendor/ rồi PATH."""
        return v


def load_settings() -> Settings:
    """Load với friendly error wrapping."""
    try:
        return Settings()
    except ConfigError:
        raise
    except Exception as e:
        msg = str(e)
        if "AIFLOW_GEMINI" in msg.upper() or "gemini" in msg.lower():
            raise ConfigError(
                "AIFLOW_GEMINI_API_KEY is required.\n"
                "Get one (free) at: https://aistudio.google.com/app/apikey\n"
                "Then add to your .env file:\n"
                "    AIFLOW_GEMINI_API_KEY=AIzaSy...\n"
            ) from e
        raise ConfigError(f"Config invalid: {msg}") from e
```

### Test plan cho Pydantic env loading (REVIEW-02 #3)

Phase 0 task 0.3 phải verify ngay với 3 case:

```python
# tests/test_config_env.py — chạy trong task 0.3
import os
from server.config import Settings, load_settings

def test_flat_env_loads():
    """AIFLOW_GEMINI_API_KEY (1 gạch) phải load vào settings.gemini.api_key."""
    os.environ["AIFLOW_GEMINI_API_KEY"] = "AIzaTest"
    s = load_settings()
    assert s.gemini.api_key.get_secret_value() == "AIzaTest"

def test_nested_field_default():
    """Sub-settings có field default vẫn work."""
    os.environ["AIFLOW_GEMINI_API_KEY"] = "AIzaTest"
    s = load_settings()
    assert s.gemini.model == "gemini-2.5-flash"  # default

def test_top_level_field():
    """Top-level vẫn load bình thường."""
    os.environ["AIFLOW_GEMINI_API_KEY"] = "AIzaTest"
    os.environ["AIFLOW_PORT"] = "9000"
    s = load_settings()
    assert s.port == 9000
```

Test này **bắt buộc pass** trước khi đi Phase 0 task 0.4.

### Startup fail-fast (REVIEW-01 #5)

`server/main.py`:
```python
def main():
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)
    
    # Continue startup
    bootstrap_schema(settings)
    uvicorn.run(...)
```

→ Lỗi config hiển thị ngay, exit code 2, không bind port.

## Validation rules (fail-fast lúc startup)

| Check | Hành động nếu fail |
|-------|---------------------|
| `gemini.api_key` empty | Raise `ConfigError`, exit code 2 |
| `gemini.api_key` không có format `AIza...` | Warning + retry với call thực |
| `flow.plan` không phải Pro/Ultra | Raise ngay |
| `data_dir` không tồn tại | Tự `mkdir -p` |
| `ffmpeg_path` resolve không thấy | Raise nếu cần FFmpeg (Phase 1+); ignore Phase 0 |
| `whisper.device=cuda` nhưng không có CUDA | Warning + fallback CPU |
| Port `8101` hoặc `9223` đã occupied | Raise với hướng dẫn đổi port |

## Cookie config flow chi tiết (per user choice)

User confirmed: **ưu tiên auto đọc Chrome, có ô paste tay**.

```
Startup:
  1. AIFLOW_COOKIE_SOURCE=auto
  2. Try browser-cookie3 read Chrome cookies for {bilibili.com, douyin.com}
     ├── Success → in-memory cache, label "auto"
     └── Fail (Chrome locked / no cookies) → silent fallback to manual_file
  
  3. Manual file fallback:
     ├── File exists → load Netscape format → in-memory cache, label "manual"
     └── File missing → empty cookie jar, label "none"

Per request:
  - Try in-memory cookies
  - If 401/-101 (Bilibili) or msToken expired (Douyin):
    - Re-trigger browser-cookie3 read (Chrome có thể đã refresh cookie)
    - Nếu vẫn fail → emit event "cookie_expired" qua WS → UI prompt user
```

UI có 3 button:
- **Auto Refresh** — re-read Chrome cookies (đóng Chrome trước)
- **Paste Manual** — textarea cho user paste cookie string
- **Open Cookie Sniffer Extension** — gọi extension cookie module (xem spec 04)

## Secret handling rules

1. **`SecretStr`** cho mọi field nhạy cảm (api_key, password) — không log raw
2. **`.env` không bao giờ commit** — `.gitignore` có sẵn
3. **`storage/cookies/*` không bao giờ commit** — sensitive PII
4. **Log lúc load config**: chỉ log key names, không log values
5. **Endpoint `/api/health`**: trả "config_loaded": true, không reveal value
6. **Callback secret cho extension**: generate runtime bằng `secrets.token_urlsafe(32)`, không persist

## Environment-specific overrides

Pydantic Settings hỗ trợ `.env.local`, `.env.test`. Convention:

```
.env              ← Dev default (commit .env.example, không commit .env)
.env.local        ← Override local (gitignore)
.env.test         ← Cho pytest (commit, dùng dummy values)
```

`AIFLOW_DEBUG=true` enable:
- Uvicorn `--reload`
- Log level → DEBUG
- FastAPI `/docs` enabled
- Pretty traceback

## Acceptance criteria cho spec này

- [ ] User mới đọc `.env.example` biết cần điền gì
- [ ] Mọi env var đều có default trừ 2 cái BẮT BUỘC user điền
- [ ] Validation fail-fast với message rõ ràng
- [ ] Không có secret hardcode bất kỳ đâu
- [ ] Cookie strategy auto + manual fallback rõ ràng
- [ ] Spec này đủ chi tiết để 1 người khác implement `config.py` mà không hỏi thêm

## Phase mapping

| Field | Cần ở Phase |
|-------|-------------|
| `gemini.*` | 1 |
| `flow.*` | 1 |
| `whisper.*` | 3 |
| `cookies.*` | 4.5 |
| `playwright.*` | 3.5 |
| `tts.*` | 3 |

Phase 0 chỉ cần: `host`, `port`, `ws_port`, `data_dir`, `gemini.api_key`, `flow.plan`.
