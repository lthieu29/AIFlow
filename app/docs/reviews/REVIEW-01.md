# Review #1 — Spec audit (2026-05-26)

> **Reviewer**: User
> **Timestamp**: 2026-05-26 ~10:46 ICT
> **Action**: Fixed in spec v1.1
> **Trigger**: User review docs v1.0 trước khi approve Phase 0 code

## Summary

User audit toàn bộ 11 spec đầu tiên (v1.0), tìm ra **7 vấn đề**:
- 3 **critical** (sẽ block Phase 0 nếu code theo spec)
- 4 **non-critical** (sẽ gây bug ở phase tương ứng)

Tất cả 7 đã được fix trong spec v1.1. File này document lại để truy ngược.

## Issue table

| # | Severity | Issue | Spec(s) affected | Fix summary |
|---|----------|-------|------------------|-------------|
| 1 | 🔴 Critical | DB schema bootstrap missing — storage/ gitignored, không có cơ chế tạo `projects.db` lần đầu | 02, 09 | `bootstrap_schema()` trong `main.py` lifespan, dùng `SQLModel.metadata.create_all()`. Set `schema_version` vào `Config` table. Phase 1+ chuyển Alembic. Smoke test thêm check verify DB tồn tại. |
| 2 | 🔴 Critical | Extension WS port hardcoded `9223` — nếu user đổi `AIFLOW_WS_PORT` thì extension mù | 03, 04, 09 | Thêm endpoint `GET /api/ext/discovery` (no auth) trả `ws_url` động. Extension fetch discovery trước khi connect WS, retry 3s nếu agent chưa run. HTTP port 8101 cố định (chicken-and-egg). |
| 3 | 🔴 Critical | G3 cascade infinite loop — scene fail → reset downstream → fail → reset vô tận | 02, 07 | `Scene.cascade_retry_count` max 2 + `Project.cascade_event_count` max 5. Khi vượt scene limit → scene dùng character ref thay last_frame + cross-fade. Khi vượt project limit → mark project=failed, user phải intervene. Termination guarantee: ≤ 50 reset operations. |
| 4 | 🟡 Med | Visual layer dùng CDN GSAP+Tailwind — fail offline | 08 | Bundle GSAP vào `vendor/visual_layer/gsap.min.js` (~70KB). Templates dùng placeholder `{{__VENDOR_GSAP__}}` thay bằng `file://` path. Bỏ Tailwind CDN (3MB load mỗi render quá nặng), dùng inline CSS. |
| 5 | 🟡 Med | GeminiSettings missing api_key crash với Pydantic error khó đọc | 01 | Class `ConfigError` + `@model_validator` trên `GeminiSettings`. Hàm `load_settings()` wrap Pydantic exception. `main.py` catch và print friendly message, exit code 2 trước khi bind port. |
| 6 | 🟡 Med | SceneAsset M:N thiếu explicit indexes | 02 | Thêm `__table_args__` với 2 `Index` explicit `(scene_id)` và `(asset_id)` cho query 2 chiều nhanh. Composite PK đã có ngầm. Thêm field `metadata.variant_idx` cho variant pinning. |
| 7 | 🟡 Med | G2.8 manual gate không có SLA — block pipeline vô hạn nếu user để 3 ngày | 02, 07 | `QualityGate.expires_at = created_at + 24h` (config `AIFLOW_GATE_USER_TIMEOUT_HOURS`). Background job mỗi 60s quét expired → auto-pick variant 0. UI countdown + snooze button. 3 modes: `auto_pick` (default) / `fail` / `snooze_max_3`. |

## Files changed

| Spec | Sections changed |
|------|------------------|
| `01-config-spec.md` | Pydantic Settings code (thêm `ConfigError`, `@model_validator`, `load_settings()`); thêm 3 config field mới |
| `02-db-schema.md` | Project + Scene thêm cascade fields; SceneAsset có `__table_args__` + indexes; QualityGate thêm SLA fields; section "Bootstrap & migration strategy" mới |
| `03-api-contract.md` | Thêm endpoint `GET /api/ext/discovery` |
| `04-extension-spec.md` | `shared.js` thay hardcoded WS URL bằng `discoverAgent()` flow |
| `07-quality-gate-spec.md` | Cascade logic bounded; G2.8 SLA section mới |
| `08-visual-layer-spec.md` | Bundle GSAP local; templates dùng placeholder; renderer thay path |
| `09-phase0-execution.md` | task 0.4 thêm `ext_discovery.py`; smoke test thêm check DB |

Không file nào bị xoá. Tổng dòng thay đổi: ~+250 added, ~-30 removed.

## Validation

Sau fix, các spec có:
- ✅ Tất cả critical bug paths có termination guarantee
- ✅ Mọi external dependency (CDN, ports) có fallback hoặc discovery
- ✅ Mọi manual checkpoint có SLA + auto-resolve
- ✅ Bootstrap path Phase 0 → Phase 1 không có gap

## Lessons learned

Cho v2 review trong tương lai, check thêm:
- Có circular dependencies giữa specs không (vd spec A nói "see B" và spec B nói "see A")?
- Có data lifecycle nào missing init/cleanup step không?
- Có hardcoded value nào nên là config không?
- Có manual gate nào không có timeout không?
- Có recursive operation nào không có depth limit không?

## Next action

User review v1.1 → approve → bắt đầu Phase 0 task 0.1 (skeleton folder).

---

**Status**: All 7 issues addressed. Spec v1.1 ready for re-review.
