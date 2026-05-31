# Implementation Plan — video-variety-expansion

## Overview

Mở rộng số "loại video làm ra" từ 6 → 37 skill bằng data-only, không sửa code. Tasks build tăng dần theo wave và check-pointed bằng test.

Thứ tự thực hiện: (1) refactor `_base` → (2) hạ tầng test → (3) refactor 6 skill cũ → (4) checkpoint → (5) thêm 30 skill mới theo từng nhóm category → (6) checkpoint → (7) test pairing + tripwire → (8) final checkpoint.

## Tasks

- [x] 1. Hạ tầng test + refactor `_base` skill
  - [x] 1.1 Refactor `skills/_base/prefix.md` theo Veo 8-element formula
    - Thay nội dung `prefix.md` theo template trong `design.md` Component 0 (≥ 60 từ; chứa 8 ô khung Veo + 3 ràng buộc cơ bản)
    - _Requirements: 1.1, 1.2, 1.3, 6.6_

  - [x] 1.2 Refactor `skills/_base/style.json` đủ 6 khoá
    - Thêm `camera_rules`, `negative_prompts` (≥ 5 mục, gồm `watermark`/`logo`/`subtitle`), `aspect_ratio` theo Component 0; giữ nguyên 3 khoá lõi
    - _Requirements: 1.4, 1.5_

  - [x] 1.3 Bộ keyword + helper test dùng chung
    - Tạo `server/tests/_skills_keywords.py` với 3 set hằng: `VEO_KEYWORDS`, `CAMERA_KEYWORDS`, `CONSTRAINT_KEYWORDS` (xem design Component 2)
    - Tạo helper `_word_count(text)` (tham khảo `test_skills_new.py`) — để tái dùng
    - _Requirements: 5.5, 5.6_

  - [x] 1.4 Test framework cho `_base`
    - File `server/tests/test_skills_all.py`: parametrize `_base` riêng; assert `validate_skill("_base") == []`, `style.json` đủ 6 khoá
    - _Requirements: 1.6, 1.8_


- [x] 2. Refactor 6 skill cũ
  - [x] 2.1 Refactor `ecommerce-fashion`
    - 6 file dữ liệu (KHÔNG đụng manifest `adapter_type`); prefix ≥ 40 từ phản ánh ≥ 5 yếu tố Veo; style.json 6 khoá; negative_prompts ≥ 8; character/scene/motion ≥ 30 từ; voice.yaml `primary_backend`+`primary_voice`; supported_adapters theo Authoritative_Adapter_Pairing
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_

  - [x] 2.2 Refactor `kdrama-romance` (cùng quy ước)
    - _Requirements: 2.1–2.10_

  - [x] 2.3 Refactor `explainer-tech` (cùng quy ước)
    - _Requirements: 2.1–2.10_

  - [x] 2.4 Refactor `cinematic-action` (cùng quy ước)
    - _Requirements: 2.1–2.10_

  - [x] 2.5 Refactor `ecommerce-tech` (cùng quy ước)
    - _Requirements: 2.1–2.10_

  - [x] 2.6 Refactor `ecommerce-food` (cùng quy ước)
    - _Requirements: 2.1–2.10_


- [x] 3. Checkpoint — `_base` + 6 skill cũ pass test framework
  - Chạy: `pytest server/tests/test_skills_all.py -k "ecommerce-fashion or kdrama-romance or explainer-tech or cinematic-action or ecommerce-tech or ecommerce-food or _base"`
  - Toàn bộ phải xanh trước khi bước sang task 4.


- [x] 4. Thêm 5 skill nhóm `commercial`
  - [x] 4.1 `ecommerce-beauty` (7 file, adapter `ecommerce_product`, supported: ecommerce_product/storyboard_manual/script_direct)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 4.1, 4.2, 4.3, 4.5_
  - [x] 4.2 `ecommerce-jewelry`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 4.3 `ecommerce-home`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 4.4 `product-tech-launch` (supported_adapters thêm `narrative_script` cho hero stories)
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 4.5 `product-minimal-rotate` (supported_adapters: ecommerce_product/script_direct/photo_slideshow)
    - _Requirements: 3.1–3.17, 4.1–4.7_


- [x] 5. Thêm 5 skill nhóm `cinematic`
  - [x] 5.1 `cinematic-noir`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 5.2 `cinematic-drama`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 5.3 `cinematic-thriller`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 5.4 `cinematic-romance`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 5.5 `cinematic-period`
    - _Requirements: 3.1–3.17, 4.1–4.7_


- [x] 6. Thêm 4 skill nhóm `social-viral`
  - [x] 6.1 `social-viral-hook` (3-second hook + payoff format)
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 6.2 `social-viral-transform`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 6.3 `social-viral-pet-comedy`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 6.4 `social-viral-meme`
    - _Requirements: 3.1–3.17, 4.1–4.7_


- [x] 7. Thêm 3 skill nhóm `nature`
  - [x] 7.1 `nature-landscape`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 7.2 `nature-wildlife`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 7.3 `nature-timelapse`
    - _Requirements: 3.1–3.17, 4.1–4.7_


- [x] 8. Thêm 3 skill nhóm `action`
  - [x] 8.1 `action-sports-pov`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 8.2 `action-extreme`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 8.3 `action-wuxia` (Chinese-flavoured action)
    - _Requirements: 3.1–3.17, 4.1–4.7_


- [x] 9. Thêm 3 skill nhóm `dialogue-driven`
  - [x] 9.1 `dialogue-interview`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 9.2 `dialogue-vlog`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 9.3 `dialogue-podcast-clip` (adapter chính = `podcast_caption`)
    - _Requirements: 3.1–3.17, 4.1–4.7_


- [x] 10. Thêm 2 skill nhóm `educational`
  - [x] 10.1 `explainer-finance`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 10.2 `explainer-history`
    - _Requirements: 3.1–3.17, 4.1–4.7_


- [x] 11. Thêm 2 skill nhóm `lifestyle`
  - [x] 11.1 `travel-vlog`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 11.2 `lifestyle-wellness`
    - _Requirements: 3.1–3.17, 4.1–4.7_


- [x] 12. Thêm 2 skill nhóm `experimental`
  - [x] 12.1 `experimental-abstract`
    - _Requirements: 3.1–3.17, 4.1–4.7_
  - [x] 12.2 `experimental-asmr` (adapter chính = `narrative_script`, nhưng supported_adapters bao gồm `podcast_caption`)
    - _Requirements: 3.1–3.17, 4.1–4.7_


- [x] 13. Thêm 1 skill nhóm `chinese-native`
  - [x] 13.1 `chinese-ink-wash`
    - _Requirements: 3.1–3.17, 4.1–4.7_


- [x] 14. Checkpoint — toàn bộ 30 skill mới pass test framework
  - Chạy: `pytest server/tests/test_skills_all.py`
  - 37 skill (1 + 6 + 30) phải pass mọi test parametrized.


- [x] 15. Test pairing + tripwire
  - [x] 15.1 Tạo `server/tests/test_skills_pairing.py`
    - 4 test parametrize 36 skill (loại `_base`): `adapter_type` đăng ký, mọi `supported_adapters` đăng ký, `adapter_type ∈ supported_adapters`, `video_remaster ∉ supported_adapters` (R4.7)
    - _Requirements: 4.1, 4.2, 4.3, 4.6, 4.7_

  - [x] 15.2 Tripwire: skill set đầy đủ + đúng
    - Trong `test_skills_all.py`: thêm `test_required_30_skills_complete()` (R3.1) và `test_no_extra_skills_outside_known_sets()` (R5.14)
    - _Requirements: 3.1, 3.17, 5.14_

  - [x] 15.3 Tripwire: core không bị sửa
    - Trong `test_skills_pairing.py`: thêm `test_no_changes_to_skill_loader_core()` assert public API của `SkillLoader` còn nguyên (`load`, `validate_skill`, `list_skills`)
    - _Requirements: 6.1–6.7_


- [x] 16. Final checkpoint — full suite xanh + commit
  - Chạy `pytest server/tests` toàn bộ; mọi test pre-existing + 2 file mới phải xanh
  - Đếm số skill bằng `ls skills/` xác nhận đúng 37 thư mục
  - Commit theo 2 hoặc 3 commit: (a) `_base` + 6 refactor; (b) 30 skill mới; (c) 2 test file
  - _Requirements: ALL_

## Notes

- Mỗi task ở wave 4–13 đều có cùng cấu trúc 7 file dữ liệu — sản xuất hàng loạt được nhờ template trong `design.md` Component 2.
- Nội dung từng skill phải **specific** cho loại video tương ứng (không copy-paste boilerplate). Bộ test sẽ phát hiện skill nội dung quá generic (camera_keyword không có, hoặc word count thiếu).
- Skill `_base` refactor (task 1.1, 1.2) ảnh hưởng **mọi** skill thừa kế nó. Vì vậy bắt buộc làm trước task 2.* và toàn bộ task 4–13.
- Không có property test (≥ 100 iteration) trong spec này — toàn bộ là parametrized example test, đủ vì surface area là static (37 thư mục, mỗi thư mục là 7 file đã biết schema).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6"] },
    { "id": 2, "tasks": ["3"] },
    { "id": 3, "tasks": ["4.1","4.2","4.3","4.4","4.5","5.1","5.2","5.3","5.4","5.5"] },
    { "id": 4, "tasks": ["6.1","6.2","6.3","6.4","7.1","7.2","7.3","8.1","8.2","8.3"] },
    { "id": 5, "tasks": ["9.1","9.2","9.3","10.1","10.2","11.1","11.2","12.1","12.2","13.1"] },
    { "id": 6, "tasks": ["14"] },
    { "id": 7, "tasks": ["15.1", "15.2", "15.3"] },
    { "id": 8, "tasks": ["16"] }
  ]
}
```
