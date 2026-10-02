# Bàn giao triển khai plan AIFlow

**28/09/2026:** đã thêm [Codex qua CAO/tmux](CODEX_TMUX.md). Cần Ubuntu WSL và ChatGPT login để nghiệm thu; các dòng “Codex vẫn khóa” trong lịch sử bên dưới không còn là mô tả mã nguồn mới nhất.

Ngày cập nhật: 27/09/2026. Phạm vi: app cá nhân, không AI local, URL Colab nhập thủ công, website nháp nhiều kênh. Giữ các thay đổi sẵn có; chưa commit hoặc deploy.

**Cập nhật mới nhất:** [Bàn giao mục 1 và 2](STUDIO_COMPLETION_V2.md) bổ sung Gemini Script Studio, series, thư viện chung, ảnh có tham chiếu, nhận clip và điều khiển fine-tune/resume/đổi giọng trên web. Ma trận dưới đây ghi lại đợt triển khai trước; các giới hạn “chưa Gemini”, “portrait chỉ nhập ngoài” đã được thay thế bởi bản cập nhật. Codex automation vẫn khóa, nghiệm thu provider/Colab thật vẫn chưa thực hiện.

## 1. Trạng thái theo plan

| Mốc | Đã triển khai | Nghiệm thu còn phụ thuộc môi trường thật |
|---|---|---|
| P0 | Gemini không bắt buộc khởi động; TTS mặc định remote; chặn inference local; backup SQLite trước thêm cột; legacy giữ nguyên loại `legacy` | Migration tự chạy trên dữ liệu thật ở lần khởi động tiếp theo; phiên này chỉ thử DB tạm |
| P1 | Notebook Kokoro EN, Drive checkpoint/model revision, token phiên, Quick Tunnel tùy chọn, batch; STT faster-whisper small en/vi tùy chọn, GPU remote, chung hàng đợi một tác vụ | Nạp model, nghe voice, kiểm tra CUDA/cuDNN, latency/VRAM và ngắt runtime trên Colab Pro |
| P2 | Check/save URL+token, queue SQLite, cache hash, retry/cancel/restart, chống gắn audio khi nội dung đổi, tải notebook/worker/batch | Tunnel thật, đổi URL/runtime và phục hồi inference đang chạy |
| P3 | Brief → outline → script → review, phiên bản/checklist/hash, editor cảnh, kiểm tra thời lượng, OpenRouter free-only, nhập JSON | Chất lượng model thật và hạn mức tài khoản. Codex automation vẫn khóa vì chưa bảo đảm chỉ dùng subscription. Gemini vẫn tùy chọn ở các adapter cũ, chưa thêm provider Gemini vào Script Studio |
| P4 | Portrait nhập ảnh từ ngoài, đối chiếu tham chiếu/duyệt, PNG/JPEG/preview native pixels, video ảnh/MP4 + lời đọc đo thực tế + im lặng + SRT, zoom ảnh tùy chọn, manifest và ZIP đã duyệt; G2 fail-closed | Ảnh giữ nhận diện từ provider ngoài, Flow/credits và tập video nội dung thật. Test kỹ thuật không chứng minh chất lượng thương mại |
| P5 | Navigation chung; tổng quan việc chờ; lọc tên/kênh/loại/trạng thái; hàng đợi audio/render; thư viện theo dự án; duyệt thành phẩm; giữ route cũ | Dùng thử với nhiều dự án thật, rà quyền tài nguyên trước giao hàng |
| P6 | Site tĩnh độc lập, sáu trang và trang chi tiết, JSON nhiều kênh vi/en, domain cấu hình, draft/noindex, kiểm tra public consent | Theo lựa chọn của bạn: chưa điền danh tính/liên hệ, chưa xuất bản và chưa gắn domain |

Đây là bàn giao source và kiểm tra local, **chưa phải tuyên bố toàn bộ hệ thống đã được nghiệm thu bằng model thật**.

## 2. Điều hướng vận hành

- `/`: việc chờ duyệt / chờ Colab và danh sách dự án thật.
- `/scripts`: xưởng kịch bản và phiên bản; xem `SCRIPT_STUDIO.md`.
- `/production`: tạo portrait, quản lý kênh, media và bộ file.
- `/production?project=<id>`: xưởng của một dự án.
- `/connections`: nhập URL/token, kiểm tra, lưu; tạo audio dự án hoặc audio độc lập.
- `/work-queue`: tổng hợp tác vụ, lọc trạng thái, hủy render hoặc mở trang audio để tiếp tục/hủy.
- `/queue`: trang audio hiện có, giữ tương thích link cũ.
- `/library`: dự án/thành phẩm và link thư viện giọng, adapter/phong cách, phiên bản kịch bản.
- `/projects`, `/timeline/:projectId`, `/export/:projectId`, `/voices`, `/new-project`: giữ nguyên.

`channel` là nhãn bạn tự đặt, ví dụ `pet-en`, `stories-en`, không kết nối hay tự tạo tài khoản mạng xã hội.

## 3. Portrait: quy trình thật đang hỗ trợ

1. Tạo dự án tại `/production`: loài, dấu hiệu nhận diện, phong cách, yêu cầu và kênh.
2. Nhập 1-3 ảnh tham chiếu PNG/JPEG/WebP. Ảnh tối đa 10 MiB, 40 megapixel.
3. Sao chép brief/prompt để tạo ảnh bằng dịch vụ ngoài **có hỗ trợ ảnh tham chiếu**. Khả năng text-to-image của Flow không được coi là bằng chứng giữ đúng danh tính thú cưng.
4. Nhập ảnh chân dung kết quả. Nhìn ảnh tham chiếu và kết quả, duyệt likeness/anatomy/crop/artifacts.
5. Xuất lượt mới. App dùng **bản mới nhất còn hoạt động**, yêu cầu bản đó đã duyệt. Lưu trữ bản mới nếu muốn quay lại bản cũ.
6. Kiểm tra preview, PNG/JPEG, kích thước pixel, listing nháp. Duyệt chất lượng, quyền sử dụng và bộ file, rồi tải ZIP.

Không upscale hay gắn nhãn “300 DPI” giả. File PNG/JPEG giữ số pixel gốc sau chuẩn hóa hướng ảnh. PNG chuyển RGB; alpha không được giữ trong bộ chân dung hiện tại. Listing là bản nháp, phải bổ sung thông tin bán hàng thật.

## 4. Video: quy trình từ kịch bản đến bộ file

1. Tạo/sửa và duyệt script trong `/scripts`, tạo dự án. Mở dự án ở `/production`, gán kênh.
2. Nếu có lời đọc: mở `/connections`, bật Colab và chọn đúng dự án để tạo audio. Khi cache đủ thì không cần mở Colab lại cho TTS.
3. Nhập ảnh hoặc MP4 cho từng cảnh; duyệt nội dung, continuity và khung hình. MP4 tối đa 100 MiB. Có thể tạo clip ở Timeline/Flow rồi nhập clip vào xưởng để duyệt.
4. Chọn phụ đề theo cảnh hoặc STT từ xa. Chọn zoom ảnh nếu muốn chuyển động nhẹ; chọn cho phép loop nếu clip ngắn hơn lời đọc. Hai lựa chọn này mặc định tắt.
5. Xuất lượt mới, nghe/xem video và đọc SRT trước khi duyệt ZIP.

### Quy tắc thời lượng

- Mỗi cảnh dài bằng `max(thời lượng kịch bản, thời lượng audio đo bằng ffprobe)`.
- Audio từng cảnh được pad im lặng tới cuối cảnh; cảnh không có narration giữ im lặng.
- Audio gốc của clip nhập bị bỏ; dùng narration đã chọn, tránh âm thanh lẫn không kiểm soát.
- Clip ngắn chỉ lặp nếu bạn bật cho phép; ảnh có thể dùng suốt cảnh. Zoom tùy chọn giới hạn 5% vùng rìa.
- 9:16 → 720×1280; 16:9 → 1280×720; 1:1 → 1080×1080. H.264/AAC, 24 fps.
- Mặc định SRT giữ nguyên văn kịch bản, mốc theo cảnh và thời lượng đọc; **không phải căn từng từ**. SRT là file riêng, không burn vào video ở đường production mới.
- STT là lời nhận dạng, có thể sai khác kịch bản; người dùng phải duyệt. Nếu STT thất bại, lượt xuất báo lỗi, không âm thầm chuyển phương pháp.

Bộ video gồm `video.mp4`, `thumbnail.jpg`, `subtitles.srt`, `script.txt`, `publishing-draft.txt`, `manifest.json`. Không tự đăng lên TikTok/Facebook/YouTube.

### Đường Flow cũ

Ảnh đầu có thể lấy từ reference asset đã qua G2 khi chưa có frame cảnh trước. Aspect/duration được truyền xuống SDK. G2 lỗi/hết hạn/mất state dừng pipeline. G3 đọc stream bằng ffprobe, không đánh giá chỉ từ dung lượng file. Kết quả từng cảnh được lưu; trạng thái partial giữ theo đường generation cũ. Đường xuất production yêu cầu đủ visual đã duyệt cho mọi cảnh.

## 5. STT trên Colab

Notebook `colab/serve_audio_api.ipynb` có ô `ENABLE_STT = False`. Đổi thành `True` khi cần, chạy sau nạp TTS và lúc queue rảnh, rồi **kiểm tra và lưu lại kết nối trong AIFlow** để nhận capability STT.

- Model `Systran/faster-whisper-small`, revision được pin trên Drive.
- GPU `int8_float16`; không fallback CPU/local.
- TTS/STT chung `ThreadPoolExecutor(max_workers=1)`.
- STT nhận PCM16 WAV tối đa 32 MiB/360 giây, tiếng `en` hoặc `vi`.
- Key chứa hash audio, language và revision; kết quả JSON có checksum, word timestamps từ worker. Bộ SRT hiện dùng segment timestamps.
- Cache transcript tại `storage/audio/transcripts`; đổi session trong khi chờ sẽ dừng lượt xuất.
- Batch không tunnel hiện dành cho TTS; muốn tránh STT qua tunnel thì chọn phụ đề theo cảnh.

API và yêu cầu CUDA/cuDNN đối chiếu [tài liệu faster-whisper](https://github.com/SYSTRAN/faster-whisper). Máy local không cài thư viện model này. Chưa chạy model thật trên Colab trong phiên triển khai.

## 6. Lỗi, hủy và restart

- Render chạy FFmpeg local; nút hủy dừng sau công đoạn hiện tại, không kill giữa lúc ghi file. STT kiểm tra yêu cầu hủy trong khi poll.
- Lượt xuất lỗi/đã hủy giữ lịch sử và intermediate. Sửa nguyên nhân rồi chọn **Xuất lượt mới**.
- Restart backend: render đang chạy thành `interrupted`, job `needs_attention`; không replay tạo tài nguyên.
- Audio restart chờ kết nối/tiếp tục. Bản cache còn hợp lệ được tái sử dụng.
- File nguồn/thành phẩm bị thay ngoài ứng dụng: kiểm tra SHA256 chặn xuất/gói giao hàng, cần nhập/xuất lại.
- Đổi ảnh tham chiếu hủy duyệt portrait cũ; sửa prompt/narration hủy duyệt visual. Đổi narration hoặc tạo tác vụ audio mới bỏ liên kết audio cũ, phải chờ bản mới hoàn tất.
- Dự án có lịch sử audio/media/output được chặn hard-delete để tránh liên kết nhầm ID tái sử dụng. Có thể lưu trữ từng media trong xưởng.
- Token chỉ ở bộ nhớ backend; đóng backend thì phải nhập lại token. ZIP không chứa token hoặc absolute path audio.

## 7. Kiểm tra đã thực hiện

Kết quả cuối đợt: **169 test Python trong nhóm regression bên dưới và 2 test Node website đều qua**; build TypeScript/Vite, kiểm tra Ruff F/E9 trên phần production/worker mới, `git diff --check` và ba luồng Chromium đều qua. Có một cảnh báo deprecation từ Starlette TestClient/httpx; chưa đổi dependency chỉ để tắt cảnh báo.

- DB tạm SQLite, không dùng database dự án thật.
- Script Studio: kiểm tra schema/free-only/revision/preflight/approval và Chromium edit → approve → project.
- Worker/API: URL, token không ghi disk, checksum/cache, queue cancel/restart/stale content, TTS idempotency và STT contract bằng model giả.
- Production: FFmpeg thật với fixture tổng hợp; duration/aspect/silence/SRT, static/zoom, PNG/JPEG native pixels, review gates, ZIP hash, recovery/cancel.
- G2: passed/overridden mới đi tiếp; expired/failed/not_found/DB error dừng.
- Backend full lifespan khởi động/dừng với storage tạm, không Gemini hoặc model local.
- UI production: Chromium desktop 1440×1000 và mobile 390×844, không page error/tràn ngang.
- Website: hai kênh build độc lập; sáu route desktop/mobile; draft/noindex và kiểm tra điều kiện release.

Các ảnh test màu trơn là **fixture kỹ thuật**, không phải sản phẩm AI mẫu để quảng bá. Screenshot tại `storage/verification/{script-studio,production,public-site}`.

Chạy lại nhóm regression:

```powershell
cd D:\Project\AIFlow\app
python -m pytest server/tests/test_script_studio.py server/tests/test_remote_audio.py server/tests/test_production.py server/tests/test_production_gates.py server/tests/test_pipeline_orchestrator.py server/tests/test_composer.py server/tests/test_quality_gate_g6.py server/tests/test_config.py -q
cd ui
npm run build
```

Không coi các test trên là kết quả toàn bộ suite cũ. Suite cũ cho local Whisper/VieNeu có hợp đồng không còn phù hợp với yêu cầu bỏ AI local.

## 8. Website nhiều kênh

Xem `D:\Project\AIFlow\public-site\README.md`. Cấu hình tại `channels.json`; `personal`/`stories` chỉ là tên nháp có thể đổi. Không kéo dữ liệu nội bộ/API hoặc ảnh khách hàng lên website tự động. Domain và Colab không phụ thuộc nhau.

## 9. Nghiệm thu bằng tài khoản của bạn

1. Mở app với phiên bản mới; startup backup trước các cột mới. Kiểm tra dự án cũ còn nguyên.
2. Bật Colab GPU, nạp Kokoro, tạo một đoạn tiếng Anh ngắn, nghe và chọn voice.
3. Kết nối tunnel nếu phù hợp; thử đổi URL/khởi động lại runtime khi một batch chưa xong, xác nhận cache/checkpoint phục hồi.
4. Tùy chọn bật STT và so phụ đề với audio thật.
5. Làm một portrait thật và một tập fiction thật; kiểm tra bằng mắt/tai trước khi giao/đăng. Provider ngoài và Flow có điều kiện sử dụng/credits riêng.
6. Điền thương hiệu và nội dung được phép công khai rồi mới quyết định hosting/domain. Codex tự động vẫn chưa bật dưới cam kết subscription-only.
