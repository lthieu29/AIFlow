# 03 — Reference Images End-to-End (Priority: P0)

> Wire asset uploads (Timeline UI) → DB → orchestrator → FlowSDK.gen_video.
> **Effort tổng**: 2 ngày
> **Phụ thuộc**: 02 task 2.1

## TL;DR

- `FlowSDK.gen_video()` đã hỗ trợ `reference_images: list[Path]` (max 4) — verified ở `flow/sdk.py:691`
- `Asset` model đã có `file_path` cho uploaded image
- `AssetLock.from_assets()` build anchor block prompt từ DB
- UI Timeline `AssetPanel` upload được character/product/location/style
- **Thiếu**: `PipelineOrchestrator._generate_scene()` chỉ pass `start_image`, KHÔNG pass `reference_images=[asset.file_path for asset in assets]`

## Task 3.1 — Build reference_images list từ assets trong _generate_scene

**Mục tiêu**: Mỗi scene gen_video pass đúng các reference image paths từ DB assets vào FlowSDK.

**Cách làm**:
1. Trong `app/server/pipeline/orchestrator.py::_generate_scene()`, sau khi build prompt:
   ```python
   # Build reference_images list từ assets (Layer 2 ref images)
   ref_images: list[Path] = []
   asset_lock_anchors = getattr(asset_lock, "anchors", []) or []
   for anchor in asset_lock_anchors[:4]:  # MAX_ANCHORS=4
       # Anchor doesn't have file_path — need to look up by Asset.id or pass assets directly
       pass
   ```
2. Refactor: pass full `assets: list[Asset]` xuống `_generate_scene` thay vì chỉ `asset_lock`. Lấy top-4 anchors theo priority → resolve `file_path`:
   ```python
   def _resolve_ref_image_paths(assets, max_count=4) -> list[Path]:
       sorted_assets = sorted(assets, key=lambda a: _ROLE_PRIORITY.get(_infer_role(a.type), 99))
       paths: list[Path] = []
       for a in sorted_assets[:max_count]:
           if a.file_path and Path(a.file_path).exists():
               paths.append(Path(a.file_path))
       return paths
   ```
3. Truyền vào SDK:
   ```python
   operation_name = await self._sdk.gen_video(
       start_image=start_frame,
       prompt=final_prompt,
       project_id=flow_project_id,
       storage_dir=storage_dir,
       reference_images=ref_images,  # NEW
   )
   ```

**File ảnh hưởng**:
- `app/server/pipeline/orchestrator.py` (`run()`, `_run_scene`, `_generate_scene` — pass thêm `assets`)
- Helper `_resolve_ref_image_paths()` mới (cùng file hoặc utils)

**Acceptance**:
- [ ] Project có 2 character + 1 location asset → log `gen_video: attached 3 reference image(s)`
- [ ] FlowSDK upload tất cả ref ảnh, append `referenceImages` vào request body
- [ ] Veo3 trả về clip có nhân vật giống ref ảnh (visual verify)
- [ ] Scene KHÔNG có asset → vẫn gen được, ref_images=[] (no error)

**Verification**:
```powershell
# Tạo project, upload 2 ảnh character qua /api/assets/upload
# Generate → check log:
grep "FlowSDK gen_video: attached" storage/logs/*.log
# Visual: download final.mp4, verify nhân vật giống ref
```

**Effort**: 0.5 ngày

## Task 3.2 — Scene-asset mapping (Phase 2)

**Mục tiêu**: Cho phép user gán asset cụ thể cho từng scene (vd: scene 1-3 dùng character A, scene 4-6 dùng character B). Hiện asset là project-wide, mọi scene đều có cùng anchor list.

**Cách làm**:
1. Verify table `SceneAsset` (đã có ở `db/models/scene_asset.py`):
   - `scene_id`, `asset_id`, `role` (e.g. "main_character", "bg_location")
2. Backend route mới:
   - `POST /api/scenes/{id}/assets` body `{asset_id, role}`
   - `DELETE /api/scenes/{id}/assets/{asset_id}`
   - `GET /api/scenes/{id}` đã trả `assets: list[AssetRef]` — tốt
3. Orchestrator `_generate_scene`:
   - Nếu scene có `SceneAsset` rows → ưu tiên dùng những asset đó
   - Nếu không → fallback dùng project-wide assets (hiện tại)
4. UI Timeline mở SceneRow → dropdown chọn assets từ project's pool

**File ảnh hưởng**:
- `app/server/api/routes/scenes.py` (thêm 2 route POST/DELETE assets)
- `app/server/pipeline/orchestrator.py` (priority: scene-specific > project-wide)
- `app/ui/src/pages/Timeline.tsx` (UI gán asset cho scene)

**Acceptance**:
- [ ] User gán 1 character cho scene 1, 1 character khác cho scene 2 → 2 clip có 2 nhân vật khác nhau
- [ ] Scene không gán asset → fallback project-wide
- [ ] DELETE asset row khỏi scene_asset → ref không xuất hiện trong clip mới gen

**Effort**: 1 ngày

## Task 3.3 — Asset reference image generation (Layer 2 — phase 2 advanced)

**Mục tiêu**: Cho user nhập text description thay vì upload ảnh → AIFlow gọi `gen_image()` (FlowSDK) tạo ref ảnh từ Gemini → save vào assets.

**Cách làm**:
1. Backend route mới: `POST /api/assets/generate`:
   - Body: `{project_id, name, type, prompt}`
   - Internal: `flow_sdk.gen_image(prompt) → bytes → save to storage/media/{pid}/assets/`
   - Tạo Asset row với `source="generated"`, `file_path=...`
2. UI: thêm tab "Tạo bằng AI" trong AssetPanel:
   - Input prompt + dropdown type
   - Nút "Sinh ảnh" → gọi API → spinner → preview kết quả → "Lưu" hoặc "Sinh lại"
3. Cost tracking: mỗi gen_image tốn ~1 credit Veo3, log vào JobLog

**File ảnh hưởng**:
- `app/server/api/routes/assets.py` (thêm `/generate`)
- `app/ui/src/pages/Timeline.tsx` (extend AssetPanel)

**Acceptance**:
- [ ] User nhập "Nam thanh niên Việt Nam mặc áo trắng" + chọn character → ảnh PNG ≥ 50KB sinh ra
- [ ] Asset row tạo với `source="generated"`
- [ ] Có thể "Sinh lại" để retry
- [ ] Ảnh sinh ra sau đó dùng được làm reference_image cho gen_video

**Effort**: 0.5 ngày

## Tổng kết Nhóm 3

| Task | Effort | Block |
|------|--------|-------|
| 3.1 reference_images list trong _generate_scene | 0.5 ngày | 02-2.1 |
| 3.2 Scene-asset mapping | 1 ngày | 3.1 |
| 3.3 Asset gen từ Gemini | 0.5 ngày | 3.1 |
| **Tổng** | **2 ngày** | |
