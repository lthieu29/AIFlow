# Requirements Document

## Introduction

`video-variety-expansion` là một spec tính năng MỚI, độc lập với `content-expansion` (đã đóng) và `aiflow` (nhật ký triển khai). Mục tiêu của tính năng này là **mở rộng sự đa dạng "loại video làm ra"** của AIFlow bằng cách thêm các skill data-only mới và refactor các skill hiện có theo công thức prompt chất lượng cao đã được battle-tested ngoài cộng đồng (tham chiếu kit `lanshu-awesome-ai-video-kit`).

Tính năng KHÔNG sửa code lõi của pipeline (`server/content/registry.py`, `server/content/skill_loader.py`, `server/content/base.py`), KHÔNG thêm video provider mới ngoài Veo3, KHÔNG đụng adapter axis hay visual-template axis. Chỉ làm việc trên **trục Skill** (data-only).

Tính năng được chia thành các nhóm công việc:

1. **Chuẩn hoá `_base` skill** — `_base/prefix.md` chuyển sang công thức Veo 8-element + camera lexicon + constraint terms; `_base/style.json` bổ sung khoá đầy đủ (đồng nhất R3.11 của content-expansion); `_base` cung cấp các nhánh `negative_prompts` mặc định để mọi skill thừa kế tránh watermark/logo/subtitle.
2. **Refactor 6 skill hiện có** (`ecommerce-fashion`, `kdrama-romance`, `explainer-tech`, `cinematic-action`, `ecommerce-tech`, `ecommerce-food`) — áp cùng formula Veo 8-element vào `prefix.md`, đồng nhất `style.json` 6 khoá, đồng nhất các template file (`character.md`, `scene.md`, `motion.md`).
3. **Thêm 30 skill mới** đại diện 30 "loại video làm ra" được lanshu liệt kê — mỗi skill là một thư mục data-only đủ 7 file, theo cùng layout đã chuẩn hoá ở Skill_Layout_7_File.
4. **Khai báo skill–adapter pairing chặt chẽ** — mỗi skill (cũ refactor + mới) khai báo `supported_adapters` chính xác để pipeline biết cặp nào hoạt động được.
5. **Test bao phủ** — mỗi skill mới phải pass `Skill_Loader.validate_skill()`, `load()` trả `LoadedSkill` với `style` hợp lệ, prefix sau load chứa các keyword cốt lõi của Veo 8-element và 3 constraint cơ bản (no-watermark, no-logo, no-subtitle).

### Trạng thái hiện tại đã xác minh (đọc code)

- Skill hiện có (sau khi `content-expansion` đóng): `_base`, `ecommerce-fashion`, `kdrama-romance`, `explainer-tech`, `cinematic-action`, `ecommerce-tech`, `ecommerce-food` — tổng 6 skill thật + 1 skill `_base`.
- `SkillLoader.validate_skill` chỉ kiểm: thư mục tồn tại, `manifest.yaml` hợp lệ, `style.json` (nếu được tham chiếu) hợp lệ. KHÔNG kiểm `prefix.md` ≥ 20 từ, KHÔNG kiểm 6 khoá `style.json` đầy đủ — các kiểm tra này phải tự test (giống pattern `test_skills_new.py` của content-expansion).
- `validate_style_json` chỉ bắt buộc 3 khoá (`art_style`, `lighting`, `color_palette`); nhưng convention của các skill mới (R3.11 của content-expansion) là 6 khoá: thêm `camera_rules`, `negative_prompts`, `aspect_ratio`. Spec này tiếp tục convention 6 khoá.
- 11 adapter hiện đăng ký qua auto-discovery: `blog_article`, `document_summary`, `ecommerce_product`, `epub_novel`, `lyric_video`, `narrative_script`, `news_bulletin`, `photo_slideshow`, `podcast_caption`, `script_direct`, `storyboard_manual`, `video_remaster` (12 — bao gồm `video_remaster` passthrough).

### Ngoài phạm vi (KHÔNG đưa vào tính năng này)

- Thêm video provider ngoài Veo3 (không tích hợp Kling/Sora/Seedance/Runway/Pika/Hailuo/Hunyuan/Wan/Jimeng/HappyHorse hay các open-source local).
- Thêm adapter input mới (đã đóng ở content-expansion R4).
- Thêm visual-layer template mới (đã đóng ở content-expansion R5).
- Sửa code lõi của pipeline (`registry.py`, `skill_loader.py`, `base.py`, `style_validator.py`).
- Custom TTS / voice training.
- Wiring skill mới vào UI Phase 5 (UI chưa làm).
- Multi-formula skill (mỗi skill dùng formula khác nhau — đã quyết định dùng **Veo 8-element thống nhất** cho mọi skill).

## Glossary

- **AIFlow**: Tool sinh video AI cá nhân, native Windows, phụ thuộc Google Flow Pro + Gemini free tier.
- **Skill**: Một thư mục data-only trong `skills/<name>/` theo Skill_Layout_7_File.
- **Skill_Layout_7_File**: 7 file của một skill: `manifest.yaml`, `style.json`, `prefix.md`, `character.md`, `scene.md`, `motion.md`, `voice.yaml`.
- **Skill_Loader**: `server/content/skill_loader.py` — load/validate/áp skill; method `validate_skill()` trả list lỗi (rỗng = hợp lệ).
- **LoadedSkill**: Dataclass do `SkillLoader.load(name)` trả về; chứa `manifest`, `style`, `prefix`, `skill_dir`.
- **Veo_8_Element_Formula**: Công thức prompt 8 yếu tố cho Veo3 (Google DeepMind official): (1) Shot framing & motion, (2) Style, (3) Lighting, (4) Character description, (5) Location, (6) Action, (7) Dialogue, (8) Audio. Khuyến nghị 100–150 từ; tách `Dialogue:` và `Audio:` thành dòng riêng.
- **Camera_Lexicon**: Bộ từ vựng máy quay chuẩn (lanshu/methodology/05) — gồm shot size (EWS/WS/MS/MCU/CU/ECU), camera motion (dolly in/out, pan, tilt, tracking, orbit, handheld, gimbal, steadicam, drone), lighting type (golden hour, blue hour, hard key light, soft window light, neon spill, volumetric, backlight, practical, studio, butterfly, tungsten, fluorescent), style keywords (cinematic, documentary, commercial, cyberpunk, vintage, anime, ink-wash, surreal, film noir, Wes Anderson), color grading (teal-orange, warm, cool, desaturated, monochrome).
- **Constraint_Terms**: Bộ từ ràng buộc chuẩn (lanshu/methodology/06) — 3 ràng buộc cơ bản BẮT BUỘC mọi prefix có (no watermark, no Logo, no subtitle/text overlay), cộng các nhánh tuỳ skill: stability, style consistency, anti-twin, camera stability, audio cleanliness.
- **Twelve_Pitfalls**: 12 lỗi thường gặp (lanshu/methodology/08) — ID drift, subtitles, logo/watermark, style drift, splice jump, twin/clone, quality decay, effect mismatch, too many references, end audio noise, Chinese mispronunciation, voice mismatch.
- **Authoritative_Adapter_Pairing**: Mỗi skill chỉ liệt kê các `adapter_type` mà skill thật sự phù hợp. Một adapter có thể xuất hiện trong nhiều skill, nhưng skill KHÔNG được liệt kê adapter mà nó không tương thích về mặt nội dung. Pipeline orchestrator sau này có thể dùng cờ này để gating.
- **Skill_Categories**: Phân loại 30 skill mới thành các nhóm có ý nghĩa cho UI Phase 5 và discovery: `commercial`, `cinematic`, `social-viral`, `nature`, `action`, `dialogue-driven`, `educational`, `lifestyle`, `experimental`, `chinese-native`.
- **Adapter_Type**: Chuỗi định danh adapter (giống convention của `content-expansion`) — gồm `script_direct`, `narrative_script`, `blog_article`, `storyboard_manual`, `epub_novel`, `ecommerce_product`, `document_summary`, `lyric_video`, `news_bulletin`, `podcast_caption`, `photo_slideshow`, `video_remaster`.
- **Style_Required_Keys**: Bộ 6 khoá bắt buộc trong `style.json`: `art_style`, `lighting`, `color_palette`, `camera_rules`, `negative_prompts`, `aspect_ratio`.
- **Manifest_Required_Fields**: Bộ trường bắt buộc trong `manifest.yaml`: `name`, `version`, `adapter_type`, `extends`, `style_ref`, `voice`, `supported_adapters`.
- **Lanshu**: `lanshu-awesome-ai-video-kit` — kit prompt-engineering tham chiếu cho 15 model AI video (Veo, Sora, Kling, Seedance, HappyHorse, Runway, Pika, Hailuo, Hunyuan, Wan, Jimeng + 4 open source). AIFlow chỉ dùng Veo3 nên chỉ áp methodology Veo + camera lexicon + constraint terms từ lanshu.

## Requirements

### Requirement 1: Chuẩn hoá `_base` skill theo Veo 8-element formula

**User Story:** Là người bảo trì AIFlow, tôi muốn `_base` skill cung cấp một foundation prompt chất lượng cao theo công thức Veo 8-element + 3 constraint cơ bản, để mọi skill thừa kế đều thừa hưởng chất lượng prompt nhất quán.

#### Acceptance Criteria

1. THE `_base/prefix.md` SHALL chứa các tên gọi tường minh của 8 yếu tố Veo (`Shot framing`, `Style`, `Lighting`, `Character`, `Location`, `Action`, `Dialogue`, `Audio`) hoặc các từ tương đương rõ nghĩa, để các skill con áp lên có thể bám vào cấu trúc đó.
2. THE `_base/prefix.md` SHALL khai báo 3 constraint cơ bản (no watermark, no logo, no subtitle/text overlay) đúng câu chữ ở dạng prompt-ready.
3. THE `_base/prefix.md` SHALL chứa tối thiểu 60 từ nội dung thực chất (không tính khoảng trắng).
4. THE `_base/style.json` SHALL chứa đầy đủ Style_Required_Keys (`art_style`, `lighting`, `color_palette`, `camera_rules`, `negative_prompts`, `aspect_ratio`).
5. THE `_base/style.json.negative_prompts` SHALL chứa tối thiểu 5 mục, bao gồm `watermark`, `logo`, `subtitle` (hoặc cụm tương đương như `text overlay`).
6. WHEN `SkillLoader.validate_skill("_base")` được gọi, THE Skill_Loader SHALL trả về một danh sách rỗng.
7. WHEN `SkillLoader.load(<bất kỳ skill nào với extends:_base>)` được gọi, THE Skill_Loader SHALL ghép `_base/prefix.md` vào trước prefix riêng của skill (đã có sẵn ở SkillLoader, nhưng SHALL được kiểm bằng test).
8. THE `_base/manifest.yaml` SHALL giữ nguyên các trường lõi sẵn có (`name: _base`, `version`, `adapter_type: ""`, `style_ref: style.json`); KHÔNG ĐƯỢC bị sửa hỏng schema.

### Requirement 2: Refactor 6 skill hiện có theo Veo 8-element formula

**User Story:** Là người bảo trì AIFlow, tôi muốn 6 skill hiện có (`ecommerce-fashion`, `kdrama-romance`, `explainer-tech`, `cinematic-action`, `ecommerce-tech`, `ecommerce-food`) được refactor theo cùng formula với 30 skill mới, để toàn bộ thư viện skill nhất quán về chất lượng và format.

#### Acceptance Criteria

1. THE 6 skill liệt kê (`ecommerce-fashion`, `kdrama-romance`, `explainer-tech`, `cinematic-action`, `ecommerce-tech`, `ecommerce-food`) SHALL giữ nguyên `adapter_type` đã khai báo (KHÔNG đổi `adapter_type` để tránh phá compatibility).
2. WHEN `SkillLoader.validate_skill(<tên skill>)` được gọi cho mỗi skill trong 6 skill trên, THE Skill_Loader SHALL trả về một danh sách rỗng.
3. THE `prefix.md` của mỗi skill trong 6 skill trên SHALL chứa tối thiểu 40 từ nội dung thực chất.
4. THE `prefix.md` của mỗi skill trong 6 skill trên SHALL phản ánh được tối thiểu 5 trong 8 yếu tố Veo (subset cụ thể tuỳ skill — ví dụ skill product không nhất thiết có Dialogue).
5. THE `style.json` của mỗi skill trong 6 skill trên SHALL chứa đầy đủ Style_Required_Keys.
6. THE `style.json.negative_prompts` của mỗi skill trong 6 skill trên SHALL chứa tối thiểu 8 mục, gồm 3 ràng buộc cơ bản (`watermark`, `logo`, `text overlay`/`subtitle`) cộng tối thiểu 2 ràng buộc đặc thù skill.
7. THE `character.md`, `scene.md`, `motion.md` của mỗi skill trong 6 skill trên SHALL không rỗng và chứa nội dung template thực chất (mỗi file ≥ 30 từ và > 1 dòng nội dung).
8. THE `voice.yaml` của mỗi skill trong 6 skill trên SHALL khai báo `primary_backend` và `primary_voice`.
9. WHERE một skill trong 6 skill trên trước đây CHƯA có `supported_adapters`, THE manifest.yaml của skill đó SHALL được bổ sung `supported_adapters` đúng theo Authoritative_Adapter_Pairing.
10. WHERE refactor sửa nội dung file dữ liệu, THE Content SHALL không thêm bất kỳ file Python (`*.py`) nào vào thư mục skill.

### Requirement 3: Thêm 30 skill mới (data-only)

**User Story:** Là người dùng AIFlow, tôi muốn có một thư viện đầy đủ 30 "loại video làm ra" để chọn phong cách phù hợp cho từng nội dung mà không phải tự nghĩ prompt từ đầu.

#### Acceptance Criteria

1. THE Content SHALL thêm đủ 30 skill mới sau dưới dạng các thư mục trong `skills/`:

   **Nhóm `commercial` (5):** `ecommerce-beauty`, `ecommerce-jewelry`, `ecommerce-home`, `product-tech-launch`, `product-minimal-rotate`.

   **Nhóm `cinematic` (5):** `cinematic-noir`, `cinematic-drama`, `cinematic-thriller`, `cinematic-romance`, `cinematic-period`.

   **Nhóm `social-viral` (4):** `social-viral-hook`, `social-viral-transform`, `social-viral-pet-comedy`, `social-viral-meme`.

   **Nhóm `nature` (3):** `nature-landscape`, `nature-wildlife`, `nature-timelapse`.

   **Nhóm `action` (3):** `action-sports-pov`, `action-extreme`, `action-wuxia`.

   **Nhóm `dialogue-driven` (3):** `dialogue-interview`, `dialogue-vlog`, `dialogue-podcast-clip`.

   **Nhóm `educational` (2):** `explainer-finance`, `explainer-history`.

   **Nhóm `lifestyle` (2):** `travel-vlog`, `lifestyle-wellness`.

   **Nhóm `experimental` (2):** `experimental-abstract`, `experimental-asmr`.

   **Nhóm `chinese-native` (1):** `chinese-ink-wash`.

2. THE Content SHALL tạo mỗi skill mới chỉ gồm file dữ liệu, không chứa file Python.
3. WHERE một skill mới được tạo, THE Content SHALL bao gồm đầy đủ Skill_Layout_7_File.
4. WHEN `SkillLoader.validate_skill(<tên skill mới>)` được gọi, THE Skill_Loader SHALL trả về một danh sách rỗng cho mỗi skill mới.
5. THE `manifest.yaml` của mỗi skill mới SHALL khai báo đầy đủ Manifest_Required_Fields.
6. WHERE một skill mới khai báo `extends: _base`, THE Skill_Loader SHALL ghép prefix của `_base` vào trước prefix riêng của skill khi load.
7. THE 30 skill mới SHALL khai báo `extends: _base` (không skill nào extends một skill khác ngoài `_base`).
8. WHEN `SkillLoader.load(<tên skill mới>)` được gọi, THE Skill_Loader SHALL trả về một LoadedSkill có `style` hợp lệ theo `validate_style_json`.
9. THE `manifest.yaml` của mỗi skill mới SHALL liệt kê các adapter tương thích trong trường `supported_adapters` theo Authoritative_Adapter_Pairing.
10. THE `prefix.md` của mỗi skill mới SHALL chứa tối thiểu 60 từ nội dung thực chất.
11. THE `prefix.md` của mỗi skill mới SHALL phản ánh được tối thiểu 5 trong 8 yếu tố Veo, và SHALL có tối thiểu 1 từ khoá camera lexicon (từ Camera_Lexicon).
12. THE `style.json` của mỗi skill mới SHALL chứa đầy đủ Style_Required_Keys.
13. THE `style.json.negative_prompts` của mỗi skill mới SHALL chứa tối thiểu 8 mục, gồm 3 ràng buộc cơ bản (`watermark`, `logo`, `text overlay`/`subtitle`) cộng tối thiểu 2 ràng buộc đặc thù skill.
14. THE `character.md`, `scene.md`, `motion.md` của mỗi skill mới SHALL không rỗng và chứa nội dung template thực chất (mỗi file ≥ 30 từ và > 1 dòng nội dung).
15. THE `voice.yaml` của mỗi skill mới SHALL khai báo `primary_backend` và `primary_voice`.
16. THE `name` trong `manifest.yaml` của mỗi skill mới SHALL khớp tên thư mục của skill (case-sensitive).
17. THE 30 tên skill mới SHALL không trùng lặp với 6 skill hiện có và không trùng lặp với nhau.

### Requirement 4: Authoritative skill–adapter pairing

**User Story:** Là người dùng AIFlow, tôi muốn từng skill khai báo chính xác các adapter mà nó thật sự phù hợp, để pipeline có thể từ chối các tổ hợp vô nghĩa và UI có thể chỉ hiển thị skill phù hợp với input đang chọn.

#### Acceptance Criteria

1. THE `manifest.yaml.adapter_type` của mỗi skill SHALL trỏ tới một adapter_type đang đăng ký trong `AdapterRegistry` sau `auto_discover`.
2. THE `manifest.yaml.supported_adapters` của mỗi skill SHALL là một danh sách non-empty các adapter_type đang đăng ký trong `AdapterRegistry`.
3. THE `manifest.yaml.adapter_type` của mỗi skill SHALL xuất hiện trong `manifest.yaml.supported_adapters` của chính skill đó (adapter chính phải nằm trong danh sách compatible).
4. THE Authoritative_Adapter_Pairing SHALL được tài liệu hoá tường minh trong `design.md` (bảng skill → list adapter_type).
5. WHERE một skill nhắm tới một loại nội dung cụ thể (ví dụ `dialogue-podcast-clip` ↔ `podcast_caption`), THE `supported_adapters` của skill đó SHALL bao gồm adapter chính của loại nội dung đó.
6. WHERE một adapter không tương thích về mặt nội dung với skill (ví dụ `video_remaster` passthrough KHÔNG nên áp skill phong cách Veo3), THE `supported_adapters` của skill SHALL không liệt kê adapter đó.
7. THE Authoritative_Adapter_Pairing SHALL không bao gồm `video_remaster` trong bất kỳ skill nào (vì `video_remaster` là passthrough, không sinh clip Veo3).

### Requirement 5: Test bao phủ — chất lượng prompt + structural

**User Story:** Là người bảo trì AIFlow, tôi muốn mỗi skill được kiểm bằng test tự động để khi sửa skill bất kỳ trong tương lai, suite test bắt được các sai lệch khỏi convention.

#### Acceptance Criteria

1. THE Content SHALL thêm test parametrized bao phủ TẤT CẢ skill (`_base` + 6 skill cũ refactor + 30 skill mới = 37 skill).
2. WHEN test chạy `SkillLoader.validate_skill(<skill>)` cho mỗi skill, THE test SHALL assert kết quả là `[]`.
3. WHEN test load mỗi skill qua `SkillLoader.load`, THE test SHALL assert `LoadedSkill.style` pass `validate_style_json`.
4. WHEN test load mỗi skill, THE test SHALL assert `LoadedSkill.style` chứa đầy đủ Style_Required_Keys.
5. WHEN test load mỗi skill ngoài `_base`, THE test SHALL assert `LoadedSkill.prefix` chứa các substring tương ứng với 3 ràng buộc cơ bản (`watermark`, `logo`, `subtitle`/`text overlay`) — chứng minh `_base` được merge vào.
6. WHEN test load mỗi skill ngoài `_base`, THE test SHALL assert `LoadedSkill.prefix` chứa tối thiểu 1 từ khoá camera lexicon từ Camera_Lexicon.
7. THE test SHALL assert mỗi skill mới (30 skill) có `prefix.md` với word count ≥ 60 (đo trên file thô, không qua merge).
8. THE test SHALL assert mỗi skill cũ (6 refactor) có `prefix.md` với word count ≥ 40.
9. THE test SHALL assert mỗi skill có 7 file đúng theo Skill_Layout_7_File.
10. THE test SHALL assert không skill nào chứa file Python (`*.py`).
11. THE test SHALL assert `manifest.yaml.name` của mỗi skill khớp tên thư mục.
12. THE test SHALL assert `manifest.yaml.adapter_type` của mỗi skill xuất hiện trong `manifest.yaml.supported_adapters`.
13. THE test SHALL assert tất cả `adapter_type` được liệt kê (chính + supported) thuộc tập 11 adapter_type đã đăng ký (loại trừ `video_remaster` per R4.7).
14. THE test SHALL assert tổng số skill mới (không tính `_base` và 6 skill cũ) là 30 — bộ skill bắt buộc đầy đủ.

### Requirement 6: Ràng buộc chung & bảo toàn pipeline lõi

**User Story:** Là người bảo trì AIFlow, tôi muốn spec này không chạm vào bất kỳ code Python lõi nào, để pipeline đã ổn định không bị rủi ro hồi quy.

#### Acceptance Criteria

1. THE Content SHALL không sửa `server/content/registry.py`.
2. THE Content SHALL không sửa `server/content/skill_loader.py`.
3. THE Content SHALL không sửa `server/content/style_validator.py`.
4. THE Content SHALL không sửa `server/content/skill_manifest.py`.
5. THE Content SHALL không sửa `server/content/base.py`.
6. THE Content SHALL không thêm hoặc sửa bất kỳ file `*.py` nào trong `server/content/adapters/`.
7. THE Content SHALL không thêm hoặc sửa bất kỳ file nào trong `server/render/visual_layer/`.
8. WHEN test chạy `auto_discover("server.content.adapters")`, THE registry SHALL có chính xác 11 adapter (như sau content-expansion + `video_remaster` = 12). Spec này không thay đổi số adapter.
9. WHERE skill mới được tạo, THE skill SHALL được phát hiện và load được CHỈ qua convention data-only, không cần thay đổi bất kỳ code nào.