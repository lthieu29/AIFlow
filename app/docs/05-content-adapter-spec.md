# 05 — ContentAdapter Framework Spec

> **Status**: Draft for review
> **Depends on**: 02-db-schema, 03-api-contract
> **Used by**: pipeline orchestrator + tất cả adapter

## Mục đích

Định nghĩa interface chuẩn để mọi loại input (script, novel, URL, blog, ...) có thể parse thành SceneList, sau đó pipeline chính chỉ làm việc với SceneList — không biết nguồn input là gì.

## Architecture nguyên tắc

```
Input thô (file/URL/text)
        ↓
ContentAdapter.parse()
        ↓
SceneList (chuẩn hoá)
        ↓
[Skill applier] — apply prefix/style từ skills/{skill_id}/
        ↓
Pipeline orchestrator (gen scenes, audio, render)
        ↓
final.mp4
```

Mỗi adapter biết:
- Input format mình hỗ trợ
- Skills nào dùng được với adapter mình
- Cách chunking input → scenes

Mỗi adapter KHÔNG biết:
- Veo3 / Gemini / TTS hoạt động ra sao
- Database schema
- FFmpeg

→ Adapter testable độc lập.

## Core data classes

### `Asset`

```python
@dataclass
class Asset:
    """Một entity tái sử dụng xuyên scenes."""
    asset_id: str                                            # adapter-generated, unique trong SceneList
    type: Literal["character", "product", "location", "object"]
    name: str
    description: str                                          # Cho LLM prompt
    
    # Generation hints
    ref_prompt: Optional[str] = None                          # Prompt cho Veo3 image gen
    ref_image_path: Optional[Path] = None                     # Nếu adapter tự upload
    ref_url: Optional[str] = None                             # Nếu là external image
    
    # Metadata
    aliases: list[str] = field(default_factory=list)         # ["Hùng", "anh", "Hùng An"]
    importance: Literal["main", "supporting", "extra"] = "supporting"
    first_appearance_scene_idx: Optional[int] = None
```

### `SceneOverlay`

```python
@dataclass
class SceneOverlay:
    """Overlay từ visual layer (intro card, lower third, ...)."""
    type: Literal["intro_card", "outro_card", "lower_third", "chapter_title", "product_card"]
    duration_sec: float
    start_offset_sec: float = 0.0    # Offset từ đầu scene
    template_vars: dict = field(default_factory=dict)
    # Vd: {"TITLE": "Hùng", "SUBTITLE": "Reviewer"}
```

### `Scene`

```python
# REVIEW-02 #6 — Location enum thay string tự do để Lớp 3 continuity
# có thể detect location_change reliable, không drift giữa adapters.
LocationCategory = Literal[
    # Indoor
    "indoor_studio",      # Studio, phòng quay trắng/xám — neutral background
    "indoor_home",        # Nhà, phòng ngủ, phòng khách
    "indoor_office",      # Văn phòng, coworking
    "indoor_retail",      # Cửa hàng, mall, showroom
    "indoor_cafe",        # Quán cafe, nhà hàng, bar
    # Outdoor
    "outdoor_urban",      # Phố, vỉa hè, tòa nhà — daylight
    "outdoor_nature",     # Công viên, rừng, bãi biển
    "outdoor_night",      # Ngoài trời ban đêm — lighting khác hẳn
    # Abstract
    "abstract",           # Nền tối/sáng thuần, không gian ảo, product-only frame
    "unspecified",        # Adapter chưa detect được — KHÔNG trigger chain reset
]


@dataclass
class Scene:
    """Một shot trong video — tương ứng 1 clip Veo3 8s."""
    scene_id: str                                             # adapter-generated
    order: int                                                 # 0, 1, 2, ...
    duration_sec: float = 8.0
    
    # Content
    narration: str                                            # Text TTS đọc
    visual_prompt: str                                        # Prompt thô cho Veo3
    
    # References
    asset_ids: list[str] = field(default_factory=list)       # Refs to Asset.asset_id
    
    # Camera + motion
    camera: Literal["static", "dynamic"] = "static"
    motion_hint: Optional[str] = None
    
    # Continuity hints
    mood: Optional[str] = None                                # "tense" | "romantic" | "action" | "calm"
    location_hint: LocationCategory = "unspecified"           # REVIEW-02 #6 — enum cố định
    
    # Visual layer
    overlay: Optional[SceneOverlay] = None
    
    # Adapter-specific extras
    metadata: dict = field(default_factory=dict)
```

### `SceneList`

```python
@dataclass
class SceneList:
    """Output chuẩn của ContentAdapter."""
    project_title: str
    skill_id: str                                             # "ecommerce-fashion"
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    
    assets: list[Asset]
    scenes: list[Scene]
    
    # Optional pre-generated audio script
    full_narration: Optional[str] = None                      # Joined narration cho TTS toàn project
    
    # Hints
    target_duration_sec: Optional[float] = None
    suggested_intro: Optional[SceneOverlay] = None
    suggested_outro: Optional[SceneOverlay] = None
    
    # Adapter metadata
    adapter_name: str
    adapter_version: str
    metadata: dict = field(default_factory=dict)
    
    def validate(self) -> tuple[bool, list[str]]:
        """Self-validation: order liên tục, asset_ids tham chiếu hợp lệ, etc."""
        ...
    
    def estimate_cost(self) -> dict:
        """Ước tính cost: số Veo3 calls, TTS duration, ..."""
        return {
            "veo3_clips": len(self.scenes) + 1,  # +1 cho ref images
            "veo3_credits_estimate": ...,
            "tts_duration_sec": ...,
            "total_video_duration_sec": sum(s.duration_sec for s in self.scenes),
        }
```

### `EpisodeList` (cho EPUB Tier 2)

```python
@dataclass
class EpisodeList:
    """Output cho long-form: 1 input → nhiều SceneList (mỗi episode)."""
    project_title: str
    episodes: list[SceneList]
    metadata: dict = field(default_factory=dict)
```

Chỉ EPUB adapter (Phase 6) trả về `EpisodeList`. Mọi adapter khác trả về `SceneList`.

## Interface `ContentAdapter`

```python
from abc import ABC, abstractmethod
from typing import Any, Union

class AdapterError(Exception):
    """Adapter parse error với code chuẩn."""
    def __init__(self, code: str, message: str, details: dict = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

class ContentAdapter(ABC):
    """Plugin interface."""
    
    name: str                       # "ecommerce_product", "video_remaster", "epub_novel"
    version: str = "1.0.0"
    description: str
    supported_skills: list[str]    # ["ecommerce-fashion", "ecommerce-tech"]
    
    # JSON schema for input validation
    input_schema: dict
    
    @abstractmethod
    async def validate(self, input_data: Any) -> tuple[bool, Optional[str]]:
        """Pre-flight: input có hợp lệ không? Cheap check, không call LLM."""
        ...
    
    @abstractmethod
    async def parse(
        self,
        input_data: Any,
        *,
        skill_id: str,
        ctx: "AdapterContext",
    ) -> Union[SceneList, EpisodeList]:
        """Parse input → SceneList chuẩn."""
        ...
    
    async def estimate_complexity(self, input_data: Any) -> dict:
        """Ước tính trước parse: số scene dự kiến, LLM calls, cost."""
        # Default impl, adapter có thể override
        return {"scenes_estimate": "unknown"}
```

### `AdapterContext`

Inject dependencies vào adapter (giúp test):

```python
@dataclass
class AdapterContext:
    llm: "GeminiClient"           # Cho parse + scene chunking
    vision: "VisionClient"         # Vision analyze ảnh
    skill_loader: "SkillLoader"    # Load skills/{id}/manifest.yaml
    workspace_dir: Path            # Tmp dir cho adapter ghi file (vd ảnh resized)
    progress_callback: Callable    # Adapter gọi để emit progress event
    config: dict                   # Adapter-specific config từ .env hoặc skill manifest
```

## Adapter registry

```python
# server/content/registry.py

class AdapterRegistry:
    _instances: dict[str, ContentAdapter] = {}
    
    @classmethod
    def discover(cls):
        """Auto-discover adapters trong server/content/adapters/*/"""
        for adapter_dir in (CONTENT_DIR / "adapters").iterdir():
            if adapter_dir.is_dir() and (adapter_dir / "adapter.py").exists():
                module = importlib.import_module(f"server.content.adapters.{adapter_dir.name}.adapter")
                # Convention: mỗi module export `ADAPTER` class instance
                if hasattr(module, "ADAPTER"):
                    cls._instances[module.ADAPTER.name] = module.ADAPTER
    
    @classmethod
    def get(cls, name: str) -> ContentAdapter:
        if name not in cls._instances:
            raise AdapterError("ADAPTER_NOT_FOUND", f"No adapter: {name}")
        return cls._instances[name]
    
    @classmethod
    def list(cls) -> list[dict]:
        return [
            {
                "name": a.name,
                "version": a.version,
                "description": a.description,
                "supported_skills": a.supported_skills,
                "input_schema": a.input_schema,
            }
            for a in cls._instances.values()
        ]
```

Convention: mỗi adapter export `ADAPTER` instance trong `adapter.py`:

```python
# server/content/adapters/ecommerce_product/adapter.py

class EcommerceProductAdapter(ContentAdapter):
    name = "ecommerce_product"
    version = "1.0.0"
    description = "E-commerce product video (TikTok/Reels style) from product image"
    supported_skills = ["ecommerce-fashion", "ecommerce-tech", "ecommerce-food"]
    input_schema = {
        "type": "object",
        "required": ["product_image_path"],
        "properties": {
            "product_image_path": {"type": "string"},
            "price": {"type": "string"},
            "category": {"type": "string", "enum": ["fashion", "tech", "food"]},
            "tone": {"type": "string", "enum": ["fun", "informative"]},
        }
    }
    
    async def validate(self, input_data): ...
    async def parse(self, input_data, *, skill_id, ctx) -> SceneList: ...

ADAPTER = EcommerceProductAdapter()
```

## Skill manifest system

Skills là DATA, không phải code. Mỗi skill là 1 folder.

### `skills/{skill_id}/manifest.yaml`

```yaml
# Required
name: ecommerce-fashion
version: 1.0.0
description: Fashion e-commerce style — editorial, knees-up framing, sweet motion
extends: _base                  # Inherit shared rules

# Compatibility
supported_adapters:
  - ecommerce_product
  - storyboard_manual
  - script_direct

# Defaults
default_aspect_ratio: "9:16"
default_fps: 30
default_camera: static

# Voice (cho TTS)
voice_profile: vi-VN-HoaiMyNeural
voice_rate: "+0%"
voice_pitch: "+0%"

# Style
style_file: style.json          # Path tương đối tới skill folder
prefix_file: prefix.md
character_template_file: character.md
scene_template_file: scene.md
motion_vocab_file: motion.md
```

### `skills/{skill_id}/style.json` (Lớp 1)

```json
{
  "art_style": "editorial fashion photography",
  "color_palette": "muted earth tones with cream highlights",
  "lighting": "soft even key light, golden hour optional",
  "lens": "85mm portrait, shallow DOF",
  "camera_style": "locked-off static frame",
  "post": "slight film grain, warm tone curve"
}
```

### `skills/{skill_id}/prefix.md`

Text prepend mọi shot prompt. VD:
```
Photoreal editorial fashion photography. Soft even key light. Sharp focus.
Subject engaged with the camera, neutral closed-mouth expression, no teeth
visible. Knees-up framing when product is in shot.
```

### `skills/{skill_id}/character.md`, `scene.md`, `motion.md`

Templates theo Toonflow format. Adapter load qua `ctx.skill_loader`.

### `skills/_base/`

Shared rules áp dụng cho mọi skill (continuity rules, safety, camera lock defaults).

```
skills/_base/
├── camera_lock.md         ← Static vs dynamic camera defaults
├── safety.md              ← Tránh NSFW, copyright, real persons
└── continuity.md          ← Rules giữ liên mạch
```

Skill khác `extends: _base` → loader merge.

## SkillLoader

```python
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._cache: dict[str, Skill] = {}
    
    def load(self, skill_id: str) -> Skill:
        if skill_id in self._cache:
            return self._cache[skill_id]
        
        manifest_path = self.skills_dir / skill_id / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        
        # Resolve extends
        if "extends" in manifest:
            base = self.load(manifest["extends"])
            manifest = merge(base, manifest)
        
        skill = Skill.from_manifest(manifest, base_dir=self.skills_dir / skill_id)
        self._cache[skill_id] = skill
        return skill
```

## Skill applier

Sau khi adapter trả `SceneList`, pipeline áp dụng skill:

```python
def apply_skill(scene_list: SceneList, skill: Skill) -> SceneList:
    """Mutate scene_list in-place: prepend prefix vào prompts, set voice, etc."""
    for scene in scene_list.scenes:
        scene.visual_prompt = f"{skill.prefix}\n\n{scene.visual_prompt}"
        if scene.camera is None:
            scene.camera = skill.default_camera
    return scene_list
```

→ Adapter KHÔNG phải biết về skill internals; chỉ trả lại scenes "raw".

## Adapter input/output contract

### Input
- Phải khớp `adapter.input_schema` (JSON Schema validate)
- Adapter trả lỗi `ADAPTER_INVALID_INPUT` nếu fail validate

### Output (SceneList)
- `scenes` không rỗng
- `scenes[i].order` liên tục từ 0
- `scenes[i].asset_ids` ⊆ `[a.asset_id for a in assets]`
- `scenes[i].duration_sec` ∈ [3, 30]
- Tổng duration ≤ `config.max_video_duration_sec`
- Số scenes ≤ `config.max_scenes_per_project`

Nếu vi phạm → adapter phải raise `AdapterError` hoặc `SceneList.validate()` trả false.

## Adapter cụ thể — overview

### `script_direct` (Phase 4.0)

Pass-through. Input là dict scenes raw, validate + return.

```python
input_schema = {
    "type": "object",
    "required": ["scenes"],
    "properties": {
        "title": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["narration", "visual_prompt"],
                "properties": {
                    "narration": {"type": "string"},
                    "visual_prompt": {"type": "string"},
                    "duration_sec": {"type": "number"},
                    "asset_ids": {"type": "array"}
                }
            }
        }
    }
}
```

### `ecommerce_product` (Phase 4.1)

Input: ảnh sản phẩm + meta. Vision analyze → script template (5 category × 4 style từ daihuo) → LLM gen scenes.

### `narrative_script` (Phase 4.2)

Input: markdown vlog. LLM split paragraph → scenes. Detect dialogue vs action.

### `blog_article` (Phase 4.3)

Input: URL hoặc markdown. LLM extract H2/key points → scenes explainer.

### `storyboard_manual` (Phase 4.4)

Input: JSON storyboard chi tiết. Strict validation.

### `video_remaster` (Phase 4.5)

Input: URL video. Download → transcribe → translate → optionally chunk thành scenes (Mode B).

### `epub_novel` (Phase 6)

Input: file EPUB + range chương. Multi-stage: parse → character extract → per-chapter scene chunk → episodes.

Trả về `EpisodeList` (không phải `SceneList`).

## Estimate complexity

Adapter có thể implement `estimate_complexity()` để UI show preview cost trước khi user commit:

```python
async def estimate_complexity(self, input_data) -> dict:
    return {
        "scenes_estimate": 8,
        "assets_estimate": 2,
        "tts_duration_estimate_sec": 60.0,
        "veo3_credits_estimate": 24,    # 8 scenes × 3 credits Pro
        "llm_calls_estimate": 3,
        "total_cost_usd_estimate": 0.0  # Free tier
    }
```

UI hiển thị: "This will use ~24 Veo3 credits and ~3 Gemini calls. Continue?"

## Acceptance criteria cho spec này

- [ ] Interface `ContentAdapter` đủ flexible cho 7 loại input khác nhau
- [ ] Dataclass `Scene` / `Asset` / `SceneList` field đủ cho mọi adapter use case
- [ ] Skill system tách biệt khỏi adapter (data not code)
- [ ] Skill có thể inherit (extends `_base`)
- [ ] Registry auto-discover adapters mà không sửa core
- [ ] Validation rules rõ ràng cả 2 phía (input + output)
- [ ] EPUB long-form được handle qua `EpisodeList` riêng
- [ ] Phase 0 không cần implement, chỉ định nghĩa interface

## Phase mapping

| Component | Phase |
|-----------|-------|
| Interface + dataclass | 4.0 |
| Registry + auto-discover | 4.0 |
| SkillLoader + applier | 4.0 |
| `_base` skill + `ecommerce-fashion` skill | 4.0 |
| `script_direct` adapter | 4.0 |
| `ecommerce_product` adapter | 4.1 |
| `narrative_script` adapter | 4.2 |
| `blog_article` adapter | 4.3 |
| `storyboard_manual` adapter | 4.4 |
| `video_remaster` adapter | 4.5 |
| `epub_novel` adapter | 6 |
