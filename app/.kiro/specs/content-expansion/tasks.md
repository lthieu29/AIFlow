# Implementation Plan — content-expansion

## Overview

Kế hoạch triển khai mở rộng ba trục tính năng (Adapter / Skill / Visual Template) của AIFlow **mà không sửa code lõi pipeline**. Mỗi task được build tăng dần và nối vào convention auto-discovery sẵn có; không có code mồ côi.

Thứ tự thực hiện: (1) hạ tầng dùng chung → (2) `script_direct` → (4) `video_remaster` wrap → (5) sửa & xác minh luồng URL→video → (7) skill mới → (8) adapter input mới → (10) visual template mới → (11) xác minh xuyên suốt. Các task checkpoint xen vào giữa.

Property tests (Hypothesis, ≥ 100 iteration) đặt sát phần logic thuần để bắt lỗi sớm. Mỗi property tham chiếu số Property trong design và clause requirement nó kiểm.

## Tasks

- [ ] 1. Thiết lập phụ thuộc và helper giới hạn pipeline dùng chung
  - [x] 1.1 Thêm phụ thuộc test và content vào `pyproject.toml`
    - Thêm `hypothesis` và `pytest-socket` vào `[project.optional-dependencies].dev`
    - Thêm nhóm extras `content` với `pypdf`, `python-docx`, `feedparser`, `Pillow`
    - _Requirements: 4.6, 6.2, 6.3_

  - [x] 1.2 Triển khai `enforce_pipeline_limits` (shared limit guard)
    - Tạo `server/content/pipeline_limits.py` với `DEFAULT_MAX_SCENES=50`, `DEFAULT_MAX_DURATION_SEC=600.0`
    - Raise `AdapterError("ADAPTER_INVALID_OUTPUT", ...)` khi số scene > max hoặc tổng duration > max; tham số hóa max để đọc từ `Settings`
    - _Requirements: 4.9, 6.2, 6.3_

  - [x] 1.3 Property test cho giới hạn pipeline
    - **Property 7: Bất biến giới hạn pipeline được enforce**
    - File `server/tests/test_pipeline_limits.py`; sinh `SceneList` quanh biên 50 scene / 600s
    - **Validates: Requirements 4.9, 6.2, 6.3**


- [ ] 2. Hoàn thiện adapter `script_direct` (pass-through)
  - [x] 2.1 Tạo schema hợp đồng input cho `script_direct`
    - `server/content/adapters/script_direct/schema.py`: `ScriptDirectScene` (extra="ignore", `narration`/`visual_prompt` non-blank, `duration_sec: float|None`, `asset_ids: list|None`) và `ScriptDirectInput` (`scenes` min_length=1)
    - _Requirements: 1.15, 1.16, 1.17, 1.18, 1.19_

  - [x] 2.2 Triển khai `ScriptDirectAdapter` + instance `ADAPTER`
    - `server/content/adapters/script_direct/adapter.py`: `adapter_type="script_direct"`, `adapt()` theo đúng thứ tự (parse JSON → kiểm `scenes` → kiểm field bắt buộc kèm index → validate TẤT CẢ duration TRƯỚC khi gán `order` → build `SceneSpec` → áp skill → `SceneList.validate()` → `enforce_pipeline_limits()`), `validate_input()` không gọi API ngoài; phơi bày `ADAPTER` và `ADAPTER_CLASS`
    - Mặc định `duration=8.0` khi thiếu `duration_sec`; áp skill prefix qua `apply_skill_to_scene`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 6.4_

  - [~] 2.3 Property test: mapping bảo toàn
    - **Property 1: Mapping bảo toàn — script_direct map đúng và đầy đủ**
    - File `server/tests/test_adapter_script_direct.py`; strategy sinh `scenes` hợp lệ (1..N), text tùy ý, duration ∈ [3,30] hoặc vắng; assert `len(scenes)==len(input)`, `scenes[i].order==i`, `scenes[i].prompt` chứa `visual_prompt`, `scenes[i].narration==narration`, `scenes[i].duration==duration_sec or 8.0`
    - **Validates: Requirements 1.4, 1.5, 1.6, 6.4**

  - [~] 2.4 Property test: JSON không hợp lệ bị từ chối
    - **Property 2: JSON không hợp lệ bị từ chối**
    - File `server/tests/test_adapter_script_direct.py`; strategy chuỗi không-parse-được JSON; assert raise `AdapterError(code="ADAPTER_INVALID_INPUT")`
    - **Validates: Requirements 1.7**

  - [~] 2.5 Property test: thiếu field bắt buộc bị từ chối kèm chỉ số
    - **Property 3: Thiếu field bắt buộc bị từ chối kèm chỉ số**
    - File `server/tests/test_adapter_script_direct.py`; sinh list hợp lệ rồi xóa/đổi-kiểu field ở index ngẫu nhiên; assert `AdapterError(code="ADAPTER_INVALID_INPUT")` và `details` tham chiếu chỉ số `i`
    - **Validates: Requirements 1.9, 1.16**

  - [~] 2.6 Property test: duration xác thực TRƯỚC khi gán order
    - **Property 4: Duration được xác thực TRƯỚC khi gán order**
    - File `server/tests/test_adapter_script_direct.py`; sinh list có ≥1 duration ngoài [3,30] (kể cả 0.0); assert raise `AdapterError` tại bước validate duration và KHÔNG có `SceneSpec` nào được gán `order` (không có output bộ phận)
    - **Validates: Requirements 1.6, 1.10**

  - [~] 2.7 Property test: áp skill thêm prefix vào mọi prompt
    - **Property 5: Áp skill thêm prefix vào mọi prompt**
    - File `server/tests/test_adapter_script_direct.py`; sinh list hợp lệ + skill prefix non-empty; assert mọi `SceneSpec.prompt` trong `SceneList` kết quả đều chứa văn bản prefix
    - **Validates: Requirements 1.14**

  - [~] 2.8 Property test: field thừa được bỏ qua, không làm fail
    - **Property 6: Field thừa được bỏ qua, không làm fail**
    - File `server/tests/test_adapter_script_direct.py`; sinh list hợp lệ + khóa thừa ngẫu nhiên ngoài tập `{narration, visual_prompt, duration_sec, asset_ids}`; assert `adapt()` thành công và khóa thừa không xuất hiện trong các trường lõi của `SceneSpec`
    - **Validates: Requirements 1.19**

  - [~] 2.9 Unit test cho `script_direct` (discover + edge case)
    - Kiểm `adapter_type`/`ADAPTER`/auto_discover (R1.1–1.3); thiếu/empty/null `scenes` (R1.8); output phòng thủ `ADAPTER_INVALID_OUTPUT` (R1.13); sai kiểu `duration_sec`/`asset_ids` (R1.17/1.18); object tối thiểu hợp lệ (R1.15); `validate_input` hợp lệ → `[]` (R1.11)
    - File `server/tests/test_adapter_script_direct.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.8, 1.11, 1.13, 1.15, 1.17, 1.18_


- [~] 3. Checkpoint — Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Wrap & đăng ký `video_remaster` thành ContentAdapter
  - [x] 4.1 Triển khai `download_with_retry` + `VideoRemasterAdapter` + instance `ADAPTER`
    - Tạo `server/content/adapters/video_remaster/__init__.py` và `adapter.py`: `adapter_type="video_remaster"`; `validate_input()` kiểm URL well-formed (scheme http/https + netloc), KHÔNG tải, KHÔNG gọi API ngoài
    - `adapt()`: resolve preset (mặc định `light`) → `download_with_retry()` (timeout + retry xác định, bọc `DownloadError`→`ADAPTER_DOWNLOAD_FAILED` với `details={"url","code"}`) → `VideoRemaster(cfg).remaster()` → map `RemasterResult`→`SceneList` (1 scene, duration clamp [3,30], `metadata.passthrough=True`, `output_path`, …) → `SceneList.validate()` + `enforce_pipeline_limits()`
    - Tái dùng `VideoRemaster` + `DownloadManager` hiện hữu; không sửa `registry.py`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.9, 2.10, 2.11, 2.12, 2.13, 6.7, 7.10_

  - [~] 4.2 Property test: URL dị dạng không kích hoạt tải
    - **Property 9: URL dị dạng không kích hoạt tải**
    - File `server/tests/test_adapter_video_remaster.py`; strategy sinh chuỗi URL dị dạng (thiếu scheme, thiếu netloc, scheme không phải http/https); mock `DownloadManager`, assert `download()` không được gọi và `validate_input()` trả list lỗi không rỗng
    - **Validates: Requirements 2.8**

  - [~] 4.3 Property test: retry tải xác định rồi báo lỗi rõ ràng
    - **Property 12: Retry tải xác định rồi báo lỗi rõ ràng**
    - File `server/tests/test_adapter_video_remaster.py`; mock download fail `k` lần / thành công lượt `j ≤ retries`; truyền `sleep_sec=0`; assert tổng số lần gọi = `min(j+1, retries+1)` và raise `AdapterError(code="ADAPTER_DOWNLOAD_FAILED")` khi mọi lần đều fail
    - **Validates: Requirements 7.10**

  - [~] 4.4 Unit test cho `video_remaster` (discover + delegation + preset)
    - Kiểm `adapter_type`/`ADAPTER`/auto_discover (R2.1–2.3); delegation + mapping `RemasterResult`→`SceneList` với fake result (R2.4/R2.7); `metadata.passthrough=True` và `source_kind="remastered_video"` (R2.7); 3 preset cụ thể (R2.11) và mặc định `light` (R2.12); `ADAPTER_DOWNLOAD_FAILED` khi download fail (R2.10)
    - File `server/tests/test_adapter_video_remaster.py`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.7, 2.10, 2.11, 2.12_


- [ ] 5. Sửa & xác minh luồng `video_remaster` URL→video end-to-end
  - [~] 5.1 Tạo script xác minh end-to-end + hoàn thiện hành vi R7 của `VideoRemaster`
    - Tạo `server/scripts/verify_video_remaster.py`: tải URL (retry/timeout) → remaster preset `LIGHT` → ghi report nghiệm thu; fallback dùng file video cục bộ khi tải/ký thất bại (R7.9); báo lỗi rõ ràng thay vì output rỗng (R7.7)
    - Xác minh/đảm bảo `VideoRemaster`: ghi SRT rỗng khi cả extract + transcribe fail và tiếp tục không crash (R7.3); preset `AGGRESSIVE` phát cảnh báo "TTS chưa triển khai" + fallback `LIGHT`, không giả vờ thành công (R7.5)
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6, 7.7, 7.9, 7.10_

  - [~] 5.2 Property test: dịch giữ nguyên text gốc khi không thể dịch
    - **Property 10: Dịch giữ nguyên text gốc khi không thể dịch**
    - File `server/tests/test_srt_translate_property.py`; strategy sinh list `SrtSegment` tùy ý; test với `gemini_client=None` và với client raise lỗi cho mọi segment; assert mỗi segment trong output giữ nguyên text gốc và timestamp (start/end) không đổi
    - **Validates: Requirements 7.4**

  - [~] 5.3 Property test: escape đường dẫn SRT cho FFmpeg trên Windows
    - **Property 11: Escape đường dẫn SRT cho FFmpeg trên Windows**
    - File `server/tests/test_ffmpeg_path_escape_property.py`; strategy sinh path Windows (ký tự ổ đĩa `X:` + dấu `\`); assert output không còn dấu `\` thô (dùng `/`) và ký tự ổ đĩa được escape thành `X\:`
    - **Validates: Requirements 7.8**

  - [~] 5.4 Integration test: chuỗi remaster trên file video cục bộ
    - Chạy subs→translate→burn trên file cục bộ với `subprocess.run`/Gemini mock; assert output tồn tại (LIGHT) và `_vi.srt` + video gốc (TRANSLATE_ONLY); download mock raise → lỗi rõ ràng
    - File `server/tests/test_remaster_e2e.py`
    - _Requirements: 7.1, 7.2, 7.3, 7.7, 7.9_

  - [~] 5.5 Unit test: preset `AGGRESSIVE` hoãn có cảnh báo
    - Assert `AGGRESSIVE` log cảnh báo "TTS chưa triển khai" / "fallback" và KHÔNG thay audio gốc (hành vi giống `LIGHT`)
    - File `server/tests/test_remaster.py` (mở rộng suite hiện có)
    - _Requirements: 7.5_

- [~] 6. Checkpoint — Ensure all tests pass, ask the user if questions arise.


- [ ] 7. Thêm Skill mới (data-only)
  - [x] 7.1 Tạo skill `explainer-tech` (7 file)
    - `skills/explainer-tech/` đủ `manifest.yaml` (`name`/`version`/`adapter_type: narrative_script`/`extends: _base`/`supported_adapters: [narrative_script, blog_article, document_summary, script_direct]`), `style.json` (6 khóa: `art_style`, `lighting`, `color_palette`, `camera_rules`, `negative_prompts`, `aspect_ratio`), `prefix.md` (≥20 từ), `character.md`/`scene.md`/`motion.md` (nội dung thực chất), `voice.yaml` (`primary_backend`+`primary_voice`); KHÔNG file `.py`
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 3.8, 3.10, 3.11, 3.12, 3.13_

  - [x] 7.2 Tạo skill `cinematic-action` (7 file)
    - `skills/cinematic-action/` (`adapter_type: narrative_script`, `supported_adapters: [narrative_script, storyboard_manual, script_direct]`), đủ 7 file theo Skill_Layout_7_File; KHÔNG file `.py`
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 3.8, 3.10, 3.11, 3.12, 3.13_

  - [x] 7.3 Tạo skill `ecommerce-tech` (7 file)
    - `skills/ecommerce-tech/` với `adapter_type: ecommerce_product` (R3.9), `supported_adapters: [ecommerce_product, storyboard_manual, script_direct]`, đủ 7 file; KHÔNG file `.py`
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13_

  - [x] 7.4 Tạo skill `ecommerce-food` (7 file)
    - `skills/ecommerce-food/` với `adapter_type: ecommerce_product` (R3.9), `supported_adapters: [ecommerce_product, storyboard_manual, script_direct]`, đủ 7 file; KHÔNG file `.py`
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13_

  - [~] 7.5 Unit test cho 4 skill mới (parametrize)
    - `validate_skill()==[]` (R3.4); `load()` trả `LoadedSkill` style hợp lệ (R3.7); đủ 7 file (R3.3); không `*.py` (R3.2); prefix ≥20 từ (R3.10); 6 khóa style (`art_style`, `lighting`, `color_palette`, `camera_rules`, `negative_prompts`, `aspect_ratio`) (R3.11); character/scene/motion thực chất (R3.12); voice fields `primary_backend`+`primary_voice` (R3.13); `adapter_type=ecommerce_product` cho tech/food (R3.9); merge `extends: _base` (R3.6)
    - File `server/tests/test_skills_new.py`
    - _Requirements: 3.2, 3.3, 3.4, 3.6, 3.7, 3.9, 3.10, 3.11, 3.12, 3.13_


- [ ] 8. Thêm Adapter cho loại input mới (cả 5)
  - [-] 8.1 Triển khai adapter `document_summary`
    - `server/content/adapters/document_summary/adapter.py` (dùng lại `extractor.py` đã có): `adapter_type="document_summary"`, trích text cục bộ (`pypdf`/`python-docx` import lazy qua `extractor.extract_text`) → chunk → scenes; tóm tắt per-chunk qua LLM nếu có `gemini_client`, fallback sentence-chunking PER-CHUNK (không all-or-nothing); `validate_input` gọi `validate_document_local()` (không gọi API ngoài); `SceneList.validate()` + `enforce_pipeline_limits()`; phơi bày `ADAPTER` và `ADAPTER_CLASS`
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9, 6.4_

  - [~] 8.2 Triển khai adapter `lyric_video`
    - `server/content/adapters/lyric_video/adapter.py`: `adapter_type="lyric_video"`; parse LRC (regex timestamp `[mm:ss.xx]` → scene theo dòng với duration từ khoảng cách timestamp) hoặc plain text (chunk theo đoạn/dòng); mỗi đoạn lời = 1 scene (`prompt=visual_hint`, `narration=lyric_line`); `validate_input` kiểm cục bộ (không gọi API ngoài); enforce limits; phơi bày `ADAPTER` và `ADAPTER_CLASS`
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9, 6.4_

  - [~] 8.3 Triển khai adapter `news_bulletin`
    - `server/content/adapters/news_bulletin/adapter.py`: `adapter_type="news_bulletin"`; parse RSS/Atom (`feedparser` import lazy hoặc `xml.etree`) cục bộ → mỗi item = 1 scene (headline + summary); `validate_input` chỉ kiểm well-formed (XML thô parse cục bộ / URL đúng cấu trúc http/https + netloc), KHÔNG fetch URL; fetch URL chỉ trong `adapt` → `ADAPTER_FETCH_ERROR` nếu lỗi; enforce limits; phơi bày `ADAPTER` và `ADAPTER_CLASS`
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9, 6.4_

  - [~] 8.4 Triển khai adapter `podcast_caption`
    - `server/content/adapters/podcast_caption/adapter.py`: `adapter_type="podcast_caption"`; transcribe audio qua `server.audio.transcribe`/StreamMerger → SRT → mỗi segment = 1 scene phụ đề (`narration=segment_text`, `duration=segment_duration` clamp [3,30]); `validate_input` kiểm file tồn tại + định dạng audio cục bộ (không gọi API ngoài); enforce limits; phơi bày `ADAPTER` và `ADAPTER_CLASS`
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9, 6.4_

  - [~] 8.5 Triển khai adapter `photo_slideshow`
    - `server/content/adapters/photo_slideshow/adapter.py`: `adapter_type="photo_slideshow"`; mỗi ảnh = 1 scene (`start_image=path`, `duration=8.0`); `validate_input` đọc header từng ảnh cục bộ (Pillow import lazy nếu có), STRICT fail-fast `ADAPTER_INVALID_INPUT` nếu bất kỳ ảnh hỏng (kèm path/chỉ số); enforce limits; phơi bày `ADAPTER` và `ADAPTER_CLASS`
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9, 6.4_

  - [~] 8.6 Unit test: cả 5 adapter discover + Protocol + adapt mẫu
    - Cả 5 adapter xuất hiện sau `auto_discover` (R4.1/R4.2); `ADAPTER` + `adapter_type` unique (R4.3); `isinstance` ContentAdapter (R4.4); ví dụ `adapt` hợp lệ với input mẫu + mock I/O → `SceneList` hợp lệ (R4.5); `validate_input` hợp lệ → `[]`
    - File `server/tests/test_adapters_new.py`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [~] 8.7 Integration test: `document_summary` fallback per-chunk
    - Mock `gemini_client` lỗi ở MỘT chunk con → chunk đó dùng sentence-chunking, các chunk khác vẫn tóm tắt qua LLM; kết quả là `SceneList` hoàn chỉnh (không all-or-nothing)
    - File `server/tests/test_adapter_document_summary.py`
    - _Requirements: 4.5, 4.6_

  - [~] 8.8 Integration test: `photo_slideshow` strict ảnh hỏng
    - Trong N ảnh có 1 ảnh hỏng/không đọc header → `validate_input` trả lỗi (kèm path/chỉ số) và `adapt` fail-fast `ADAPTER_INVALID_INPUT`
    - File `server/tests/test_adapter_photo_slideshow.py`
    - _Requirements: 4.6_

  - [~] 8.9 Integration test: `news_bulletin` URL-không-phải-feed
    - URL trỏ HTML hợp lệ nhưng không phải RSS/Atom: `validate_input` PASS (chỉ well-formed), `adapt` raise `ADAPTER_FETCH_ERROR` (fetch mock trả HTML không-feed)
    - File `server/tests/test_adapter_news_bulletin.py`
    - _Requirements: 4.6_

- [~] 9. Checkpoint — Ensure all tests pass, ask the user if questions arise.


- [ ] 10. Thêm Visual-layer Template mới
  - [x] 10.1 Tạo template `quote_card.html`
    - `server/render/visual_layer/templates/quote_card.html`: biến `{{QUOTE}}`/`{{AUTHOR}}`; GSAP qua `{{__VENDOR_GSAP__}}`; `window.__hf={duration:5.0, seek(t){tl.seek(t)}}`; ≥1 animation gắn timeline (fade/scale quote + slide author); nền trong suốt `document.body.style.background='transparent'`; kích thước 1080×1920
    - _Requirements: 5.1, 5.2, 5.3, 5.7, 5.8, 5.9_

  - [x] 10.2 Tạo template `stat_card.html`
    - Biến `{{STAT_VALUE}}`/`{{STAT_LABEL}}`; `duration:4.0`; count-up/scale số liệu theo timeline; convention như 10.1
    - _Requirements: 5.1, 5.2, 5.3, 5.7, 5.8, 5.9_

  - [x] 10.3 Tạo template `news_ticker.html`
    - Biến `{{HEADLINE}}`/`{{SOURCE}}`; `duration:6.0`; ticker trượt ngang (translateX) theo timeline; convention như 10.1
    - _Requirements: 5.1, 5.2, 5.3, 5.7, 5.8, 5.9_

  - [x] 10.4 Tạo template `lyric_line.html`
    - Biến `{{LINE}}`/`{{NEXT_LINE}}`; `duration:4.0`; fade-in/out + highlight theo timeline; convention như 10.1
    - _Requirements: 5.1, 5.2, 5.3, 5.7, 5.8, 5.9_

  - [x] 10.5 Đăng ký 4 template vào `TEMPLATE_REGISTRY`
    - Thêm 4 mục `HfTemplateMetadata(name, duration, 1080, 1920, variables=[...])` vào `server/render/visual_layer/template_registry.py`: `quote_card` (5.0, ["QUOTE","AUTHOR"]), `stat_card` (4.0, ["STAT_VALUE","STAT_LABEL"]), `news_ticker` (6.0, ["HEADLINE","SOURCE"]), `lyric_line` (4.0, ["LINE","NEXT_LINE"])
    - _Requirements: 5.5, 5.6, 5.8_

  - [~] 10.6 Unit test cho template mới (mở rộng suite hiện có)
    - Mở rộng `server/tests/test_visual_layer_templates.py` để bao gồm 4 template mới: tồn tại/vị trí file (R5.1/5.2); `window.__hf`/`duration`/`seek` trong HTML (R5.3); registry metadata + `get_template_path` tồn tại trên đĩa (R5.5/5.6); GSAP placeholder `{{__VENDOR_GSAP__}}`, không CDN (R5.7); biến `{{KEY}}` khớp `variables` (R5.8); bộ bắt buộc `{quote_card, stat_card, news_ticker, lyric_line}` thiếu một → fail, rỗng → fail (R5.10)
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6, 5.7, 5.8, 5.10_

  - [~] 10.7 Integration test: render + hf contract
    - Nếu Playwright/Chromium khả dụng: render mỗi template mới, assert `validate_hf_contract.passed`; render 2 frame `t` khác nhau và assert frame khác nhau; nếu không khả dụng → `pytest.skip`
    - File `server/tests/test_visual_layer_render.py`
    - _Requirements: 5.4, 5.9_


- [ ] 11. Xác minh xuyên suốt (bảo toàn core + no-network)
  - [~] 11.1 Property test: `validate_input` không gọi API ngoài
    - **Property 8: `validate_input` từ chối input không hợp lệ mà không gọi API ngoài**
    - File `server/tests/test_validate_input_no_network.py`; dùng `pytest-socket` disable socket cho `script_direct` + 5 adapter mới có input dễ sinh; assert `validate_input` trả list lỗi không rỗng VÀ không raise `SocketBlockedError` (tức không gọi mạng)
    - **Validates: Requirements 1.12, 4.6**

  - [~] 11.2 Smoke test: auto-discovery + data-only + đủ bộ
    - Mọi adapter mới đăng ký thuần qua auto-discovery, không sửa `registry.py`/`SkillLoader` (R6.1, 4.7, 4.8); skill chỉ chứa data, không `*.py` (R3.2); đủ cả 5 adapter input (R4.2); đủ 4 skill mới (R3.1); đủ 4 template mới trong registry (R5.1/5.5)
    - File `server/tests/test_content_expansion_smoke.py`
    - _Requirements: 3.1, 3.2, 4.2, 4.7, 4.8, 6.1, 6.5_

- [~] 12. Final checkpoint — Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks đánh dấu `*` là optional (test) và có thể bỏ qua để ra MVP nhanh; task lõi (không `*`) phải triển khai.
- Mỗi task tham chiếu clause requirement cụ thể để truy vết.
- Mỗi correctness property (1–12) được hiện thực bằng MỘT property-based test (≥100 iteration) gắn comment tham chiếu design.
- Nguyên tắc xuyên suốt: tái sử dụng code hiện hữu, không sửa code lõi `registry.py`/`SkillLoader`; mọi đăng ký qua convention auto-discovery.
- Live verification thật (R7.6) chạy thủ công qua script ở task 5.1; nếu signing/tải thất bại thì hoãn live và xác minh bằng file cục bộ (R7.9).
- Checkpoints (task 3, 6, 9, 12) đảm bảo kiểm tra tăng dần.
- `test_visual_layer_templates.py` hiện chỉ bao gồm 5 template gốc — task 10.6 phải mở rộng để bao gồm 4 template mới và kiểm bộ bắt buộc (R5.10).
- `document_summary` đã có `extractor.py` — task 8.1 chỉ cần viết `adapter.py` tích hợp extractor.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": ["1.1", "1.2", "2.1", "7.1", "7.2", "7.3", "7.4", "10.1", "10.2", "10.3", "10.4"]
    },
    {
      "id": 1,
      "tasks": ["1.3", "2.2", "4.1", "8.1", "8.2", "8.3", "8.4", "8.5", "10.5", "7.5"]
    },
    {
      "id": 2,
      "tasks": ["2.3", "2.4", "2.5", "2.6", "2.7", "2.8", "4.2", "4.3", "5.1", "8.6", "8.7", "8.8", "8.9", "10.6"]
    },
    {
      "id": 3,
      "tasks": ["2.9", "4.4", "5.2", "5.3", "5.4", "10.7"]
    },
    {
      "id": 4,
      "tasks": ["5.5", "11.1", "11.2"]
    }
  ]
}
```
