# 01 — Hoàn thiện UI (Priority: P0)

> Ưu tiên cao. Cần hoàn thành trước khi user thực sự test được toàn bộ flow.
> **Effort tổng**: 7 ngày
> **Phụ thuộc**: 02 (multi-scene pipeline) cho task 1.3, 1.4

## TL;DR

5 mảng UI còn thiếu / chưa nối:
1. Pre-generate TTS demo cho 5 preset voices (hiện `demo_audio_path=None`)
2. Wiring `/api/content/parse` từ NewProject để re-parse + preview scenes
3. Kết nối orchestrator multi-scene từ Timeline (hiện chỉ gen-clip single shot)
4. Real-time progress per-scene (hiện UI chỉ 1 progress bar)
5. Hiển thị per-scene status cards live

## Task 1.1 — Pre-generate TTS demo cho preset voices

**Mục tiêu**: 5 preset voices (Binh, Lan, Nam, vi-VN-HoaiMyNeural, vi-VN-NamMinhNeural) có file demo MP3 được generate sẵn ở `storage/voice_gallery/{voice_id}/demo.mp3` để VoiceGallery UI play được.

**Cách làm**:
1. Tạo script `app/server/scripts/pregenerate_demos.py`:
   - Đọc `PRESET_VOICE_METADATA` từ `voice_catalog.py`
   - Với mỗi voice → gọi `TTSService.synthesize()` với câu mẫu phù hợp ngôn ngữ + voice
   - Lưu file vào `storage/voice_gallery/{voice_id}/demo.mp3`
   - Update catalog/metadata để route `/tts/voices/{id}/demo` resolve đúng
2. Update `voice_catalog.py`: gắn `demo_audio_path="demo.mp3"` cho 5 preset (relative filename, route `/api/tts/voices/{id}/demo` đã serve qua `safe_file_or_404`).
3. Sample text khuyến nghị (mỗi voice 1 câu, 8-12 giây):
   - VN giọng nam: "Xin chào, tôi là giọng đọc {name}. Hôm nay là một ngày đẹp trời để kể câu chuyện của bạn."
   - VN giọng nữ: tương tự
4. Chạy 1 lần khi setup hoặc add vào CLI: `python -m server.scripts.pregenerate_demos`.

**File ảnh hưởng**:
- `app/server/scripts/pregenerate_demos.py` (new)
- `app/server/audio/tts/voice_catalog.py` (set `demo_audio_path`)
- `app/server/audio/tts/voice_metadata.py` (đảm bảo preset cũng lookup demo)

**Acceptance**:
- [ ] Script chạy thành công, tạo 5 file MP3 trong `storage/voice_gallery/{id}/demo.mp3`
- [ ] `GET /api/tts/voices` trả về `demo_audio_path: "/tts/voices/{id}/demo"` cho cả preset
- [ ] UI VoiceGallery: nút "Demo" enabled cho cả 5 preset, click play được
- [ ] File MP3 ≥ 50KB, ffprobe duration > 3s
- [ ] Re-run script idempotent (skip nếu đã có)

**Verification**:
```powershell
python -m server.scripts.pregenerate_demos
ls storage/voice_gallery/*/demo.mp3
curl http://127.0.0.1:8101/api/tts/voices | jq '.[].demo_audio_path'
```

**Effort**: 1 ngày

## Task 1.2 — Wiring /api/content/parse từ NewProject

**Mục tiêu**: Cho phép user bấm "Xem trước cảnh" trong NewProject để gọi `/api/content/parse` và preview SceneList trước khi commit tạo project. Hiện UI submit thẳng dữ liệu thô qua POST /projects, không có cơ hội review.

**Cách làm**:
1. Thêm endpoint helper trong `app/ui/src/api/client.ts`:
   - `parseContent(adapter: string, inputData: object)` → `POST /api/content/parse`
   - Type `SceneSpecOut` + `SceneListOut` (mirror server pydantic).
2. Update `NewProject.tsx`:
   - Thêm nút "Xem trước cảnh" (secondary, bên cạnh "Tạo dự án")
   - Khi bấm → gọi `parseContent()` → mở modal/panel hiển thị scene list (order, duration, prompt, narration)
   - Cho user edit inline rồi mới Submit (gửi sceneList override qua adapter_input.scenes hoặc lưu draft scenes)
3. Cải tiến: nếu adapter parse fail, hiển thị error nhưng cho phép user vẫn tạo project (như hiện tại) hoặc cancel.

**File ảnh hưởng**:
- `app/ui/src/api/client.ts` (thêm `parseContent`)
- `app/ui/src/pages/NewProject.tsx` (thêm preview button + modal)
- `app/ui/src/components/ScenePreview.tsx` (new — modal/panel)

**Acceptance**:
- [ ] Có nút "Xem trước cảnh" trong NewProject form
- [ ] Bấm nút → loading → hiển thị danh sách cảnh với prompt/duration/narration
- [ ] Có cost estimate (từ `estimated_cost` của SceneListOut)
- [ ] Đóng modal mà không tạo project được
- [ ] Edit cảnh trong preview → trạng thái lưu local cho tới khi submit

**Verification**:
- E2E: tạo blog_article với URL → click Preview → thấy ≥ 1 scene → close → submit thành công
- Không break flow tạo project hiện tại

**Effort**: 1.5 ngày

## Task 1.3 — Kết nối orchestrator multi-scene từ Timeline

**Mục tiêu**: Khi user bấm "Tạo video" trong Timeline, hệ thống chạy đầy đủ pipeline (G1 → all scenes → G6 final.mp4) thay vì chỉ dry-run. Hiện `_orchestrate()` chỉ gọi `orch.run()` (sinh từng clip) nhưng KHÔNG gọi `compose_with_g6` → không có file final.

**Cách làm**:
1. Patch `app/server/api/routes/projects.py::_orchestrate()`:
   - Sau khi `orch.run()` xong, build `ComposeConfig` từ `scenes` (lấy `video_path`, `audio_path`) + project aspect
   - Gọi `orch.compose_with_g6(project_id, compose_config, expected_duration, aspect_ratio)`
   - Lưu output_path → `storage/output/{project_id}/final.mp4` (compose_with_g6 đã ghi sẵn theo composer)
2. Bổ sung subtitle compose: nếu có file SRT từ Whisper transcribe (Phase 3.3) → đính kèm
3. Đảm bảo có audio_path cho từng scene (orchestrator gọi `synthesize_narration` đã có sẵn — verify scene.narration không rỗng)
4. Test: cho 1 project 3 scenes có narration → bấm Tạo video (không dry-run) → final.mp4 generate được, mở xem được

**File ảnh hưởng**:
- `app/server/api/routes/projects.py` (mở rộng `_orchestrate()`)
- `app/server/render/composer.py` (verify ComposeConfig schema)

**Acceptance**:
- [ ] Project có scenes với narration → "Tạo video" (không dry-run) sinh ra `storage/output/{project_id}/final.mp4`
- [ ] File MP4 mở được, có cả video + audio + subtitle (nếu có Whisper)
- [ ] G6 quality gate pass; nếu fail có retry tự động (đã có sẵn trong `compose_with_g6`)
- [ ] Project status chuyển `done` sau khi final.mp4 ready
- [ ] Nếu có scene fail (G3 exhaust retries) → orchestrator vẫn compose phần còn lại, log warning

**Verification**:
- Tạo project 3 scenes (skill ecommerce-fashion, image dummy) → Generate → check final.mp4 ≥ 100KB, duration ≈ tổng scene
- Verify SSE events: scene_started → scene_completed (×3) → pipeline_completed → gate G6 status

**Effort**: 2 ngày

## Task 1.4 — Real-time progress per-scene (SSE bridge)

**Mục tiêu**: UI Timeline hiển thị status thực tế từng cảnh đang generate (đang gen / xong / fail) thay vì 1 progress bar chung. EventBus đã publish `scene_started/completed/failed` nhưng không bridge vào JobLog → SSE không thấy được.

**Cách làm**:
1. Tạo helper `EventBusJobLogBridge`:
   - Subscribe vào `EventBus` cho 6 event types
   - Mỗi event → `add_job_log(session, job_id, level, structured_message)`
   - Format message JSON-prefix để FE parse: `[SCENE:5/10] generating...` hoặc dạng JSON serialize
2. Wire bridge trong `_run_generation()` (`projects.py:492`):
   ```python
   bridge = EventBusJobLogBridge(event_bus, engine, job_id)
   orch = PipelineOrchestrator(settings, sdk, event_bus=bridge.bus)
   ```
3. Update SSE endpoint `/api/jobs/{id}/stream`:
   - Khi emit `job.log`, parse structured prefix → emit thêm `job.scene_progress` event với `{scene_order, status, percent}`
4. Update `Timeline.tsx`:
   - Lưu state `scenesProgress: Record<sceneId, ProgressInfo>`
   - Listen `job.scene_progress` event → update riêng từng scene card
   - Render badge `Đang tạo cảnh 3/10`, mini progress bar trên từng SceneRow

**File ảnh hưởng**:
- `app/server/pipeline/event_bus_bridge.py` (new)
- `app/server/api/routes/projects.py` (`_run_generation` wire bridge)
- `app/server/api/routes/jobs.py` (parse structured log → emit `job.scene_progress`)
- `app/ui/src/pages/Timeline.tsx` (per-scene progress UI)

**Acceptance**:
- [ ] Mỗi scene có badge realtime: `pending → generating → completed/failed`
- [ ] Progress bar tổng thể tính theo `completed_scenes / total_scenes`
- [ ] Scene đang generate có animation/pulse
- [ ] Scene fail hiển thị màu đỏ + tooltip lý do
- [ ] Performance: SSE poll 1s, không lag UI dù 50 scenes

**Verification**:
- DevTools → Network → SSE stream → thấy `job.scene_progress` events
- Visual: gen 5 scenes, mỗi cảnh tuần tự đổi badge

**Effort**: 1.5 ngày

## Task 1.5 — Hiển thị G2 (Asset Approval) gate trong UI

**Mục tiêu**: Pipeline tạm dừng ở G2 chờ user approve assets. UI hiện không có chỗ tương tác → orchestrator timeout 24h. Cần modal/panel cho phép user approve / override / reject.

**Cách làm**:
1. Backend đã có `g2_asset_approval.py` với DB row `quality_gate` status. Thêm route:
   - `GET /api/projects/{id}/gates/pending` → list gates đang `checking`
   - `POST /api/projects/{id}/gates/{gate_id}/approve` → mark `passed`
   - `POST /api/projects/{id}/gates/{gate_id}/override` → mark `overridden`
2. UI Timeline detect SSE event `gate.status_changed` với `status: "checking"` → show modal:
   - List asset refs với thumbnail
   - 2 nút: "Duyệt và tiếp tục" / "Bỏ qua (override)"
3. Sau khi click → POST → orchestrator polling thấy status đổi → tiếp tục pipeline

**File ảnh hưởng**:
- `app/server/api/routes/projects.py` (thêm 3 route gates)
- `app/server/pipeline/gates/g2_asset_approval.py` (verify approve/override helpers)
- `app/ui/src/components/AssetApprovalModal.tsx` (new)
- `app/ui/src/pages/Timeline.tsx` (listen gate event, mở modal)

**Acceptance**:
- [ ] Pipeline pause ở G2 → UI hiện modal trong < 5s
- [ ] User approve → pipeline tiếp tục
- [ ] User override → pipeline tiếp tục với cờ override=True
- [ ] User không tương tác trong 24h → gate auto-expire (đã có sẵn từ `periodic_gate_checker`)

**Effort**: 1 ngày

## Tổng kết Nhóm 1

| Task | Effort | Dependency |
|------|--------|------------|
| 1.1 Pre-gen TTS demo | 1 ngày | — |
| 1.2 Wire /content/parse | 1.5 ngày | — |
| 1.3 Multi-scene from Timeline | 2 ngày | Nhóm 2 task 2.1 |
| 1.4 Per-scene progress SSE | 1.5 ngày | Nhóm 2 task 2.1 |
| 1.5 G2 approval modal | 1 ngày | — |
| **Tổng** | **7 ngày** | |
