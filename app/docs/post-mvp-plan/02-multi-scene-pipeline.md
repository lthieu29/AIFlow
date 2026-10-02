# 02 — Multi-scene Pipeline Trigger (Priority: P0)

> Backend wiring để 1 API call chạy đầy đủ G1 → orchestrator → compose → G6.
> **Effort tổng**: 4 ngày
> **Phụ thuộc**: không (foundation)

## TL;DR

`PipelineOrchestrator` đã có đủ logic, nhưng `_orchestrate()` trong `projects.py` chỉ gọi `orch.run()` (sinh từng clip riêng lẻ), KHÔNG:
- Build `ComposeConfig` từ các scenes đã gen
- Gọi `compose_with_g6` để ghép thành `final.mp4`
- Gọi `transcribe.py` (Whisper) để sinh subtitle SRT
- Bridge EventBus → JobLog cho SSE

→ User bấm "Tạo video" (không dry-run) hiện tại sẽ chạy gen từng clip nhưng KHÔNG có file final → trạng thái "done" sai.

## Task 2.1 — Mở rộng _orchestrate() để gọi compose_with_g6

**Mục tiêu**: Sau khi `orch.run()` xong, build `ComposeConfig` và gọi `compose_with_g6` để sinh `storage/output/{project_id}/final.mp4`.

**Cách làm**:
1. Trong `app/server/api/routes/projects.py::_orchestrate()` (line 596), sau `await orch.run(...)`:
   ```python
   # Reload scenes to get video_path / audio_path populated
   with Session(engine) as session:
       scenes_done = list(session.exec(
           select(Scene).where(Scene.project_id == project_id).order_by(Scene.order)
       ).all())
       project = session.get(Project, project_id)

   # Build ComposeConfig
   from server.render.composer import (
       ComposeConfig, ClipInput, AudioConfig, SubtitleConfig
   )
   clips = [
       ClipInput(
           file_path=Path(s.video_path),
           duration=s.duration,
           transition="direct_concat",
           has_audio=False,
       )
       for s in scenes_done if s.video_path and Path(s.video_path).exists()
   ]
   audio_paths = [Path(s.audio_path) for s in scenes_done
                  if s.audio_path and Path(s.audio_path).exists()]

   compose_config = ComposeConfig(
       project_id=project_id,
       clips=clips,
       audio=AudioConfig(narration_files=audio_paths),
       subtitle=SubtitleConfig(segments=[]),  # populate from Whisper task 2.3
       aspect=project.aspect,
       output_dir=Path(settings.data_dir) / "output" / str(project_id),
   )

   expected_dur = sum(c.duration for c in clips)
   final_path = orch.compose_with_g6(
       project_id=project_id,
       compose_config=compose_config,
       expected_duration=expected_dur,
       aspect_ratio=project.aspect,
   )
   logger.info(f"[orchestrate] final.mp4 generated: {final_path}")
   ```
2. Verify `ComposeConfig` schema trong `composer.py` có các field trên (đọc file đầy đủ)
3. Skip compose nếu không có scene nào success (all_passed=False và 0 video_path)

**Acceptance**:
- [ ] Sau Generate (không dry-run), `storage/output/{project_id}/final.mp4` tồn tại, ≥ 100KB
- [ ] G6 quality gate được gọi, log thấy attempt/result
- [ ] Project status = `done` sau khi final.mp4 ready
- [ ] Khi orch.run thất bại tất cả scene → không gọi compose, set project=`ready`

**Verification**:
```powershell
# Tạo project test, gen 3 scenes có narration ngắn
curl -X POST http://127.0.0.1:8101/api/projects/{id}/generate -d '{"dry_run": false}'
# Đợi job done → check file
ls storage/output/{id}/final.mp4
ffprobe -i storage/output/{id}/final.mp4 -show_streams
```

**Effort**: 1.5 ngày

## Task 2.2 — EventBus → JobLog bridge cho SSE

**Mục tiêu**: 6 event types từ EventBus phải được persist vào JobLog (cùng job_id) để `/api/jobs/{id}/stream` SSE đẩy lên FE realtime.

**Cách làm**:
1. Tạo `app/server/pipeline/event_bus_bridge.py`:
   ```python
   class EventBusJobLogBridge:
       """Subscribes to EventBus events, persists them as JobLog entries
       with structured prefix so SSE consumers can parse per-scene status."""

       def __init__(self, bus, engine, job_id):
           self.bus = bus; self.engine = engine; self.job_id = job_id
           bus.subscribe("scene_started", self._on_scene_started)
           bus.subscribe("scene_completed", self._on_scene_completed)
           bus.subscribe("scene_failed", self._on_scene_failed)
           bus.subscribe("pipeline_completed", self._on_pipeline_completed)
           bus.subscribe("pipeline_failed", self._on_pipeline_failed)
           bus.subscribe("gate_status_changed", self._on_gate_status)

       def _log(self, level, evt_type, data):
           import json as _json
           with Session(self.engine) as s:
               add_job_log(s, self.job_id, level,
                           f"[EVT:{evt_type}] {_json.dumps(data, ensure_ascii=False)}")
   ```
2. Wire vào `_run_generation()` ngay sau `update_job_status` running:
   ```python
   bus = EventBus()
   bridge = EventBusJobLogBridge(bus, engine, job_id)
   # rồi truyền bus vào orchestrator
   orch = PipelineOrchestrator(settings, sdk, event_bus=bus)
   ```
3. Update `/api/jobs/{id}/stream` SSE generator (`jobs.py`):
   - Parse log message với prefix `[EVT:xxx]`
   - Emit thêm SSE event riêng: `event: job.scene_progress` / `job.gate` / `job.pipeline`
   - FE listen từng event type độc lập

**Acceptance**:
- [ ] Mỗi scene_started/completed/failed tạo 1 JobLog row
- [ ] SSE stream có cả `job.log` (legacy) + `job.scene_progress` + `job.gate`
- [ ] Payload JSON parse được, có `scene_order`, `attempt`, `status`
- [ ] Bridge cleanup (unsubscribe) khi job xong

**File ảnh hưởng**:
- `app/server/pipeline/event_bus_bridge.py` (new)
- `app/server/api/routes/projects.py` (`_run_generation`)
- `app/server/api/routes/jobs.py` (parse + emit thêm event types)

**Effort**: 1 ngày

## Task 2.3 — Whisper transcribe + subtitle SRT cho final.mp4

**Mục tiêu**: Sau khi compose audio xong, transcribe để có subtitle segments, đính kèm vào ComposeConfig hoặc sinh file SRT riêng cho `/api/projects/{id}/export/srt`.

**Cách làm**:
1. Sau `orch.run()` và TRƯỚC `compose_with_g6`:
   ```python
   from server.audio.transcribe import transcribe_audio_segments
   # Concat narration files thành 1 audio temp để transcribe
   merged_audio = merge_narrations(audio_paths, settings)
   subtitle_segments = transcribe_audio_segments(merged_audio, settings)
   compose_config.subtitle = SubtitleConfig(segments=subtitle_segments)
   ```
2. Verify `transcribe.py` API trả về list[SubtitleSegment] hoặc tương đương
3. Lưu file SRT chính thức vào `storage/output/{project_id}/subtitle.srt` để `/api/projects/{id}/export/srt` serve được
4. Nếu Whisper fail / không có narration → skip subtitle (không block pipeline)

**Acceptance**:
- [ ] final.mp4 có subtitle burn-in (drawtext) khớp narration
- [ ] File SRT export tải được, mở Notepad đọc có thời gian + text
- [ ] Whisper fail không crash pipeline, chỉ log warning
- [ ] Subtitle align với audio (drift ≤ 200ms)

**Effort**: 1 ngày

## Task 2.4 — Failure recovery + partial output

**Mục tiêu**: Pipeline robust với failure: nếu 1-2 scene fail, vẫn compose phần còn lại; nếu G6 fail tất cả retry, log đầy đủ.

**Cách làm**:
1. Trong `_orchestrate()`, nhận return `all_passed: bool` từ `orch.run()`
2. Nếu `all_passed=False`:
   - Lọc clips chỉ lấy scene có `video_path` exist
   - Nếu vẫn còn ≥ 1 clip → vẫn compose (output là partial)
   - Log warning về scene bị skip
3. Nếu 0 clip → raise → catch ở `_run_generation` → mark job failed
4. Update Project status:
   - All passed → `done`
   - Partial (some scenes ok) → `done_partial` (mới, hoặc `done` + flag `partial_failure`)
   - Tất cả fail → `ready` (cho phép retry)

**File ảnh hưởng**:
- `app/server/api/routes/projects.py` (`_orchestrate`, `_run_generation`)
- `app/server/db/models/project.py` (cân nhắc thêm `partial_failure: bool`)

**Acceptance**:
- [ ] Test: cho 3 scenes, mock 1 scene fail → final.mp4 vẫn ra với 2 clip
- [ ] Test: tất cả 3 scene fail → job=failed, project=ready, không có final.mp4
- [ ] JobLog có entry rõ ràng: `Scene 1 failed (G3 exhausted)`, `Composing 2/3 scenes`
- [ ] UI Timeline hiển thị scene bị skip

**Effort**: 0.5 ngày

## Tổng kết Nhóm 2

| Task | Effort | Block |
|------|--------|-------|
| 2.1 Mở rộng _orchestrate gọi compose_with_g6 | 1.5 ngày | — |
| 2.2 EventBus → JobLog bridge | 1 ngày | — |
| 2.3 Whisper subtitle pipeline | 1 ngày | 2.1 |
| 2.4 Failure recovery + partial output | 0.5 ngày | 2.1 |
| **Tổng** | **4 ngày** | |
