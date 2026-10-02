# Session Summary — AIFlow Post-MVP Plan

> File này tóm tắt session 2026-06-06 để chuyển sang session khác tránh context quá lớn.

## Yêu cầu của user

User yêu cầu phân tích project AIFlow (đọc 2 lần để chắc chắn) và viết kế hoạch thi công chi tiết cho 5 nhóm tính năng còn thiếu sau MVP, lưu vào `app/docs/` (tự tạo thư mục mới), dùng checklist để theo dõi tiến độ.

## Output đã tạo

Thư mục mới: `app/docs/post-mvp-plan/`

| File | Mục đích | Effort |
|------|----------|--------|
| README.md | Master index + tracker tổng hợp | — |
| 01-ui-completion.md | 5 task hoàn thiện UI (P0) | 7 ngày |
| 02-multi-scene-pipeline.md | 4 task wiring orchestrator (P0) | 4 ngày |
| 03-reference-images-e2e.md | 3 task reference images (P0) | 2 ngày |
| 04-ux-polish.md | 5 task UX polish (P1) | 5 ngày |
| 05-new-features.md | 3 feature lớn (P2) | 14 ngày |

**Tổng**: 20 task, ~32 ngày

## Phát hiện quan trọng từ phân tích source

### Project context
- **Tech stack**: Python 3.12 FastAPI + React 18 + Chrome MV3 extension
- **DB**: SQLite + SQLModel
- **TTS**: VieNeu (primary) + edge_tts (fallback)
- **Video gen**: Google Flow Veo3 (qua extension proxy)
- **AI**: Gemini API
- **Working dir**: `D:\Project\AIFlow\app\`
- **Indexed bởi GitNexus**: 10329 symbols, 19788 relationships, 248 execution flows

### Cấu trúc chính
```
app/
├── server/          (FastAPI + pipeline + 13 adapters)
│   ├── api/routes/  (12 routes: projects, scenes, tts, content, jobs, assets, ...)
│   ├── pipeline/    (orchestrator, event_bus, gates G1-G6)
│   ├── audio/tts/   (service + edge + vieneu providers)
│   ├── flow/        (sdk, client, ws_server, downloader)
│   ├── render/      (composer, visual_layer, ffmpeg_utils)
│   ├── ai/          (gemini + 4 prompt builders)
│   └── content/     (13 adapters, registry, skills_loader)
├── ui/src/          (React, 5 pages, zustand store)
├── skills/          (36 skill packs)
├── docs/            (12 specs + ADRs + reviews)
└── storage/         (DB, output, voice_gallery, media)
```

### 6 phát hiện chính (gap cần fix)

1. **Demo audio thiếu**: 5 preset voices trong `voice_catalog.py` đều có `demo_audio_path=None` → user không nghe thử được trong VoiceGallery UI.

2. **Pipeline không sinh final.mp4 thật**: `_orchestrate()` ở `app/server/api/routes/projects.py:596` chỉ gọi `orch.run()` (gen từng clip) nhưng KHÔNG gọi `compose_with_g6` → status `done` sai, không có file final khi không phải dry-run.

3. **reference_images không truyền**: `FlowSDK.gen_video()` (`flow/sdk.py:691`) đã hỗ trợ `reference_images: list[Path]` (max 4) nhưng `PipelineOrchestrator._generate_scene()` chỉ pass `start_image`, KHÔNG pass assets.

4. **EventBus → JobLog bridge chưa có**: EventBus publish 6 event types (scene_started/completed/failed, pipeline_*, gate_*) nhưng không persist vào JobLog → SSE `/api/jobs/{id}/stream` chỉ thấy progress chung, không thấy per-scene.

5. **/api/content/parse không được UI gọi**: Endpoint tồn tại nhưng `NewProject.tsx` submit thẳng `adapter_input` qua POST /projects, không có preview/edit scenes.

6. **Scheduler / Template Gallery / Multi-language**: Chưa có gì.

## Tóm tắt 20 task

### Nhóm 1 — Hoàn thiện UI (P0, 7 ngày)
- **1.1** Pre-generate TTS demo cho 5 preset voices (1 ngày)
- **1.2** Wire `/api/content/parse` từ NewProject để preview scenes (1.5 ngày)
- **1.3** Kết nối orchestrator multi-scene từ Timeline — gọi compose_with_g6 (2 ngày)
- **1.4** Real-time progress per-scene qua SSE bridge (1.5 ngày)
- **1.5** Hiển thị G2 Asset Approval gate trong UI modal (1 ngày)

### Nhóm 2 — Multi-scene Pipeline (P0, 4 ngày)
- **2.1** Mở rộng `_orchestrate()` để gọi `compose_with_g6` (1.5 ngày)
- **2.2** EventBus → JobLog bridge cho SSE realtime (1 ngày)
- **2.3** Whisper transcribe + subtitle SRT cho final.mp4 (1 ngày)
- **2.4** Failure recovery + partial output (0.5 ngày)

### Nhóm 3 — Reference Images E2E (P0, 2 ngày)
- **3.1** Build `reference_images` list từ assets trong `_generate_scene` (0.5 ngày)
- **3.2** Scene-asset mapping (gán asset cụ thể cho từng scene) (1 ngày)
- **3.3** Asset gen từ Gemini (text → ref image) (0.5 ngày)

### Nhóm 4 — UX Polish (P1, 5 ngày)
- **4.1** Toast / notification system với react-hot-toast (0.5 ngày)
- **4.2** Loading skeletons (1 ngày)
- **4.3** Scene preview thumbnail (1 ngày)
- **4.4** Drag-and-drop reorder scenes với @dnd-kit (1 ngày)
- **4.5** Batch scene editing (multi-select) (1.5 ngày)

### Nhóm 5 — Tính năng mới (P2, 14 ngày)
- **5.1** Scheduler — cron jobs với APScheduler (5 ngày)
- **5.2** Template Gallery — 10 pre-built templates (4 ngày)
- **5.3** Multi-language — TTS + subtitle nhiều ngôn ngữ song song (5 ngày)

## Thứ tự thi công khuyến nghị

1. **Tuần 1** (P0): Nhóm 2 + Nhóm 3 → unlock pipeline thật, không còn chỉ dry-run
2. **Tuần 2** (P0): Nhóm 1 + 1.1 demo TTS → user thấy được full flow
3. **Tuần 3** (P1): Nhóm 4 → product feel chuyên nghiệp
4. **Tuần 4-7** (P2): Nhóm 5 — feature lớn ngoài MVP

## Files đã đọc / phân tích trong session

### Source code
- `app/server/main.py` — FastAPI lifespan, register routers
- `app/server/config.py` — Pydantic Settings v2, sub-settings
- `app/server/api/routes/projects.py` — `_orchestrate()`, `_run_generation()`, `_run_dry_run()`
- `app/server/api/routes/scenes.py` — GET/PATCH scene
- `app/server/api/routes/tts.py` — voice listing, synthesize, custom upload
- `app/server/api/routes/content.py` — `/api/content/parse` endpoint
- `app/server/api/routes/jobs.py` — SSE stream `/api/jobs/{id}/stream`
- `app/server/api/routes/assets.py` — upload/list/delete reference images
- `app/server/pipeline/orchestrator.py` — `PipelineOrchestrator.run()`, `compose_with_g6()`, `_generate_scene()`
- `app/server/pipeline/event_bus.py` — 6 event types, sub/pub
- `app/server/pipeline/job_manager.py` — Job + JobLog CRUD
- `app/server/audio/tts/service.py` — TTSService with FallbackChain
- `app/server/audio/tts/voice_catalog.py` — 5 preset voices (demo_audio_path=None)
- `app/server/audio/tts/voice_metadata.py` — preset + custom merger
- `app/server/flow/sdk.py` — `gen_video()` với reference_images param
- `app/server/db/models/{project,scene,asset}.py` — SQLModel schemas
- `app/server/ai/prompts/asset_lock.py` — Layer 2 continuity
- `app/server/render/composer.py` — VideoComposer + ComposeConfig

### UI files
- `app/ui/src/App.tsx` — Routes + StatusBar
- `app/ui/src/api/client.ts` — Axios + helpers (getVoices, synthesize, uploadAsset, ...)
- `app/ui/src/store/index.ts` — Zustand stores (useAppStore, useVoiceStore)
- `app/ui/src/pages/Dashboard.tsx` — Project list
- `app/ui/src/pages/NewProject.tsx` — Adapter + skill + voice picker
- `app/ui/src/pages/Timeline.tsx` — Scene editor + AssetPanel + TTSPreview
- `app/ui/src/pages/VoiceGallery.tsx` — Voice browser + upload + delete
- `app/ui/src/pages/Export.tsx` — Final video preview + download

### Docs
- `app/docs/PLAN.md` — Master plan v1.3 (Phase 0-7 roadmap)
- `app/docs/03-api-contract.md` — REST/WS contract
- `app/docs/10-tts-spec.md` — TTS provider abstraction (read top 200 lines)

## Cách tiếp tục session mới

Khi session mới bắt đầu:
1. Đọc `D:\Project\AIFlow\app\docs\post-mvp-plan\README.md` để có tổng quan
2. Chọn task muốn thi công → đọc file `0X-...md` tương ứng
3. Mỗi task có acceptance checklist `[ ]` — đánh dấu khi xong
4. Update bảng "Tổng tiến độ" trong README.md

## Lưu ý quan trọng cho session mới

### GitNexus integration
Project được index bởi GitNexus. Trước khi edit symbol nào:
- Chạy `gitnexus_impact({target: "symbolName", direction: "upstream"})` để biết blast radius
- Chạy `gitnexus_detect_changes()` trước khi commit
- Refer `.claude/skills/gitnexus/` cho workflow cụ thể

### Quy ước task tracking
- `[ ]` chưa làm
- `[~]` đang làm
- `[x]` xong + verify
- `[!]` block, cần input
- `[-]` hủy

### File quan trọng cần biết khi code
- `_orchestrate()` — `app/server/api/routes/projects.py:596` — nơi cần fix Nhóm 2 task 2.1
- `_generate_scene()` — `app/server/pipeline/orchestrator.py:617` — nơi cần fix Nhóm 3 task 3.1
- `voice_catalog.py:52` — PRESET_VOICE_METADATA cần update demo_audio_path
- `_run_generation()` — `app/server/api/routes/projects.py:492` — nơi wire EventBus bridge

### Dependencies sẽ cần cài thêm
- `react-hot-toast` (Nhóm 4.1)
- `@dnd-kit/core` + `@dnd-kit/sortable` (Nhóm 4.4)
- `apscheduler` (Nhóm 5.1)
- `feedparser` (Nhóm 5.1 RSS strategy)
