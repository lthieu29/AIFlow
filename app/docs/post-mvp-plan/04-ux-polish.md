# 04 — UX Polish (Priority: P1)

> Sau khi pipeline + UI cơ bản chạy, làm cho product feel chuyên nghiệp.
> **Effort tổng**: 5 ngày
> **Phụ thuộc**: 01-03 đã xong (UI cơ bản hoạt động)

## Task 4.1 — Toast / notification system

**Mục tiêu**: Thay `alert()` (Dashboard:72, Timeline:285) và inline error bằng toast notifications nhất quán.

**Cách làm**:
1. Cài `react-hot-toast` (đã được dùng nhiều, MIT, ~5KB):
   ```bash
   npm i react-hot-toast --save
   ```
2. Mount `<Toaster />` ở `App.tsx` (corner top-right, dark theme).
3. Tạo wrapper `app/ui/src/lib/toast.ts`:
   - `toast.success(msg)` / `error(msg)` / `info(msg)` / `loading(promise, msgs)`
   - Pre-set styles theo design system (zinc-900 bg, emerald accent).
4. Refactor 8 chỗ trong code dùng `alert()` / inline error block → toast.
5. Loading toast: `toast.promise(handleGenerate(), {loading: "Đang tạo...", success: "Tạo xong!", error: "Thất bại"})`.

**File ảnh hưởng**:
- `app/ui/package.json` (+ react-hot-toast)
- `app/ui/src/App.tsx` (+ `<Toaster />`)
- `app/ui/src/lib/toast.ts` (new wrapper)
- 5 file pages (Dashboard, Timeline, NewProject, VoiceGallery, Export)

**Acceptance**:
- [ ] Bấm Delete project → toast confirm thay alert
- [ ] Save scene success/fail → toast
- [ ] Generate → loading toast tự update theo SSE event
- [ ] Toast tự dismiss sau 4s, có nút close
- [ ] A11y: aria-live region

**Effort**: 0.5 ngày

## Task 4.2 — Loading skeletons

**Mục tiêu**: Thay text "Đang tải..." bằng skeleton placeholders để giảm cognitive load.

**Cách làm**:
1. Tạo component `app/ui/src/components/Skeleton.tsx`:
   - Variants: `<SkeletonRow />`, `<SkeletonCard />`, `<SkeletonText lines={3} />`
   - Tailwind: `bg-white/[0.04] animate-pulse rounded-xl`
2. Apply ở:
   - Dashboard: list 5 SkeletonRow trong khi load
   - Timeline: 3 SkeletonCard trong khi load scenes
   - VoiceGallery: 6 SkeletonCard cho voice grid
   - Export: SkeletonCard cho video player
3. Logic: render skeleton thay vì content khi `loading && data.length === 0`

**File ảnh hưởng**:
- `app/ui/src/components/Skeleton.tsx` (new)
- 4 page files (Dashboard, Timeline, VoiceGallery, Export)

**Acceptance**:
- [ ] First load show skeleton trong < 100ms
- [ ] Skeleton match shape của content thật (cùng padding/dimension)
- [ ] Animation pulse mượt 60fps
- [ ] Khi có data → fade-in transition

**Effort**: 1 ngày

## Task 4.3 — Scene preview thumbnail

**Mục tiêu**: Mỗi SceneRow trong Timeline có thumbnail (start_frame hoặc auto-gen) thay vì chỉ text. User dễ scan.

**Cách làm**:
1. Backend:
   - `GET /api/scenes/{id}/thumbnail` — serve `last_frame_path` hoặc gen từ video_path nếu chưa có
   - Nếu chưa gen → return placeholder
2. UI Timeline `SceneRow`:
   - Thêm `<img src="/api/scenes/{id}/thumbnail" />` aspect-video, w-32, rounded-lg
   - Lazy load với `loading="lazy"`
   - Nếu 404 → render placeholder icon (FilmStrip)
3. Sau khi scene gen xong → invalidate cache, reload thumbnail

**File ảnh hưởng**:
- `app/server/api/routes/scenes.py` (thêm route thumbnail)
- `app/ui/src/pages/Timeline.tsx` (SceneRow render thumb)

**Acceptance**:
- [ ] SceneRow render thumb trong < 1s
- [ ] Scene chưa gen → placeholder icon
- [ ] Scene đã gen → ảnh đầu hoặc cuối clip
- [ ] Cache hit ở browser, không reload mỗi render

**Effort**: 1 ngày

## Task 4.4 — Drag-and-drop reorder scenes

**Mục tiêu**: Thay nút lên/xuống bằng drag handle để reorder scene tự nhiên hơn.

**Cách làm**:
1. Cài `@dnd-kit/core` + `@dnd-kit/sortable` (~12KB, A11y-friendly):
   ```bash
   npm i @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
   ```
2. Wrap scene list trong `<DndContext>` + `<SortableContext>`:
   - `useSortable()` cho mỗi SceneRow
   - Drag handle icon (DotsSixVertical) ở góc trái card
3. Sau drop → reorder local state → batch PATCH server (`PATCH /api/scenes/{id}` với new order)
4. Optimistic UI: update local trước, rollback nếu API fail
5. Giữ nút lên/xuống làm fallback A11y (keyboard)

**File ảnh hưởng**:
- `app/ui/package.json`
- `app/ui/src/pages/Timeline.tsx` (DndContext + SortableContext)

**Acceptance**:
- [ ] Kéo SceneRow đổi vị trí mượt, không lag
- [ ] Sau drop → API update order, refresh → vị trí mới persist
- [ ] Keyboard: Tab + Space để move (A11y)
- [ ] Drag visual feedback (shadow, opacity)
- [ ] Không cho drag khi `isGenerating`

**Effort**: 1 ngày

## Task 4.5 — Batch scene editing

**Mục tiêu**: Cho phép multi-select scenes + apply action (delete, duplicate, change duration).

**Cách làm**:
1. UI Timeline:
   - Checkbox góc mỗi SceneRow
   - Top toolbar khi có selection: "Đã chọn 3 cảnh" + nút Delete / Duplicate / Set duration
   - Shift-click để select range, Cmd/Ctrl-click để toggle
2. Backend route:
   - `POST /api/scenes/batch` body `{action: "delete"|"set_duration"|"duplicate", scene_ids: list[int], payload?: dict}`
   - Hoặc dùng các route hiện có lặp lại với `Promise.all`
3. Confirm dialog cho destructive actions (delete)
4. Sau batch action → reload project

**File ảnh hưởng**:
- `app/ui/src/pages/Timeline.tsx` (selection state + toolbar)
- `app/server/api/routes/scenes.py` (route /batch optional)

**Acceptance**:
- [ ] Checkbox select 3 scenes → toolbar hiện "Đã chọn 3 cảnh"
- [ ] Click "Xóa" → confirm → 3 scene bị xóa, list refresh
- [ ] Click "Set duration" → input 5s → tất cả 3 scene đổi duration
- [ ] Esc deselect tất cả
- [ ] Selection mất khi rời page

**Effort**: 1.5 ngày

## Tổng kết Nhóm 4

| Task | Effort | Block |
|------|--------|-------|
| 4.1 Toast system | 0.5 ngày | — |
| 4.2 Loading skeletons | 1 ngày | — |
| 4.3 Scene thumbnail | 1 ngày | 02-2.1 |
| 4.4 Drag-drop reorder | 1 ngày | — |
| 4.5 Batch scene editing | 1.5 ngày | — |
| **Tổng** | **5 ngày** | |
