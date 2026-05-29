# 02 — Database Schema Spec

> **Status**: Draft for review
> **Depends on**: 00-folder-structure, 05-content-adapter (interface)
> **Used by**: tất cả module persist state

## Mục đích

Định nghĩa toàn bộ table SQLite cho AIFlow. Schema phải:
- Hỗ trợ multi-project, mỗi project là 1 video độc lập
- Track được mọi asset (character/product/location ref images)
- Track được mọi job (Veo3 gen, TTS, transcribe, render)
- Cho phép resume sau crash (job có state machine rõ ràng)
- Cho phép re-gen 1 scene mà không animate lại từ đầu

## Stack

- **SQLite 3** (built-in Python, không cần server riêng)
- **SQLModel** (Pydantic + SQLAlchemy 2.0) — type-safe ORM
- **Alembic** — migrations từ Phase 1 trở đi (Phase 0 chỉ tạo schema raw)
- File: `storage/projects.db`

## ERD overview

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Project  │────<│ Scene    │     │ Asset    │
│          │     │          │     │          │
│ id       │     │ project  │  ┌─>│ project  │
│ title    │     │ order    │  │  │ name     │
│ skill_id │     │ duration │  │  │ type     │
│ aspect   │     │ status   │  │  │ ref_url  │
│ adapter  │     │ ...      │  │  │ ...      │
└────┬─────┘     └────┬─────┘  │  └──────────┘
     │                │        │
     │           ┌────▼────────┴───┐
     │           │ SceneAsset      │  (many-to-many)
     │           │ scene_id        │
     │           │ asset_id        │
     │           │ role            │  (main_character | product | bg_location)
     │           └─────────────────┘
     │
     │           ┌──────────┐     ┌──────────┐
     │           │ Job      │     │ JobLog   │
     │           │          │     │          │
     │           │ id       │<────│ job_id   │
     │           │ scene_id?│     │ ts       │
     │           │ asset_id?│     │ level    │
     │           │ type     │     │ message  │
     │           │ status   │     │          │
     │           │ params   │     └──────────┘
     │           │ result   │
     │           │ error    │
     │           └──────────┘
     │
     │           ┌──────────┐
     └──────────>│ Style    │
                 │ project  │
                 │ json     │   (Lớp 1 continuity — style.json)
                 └──────────┘

┌──────────┐     ┌──────────┐
│ Config   │     │ Cookie   │
│ key      │     │ platform │
│ value    │     │ data     │
│          │     │ exp      │
└──────────┘     └──────────┘
```

## Bảng chi tiết

### Bảng `project`

```python
class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    short_id: str = Field(index=True, unique=True)        # Vd: "p_a3f9"
    title: str
    description: Optional[str] = None
    
    # Adapter info
    adapter_name: str                                       # "ecommerce_product" | "video_remaster" | ...
    adapter_input: dict = Field(sa_column=Column(JSON))     # Raw input cho adapter
    
    # Skill + style
    skill_id: str                                           # "ecommerce-fashion"
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    target_duration_sec: Optional[float] = None             # Target duration (TTS-driven)
    
    # State
    status: Literal[
        "draft",          # Just created, no scenes yet
        "parsing",        # Adapter đang parse input
        "ready",          # SceneList ready, chờ user click "Generate"
        "generating",     # Đang gen scenes
        "composing",      # Đang merge final video
        "done",           # Có final.mp4
        "failed",         # Có failure không recover được
        "archived",       # User archive
    ] = "draft"
    
    # Output
    output_path: Optional[str] = None                       # Relative tới storage/output/
    
    # Cascade tracking (REVIEW-01 #3 — bounded cascade)
    cascade_event_count: int = 0                            # Toàn project max 5 cascade events
    
    # Timestamps
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None
```

### Bảng `style`

```python
class Style(SQLModel, table=True):
    """Lớp 1 — style lock per project. 1 project = 1 row."""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True, unique=True)
    
    # Loaded từ skills/{skill_id}/style.json + có thể override per project
    style_json: dict = Field(sa_column=Column(JSON))
    
    # Cached prompts
    prefix_text: str                                        # prepend mọi shot prompt
    camera_lock: Literal["static", "dynamic"] = "static"
    
    # Voice config
    voice_id: Optional[str] = None                          # vi-VN-HoaiMyNeural | ...
```

### Bảng `asset`

```python
class Asset(SQLModel, table=True):
    """Lớp 2 — character/product/location ref. Reusable xuyên scenes."""
    id: Optional[int] = Field(default=None, primary_key=True)
    short_id: str = Field(index=True)                       # "a_x7p2"
    project_id: int = Field(foreign_key="project.id", index=True)
    
    name: str                                                # "Hùng" | "Áo trắng" | "Quán cafe"
    type: Literal["character", "product", "location", "object"]
    description: str                                         # Cho LLM
    
    # Generation
    ref_prompt: Optional[str] = None                         # Prompt sinh ref image
    ref_media_id: Optional[str] = None                       # Veo3 mediaId
    ref_local_path: Optional[str] = None                     # Local cached path
    ref_url: Optional[str] = None                            # Original CDN URL (TTL 1h)
    
    # Status
    status: Literal[
        "pending",        # Chờ gen
        "generating",     # Đang gen ref image
        "ready",          # Có ref image, dùng được
        "failed",         # Gen fail
        "user_uploaded",  # User upload trực tiếp, skip gen
    ] = "pending"
    
    # Aliases (cho epub: "anh", "anh ấy", "Hùng An" cùng 1 character)
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    
    # Source tracking
    first_appearance_scene_id: Optional[int] = None
    
    created_at: datetime = Field(default_factory=utcnow)
```

### Bảng `scene`

```python
class Scene(SQLModel, table=True):
    """Lớp 3 — 1 scene = 1 clip Veo3 8s."""
    id: Optional[int] = Field(default=None, primary_key=True)
    short_id: str = Field(index=True)                       # "s_k3j8"
    project_id: int = Field(foreign_key="project.id", index=True)
    order: int                                               # 0, 1, 2, ...
    
    # Content
    duration_sec: float                                      # Default 8 (Veo3 fixed)
    narration: str                                           # Text TTS
    visual_prompt: str                                       # Final prompt cho Veo3 (sau khi áp dụng continuity)
    visual_prompt_raw: Optional[str] = None                  # Prompt thô từ adapter (trước continuity)
    
    # Camera + motion
    camera: Literal["static", "dynamic"] = "static"
    motion_hint: Optional[str] = None                        # "half-step → glance → hair-tuck"
    
    # Continuity refs (Lớp 3)
    prev_last_frame_path: Optional[str] = None               # Frame cuối scene N-1
    start_image_media_id: Optional[str] = None               # Cho Veo3 i2v
    
    # Generation
    video_media_id: Optional[str] = None                     # Veo3 video mediaId
    video_local_path: Optional[str] = None
    video_url: Optional[str] = None                          # Original CDN URL
    last_frame_path: Optional[str] = None                    # Extracted frame cuối (cho scene N+1)
    
    # Overlay (cho visual layer)
    overlay: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    # vd: {type:"lower_third", text:"Hùng", duration:5.0, start_offset:1.0}
    
    # Status
    status: Literal[
        "pending",
        "generating",
        "ready",
        "failed",
        "user_skipped",
    ] = "pending"
    
    retry_count: int = 0                                     # Auto-retry max 2 lần
    cascade_retry_count: int = 0                             # Số lần scene bị reset do upstream cascade (REVIEW-01 #3, max 2)
    
    created_at: datetime = Field(default_factory=utcnow)
```

### Bảng `scene_asset` (many-to-many)

```python
class SceneAsset(SQLModel, table=True):
    """Mỗi scene dùng những asset nào (refs cho Veo3).
    
    REVIEW-01 #6 — composite PK + 2 single-column indexes để query 2 chiều nhanh:
    - "asset nào trong scene X?" → (scene_id) index
    - "scene nào dùng asset Y?" → (asset_id) index
    """
    __table_args__ = (
        Index("ix_sceneasset_scene", "scene_id"),
        Index("ix_sceneasset_asset", "asset_id"),
    )
    
    scene_id: int = Field(foreign_key="scene.id", primary_key=True)
    asset_id: int = Field(foreign_key="asset.id", primary_key=True)
    role: Literal["main_character", "product", "bg_location", "extra"] = "extra"
    metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # metadata.variant_idx — pin variant nào (0-3) khi asset có 4 variants
```

### Bảng `job`

```python
class Job(SQLModel, table=True):
    """In-process worker queue, persistent qua restart."""
    id: Optional[int] = Field(default=None, primary_key=True)
    short_id: str = Field(index=True)                       # "j_..."
    project_id: int = Field(foreign_key="project.id", index=True)
    
    # Target
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id")
    asset_id: Optional[int] = Field(default=None, foreign_key="asset.id")
    
    # Type
    type: Literal[
        "gen_image",       # Gen ref image cho asset
        "gen_video",       # Gen video cho scene
        "tts",             # TTS audio cho project
        "transcribe",      # Whisper transcribe
        "compose",         # Final ffmpeg merge
        "remaster",        # Stage 3 remaster filters
        "download",        # Bilibili/Douyin download
        "translate",       # Subtitle translate
    ]
    
    # State
    status: Literal[
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "retrying",
    ] = "queued"
    
    priority: int = 0                                        # Lower = high priority
    
    # Payload
    params: dict = Field(default_factory=dict, sa_column=Column(JSON))
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: Optional[str] = None
    error_code: Optional[str] = None                         # Vd: "FLOW_403", "QUOTA_EXCEEDED"
    
    # Timing
    created_at: datetime = Field(default_factory=utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    
    # Retry
    retry_count: int = 0
    max_retries: int = 2
```

### Bảng `job_log`

```python
class JobLog(SQLModel, table=True):
    """Per-job detailed log. Append-only, có thể truncate sau N ngày."""
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    ts: datetime = Field(default_factory=utcnow)
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"] = "INFO"
    message: str
    extra: dict = Field(default_factory=dict, sa_column=Column(JSON))
```

### Bảng `quality_gate`

```python
class QualityGate(SQLModel, table=True):
    """Track G1-G6 results per project (xem docs/07)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    gate: Literal["G1", "G2", "G3", "G4", "G5", "G6"]
    target_id: Optional[int] = None                          # scene_id hoặc asset_id
    target_type: Optional[Literal["scene", "asset", "project"]] = None
    
    status: Literal["pending", "pass", "fail", "manual_override"] = "pending"
    score: Optional[float] = None                            # 0-1 nếu có metric (REVIEW-02 #8 — reserved cho LLM judge G1.8/G3.9 + face confidence G2.4)
    reason: Optional[str] = None                             # Why fail
    
    # SLA cho manual gates (REVIEW-01 #7)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: Optional[datetime] = None                    # Manual gates có deadline
    snooze_count: int = 0                                    # User snooze bao nhiêu lần
    
    actioned_at: Optional[datetime] = None
    actioned_by: Literal["auto", "user", "auto_timeout"] = "auto"
```

### Bảng `cookie`

```python
class Cookie(SQLModel, table=True):
    """Persist cookies per platform. Encrypted optional."""
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: Literal["bilibili", "douyin", "tiktok", "youtube"] = Field(unique=True, index=True)
    
    # Storage
    cookie_string: str                                       # "key1=val1; key2=val2; ..."
    source: Literal["auto", "manual", "extension"]
    
    # Validity
    captured_at: datetime = Field(default_factory=utcnow)
    expires_at: Optional[datetime] = None                    # Estimate (Bilibili 30d)
    last_used_at: Optional[datetime] = None
    last_validated_at: Optional[datetime] = None
    is_valid: bool = True
```

### Bảng `config`

```python
class Config(SQLModel, table=True):
    """Runtime mutable config (không phải .env). Vd: Veo3 daily credits used."""
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=utcnow)
    
# Khoá quan trọng:
# - "veo3_credits_used_today" : "37"
# - "veo3_credits_reset_at"   : "2026-05-27T00:00:00Z"
# - "extension_callback_secret" : "abc..." (regenerated each restart)
# - "schema_version" : "1"
```

## Indexes

| Bảng | Index | Lý do |
|------|-------|-------|
| `project` | `short_id` UNIQUE | Lookup public id |
| `project` | `status` | Filter list active projects |
| `asset` | `project_id` | Foreign key |
| `asset` | `short_id` | Lookup |
| `asset` | `(project_id, type)` | List characters per project |
| `scene` | `project_id` | Foreign key |
| `scene` | `(project_id, order)` UNIQUE | Đảm bảo order distinct |
| `scene_asset` | `(scene_id, asset_id)` PK composite | M:N junction (REVIEW-01 #6) |
| `scene_asset` | `scene_id` | Lookup "asset nào trong scene X" |
| `scene_asset` | `asset_id` | Lookup "scene nào dùng asset Y" |
| `job` | `(status, priority, created_at)` | Worker queue pull |
| `job` | `project_id` | List jobs per project |
| `job` | `scene_id`, `asset_id` | Lookup ngược |
| `job_log` | `(job_id, ts)` | Time-ordered logs |

## State machines

### Project status

```
draft → parsing → ready → generating → composing → done
                              │
                              ↓
                            failed (recoverable)
                              │
                              ↓
                            user retry → generating
```

### Scene status

```
pending → generating → ready
              │
              ↓ (max 2 retries)
            failed
              │
              ↓
        user_skipped (skip này, render thiếu scene)
```

### Job status

```
queued → running → succeeded
            │
            ↓
          failed → retrying → running
            │         │
            │         ↓ (max retries)
            │       failed (final)
            │
            ↓
        cancelled (user)
```

## Bootstrap & migration strategy

### Vấn đề review (REVIEW-01 #1)

`storage/` gitignored → `projects.db` không có sẵn lúc clone repo. Phase 0 cần bootstrap DB schema lần đầu, không có nó pipeline crash ngay khi gọi DB.

### Phase 0 — Bootstrap rõ ràng trong startup

`server/db/session.py`:

```python
from pathlib import Path
from sqlmodel import SQLModel, create_engine
from server.config import Settings

_engine = None

def get_engine(settings: Settings):
    global _engine
    if _engine is None:
        db_path = settings.data_dir / "projects.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            echo=settings.debug,
        )
    return _engine

def bootstrap_schema(settings: Settings):
    """Phase 0-1: dùng SQLModel.metadata.create_all().
    Idempotent — chạy lại không lỗi nếu schema đã tồn tại.
    Set schema_version vào bảng Config sau khi tạo xong.
    
    REVIEW-02 #4 — Import order critical: phải import TẤT CẢ models trước
    create_all() để SQLModel.metadata.tables registry đầy đủ.
    """
    # CRITICAL: import models package, KHÔNG import 1 file lẻ.
    # __init__.py re-export mọi class → mọi table register vào metadata.
    from server.db import models  # noqa: F401
    
    engine = get_engine(settings)
    SQLModel.metadata.create_all(engine)
    
    # Set schema version
    from sqlmodel import Session, select
    with Session(engine) as session:
        existing = session.exec(
            select(models.Config).where(models.Config.key == "schema_version")
        ).first()
        if existing is None:
            session.add(models.Config(key="schema_version", value="1"))
            session.commit()
```

### Models package layout (REVIEW-02 #4)

```
server/db/models/
├── __init__.py              ← Re-export TẤT CẢ classes
├── project.py               ← class Project
├── job.py                   ← class Job, class JobLog
├── config.py                ← class Config
└── (Phase 2+) scene.py, asset.py, scene_asset.py, style.py, quality_gate.py, cookie.py
```

`server/db/models/__init__.py`:

```python
"""Models package — re-export mọi SQLModel class.

CRITICAL: bootstrap_schema() phụ thuộc vào việc mọi class được import lúc
`from server.db import models`. Nếu thêm model mới (Phase 2+), PHẢI add vào
__all__ và import statement dưới đây, không thì create_all() sẽ skip table.
"""
from server.db.models.project import Project
from server.db.models.job import Job, JobLog
from server.db.models.config import Config

__all__ = ["Project", "Job", "JobLog", "Config"]

# Phase 2+ thêm:
# from server.db.models.scene import Scene
# from server.db.models.asset import Asset
# from server.db.models.scene_asset import SceneAsset
# from server.db.models.style import Style
# from server.db.models.quality_gate import QualityGate
# from server.db.models.cookie import Cookie
# __all__ += ["Scene", "Asset", "SceneAsset", "Style", "QualityGate", "Cookie"]
```

### Test bootstrap đầy đủ

Trong `scripts/smoke_phase0.py` (đã có ở spec 09):

```python
@check("DB bootstrap creates all Phase 0 tables (REVIEW-02 #4)")
async def check_db_tables():
    from sqlalchemy import inspect
    engine = get_engine(load_settings())
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {"project", "job", "joblog", "config"}
    missing = expected - tables
    assert not missing, f"Phase 0 thiếu bảng: {missing}"
```

`server/main.py` lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bootstrap DB lần đầu
    settings = Settings()
    bootstrap_schema(settings)
    log.info(f"DB initialized at {settings.data_dir / 'projects.db'}")
    yield
```

Acceptance Phase 0: chạy `python -m server.main` lần đầu → file `storage/projects.db` xuất hiện, có 4 bảng (Project, Job, JobLog, Config).

### Phase 1+ — Migration chính thức

Khi schema bắt đầu evolve (Phase 2 thêm Scene/Asset), chuyển sang Alembic:

1. `pip install alembic`
2. `alembic init server/db/migrations`
3. Edit `alembic.ini` để dùng SQLite connection từ Settings
4. Migration mỗi schema change: `alembic revision --autogenerate -m "add scene table"`
5. Lifespan đổi từ `bootstrap_schema()` sang:
```python
from alembic.config import Config as AlembicConfig
from alembic import command

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    alembic_cfg = AlembicConfig("alembic.ini")
    command.upgrade(alembic_cfg, "head")  # Auto migrate to latest
    yield
```

6. Lưu `schema_version` trong bảng `config` cập nhật theo Alembic revision

### Reset workflow (developer)

```powershell
# Wipe DB hoàn toàn (Phase 0-1 acceptable, Phase 2+ cần backup trước)
rm storage/projects.db
python -m server.main  # Tự bootstrap lại

# Phase 2+: rollback 1 step
alembic downgrade -1

# Reset hoàn toàn về schema cũ
alembic downgrade base
alembic upgrade head
```

### Test data seed

`scripts/seed_db.py` (Phase 0+):
```python
"""Tạo 1 project demo để test UI/CLI."""
from server.config import Settings
from server.db.session import get_engine, bootstrap_schema
from server.db.models import Project

settings = Settings()
bootstrap_schema(settings)
# ... insert demo project
```

Chạy 1 lần khi user muốn dữ liệu mẫu.

## Cleanup policy

| Data | Retention |
|------|-----------|
| `project.status = "archived"` > 90 ngày | Cleanup thủ công (UI button "Delete archived") |
| `job_log.ts` > 30 ngày, job đã succeeded | Tự xoá daily cron |
| `storage/media/{project_id}/` cho project archived | Xoá kèm khi archive |
| `cookie.is_valid = false` > 7 ngày | Xoá để tránh leak |

## Acceptance criteria cho spec này

- [ ] Mọi entity (Project/Asset/Scene/Job) có FK chính xác
- [ ] State machine không có dead-end
- [ ] Index covered query patterns chính (list scenes per project, pull next queued job, etc.)
- [ ] Schema đủ flexible cho 6 adapters khác nhau (script_direct → epub_novel)
- [ ] Có chỗ persist cookies + secrets động (callback secret)
- [ ] Phase 0 implement được subset: chỉ Project + Scene + Job + JobLog + Config

## Phase mapping

| Bảng | Cần ở Phase |
|------|-------------|
| Project, Job, JobLog, Config | 0 (skeleton), 1 (full) |
| Scene, Asset, SceneAsset, Style | 2 |
| QualityGate | 2-3 |
| Cookie | 4.5 |
