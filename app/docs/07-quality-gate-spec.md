# 07 — Quality Gate G1-G6 Spec

> **Status**: Draft for review
> **Depends on**: 02-db-schema (QualityGate table), 06-continuity
> **Used by**: pipeline orchestrator

## Mục đích

Mỗi bước trong pipeline có thể thất bại theo nhiều cách (LLM trả JSON sai, Veo3 trả video đen, audio sync drift, v.v.). Quality Gate là 6 checkpoint **bắt buộc pass** trước khi sang bước kế. Mục tiêu:

1. **Catch errors sớm** — phát hiện vấn đề ở step N, không để cascade fail tới step N+5
2. **Save cost** — không gen tiếp khi step trước đã rotten
3. **Manual override** — user có thể force-pass nếu auto check sai
4. **Visibility** — UI thấy rõ chỗ nào đang stuck, fail vì sao

## Mô hình

```
Pipeline:
  Step 1: Adapter parse → Step 2: Gen ref images → Step 3: Gen scenes
                                                    → Step 4: Audio
                                                    → Step 5: Subtitle
                                                    → Step 6: Compose

Gates:
  G1 ──── G2 ──── G3 ──── G4 ──── G5 ──── G6
   ↓       ↓       ↓       ↓       ↓       ↓
  After  After   After   After   After   After
  parse  refs    each    audio   subtitle compose
                 scene
```

Mỗi gate có:
- **Input**: artifact của step vừa xong
- **Checks**: list rules + thresholds
- **Result**: pass | fail | manual_override
- **On fail action**: auto-retry / cascade revert / wait for user

DB: bảng `quality_gate` (xem spec 02). Mỗi project + gate + target = 1 row.

UI hiển thị 🟢🟡🔴 cho mỗi gate, click vào xem detail.

---

## G1 — Script & SceneList validation

**Trigger**: sau `Adapter.parse()`, trước Step 2.

**Target**: `Project` (1 row per project).

### Checks

| Check ID | Rule | Severity |
|----------|------|----------|
| G1.1 | `len(scenes) > 0` | Critical (fail) |
| G1.2 | `len(scenes) <= config.max_scenes_per_project` | Critical |
| G1.3 | `sum(s.duration_sec) <= config.max_video_duration_sec` | Critical |
| G1.4 | Mỗi scene có `narration` non-empty và `visual_prompt` non-empty | Critical |
| G1.5 | `scene[i].asset_ids` ⊆ `[a.asset_id for a in assets]` | Critical |
| G1.6 | Mỗi scene `duration_sec ∈ [3, 16]` | Warning (auto-clamp) |
| G1.7 | `len(assets)` ∈ [0, 10] | Warning (LLM gen quá nhiều assets) |
| G1.8 | LLM-as-judge: scenes có cốt truyện coherent không? | Warning (Phase 4+) |
| G1.9 | `narration` không chứa profanity / toxic | Warning (skill safety) |
| G1.10 | Estimate cost ≤ user budget | Warning (UI prompt confirm) |

### Action on fail

- Critical fail (G1.1-G1.5): **block pipeline**, surface error tới user. Force re-parse hoặc re-input.
- Warning fail (G1.6+): **auto-fix** + log warning + tiếp tục.
  - G1.6: clamp duration vào [3, 16]
  - G1.7: drop assets có `importance="extra"` cho tới khi ≤ 10
  - G1.10: pause pipeline, hiển thị "This will use $X. Continue?"

### Manual override

User có thể "Edit SceneList" trong UI → sửa narration/prompt trực tiếp → re-validate G1.

### Output

```python
@dataclass
class GateG1Result:
    passed: bool
    critical_failures: list[str]
    warnings: list[str]
    auto_fixed: list[str]
    estimated_cost: dict
```

---

## G2 — Reference image quality

**Trigger**: sau khi gen tất cả `Asset.ref_image` (Lớp 2 continuity).

**Target**: `Asset` (1 row per asset).

### Checks

| Check ID | Rule | Severity |
|----------|------|----------|
| G2.1 | `Asset.ref_local_path` exists, file size > 50KB (không phải placeholder) | Critical |
| G2.2 | Image resolve đúng (PIL load OK), không corrupt | Critical |
| G2.3 | Image dimensions ≥ 720×720 | Critical |
| G2.4 | Cho character: face detect (cv2) trả về ≥ 1 face với confidence > 0.6 | Warning |
| G2.5 | Cho character: face frontal (yaw < 30°, pitch < 20°) — manual heuristic | Warning |
| G2.6 | Cho character: mouth closed (mouth aspect ratio < 0.3) — heuristic | Warning |
| G2.7 | Image NOT mostly black/white (avg brightness ∈ [30, 220]) | Warning |
| G2.8 | Veo3 returned 4 variants → user picks 1 | **Manual gate với SLA** (REVIEW-01 #7) |

### Action on fail

- Critical (G2.1-G2.3): **auto-retry max 2 lần**. Nếu vẫn fail → mark asset `failed`, surface tới user.
- Warning (G2.4-G2.7): **prompt user review**. UI show ref image + warning. User có thể:
  - Accept anyway
  - Regenerate với hint mới (vd "make face more frontal")
  - Upload manual image
- Manual (G2.8): **bắt buộc user click chọn variant** trong SLA — xem dưới.

### G2.8 SLA & timeout (REVIEW-01 #7)

**Vấn đề**: nếu user mở project rồi để đó 3 ngày, pipeline block hoàn toàn — Veo3 credits bị giữ, jobs queued không tiến triển.

**Cơ chế**:

1. Khi G2.8 trigger, tạo `QualityGate` row với:
   - `status = "pending"`
   - `expires_at = created_at + AIFLOW_GATE_USER_TIMEOUT_HOURS (default 24h)`

2. Background task **`periodic_gate_checker()`** scan mỗi 60s — schedule trong
   lifespan (xem spec 09 task 0.4, REVIEW-02 #7). Phase 0 là no-op skeleton,
   Phase 2.2 implement đầy đủ logic dưới:

```python
async def check_expired_gates():
    """Run mỗi 60s, xử lý gate đã quá SLA."""
    expired = session.exec(
        select(QualityGate).where(
            QualityGate.status == "pending",
            QualityGate.gate == "G2",
            QualityGate.expires_at < datetime.utcnow(),
        )
    ).all()
    
    for gate_row in expired:
        # Default behavior: auto-pick variant 0
        asset = session.get(Asset, gate_row.target_id)
        asset.ref_media_id = asset.metadata.get("variants", [None])[0]
        asset.status = "ready"
        
        gate_row.status = "manual_override"
        gate_row.actioned_by = "auto"
        gate_row.reason = f"User timeout after {settings.gate_user_timeout_hours}h — auto-picked variant 0"
        
        # Resume pipeline
        await emit_event("gate_auto_resolved", {
            "gate": "G2.8",
            "asset_id": asset.id,
            "action": "auto_pick_variant_0",
        })
        log.warning(f"G2.8 timeout: asset {asset.id} auto-resolved with variant 0")
```

3. UI hiển thị countdown timer cho mỗi pending gate. Khi < 1h, push notification.

4. User có thể extend deadline bằng cách click "Snooze 24h" → `expires_at += 24h`.

### Config

```dotenv
AIFLOW_GATE_USER_TIMEOUT_HOURS=24      # Default 24h
AIFLOW_GATE_TIMEOUT_BEHAVIOR=auto_pick # auto_pick | fail | snooze_max_3
```

`AIFLOW_GATE_TIMEOUT_BEHAVIOR` options:
- `auto_pick` (default): auto-pick variant 0, log warning, continue
- `fail`: mark project failed, require user manual recovery
- `snooze_max_3`: tự snooze tối đa 3 lần, sau đó auto-pick

### Heuristic implementations

```python
def check_face_frontal(image_path: Path) -> dict:
    """Use mediapipe Face Mesh để estimate yaw/pitch."""
    import mediapipe as mp
    # ...
    return {"yaw_deg": yaw, "pitch_deg": pitch, "confidence": conf}

def check_mouth_closed(image_path: Path) -> dict:
    """Mouth aspect ratio (height/width). Closed: < 0.3."""
    # ...
```

### Manual override

User có nút "Override G2 — accept all refs" (cho test/dev hoặc nếu heuristic sai).

---

## G3 — Scene clip validation

**Trigger**: sau khi gen mỗi scene video (Lớp 3 continuity).

**Target**: `Scene` (1 row per scene).

### Checks

| Check ID | Rule | Severity |
|----------|------|----------|
| G3.1 | `Scene.video_local_path` exists, size > 200KB | Critical |
| G3.2 | ffprobe duration ≈ scene.duration_sec ± 0.5s | Critical |
| G3.3 | ffprobe codec = h264 (Veo3 default) | Warning |
| G3.4 | First frame brightness > 10 (not all black) | Critical |
| G3.5 | Last frame brightness > 10 | Critical |
| G3.6 | Video không stuck (sample 3 frames spaced, must differ visually) | Warning |
| G3.7 | Last frame extracted thành công cho scene chain | Critical |
| G3.8 | Audio track presence: nếu Veo3 3.1 native audio enabled → check codec | Warning |
| G3.9 | LLM-as-judge: prompt match content? (Phase 3+) | Warning, optional |

### Action on fail

- Critical: **auto-retry max 2 lần**.
  - Retry 1: cùng prompt, request Veo3 mới
  - Retry 2: **regenerate với weight tăng** ref images, hoặc fallback từ "lite" → "fast" model
  - Sau 2 retry: mark `failed`, cascade re-evaluate downstream scenes
- Warning: log + tiếp tục, surface tới user nếu nhiều scene fail.

### Cascade logic khi scene fail (REVIEW-01 #3 — bounded)

Scene N fail → scene N+1 mất start_image → cũng phải re-gen.

**Vấn đề tiềm ẩn**: nếu scene 1 fail repeatedly, mỗi lần cascade reset toàn bộ downstream → re-gen → fail lại → reset → ... vô hạn. Phải giới hạn.

**Bounded cascade**: thêm 2 counter ở cả Scene level và Project level:

```python
# server/db/models.py — thêm field
class Scene:
    # ... existing fields ...
    retry_count: int = 0              # Số lần CHÍNH scene này bị retry
    cascade_retry_count: int = 0      # Số lần scene này bị reset DO cascade từ upstream
    
class Project:
    # ... existing fields ...
    cascade_event_count: int = 0      # Tổng số cascade event trong project (toàn cục)

# server/pipeline/quality_gate.py
MAX_CASCADE_DEPTH_PER_SCENE = 2       # 1 scene bị cascade reset tối đa 2 lần
MAX_CASCADE_EVENTS_PER_PROJECT = 5    # Toàn project tối đa 5 cascade event
MAX_RETRY_PER_SCENE = 2               # Bản thân scene retry max 2 lần
```

```python
async def on_scene_failed(scene: Scene, project: Project):
    """Cascade reset downstream scenes — bounded."""
    
    # 1. Hard limit toàn project
    if project.cascade_event_count >= MAX_CASCADE_EVENTS_PER_PROJECT:
        log.error(f"Project {project.id}: cascade limit ({MAX_CASCADE_EVENTS_PER_PROJECT}) reached")
        project.status = "failed"
        await emit_event("project_cascade_blocked", {
            "project_id": project.id,
            "reason": "max_cascade_events",
            "user_action_required": "manual_review",
        })
        return  # KHÔNG cascade nữa
    
    # 2. Mark scene fail
    scene.status = "failed"
    
    # 3. Find downstream scenes phụ thuộc scene này
    downstream = [
        s for s in project.scenes
        if s.order > scene.order
        and s.start_image_media_id == scene.last_frame_media_id
    ]
    
    # 4. Cascade reset, NHƯNG check per-scene cascade limit
    affected_scenes = []
    blocked_scenes = []
    for s in downstream:
        if s.cascade_retry_count >= MAX_CASCADE_DEPTH_PER_SCENE:
            # Scene đã bị cascade reset 2 lần — không reset nữa
            # Mark independent: dùng character ref thay vì last_frame
            s.start_image_media_id = None  # Sẽ dùng main_character.ref_media_id
            s.metadata["cascade_blocked"] = True
            blocked_scenes.append(s.id)
            log.warning(f"Scene {s.id}: cascade blocked sau {MAX_CASCADE_DEPTH_PER_SCENE} lần reset, "
                        f"sẽ gen với character ref thay")
        else:
            s.status = "pending"
            s.start_image_media_id = None
            s.cascade_retry_count += 1
            affected_scenes.append(s.id)
    
    project.cascade_event_count += 1
    
    # 5. Notify
    await emit_event("scene_cascade_failed", {
        "scene_id": scene.id,
        "affected": affected_scenes,
        "blocked": blocked_scenes,
        "cascade_event_num": project.cascade_event_count,
        "max_events": MAX_CASCADE_EVENTS_PER_PROJECT,
    })
```

### Termination guarantee

Mỗi cascade event:
- Increment `project.cascade_event_count` → ≤ 5
- Increment `scene.cascade_retry_count` cho mỗi downstream → ≤ 2

Worst case: 5 cascade events × 5 downstream scenes × 2 cascade retries = 50 reset operations toàn project. Có giới hạn rõ ràng, không infinite loop.

### Recovery path khi blocked

Scene có `cascade_blocked=true`:
1. Skip start_image dependency, dùng `main_character.ref_media_id` thay
2. Insert cross-fade 0.5s với scene trước → che jump cut
3. Continue như scene độc lập

Project có `status="failed"` do cascade limit:
1. UI surface: "Pipeline blocked: too many cascade failures. Please review failing scenes."
2. User action: skip individual scenes hoặc fix prompt thủ công
3. User click "Retry from scene N" → reset `cascade_event_count = 0`, restart

### Config

```dotenv
AIFLOW_MAX_CASCADE_PER_SCENE=2      # Default
AIFLOW_MAX_CASCADE_PER_PROJECT=5    # Default
```

### Manual override

- "Skip scene": mark `user_skipped`, render thiếu scene đó (cross-fade qua)
- "Regenerate with custom prompt": user edit prompt, re-gen
- "Upload custom video": user upload mp4 thay thế

---

## G4 — Audio quality

**Trigger**: sau khi TTS full_narration (Lớp 4 continuity).

**Target**: `Project` (1 audio per project).

### Checks

| Check ID | Rule | Severity |
|----------|------|----------|
| G4.1 | Audio file exists, size > 10KB | Critical |
| G4.2 | ffprobe duration ≈ estimate (số từ × WPM ÷ 60) ± 20% | Warning |
| G4.3 | Audio không silent (RMS > -60 dBFS) | Critical |
| G4.4 | Không có gap silence > 1.5s giữa segments | Warning |
| G4.5 | Audio sample rate ≥ 16kHz | Critical |
| G4.6 | Audio mono hoặc stereo (channels ∈ [1, 2]) | Critical |
| G4.7 | Voice quality: không chứa "[uh]", "[um]", garbage tokens | Warning |

### Action on fail

- Critical: retry với voice profile khác (fallback chain).
- Warning G4.4 (gap): tự cắt silence > 1s → re-stitch.

### Voice fallback chain

```python
VOICE_FALLBACK = {
    "vi-VN-HoaiMyNeural": ["vi-VN-NamMinhNeural", "vi-VN-HoaiMyNeural"],
    # nếu primary fail → try secondary
}
```

### Manual override

User regen audio với voice riêng, hoặc upload custom audio.

---

## G5 — Subtitle alignment

**Trigger**: sau khi Whisper transcribe.

**Target**: `Project`.

### Checks

| Check ID | Rule | Severity |
|----------|------|----------|
| G5.1 | Số segment > 0 | Critical |
| G5.2 | Whisper avg confidence ≥ 0.6 | Warning |
| G5.3 | Mỗi segment confidence ≥ 0.4 | Warning |
| G5.4 | `segment[i].text` không chứa Whisper hallucination ("Cảm ơn các bạn đã xem") nếu narration không nói thế | Warning |
| G5.5 | Total segment duration ≈ audio duration ± 1s | Critical |
| G5.6 | Mỗi segment không quá ngắn (< 0.5s) hoặc quá dài (> 8s) | Warning |
| G5.7 | Segment text không trùng lặp 100% với segment trước | Warning |

### Action on fail

- Critical: retry transcribe với model lớn hơn (small → medium → large-v3).
- Warning G5.4 (hallucination): scan blacklist phrases, drop segment có hallucination.
- Warning G5.6: merge segments quá ngắn, split segments quá dài.

### Manual override

User edit subtitle UI inline (Phase 5).

---

## G6 — Final composition

**Trigger**: sau khi ffmpeg merge final.mp4.

**Target**: `Project`.

### Checks

| Check ID | Rule | Severity |
|----------|------|----------|
| G6.1 | `final.mp4` exists, size > 500KB | Critical |
| G6.2 | ffprobe duration = sum(scene durations) + intro + outro ± 0.5s | Critical |
| G6.3 | Video stream codec = h264 | Critical |
| G6.4 | Audio stream codec = aac | Critical |
| G6.5 | Audio + video synced: peak audio energy align với scene transitions ± 0.3s | Warning |
| G6.6 | Subtitle overlay readable (Phase 3+: render preview, OCR check?) | Optional |
| G6.7 | File playable: ffprobe `-show_streams` không error | Critical |
| G6.8 | Output resolution match aspect_ratio (1080×1920 cho 9:16, 1920×1080 cho 16:9) | Critical |

### Action on fail

- Critical: retry compose với fallback ffmpeg flags. Nếu vẫn fail → manual mode (output raw scenes + audio + srt, user merge tay).
- Warning G6.5: log + tiếp tục, output vẫn xài được.

### Manual override

- "Re-render with different transitions"
- "Download raw assets" (zip scenes + audio + srt)

---

## Gate dependency graph

```
G1 ──┐
     ├──► G2 ──► G3 ──┐
G4 ──┤                ├──► G6
     ├──► G5 ────────┘
     └────────────────┘
```

- G1 không phụ thuộc gì
- G2 cần G1 pass
- G3 cần G2 pass
- G4 chạy song song G2 (audio không phụ thuộc visual)
- G5 cần G4 pass
- G6 cần G3, G4, G5 đều pass

## State management

```python
class QualityGateRunner:
    async def run_gate(self, gate: GateName, target_id: int, project: Project) -> GateResult:
        ...
    
    async def cascade_invalidate(self, gate: GateName, target_id: int):
        """Invalidate downstream gates khi target fail."""
        ...
    
    async def manual_override(self, gate_record_id: int, user_action: str):
        """User force-pass."""
        ...
```

DB row lifecycle:
```
pending → pass
pending → fail → (retry: pending) → pass
pending → fail → (max retries) → manual_override (by user)
```

## Logging + observability

Mỗi gate eval emit:
```json
{
  "event": "gate_eval",
  "gate": "G3",
  "target_id": 42,
  "target_type": "scene",
  "status": "fail",
  "checks": [
    {"id": "G3.1", "passed": true},
    {"id": "G3.4", "passed": false, "details": {"first_frame_brightness": 5}}
  ],
  "duration_ms": 1234
}
```

UI hiển thị từng check trong Detail panel.

## Configuration

User có thể nới lỏng gate via `.env`:

```dotenv
AIFLOW_QUALITY_STRICT=false      # Default true. False = warning thành info, không block
AIFLOW_GATE_AUTO_RETRY=true      # Default true
AIFLOW_GATE_AUTO_OVERRIDE_WARNINGS=true  # Tự pass warnings, vẫn block critical
```

## Acceptance criteria

- [ ] Mỗi gate có checks rõ ràng với severity (critical / warning)
- [ ] Action on fail rõ ràng: retry / cascade / manual
- [ ] Manual override flow cho mọi gate
- [ ] Cascade logic khi scene fail không infinite loop
- [ ] DB schema track được mọi gate state per project
- [ ] UI có thể hiển thị state đầy đủ qua API `/api/projects/{pid}/gates`
- [ ] Phase 2 implement được G1-G3 không cần G4-G6 (audio Phase 3)

## Phase mapping

| Gate | Phase implement |
|------|-----------------|
| G1 | 2.1 (cùng SceneList) |
| G2 | 2.2 |
| G3 | 2.3 |
| G4 | 3.1 |
| G5 | 3.2 |
| G6 | 3.3 |
