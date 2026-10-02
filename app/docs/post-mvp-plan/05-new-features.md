# 05 — Tính năng mới ngoài spec (Priority: P2)

> 3 feature lớn, ngoài MVP boundary. Effort cao, nên làm sau khi 01-04 ổn định.
> **Effort tổng**: 14 ngày
> **Phụ thuộc**: 01-04 hoàn thành

## Task 5.1 — Scheduler (lên lịch tạo video tự động)

**Mục tiêu**: User tạo "Job định kỳ" (daily / weekly / cron expression) → server tự gen video theo schedule, dùng template + skill cố định, có thể nhận input động (vd RSS feed, latest news).

### Bước 1 — DB schema

Tạo bảng `schedule`:
```python
class Schedule(SQLModel, table=True):
    id: int = primary_key
    name: str  # "Daily TikTok ecommerce"
    cron: str  # "0 9 * * *" — mỗi ngày 9h
    project_template_id: int  # link tới Project được dùng làm template
    adapter: str
    skill: str
    voice_id: str
    enabled: bool = True
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at, updated_at
```

Migration alembic version mới.

### Bước 2 — Scheduler engine

`app/server/pipeline/scheduler.py`:
```python
class ScheduleRunner:
    """APScheduler wrapper — đọc bảng schedule, fire job khi đến giờ."""
    def __init__(self, settings):
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        self._scheduler = AsyncIOScheduler()
    async def start(self):
        # Load all enabled schedules từ DB
        # cron_trigger từ field cron
        # callback: clone project_template_id → submit POST /generate
```

Thêm vào `lifespan()` (`main.py`): khởi động ScheduleRunner sau VideoPoller.

### Bước 3 — Adapter input cho recurring

Mỗi Schedule có `adapter_input_strategy`:
- `static`: dùng input cố định lưu trong DB
- `rss_feed`: fetch RSS URL → lấy latest article → blog_article adapter
- `prompt_template`: gen prompt từ Gemini với template (vd "Tạo 1 vlog ngắn về thời tiết hôm nay")

### Bước 4 — REST API

```
GET    /api/schedules           — list
POST   /api/schedules           — create
PATCH  /api/schedules/{id}      — update (enable/disable, sửa cron)
DELETE /api/schedules/{id}
POST   /api/schedules/{id}/run-now  — fire ngay
GET    /api/schedules/{id}/history  — list các project đã sinh
```

### Bước 5 — UI page

`/schedules` mới:
- List schedule cards: name, cron readable ("Hàng ngày 9h sáng"), last_run, next_run, status
- Tạo schedule wizard: 4 bước (chọn template project → cron → input strategy → confirm)
- Cron picker tự built (preset: hourly / daily / weekly + advanced raw input)

### File ảnh hưởng
- `app/server/db/models/schedule.py` (new)
- `app/server/db/migrations/versions/xxx_add_schedule.py` (new)
- `app/server/pipeline/scheduler.py` (new)
- `app/server/api/routes/schedules.py` (new)
- `app/server/main.py` (start ScheduleRunner)
- `app/ui/src/pages/Schedules.tsx` (new)
- `app/ui/src/api/client.ts` (thêm helpers)

### Acceptance
- [ ] Tạo schedule cron `*/5 * * * *` (mỗi 5 phút) → 5 phút sau có project mới sinh, có final.mp4
- [ ] Disable schedule → không fire nữa
- [ ] Schedule history hiển thị 10 lần chạy gần nhất
- [ ] Run-now button fire job ngay
- [ ] Server restart → schedule load lại từ DB, fire đúng giờ
- [ ] RSS strategy: tạo schedule với feed URL → mỗi lần chạy lấy latest 1 article

### Dependencies cài thêm
- `apscheduler` (Python, MIT) cho cron
- `feedparser` cho RSS strategy

**Effort**: 5 ngày

## Task 5.2 — Template Gallery (project templates)

**Mục tiêu**: User chọn template có sẵn (vd "Ecommerce 30s", "Vlog 3 phút", "News bulletin 1 phút") → tự động fill toàn bộ adapter + skill + voice + scene structure.

### Khái niệm

Template = preset cho New Project + scene blueprint. Khác với skill (chỉ là style.json) — template là full project config.

### Bước 1 — Template format

`app/server/templates/{template_id}/template.json`:
```json
{
  "id": "ecommerce_30s_tiktok",
  "name": "Ecommerce 30s — TikTok",
  "description": "Video sản phẩm ngắn cho TikTok/Reels",
  "thumbnail": "thumbnail.png",
  "adapter": "ecommerce_product",
  "skill": "ecommerce-fashion",
  "voice_id": "Binh",
  "aspect_ratio": "9:16",
  "scene_blueprint": [
    {"order": 0, "duration": 3, "prompt_template": "Hook: cận cảnh {product_name}", "narration_template": "Bạn đã thử {product_name} chưa?"},
    {"order": 1, "duration": 4, "prompt_template": "Show feature {feature_1}", "narration_template": "{feature_1_description}"},
    ...
  ],
  "required_inputs": ["product_name", "product_image_path"]
}
```

### Bước 2 — Pre-built templates (10 cái)

Bộ template ban đầu:
1. `ecommerce_30s_tiktok` — sản phẩm 30s
2. `ecommerce_60s_landing` — sản phẩm 60s
3. `vlog_3min_lifestyle` — vlog 3 phút
4. `news_bulletin_60s` — bản tin 60s
5. `explainer_2min_tech` — giải thích công nghệ 2 phút
6. `cinematic_30s_action` — short cinematic
7. `lyric_video_full_song` — lyric video
8. `epub_chapter_5min` — 1 chương truyện
9. `social_viral_15s` — viral hook 15s
10. `podcast_caption_5min` — clip podcast

### Bước 3 — Loader

`app/server/templates/loader.py`:
```python
def list_templates() -> list[TemplateMeta]: ...
def get_template(template_id: str) -> Template: ...
def apply_template(template, user_inputs: dict) -> ProjectCreateRequest: ...
```

### Bước 4 — REST API

```
GET  /api/templates              — list templates với thumbnail
GET  /api/templates/{id}         — detail
POST /api/templates/{id}/apply   — preview project create từ template + user_inputs
```

### Bước 5 — UI page

`/templates` page mới + integrate vào NewProject:
- Tab "Từ template" trong New Project
- Grid card template với thumbnail (3 cột)
- Click → form điền `required_inputs` → "Tạo dự án" → tạo project có sẵn scene blueprint
- Filter: theo aspect_ratio, theo độ dài (short/medium/long)

### File ảnh hưởng
- `app/server/templates/loader.py` (new)
- `app/server/templates/{10 folders}/template.json` + thumbnail.png
- `app/server/api/routes/templates.py` (new)
- `app/ui/src/pages/Templates.tsx` (new)
- `app/ui/src/pages/NewProject.tsx` (thêm tab Template)

### Acceptance
- [ ] 10 template hiển thị grid với thumbnail
- [ ] Click `ecommerce_30s_tiktok` → form yêu cầu nhập product_name + image_path → submit → project có 5 scenes pre-fill
- [ ] Template scene_blueprint render đúng prompt + narration variables
- [ ] User custom template (export JSON từ project hiện tại) — bonus

**Effort**: 4 ngày

## Task 5.3 — Multi-language (TTS + subtitle nhiều ngôn ngữ cùng lúc)

**Mục tiêu**: Cho user generate 1 video → output N versions với N ngôn ngữ khác nhau (vd: VN + EN + zh-CN). Mỗi version có TTS riêng + subtitle riêng nhưng cùng video clips.

### Bước 1 — DB schema mở rộng

Thêm `Project.languages: list[str]` (JSON column hoặc bảng phụ):
```python
class ProjectLanguage(SQLModel, table=True):
    project_id: int (FK)
    language: str  # "vi-VN" | "en-US" | "zh-CN"
    voice_id: str
    is_primary: bool
```

Hoặc lưu trong `Project.metadata: JSON`.

### Bước 2 — Translation pipeline

Thêm step mới trong orchestrator (sau khi gen scenes nhưng trước compose):
1. Take primary language narration (ví dụ: vi-VN)
2. Với mỗi target language:
   - Gemini translate narration → target text
   - TTS synthesize target text với voice phù hợp
   - Whisper transcribe target audio → SRT
   - Lưu vào `storage/output/{project_id}/{lang}/audio.mp3` + `subtitle.srt`

### Bước 3 — Compose nhiều version

Trong `_orchestrate()`:
```python
for lang in project.languages:
    compose_config = ComposeConfig(
        ...
        audio=AudioConfig(narration_files=audio_paths_per_lang[lang]),
        subtitle=SubtitleConfig(segments=segments_per_lang[lang]),
        output_dir=Path(...) / lang,
    )
    final_path = orch.compose_with_g6(...)
    # Output: storage/output/{pid}/{lang}/final.mp4
```

### Bước 4 — REST API mở rộng

- `POST /api/projects` body có thêm `languages: ["vi-VN", "en-US"]`, `voice_per_language: {"vi-VN": "Binh", "en-US": "en-US-AvaNeural"}`
- `GET /api/projects/{id}/output?lang=en-US` — serve final.mp4 theo lang
- `GET /api/projects/{id}/export/srt?lang=en-US`

### Bước 5 — UI

NewProject:
- Multi-select language (Combobox cho phép multi)
- Mỗi language chọn voice riêng
- Primary language = lang đầu tiên

Export:
- Tabs `[VI] [EN] [ZH]` — switch giữa các version
- Mỗi tab có video player + SRT download riêng

### File ảnh hưởng
- `app/server/db/models/project.py` hoặc `project_language.py` (new)
- `app/server/ai/gemini.py` (thêm `translate_narration`)
- `app/server/pipeline/orchestrator.py` (translation step + multi compose)
- `app/server/api/routes/projects.py` (`output?lang=`, `export/srt?lang=`)
- `app/ui/src/pages/NewProject.tsx` (multi-language picker)
- `app/ui/src/pages/Export.tsx` (tabs language)

### Acceptance
- [ ] Tạo project với languages = ["vi-VN", "en-US"] → sinh 2 file final.mp4 trong 2 folder
- [ ] Subtitle SRT đúng tiếng cho mỗi version
- [ ] Audio trong final.mp4 là TTS của lang tương ứng
- [ ] UI Export switch tab → video player update
- [ ] Cost đúng: gen video clips chỉ 1 lần, chỉ TTS + subtitle chạy N lần

### Cảnh báo
- Translation chất lượng phụ thuộc Gemini → có thể đi lệch nghĩa, cho phép user edit thủ công
- Voice cho EN/ZH cần preset edge_tts tương ứng (vi-VN-* không dùng được cho EN)
- Lip-sync: vì video clip giữ nguyên, audio EN có thể không khớp môi nhân vật → chỉ phù hợp narration off-screen, không phải dialogue

**Effort**: 5 ngày

## Tổng kết Nhóm 5

| Task | Effort | Block |
|------|--------|-------|
| 5.1 Scheduler | 5 ngày | 02-2.1 |
| 5.2 Template Gallery | 4 ngày | — |
| 5.3 Multi-language | 5 ngày | 02-2.1, 02-2.3 |
| **Tổng** | **14 ngày** | |

## Ghi chú chiến lược

3 task này KHÔNG block lẫn nhau, có thể parallel hoặc ưu tiên theo nhu cầu user:
- Nếu user cần auto post-content định kỳ → ưu tiên 5.1 Scheduler
- Nếu user nhấn mạnh đa kênh / đa khán giả → ưu tiên 5.2 Template Gallery
- Nếu user cần global reach → ưu tiên 5.3 Multi-language

Khuyến nghị thứ tự thực hiện:
1. **5.2 trước** — đơn giản nhất, mở rộng UI hiện có, value cao
2. **5.1** — cần infra mới (cron) nhưng độc lập
3. **5.3** — phức tạp nhất, đụng nhiều layer (translation, TTS, compose), nên làm cuối
