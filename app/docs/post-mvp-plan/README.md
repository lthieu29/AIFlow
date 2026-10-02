# AIFlow — Kế hoạch thi công Post-MVP

> Tài liệu này tập hợp 5 nhóm tính năng còn thiếu sau MVP, mô tả hiện trạng, lộ trình thi công, và checklist hoàn thành để theo dõi tiến độ.

## Reading order

1. **README.md** (file này) — overview + tracker tổng hợp
2. **01-ui-completion.md** — Hoàn thiện UI (5 task)
3. **02-multi-scene-pipeline.md** — Wiring orchestrator vào API generate
4. **03-reference-images-e2e.md** — Asset → orchestrator → SDK
5. **04-ux-polish.md** — Toast, skeleton, drag-drop, batch edit, thumbnail
6. **05-new-features.md** — Scheduler, Template Gallery, Multi-language

## Hiện trạng phân tích (đã đọc source 2 lần)

### Đã có
- FastAPI server + 12 routes (`/api/projects`, `/api/scenes`, `/api/tts`, `/api/content/parse`, `/api/jobs/{id}/stream`, `/api/assets/*`, ...)
- React 18 UI với 5 trang (Home, Dashboard, NewProject, Timeline, Export, VoiceGallery)
- `PipelineOrchestrator` đầy đủ (G1 → Style/Asset Lock → G2 → sequential gen → G3 retry → last-frame chain)
- `FlowSDK.gen_video()` đã hỗ trợ `reference_images: list[Path]` (max 4)
- 5 preset voices trong `voice_catalog.py` + custom voice gallery
- 13 ContentAdapter (ecommerce, narrative, blog, storyboard, epub, video_remaster, ...)
- 36 skill packs trong `app/skills/`
- `EventBus` publish 6 event types (scene_started/completed/failed, pipeline_*, gate_*)
- SSE `/api/jobs/{id}/stream` đọc JobLog mỗi 1s
- Asset upload UI trong Timeline page (character/product/location/style)
- TTS service với fallback chain (vieneu → edge_tts)
- G6 final video gate với retry logic
- Dry-run mode tạo placeholder MP4 không tốn credit Veo3

### Thiếu / chưa nối
- **Demo audio** cho 5 preset voices đều `demo_audio_path=None` → user không nghe thử được
- **Orchestrator không gọi compose_with_g6** trong `_orchestrate()` (projects.py:596) → không sinh final.mp4 thật khi không phải dry-run
- **`reference_images` không được pass** từ orchestrator vào SDK (`_generate_scene` chỉ pass `start_image`)
- **EventBus → JobLog bridge** chưa có → SSE chỉ thấy progress chung, không thấy per-scene
- **`/api/content/parse` không được UI gọi** — NewProject submit thẳng `adapter_input` qua POST /projects, không re-parse được
- **Scheduler / Template / Multi-language**: hoàn toàn chưa có

## Tổng tiến độ

| Nhóm | Số task | Hoàn thành | Còn lại | Effort tổng |
|------|---------|------------|---------|-------------|
| 1. Hoàn thiện UI | 5 | 0 | 5 | 7 ngày |
| 2. Multi-scene pipeline | 4 | 0 | 4 | 4 ngày |
| 3. Reference images E2E | 3 | 0 | 3 | 2 ngày |
| 4. UX Polish | 5 | 0 | 5 | 5 ngày |
| 5. Tính năng mới | 3 | 0 | 3 | 14 ngày |
| **TỔNG** | **20** | **0** | **20** | **~32 ngày** |

## Quy ước đánh dấu task

- `[ ]` — chưa bắt đầu
- `[~]` — đang làm
- `[x]` — đã xong + đã verify
- `[!]` — bị block, cần input
- `[-]` — đã hủy / không làm

Mỗi task có: **mục tiêu**, **acceptance**, **file ảnh hưởng**, **verification command**.

## Thứ tự khuyến nghị thi công

1. **P0 — Tuần 1**: Nhóm 2 (multi-scene pipeline) + Nhóm 3 (reference images) → unlock pipeline thật, không còn chỉ dry-run
2. **P0 — Tuần 2**: Nhóm 1 (hoàn thiện UI) + 1.1 demo TTS → user thấy được toàn bộ flow
3. **P1 — Tuần 3**: Nhóm 4 (UX polish) → product feel
4. **P2 — Tuần 4-7**: Nhóm 5 (Scheduler / Template / Multi-lang) — feature lớn, ngoài MVP

## Last updated

- 2026-06-06 — Tạo plan v1.0 sau khi phân tích source 2 lần
