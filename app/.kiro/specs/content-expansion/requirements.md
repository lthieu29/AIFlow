# Requirements Document

## Introduction

`content-expansion` là một spec tính năng MỚI, độc lập với spec `aiflow` (vốn là nhật ký triển khai trước đó). Mục tiêu của tính năng này là **mở rộng hai trục tính năng trực giao đã có sẵn** của AIFlow mà KHÔNG sửa code lõi (core) của pipeline:

- **Trục Adapter** (loại input): hoàn thiện adapter còn dở, đăng ký adapter đã có logic nhưng chưa wrap, và thêm các adapter cho loại input mới.
- **Trục Skill** (phong cách): thêm các skill data-only mới.
- **Trục Visual Template** (lớp overlay): thêm các template HTML+GSAP mới.

Tính năng được chia thành 6 nhóm công việc:

1. **Hoàn thiện adapter `script_direct`** — adapter pass-through, nhận dict/JSON scenes thô, validate theo hợp đồng spec 05, trả về `SceneList`, đăng ký qua auto-discovery.
2. **Wrap & đăng ký `video_remaster` thành ContentAdapter** — bắc cầu logic `VideoRemaster`/crawler đã có thành một adapter đăng ký được (`adapter_type = "video_remaster"`), tái sử dụng code crawler hiện hữu, không viết lại.
3. **Thêm Skill mới (data-only)** — tối thiểu `explainer-tech`, `cinematic-action`, cộng các biến thể `ecommerce-tech`, `ecommerce-food`; mỗi skill theo layout 7 file và phải pass `SkillLoader.validate_skill()`.
4. **Thêm Adapter cho loại input mới** — cả năm adapter sau đều thuộc phạm vi và BẮT BUỘC triển khai cho tính năng này: PDF/Word → video tóm tắt (`document_summary`), bài hát + lời → lyric video (`lyric_video`), RSS/news → bản tin (`news_bulletin`), podcast/audio → video phụ đề (`podcast_caption`), album ảnh → slideshow kỷ niệm (`photo_slideshow`).
5. **Thêm Visual-layer Template mới** — các template overlay ngoài 5 cái hiện có (ví dụ `quote_card`, `stat_card`, `news_ticker`, `lyric_line`), tích hợp với `playwright_renderer` + `hf_protocol` + `template_registry`.
6. **Sửa & xác minh luồng `video_remaster` URL→video chạy thật end-to-end** — đảm bảo chuỗi đầy đủ (download → lấy/transcribe phụ đề → dịch sang tiếng Việt qua Gemini → burn phụ đề) thực sự chạy được với URL Bilibili/Douyin thật cho preset `LIGHT` và `TRANSLATE_ONLY` (không chỉ test mock); preset `AGGRESSIVE` (thay audio gốc bằng TTS tiếng Việt) được HOÃN và phải hành xử có thể dự đoán, không giả vờ thành công.

### Trạng thái hiện tại đã xác minh (đọc code)

- Adapter đăng ký & hoạt động (5): `ecommerce_product`, `narrative_script`, `blog_article`, `storyboard_manual`, `epub_novel`.
- `script_direct`: thư mục `server/content/adapters/script_direct/` chỉ có `__init__.py` rỗng — CHƯA triển khai.
- `video_remaster`: logic lõi TỒN TẠI ở `server/content/crawlers/remaster.py` (class `VideoRemaster`) + downloaders/signing/cookies/stream_merger, nhưng CHƯA được wrap thành adapter trong `server/content/adapters/video_remaster/` và KHÔNG xuất hiện trong registry.
- Luồng `video_remaster` URL→video còn lỗ hổng đã xác minh (đọc code `server/content/crawlers/remaster.py`):
  - Preset `AGGRESSIVE` CHƯA triển khai đầy đủ: `remaster_video()` ghi log cảnh báo ("TTS audio replacement is not yet implemented") rồi âm thầm fallback về `LIGHT` (chỉ burn phụ đề).
  - Chuỗi đầy đủ (Download_Manager download → trích/transcribe phụ đề qua StreamMerger → dịch qua Gemini → burn phụ đề) mới chỉ chạy với test mock; CHƯA được xác minh chạy thật với URL Bilibili/Douyin thực tế.
  - Anti-bot signing (`a_bogus` / `wbi`) hiện là STUB/placeholder và có thể lỗi thời nếu platform xoay thuật toán; download URL thật có thể bị từ chối/rate-limit.
- Skill hiện có (2): `ecommerce-fashion`, `kdrama-romance`; skill `_base` cung cấp rule dùng chung.
- Visual template hiện có (5): `intro_card`, `outro_card`, `lower_third`, `chapter_title`, `product_card`.

### Ngoài phạm vi (KHÔNG đưa vào tính năng này)

- Thêm video provider ngoài Veo3 (không tích hợp fal.ai/Kling/Seedance).
- Custom TTS / voice training (Colab LoRA).
- Định dạng export mới ngoài CapCut export hiện có.
- Preset `AGGRESSIVE` của `video_remaster` (thay audio gốc bằng TTS tiếng Việt) — HOÃN lại, chưa triển khai trong phạm vi tính năng này. Yêu cầu duy nhất là `AGGRESSIVE` phải hành xử có thể dự đoán và không giả vờ thành công như thể audio đã được thay (xem Requirement 7).

## Glossary

- **AIFlow**: Tool sinh video AI cá nhân, native Windows, phụ thuộc Google Flow Pro + Gemini free tier.
- **Adapter_Registry**: Thành phần `server/content/registry.py` (singleton `REGISTRY`) auto-discover và quản lý các adapter qua convention `adapter_type` + instance module-level `ADAPTER`.
- **ContentAdapter**: Protocol ở `server/content/base.py` mà mọi adapter phải thỏa (có `adapter_type`, async `adapt(input) -> SceneList`, `validate_input(input) -> list[str]`).
- **AdapterInput**: Dataclass input chuẩn (`source_type`, `raw_content`, `assets`, `skill_name`, `options`).
- **SceneList**: Output chuẩn của adapter — gồm `project_id`, danh sách `SceneSpec`, `style_ref`, `voice`, `metadata`; có method `validate()`.
- **SceneSpec**: Một cảnh ứng với một clip Veo3 (`order`, `prompt`, `duration`, `start_image`, `location_hint`, `narration`).
- **Script_Direct_Adapter**: Adapter pass-through cần hoàn thiện, `adapter_type = "script_direct"`.
- **Video_Remaster_Adapter**: Adapter cần wrap, `adapter_type = "video_remaster"`.
- **VideoRemaster**: Class lõi đã có ở `server/content/crawlers/remaster.py` thực hiện download/extract sub/transcribe/translate/burn sub.
- **Remaster_Preset**: Enum `RemasterPreset` ở `server/content/crawlers/remaster.py` gồm `LIGHT` (burn phụ đề đã dịch lên video), `TRANSLATE_ONLY` (chỉ dịch SRT, không sửa video), và `AGGRESSIVE` (thay audio gốc bằng TTS — hiện CHƯA triển khai, fallback về `LIGHT`).
- **Stream_Merger**: Class `StreamMerger` ở `server/content/crawlers/stream_merger.py`; cung cấp `extract_subs` (trích phụ đề nhúng) và `transcribe` (transcribe audio qua Whisper) để sinh SRT.
- **Gemini_Client**: Client `server/ai/gemini.GeminiClient` dùng để dịch văn bản phụ đề; truyền vào `RemasterConfig.gemini_client`. Nếu `None`, việc dịch fallback giữ nguyên text gốc.
- **Anti_Bot_Signing**: Bộ module ký chống bot ở `server/content/crawlers/signing/` (`a_bogus` cho Douyin, `wbi` cho Bilibili); hiện là STUB/placeholder, có thể lỗi thời khi platform xoay thuật toán.
- **Translated_SRT**: File phụ đề SRT đã dịch sang tiếng Việt do `translate_srt` sinh ra (hậu tố `_vi.srt`).
- **End_To_End_Verification**: Lần chạy xác minh THỰC TẾ (không phải test mock) toàn bộ luồng `video_remaster` đối với một URL Bilibili/Douyin thật, có ghi nhận bước/kết quả nghiệm thu.
- **Download_Manager**: `server/content/crawlers/manager.py` — auto-detect platform và dispatch downloader (Bilibili/Douyin/TikTok/generic).
- **Skill**: Một thư mục data-only trong `skills/<name>/` theo layout 7 file (`manifest.yaml`, `style.json`, `prefix.md`, `character.md`, `scene.md`, `motion.md`, `voice.yaml`).
- **Skill_Loader**: `server/content/skill_loader.py` — load/validate/áp dụng skill; method `validate_skill()` trả về danh sách lỗi (rỗng = hợp lệ).
- **Visual_Template**: File HTML+GSAP trong `server/render/visual_layer/templates/` phơi bày hợp đồng `window.__hf`.
- **Template_Registry**: `server/render/visual_layer/template_registry.py` — map tên template → `HfTemplateMetadata`.
- **Playwright_Renderer**: `server/render/visual_layer/playwright_renderer.py` — render template thành frame/overlay.
- **HfProtocol**: Hợp đồng `window.__hf = { duration: <float>, seek(t) {...} }` mà mọi Visual_Template phải phơi bày (`server/render/visual_layer/hf_protocol.py`).
- **Skill_Layout_7_File**: Bộ 7 file của một skill: `manifest.yaml`, `style.json`, `prefix.md`, `character.md`, `scene.md`, `motion.md`, `voice.yaml`.
- **Max_Scenes**: Giới hạn `max_scenes_per_project = 50` (config).
- **Max_Duration**: Giới hạn `max_video_duration_sec = 600` (config).
- **Veo3_Clip_Duration**: Mỗi clip Veo3 cố định 8 giây; video dài = nhiều clip.

## Requirements

### Requirement 1: Hoàn thiện adapter `script_direct` (pass-through)

**User Story:** Là người dùng AIFlow, tôi muốn đưa thẳng một dict/JSON scenes đã soạn sẵn vào pipeline, để tạo video mà không cần adapter gọi LLM.

#### Acceptance Criteria

1. THE Script_Direct_Adapter SHALL khai báo thuộc tính class `adapter_type` bằng `"script_direct"`.
2. THE Script_Direct_Adapter SHALL phơi bày một instance module-level `ADAPTER` trong `server/content/adapters/script_direct/adapter.py` để Adapter_Registry auto-discover.
3. WHEN Adapter_Registry chạy `auto_discover("server.content.adapters")`, THE Adapter_Registry SHALL đăng ký `script_direct` vào danh sách adapter khả dụng.
4. WHEN một AdapterInput có `raw_content` là JSON hợp lệ chứa mảng `scenes` mà mỗi phần tử có `narration` và `visual_prompt`, THE Script_Direct_Adapter SHALL trả về một SceneList với mỗi phần tử `scenes` ánh xạ thành một SceneSpec.
5. WHEN một SceneSpec được tạo từ một phần tử scene đầu vào không có trường `duration_sec`, THE Script_Direct_Adapter SHALL gán `duration` mặc định bằng `8.0` giây.
6. WHEN tạo SceneList, THE Script_Direct_Adapter SHALL xác thực `duration` của mỗi scene đầu vào nằm trong khoảng [3, 30] giây TRƯỚC, và chỉ sau khi toàn bộ `duration` hợp lệ mới gán `order` cho các SceneSpec liên tục bắt đầu từ 0 theo thứ tự xuất hiện trong input.
7. IF `raw_content` không phải JSON hợp lệ, THEN THE Script_Direct_Adapter SHALL raise AdapterError với code `"ADAPTER_INVALID_INPUT"`.
8. IF `raw_content` là JSON hợp lệ nhưng thiếu mảng `scenes` hoặc `scenes` rỗng, THEN THE Script_Direct_Adapter SHALL raise AdapterError với code `"ADAPTER_INVALID_INPUT"`.
9. IF một phần tử trong `scenes` thiếu trường bắt buộc `narration` hoặc `visual_prompt`, THEN THE Script_Direct_Adapter SHALL raise AdapterError với code `"ADAPTER_INVALID_INPUT"` kèm chỉ số phần tử lỗi trong `details`.
10. IF một phần tử trong `scenes` có `duration` không hợp lệ (ví dụ `0.0` giây hoặc ngoài khoảng [3, 30] giây), THEN THE Script_Direct_Adapter SHALL raise AdapterError ngay tại bước xác thực `duration` đó TRƯỚC khi gán `order` cho bất kỳ SceneSpec nào.
11. WHEN `validate_input` được gọi với AdapterInput hợp lệ, THE Script_Direct_Adapter SHALL trả về một danh sách rỗng.
12. WHEN `validate_input` được gọi với AdapterInput không hợp lệ, THE Script_Direct_Adapter SHALL trả về danh sách chuỗi lỗi mô tả được cho con người mà không gọi API bên ngoài.
13. IF SceneList sinh ra vi phạm `SceneList.validate()` (order không liên tục hoặc `duration` ngoài khoảng [3, 30]), THEN THE Script_Direct_Adapter SHALL raise AdapterError với code `"ADAPTER_INVALID_OUTPUT"`.
14. WHERE AdapterInput có `skill_name` được đặt, THE Script_Direct_Adapter SHALL áp dụng prefix của skill vào prompt của mỗi SceneSpec qua Skill_Loader.
15. THE Script_Direct_Adapter SHALL chấp nhận input là một JSON object có một trường mảng bắt buộc ở cấp cao nhất tên `scenes`.
16. THE Script_Direct_Adapter SHALL yêu cầu mỗi phần tử trong mảng `scenes` là một object có hai trường bắt buộc `narration` (kiểu string) và `visual_prompt` (kiểu string).
17. WHERE một phần tử `scenes` có trường tùy chọn `duration_sec`, THE Script_Direct_Adapter SHALL yêu cầu `duration_sec` là kiểu number.
18. WHERE một phần tử `scenes` có trường tùy chọn `asset_ids`, THE Script_Direct_Adapter SHALL yêu cầu `asset_ids` là kiểu array.
19. IF một phần tử `scenes` chứa trường ngoài tập `narration`, `visual_prompt`, `duration_sec`, `asset_ids`, THEN THE Script_Direct_Adapter SHALL bỏ qua trường thừa đó mà không làm thất bại quá trình xác thực.

> **Lưu ý hợp đồng input:** Hợp đồng `script_direct` JSON nêu trong các tiêu chí 15–19 (mảng `scenes` bắt buộc; mỗi scene bắt buộc `narration: string` và `visual_prompt: string`; tùy chọn `duration_sec: number` và `asset_ids: array`) là hợp đồng input có thẩm quyền (authoritative) cho tính năng này. Hợp đồng này phản ánh (mirror) `input_schema` của `script_direct` trong spec 05 (`docs/05-content-adapter-spec.md`), nhưng phần văn bản tại đây là nguồn chuẩn cho tính năng này nên Requirement 1 không bị âm thầm vô hiệu nếu spec 05 thay đổi.

### Requirement 2: Wrap & đăng ký `video_remaster` thành ContentAdapter

**User Story:** Là người dùng AIFlow, tôi muốn dán một URL video (Bilibili/Douyin) và nhận lại video re-cut có phụ đề tiếng Việt, để remaster nội dung qua luồng adapter chuẩn.

> **Lưu ý phân định phạm vi:** Requirement 2 chỉ tập trung vào việc **wrap & đăng ký** logic `VideoRemaster` đã có thành một ContentAdapter (mặt giao diện/registry). Việc **sửa lỗi và xác minh luồng URL→video thực sự chạy được end-to-end** (download → phụ đề → dịch → burn) được tách riêng tại Requirement 7.

#### Acceptance Criteria

1. THE Video_Remaster_Adapter SHALL khai báo thuộc tính class `adapter_type` bằng `"video_remaster"`.
2. THE Video_Remaster_Adapter SHALL phơi bày một instance module-level `ADAPTER` trong `server/content/adapters/video_remaster/adapter.py` để Adapter_Registry auto-discover.
3. WHEN Adapter_Registry chạy `auto_discover("server.content.adapters")`, THE Adapter_Registry SHALL đăng ký `video_remaster` vào danh sách adapter khả dụng.
4. THE Video_Remaster_Adapter SHALL tái sử dụng class VideoRemaster ở `server/content/crawlers/remaster.py` và Download_Manager ở `server/content/crawlers/manager.py` thay vì viết lại logic download/transcribe/translate.
5. WHEN một AdapterInput có `raw_content` là một URL video đúng định dạng và hợp lệ, THE Video_Remaster_Adapter SHALL tải video về thư mục làm việc trước khi xử lý tiếp; việc Download_Manager có nhận dạng được platform hay không SHALL chỉ quyết định downloader nào được dùng (downloader chuyên dụng hoặc GenericDownloader), chứ không phải điều kiện chặn tải.
6. WHEN video đã tải về, THE Video_Remaster_Adapter SHALL lấy phụ đề (trích phụ đề nhúng hoặc transcribe) rồi dịch sang tiếng Việt thông qua VideoRemaster.
7. WHEN remaster hoàn tất, THE Video_Remaster_Adapter SHALL trả về một SceneList tuân thủ `SceneList.validate()`.
8. WHEN `validate_input` được gọi với AdapterInput có `raw_content` là một URL dị dạng (malformed — không phải một URL đúng cấu trúc), THE Video_Remaster_Adapter SHALL trả về danh sách chuỗi lỗi mô tả được cho con người và SHALL không tải video về.
9. IF `raw_content` là một URL đúng cấu trúc và hợp lệ nhưng trỏ tới một platform mà Download_Manager không có downloader chuyên dụng (platform không được nhận dạng), THEN THE Video_Remaster_Adapter SHALL dùng GenericDownloader làm fallback để tải video.
10. IF việc tải video thất bại, THEN THE Video_Remaster_Adapter SHALL raise AdapterError với code phản ánh nguyên nhân lỗi tải.
11. WHERE AdapterInput `options` cung cấp một remaster preset (`light`, `aggressive`, hoặc `translate_only`), THE Video_Remaster_Adapter SHALL truyền preset đó vào RemasterConfig.
12. IF `options` không cung cấp preset, THEN THE Video_Remaster_Adapter SHALL dùng preset mặc định `light`.
13. THE Video_Remaster_Adapter SHALL không yêu cầu chỉnh sửa code lõi của Adapter_Registry để đăng ký được.

### Requirement 3: Thêm Skill mới (data-only)

**User Story:** Là người dùng AIFlow, tôi muốn có thêm các phong cách dựng video mới (explainer công nghệ, hành động điện ảnh, e-commerce công nghệ/đồ ăn), để áp dụng phong cách phù hợp với từng loại nội dung.

#### Acceptance Criteria

1. THE Content_Expansion SHALL thêm tối thiểu các skill `explainer-tech`, `cinematic-action`, `ecommerce-tech`, và `ecommerce-food` dưới dạng thư mục trong `skills/`.
2. THE Content_Expansion SHALL tạo mỗi skill mới chỉ gồm file dữ liệu, không chứa file mã Python.
3. WHERE một skill mới được tạo, THE Content_Expansion SHALL bao gồm đầy đủ Skill_Layout_7_File (`manifest.yaml`, `style.json`, `prefix.md`, `character.md`, `scene.md`, `motion.md`, `voice.yaml`).
4. WHEN Skill_Loader chạy `validate_skill(<tên skill mới>)`, THE Skill_Loader SHALL trả về một danh sách rỗng (không có lỗi) cho mỗi skill mới.
5. THE manifest.yaml của mỗi skill mới SHALL khai báo các trường bắt buộc `name`, `version`, và `adapter_type` theo schema SkillManifest.
6. WHERE một skill mới khai báo `extends: _base`, THE Skill_Loader SHALL ghép prefix của `_base` vào trước prefix riêng của skill khi load.
7. WHEN Skill_Loader chạy `load(<tên skill mới>)`, THE Skill_Loader SHALL trả về một LoadedSkill có `style` hợp lệ theo `validate_style_json`.
8. THE manifest.yaml của mỗi skill mới SHALL liệt kê các adapter tương thích trong trường `supported_adapters`.
9. THE manifest.yaml của skill `ecommerce-tech` và `ecommerce-food` SHALL khai báo `adapter_type` là `ecommerce_product` để tương thích với adapter e-commerce hiện có.
10. THE `prefix.md` của mỗi skill mới SHALL chứa tối thiểu 20 từ (không tính khoảng trắng) nội dung hướng dẫn phong cách thực chất.
11. THE `style.json` của mỗi skill mới SHALL là một JSON object hợp lệ chứa tối thiểu các khóa mà các skill hiện có dùng: `art_style`, `lighting`, `color_palette`, `camera_rules`, `negative_prompts`, và `aspect_ratio` (theo đúng tập khóa của `ecommerce-fashion`/`kdrama-romance`).
12. THE `character.md`, `scene.md`, và `motion.md` của mỗi skill mới SHALL mỗi file không rỗng và chứa nội dung template thực chất (không chỉ một dòng tiêu đề).
13. THE `voice.yaml` của mỗi skill mới SHALL khai báo một hồ sơ giọng đọc dùng được, tối thiểu gồm một backend chính (`primary_backend`) và một giọng chính (`primary_voice`).

### Requirement 4: Thêm Adapter cho loại input mới (cả năm đều bắt buộc)

**User Story:** Là người dùng AIFlow, tôi muốn tạo video từ các loại input mới (tài liệu PDF/Word, bài hát + lời, RSS/news, podcast/audio, album ảnh), để mở rộng nguồn nội dung đầu vào.

#### Acceptance Criteria

1. THE Content_Expansion SHALL triển khai và đăng ký đủ cả năm adapter input mới: `document_summary` (PDF/Word → video tóm tắt), `lyric_video` (bài hát + lời → lyric video), `news_bulletin` (RSS/news feed → bản tin), `podcast_caption` (podcast/audio → video phụ đề), và `photo_slideshow` (album ảnh → slideshow kỷ niệm).
2. THE Content_Expansion SHALL coi cả năm adapter ở tiêu chí 1 là bắt buộc trong phạm vi tính năng này.
3. WHERE một adapter input mới được triển khai, THE adapter mới SHALL khai báo thuộc tính class `adapter_type` duy nhất và phơi bày instance module-level `ADAPTER` để Adapter_Registry auto-discover.
4. WHERE một adapter input mới được triển khai, THE adapter mới SHALL thỏa Protocol ContentAdapter (có `adapter_type`, async `adapt`, và `validate_input`).
5. WHEN một adapter input mới chạy `adapt`, THE adapter mới SHALL trả về một SceneList tuân thủ `SceneList.validate()`.
6. WHEN một adapter input mới chạy `validate_input` với input không hợp lệ, THE adapter mới SHALL trả về danh sách chuỗi lỗi mô tả được cho con người mà không thực hiện bất kỳ lời gọi API bên ngoài nào (lời gọi mạng/LLM) và không dựa vào dữ liệu đã cache từ các lần gọi API bên ngoài trước; THE adapter mới MAY dùng lời gọi thư viện cục bộ (ví dụ phân tích cấu trúc PDF bằng thư viện cục bộ như `pypdf`, đọc header file, kiểm tra định dạng cục bộ) và kiểm tra file cục bộ.
7. THE adapter input mới SHALL đăng ký được thuần túy qua convention auto-discovery mà KHÔNG ĐÒI HỎI bất kỳ thay đổi nào ở code lõi.
8. WHEN code lõi bị chỉnh sửa, THE Adapter_Registry SHALL vẫn đăng ký adapter input mới qua convention auto-discovery; ràng buộc là adapter KHÔNG ĐƯỢC ĐÒI HỎI thay đổi code lõi, chứ không phải việc thay đổi code lõi sẽ chặn đăng ký.
9. WHERE một adapter input mới sinh ra số scene vượt Max_Scenes hoặc tổng thời lượng vượt Max_Duration, THE adapter mới SHALL raise AdapterError với code `"ADAPTER_INVALID_OUTPUT"`.

### Requirement 5: Thêm Visual-layer Template mới

**User Story:** Là người dùng AIFlow, tôi muốn có thêm các template overlay (thẻ trích dẫn, thẻ số liệu, ticker tin tức, dòng lời bài hát), để làm phong phú lớp đồ họa của video.

#### Acceptance Criteria

1. THE Content_Expansion SHALL thêm các Visual_Template mới ngoài 5 template hiện có, tối thiểu gồm `quote_card`, `stat_card`, `news_ticker`, và `lyric_line`.
2. WHERE một Visual_Template mới được tạo, THE Visual_Template SHALL được đặt làm file HTML trong `server/render/visual_layer/templates/`.
3. WHERE một Visual_Template mới được tạo, THE Visual_Template SHALL phơi bày đối tượng `window.__hf` với thuộc tính `duration` là số hữu hạn dương và method `seek(t)`.
4. WHEN Playwright_Renderer load một Visual_Template mới và chạy `validate_hf_contract`, THE kết quả validate SHALL có `passed` bằng `True`.
5. WHERE một Visual_Template mới được tạo, THE Content_Expansion SHALL thêm một mục tương ứng vào Template_Registry với `HfTemplateMetadata` khai báo `name`, `duration`, `width`, `height`, và `variables`.
6. WHEN `get_template_path(<tên template mới>)` được gọi, THE Template_Registry SHALL trả về đường dẫn tới file HTML tồn tại trên đĩa.
7. THE mỗi Visual_Template mới SHALL nạp GSAP qua placeholder `{{__VENDOR_GSAP__}}` theo cùng convention với các template hiện có.
8. WHERE một Visual_Template mới khai báo biến `{{KEY}}`, THE `HfTemplateMetadata.variables` tương ứng trong Template_Registry SHALL liệt kê đầy đủ các tên biến đó.
9. THE mỗi Visual_Template mới SHALL bao gồm tối thiểu một animation điều khiển bằng GSAP gắn vào timeline để `seek(t)` của HfProtocol có ý nghĩa (frame thay đổi theo `t`), nhất quán với các template hiện có.
10. IF bất kỳ template nào trong bộ tối thiểu bắt buộc (`quote_card`, `stat_card`, `news_ticker`, `lyric_line`) không tồn tại trong Template_Registry, THEN việc xác thực bộ template SHALL thất bại; việc xác thực SHALL không được coi là pass khi bộ template rỗng hoặc thiếu bất kỳ template bắt buộc nào.

### Requirement 6: Ràng buộc chung & bảo toàn pipeline lõi

**User Story:** Là người bảo trì AIFlow, tôi muốn mọi phần mở rộng tuân theo convention sẵn có và không phá vỡ giới hạn pipeline, để pipeline lõi không phải sửa đổi.

#### Acceptance Criteria

1. THE Content_Expansion SHALL đăng ký mọi adapter mới chỉ qua convention auto-discovery (`adapter_type` + instance `ADAPTER`) mà không sửa code lõi của Adapter_Registry.
2. WHEN bất kỳ adapter nào (mới hoặc được wrap) sinh ra SceneList, THE adapter SHALL đảm bảo số scene không vượt Max_Scenes (50).
3. WHEN bất kỳ adapter nào (mới hoặc được wrap) sinh ra SceneList, THE adapter SHALL đảm bảo tổng thời lượng các scene không vượt Max_Duration (600 giây).
4. WHEN một SceneSpec được tạo mà không có thời lượng tường minh, THE adapter SHALL gán `duration` bằng Veo3_Clip_Duration (8.0 giây).
5. THE mỗi skill mới SHALL pass `Skill_Loader.validate_skill()` mà không cần sửa code Skill_Loader.
6. THE mỗi Visual_Template mới SHALL tuân thủ hợp đồng `window.__hf` của HfProtocol và phải được Template_Registry phát hiện.
7. THE Content_Expansion SHALL tái sử dụng code crawler hiện có cho `video_remaster` thay vì nhân bản logic crawler.

### Requirement 7: Sửa & xác minh luồng `video_remaster` URL→video chạy thật end-to-end

**User Story:** Là người dùng AIFlow, tôi muốn luồng "tạo video từ URL" (Bilibili/Douyin) thực sự chạy được từ đầu đến cuối với URL thật, để nhận lại video có phụ đề tiếng Việt thay vì chỉ có test mock và một preset chưa triển khai âm thầm fallback.

> **Lưu ý phân định phạm vi:** Requirement 7 bổ sung cho Requirement 2. Requirement 2 = wrap logic vào adapter; Requirement 7 = sửa lỗi và xác minh luồng URL→video bên dưới (`VideoRemaster` + Download_Manager + Stream_Merger + Gemini_Client) thực sự hoạt động. Preset `AGGRESSIVE` (thay audio bằng TTS) nằm NGOÀI phạm vi và được hoãn lại (xem AC 5).

#### Acceptance Criteria

1. WHEN một URL video VỪA được Download_Manager nhận dạng VỪA hợp lệ được xử lý với preset `LIGHT`, THE VideoRemaster SHALL chạy đủ chuỗi end-to-end: tải video → lấy phụ đề (ưu tiên trích phụ đề nhúng qua `Stream_Merger.extract_subs`, fallback transcribe qua `Stream_Merger.transcribe`) → dịch nguồn→tiếng Việt qua Gemini_Client → burn phụ đề đã dịch → tạo ra một file video đầu ra tồn tại trên đĩa.
2. WHEN một URL video hợp lệ được xử lý với preset `TRANSLATE_ONLY`, THE VideoRemaster SHALL tạo ra một Translated_SRT tiếng Việt và SHALL trả về đường dẫn video gốc mà không sửa đổi video.
3. IF cả việc trích phụ đề nhúng VÀ việc transcribe đều thất bại, THEN THE VideoRemaster SHALL ghi một SRT rỗng và tiếp tục pipeline mà không làm pipeline crash.
4. IF Gemini_Client không được cấu hình (`None`) HOẶC việc dịch một segment thất bại, THEN THE VideoRemaster SHALL giữ nguyên text gốc (chưa dịch) của segment đó thay vì làm hỏng toàn bộ công việc.
5. WHERE preset là `AGGRESSIVE`, THE VideoRemaster SHALL được xử lý như tính năng HOÃN/CHƯA triển khai và SHALL phát một tín hiệu rõ ràng về hành vi thực tế (báo "chưa triển khai / hoãn" HOẶC ghi log cảnh báo rõ ràng rằng đang fallback về hành vi `LIGHT`) để người dùng không bị hiểu nhầm rằng audio đã được thay bằng TTS.
6. THE End_To_End_Verification SHALL được thực hiện bằng một lần chạy thực tế (không chỉ test mock) đối với tối thiểu một URL Bilibili hoặc Douyin thật, và bước cùng kết quả nghiệm thu SHALL được ghi lại thành tài liệu.
7. IF Anti_Bot_Signing (`a_bogus`/`wbi`) hoặc bước tải video thất bại đối với một URL thật, THEN THE VideoRemaster SHALL phát một thông báo lỗi rõ ràng, đọc được cho con người chỉ rõ thất bại tải/ký, thay vì tạo ra đầu ra rỗng một cách âm thầm.
8. WHERE hệ điều hành là Windows, THE VideoRemaster SHALL tạo đường dẫn filter `subtitles=` của FFmpeg đúng định dạng (escape ký tự `\` và dấu hai chấm ổ đĩa qua `_escape_srt_path_for_ffmpeg`) để việc burn phụ đề hoạt động với đường dẫn có ký tự ổ đĩa trên Windows.
9. IF Anti_Bot_Signing hoặc bước tải video thất bại trong lần chạy xác minh đến mức không URL thật nào tải được, THEN THE thất bại đó SHALL được ghi lại thành tài liệu và phần End_To_End_Verification trực tiếp (live) SHALL được hoãn sang một task tiếp theo; phần còn lại của luồng SHALL vẫn được xác minh bằng một file video cung cấp cục bộ để chứng minh chuỗi lấy phụ đề → dịch → burn của preset `LIGHT`/`TRANSLATE_ONLY` chạy được mà không bị chặn bởi việc ký.
10. THE bước tải video SHALL áp dụng một timeout có giới hạn và một chính sách retry xác định (timeout cấu hình được kèm một số lần thử lại cố định, nhỏ), và SHALL bị coi là "thất bại" sau khi timeout/retry cạn kiệt, đồng thời phát một thông báo lỗi rõ ràng thay vì treo vô hạn.
