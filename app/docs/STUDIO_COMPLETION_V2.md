# Bàn giao mục 1 và 2 — Xưởng sản xuất và fine-tune

**Hiện tại 04/10/2026:** podcast có lời **90 giây, project 7/output 5 đã approved qua Client**, [MP4](../storage/pottery-three-characters/chiec-bat-chua-tron-podcast-90s.mp4), [SRT](../storage/pottery-three-characters/chiec-bat-chua-tron-podcast-90s.srt) và [ZIP](../storage/pottery-three-characters/chiec-bat-chua-tron-podcast-90s-delivery.zip) đã kiểm chứng; xem [mục 9 và bằng chứng cuối](#delivery-oct04). Backend **3049 test passed**, audio/phụ đề **70/70 kiểm tra đạt**. Review có hỗ trợ máy, chưa xác nhận nghe toàn bộ của người dùng; giọng YouTube còn awaiting_review, inference provider ngoài và áp dụng launcher mới chưa có receipt live. Các mục có ngày 27–28/09 và snapshot trước ở dưới ghi lịch sử; câu “không inference thật” trong đợt đó không mô tả lượt Flow/TTS/render 04/10.

**Cập nhật 28/09/2026:** đã thay adapter Codex khóa bằng luồng [CAO + tmux trong WSL](CODEX_TMUX.md), có cấu hình, receipt, sync/cancel và kiểm tra JSON. Chưa nghiệm thu runtime thật vì máy chưa có Ubuntu WSL. Các mô tả “Codex khóa” dưới đây là trạng thái ngày 27/09 trước quyết định này.

Ngày: 27/09/2026. Đây là trạng thái mã nguồn của đợt bổ sung mới nhất, thay thế các mô tả “chỉ nhập ảnh ngoài”, “chỉ notebook”, “chưa có Gemini” trong báo cáo trước.

## 1. Phạm vi đã làm

| Hạng mục | Kết quả |
|---|---|
| Gemini kịch bản | Chọn provider/model riêng; structured output được kiểm tra schema; lỗi không tự retry/chuyển model. Có brief tiếng Việt/Anh |
| Codex CLI | Adapter khóa trước khi chạy CLI. **Chưa hoàn thành automation** vì chưa bảo đảm chặn credits ngoài subscription; vẫn dùng xuất prompt/nhập JSON |
| Series | Bible/canon có phiên bản; mỗi tập giữ snapshot. Khóa giọng, ngôn ngữ, tốc độ và revision model theo tập; cập nhật canon yêu cầu kịch bản đã duyệt |
| Ảnh có tham chiếu | Gọi Gemini từ xưởng portrait/video, model do người dùng cấu hình. Portrait cần 1–3 ảnh; video phải qua cổng duyệt kịch bản. Ảnh trả về chưa được duyệt |
| Bàn giao sản xuất | Kịch bản → project → audio/Timeline → nhận clip vào xưởng → duyệt → render/xuất. Nhận clip là thao tác rõ ràng, có kiểm tra hash và tránh nhập lặp |
| Kết nối/thư viện chung | `/studio-settings`: OpenRouter, Gemini, ảnh, trạng thái Flow/Colab; nhân vật/phong cách/bối cảnh/tham chiếu dùng lại dưới dạng snapshot |
| Điều khiển fine-tune | `/voice-training`: gửi lựa chọn, download, chuẩn bị, nghe/sửa transcript, duyệt dataset, train, xem bước đã lưu, yêu cầu dừng, resume, nghe/duyệt giọng, load |
| Đổi giọng | Dỡ model cũ và load profile đã duyệt trong cùng runtime; không cho tranh GPU với tác vụ khác |
| Resume | Trainer riêng lưu adapter + optimizer + scheduler + RNG + vị trí dữ liệu sau mỗi bước optimizer trên Drive |
| Batch fine-tuned TTS | Notebook mới có đường load giọng đã duyệt và chạy manifest/ZIP không cần tunnel; phải dừng API trước |

Không chạy model trên Windows. Không có lời gọi inference thật trong đợt thi công này. Gemini **không được cam kết miễn phí**: chỉ bật sau khi nhập key/model và xác nhận quota/billing. OpenRouter giữ cơ chế free-only đã có.

## 2. Bắt đầu với xưởng

1. Khởi động lại backend/frontend. Backend thêm bốn bảng studio và có cơ chế backup SQLite trước nâng cấp; chưa chạy nâng cấp DB thật trong phiên thi công. Migration tương ứng: `0007`.
2. Mở `/studio-settings`, nhập key provider cho phiên server. Key chỉ ở RAM, restart phải nhập lại. Kiểm tra model/quota của tài khoản trước khi tạo.
3. Tạo series, ghi nhân vật/bối cảnh/diễn biến vào bible, chọn ngôn ngữ. Nếu cần khóa giọng/model, kết nối Colab và load đúng giọng trước khi chọn. Bản cập nhật series áp dụng cho tập mới.
4. `/scripts`: chọn series hoặc tập độc lập, chọn provider/model; đi qua outline, script, review, chỉnh sửa và duyệt. Tạo project rồi mở xưởng sản xuất.
5. Với portrait, tạo dự án và nhập ảnh tham chiếu, sau đó bấm tạo ảnh. Với video, chọn cảnh cần ảnh hoặc làm clip ở Timeline rồi bấm **Nhận clip từ Timeline vào xưởng**.
6. Nghe lời đọc, duyệt hình/clip và xuất theo quy trình production hiện có. Ảnh bị trả về sau khi brief/tham chiếu thay đổi được đánh dấu cần xử lý, không tự dùng để xuất.
7. Thư viện chung nhận mô tả và ID ảnh trong xưởng nếu có; áp dụng vào ID dự án. Cấu hình series và library hiện vẫn cần một số ID nhập thủ công; chưa có trình tìm kiếm tài nguyên nâng cao.

`Xem trạng thái các lần tạo ảnh` giúp kiểm tra sau khi reload/mất kết nối. Tác vụ ảnh bị ngắt không tự gửi lại vì có thể nhà cung cấp đã xử lý/tính quota. Kiểm tra kết quả/trạng thái trước khi chủ động tạo lượt mới.

## 3. Fine-tune điều khiển từ web

1. Vào `/voice-training`, tải **notebook điều khiển** và **gói worker**. Mở `control_voice_training.ipynb` trong Colab GPU, chạy từng ô setup, upload ZIP và mount My Drive.
2. Tạo Colab Secrets `R2_ACCESS_KEY_ID` và `R2_SECRET_ACCESS_KEY`, cấp quyền đọc notebook. Chỉ cần secrets khi tải nguồn R2; không cần public bucket.
3. Bật API/tunnel ở notebook; dán URL và token phiên vào phần **Kết nối điều khiển Colab**. Bước này chưa tải media/chạy train.
4. Quét R2 phía dưới: phân trang toàn bucket/prefix, lọc đuôi hỗ trợ. Chọn file của một giọng, tên/ngôn ngữ, xác nhận rồi **Gửi lựa chọn sang Colab • chưa tải media**.
5. Bấm **Tải đúng file đã chọn**, chờ xong; bấm **Tách audio / chép lời**. Chỉ những object đã chọn được tải; kiểm tra metadata/checksum giữ nguyên.
6. Mở dataset: nghe từng đoạn, sửa transcript, loại đoạn sai người/nhạc/lỗi, đánh dấu đã nghe và lưu. Duyệt toàn bộ dataset đã lưu; tối thiểu 20 đoạn được dùng và đã duyệt. Sửa lại sẽ hủy duyệt cũ.
7. Chọn epochs rồi train. UI cập nhật trạng thái và số bước optimizer đã lưu khoảng 5 giây/lần. Lỗi chi tiết ở `MyDrive/AIFlow/voice-training/<job>/actions/<request>.log`; UI không truyền toàn bộ log/secret.
8. Sau train, nhập câu mới để sinh mẫu; nghe và duyệt. Bấm **Load / đổi sang giọng này**, rồi **Dùng giọng đang load cho TTS trong AIFlow** để cập nhật danh sách giọng và revision ở trang audio.
9. Khi hết việc, dùng ô dừng rồi **Disconnect and delete runtime**. Ngắt kết nối trên web chỉ bỏ URL/token phía app, không tắt GPU Colab.

ZIP và notebook thủ công cũ vẫn là phương án dự phòng. Khi chỉ dùng lại giọng, mở notebook điều khiển, mount Drive, bật API và chọn run đã duyệt để load; không cần tải lại hay train.

Dữ liệu trên máy dùng **Gửi media local sang Colab / Drive**: nhận MP3, WAV, FLAC, M4A, OGG, AAC, OPUS, MP4, MOV, MKV, WEBM; tối đa 2 GiB/file, 20 GiB/lượt và 5000 file có tên riêng. UI gửi metadata trước rồi `File.slice` từng 8 MiB qua backend, không đọc cả file vào RAM trình duyệt. Colab kiểm tra offset/checksum từng phần, xác minh có stream âm thanh và lưu SHA-256 toàn file trước khi cho chuẩn bị dataset. Gửi lại cùng lựa chọn tiếp tục từ offset đã lưu; sau refresh, chọn lại cùng file/tên giọng (trình duyệt chỉ lưu metadata và request ID). Worker cũ chưa hỗ trợ `chunks-v1` sẽ báo cập nhật gói worker; endpoint WAV cũ vẫn được giữ.

Chuẩn bị dataset chuẩn hóa audio/video và sample rate khác nhau thành mono 24 kHz PCM theo từng đoạn tối đa 600 giây; scratch được xóa sau mỗi đoạn. Checkpoint giữ checksum nguồn, revision ASR, normalization và checksum clip; tiếp tục không chép lời lại đoạn đã hoàn tất. Transcript được giữ nguyên cùng timestamp toàn nguồn. Nhóm từ sát một giây đầu/cuối tại biên nhân tạo bị loại bảo thủ và ghi lý do trong checkpoint, tránh train từ bị cắt hoặc lặp do overlap; có thể mất một ít lời nói ở mỗi biên. `review.json` đã có không bị ghi đè, các đoạn mới chưa được duyệt. Năm giờ PCM mono 24 kHz 16-bit khoảng 824 MiB nằm trong giới hạn upload; thời lượng không chứng minh chất lượng hoặc cùng người nói.

Nghiệm thu live qua Client → backend → Colab/Drive dùng job `fbb24e66007d43d0a721ca13090e0c78`, bốn fixture tổng khoảng 84 giây; dataset QA chưa được duyệt và không dùng huấn luyện Thuần:

- [Chuẩn hóa live](../storage/thuan-podcast/raw-media-live-fixtures/normalization-live.json): MP3 mono 32 kHz, MP4 stereo 44,1 kHz, WAV stereo 48 kHz và WAV QA 60 giây đã tạo 23 clip, tất cả mono 24 kHz PCM 16-bit; lưu bốn checkpoint.
- [Upload/resume live](../storage/thuan-podcast/raw-media-live-fixtures/upload-resume-live.json): Playwright chặn request chunk thứ hai sau khi Drive xác nhận offset `8.388.608`. Sau reload trang/chọn lại cùng file, UI tiếp tục từ offset đó đến `11.520.078`, checksum toàn file khớp fixture; không gửi lại ba file đã hoàn tất.
- [Từ chối file không audio](../storage/thuan-podcast/raw-media-live-fixtures/no-audio-rejected-live.json): MP4 chỉ có video trả HTTP 422 với thông báo media không có âm thanh/thời lượng hợp lệ.

Bằng chứng này xác nhận luồng với fixture nhỏ và một file vượt 8 MiB; chưa nghiệm thu hiệu năng upload/ASR với dữ liệu 5 giờ hoặc biên xử lý 600 giây trên runtime thật. Chuẩn hóa đúng định dạng không tự xác nhận transcript, đúng người nói hoặc chất lượng giọng.

Setup của hai notebook fine-tune gỡ `torchao` tùy chọn trong runtime Colab dành cho AIFlow. Pipeline dùng LoRA với weight FP32, không dùng lượng tử hóa; `torchao` cũ có sẵn trong Colab làm PEFT lỗi ngay khi gắn adapter. Nếu phiên đang chạy gặp lỗi này, dùng `python -m pip uninstall -y torchao` trong runtime Colab rồi chạy lại bước train bằng process Python mới; giữ nguyên phiên bản Torch.

## 4. Resume và batch

Mỗi run mới có `train.parquet`, `review.json`, `trainer-config.json`, `environment.txt`, `trainer-state.pt`, `progress.json`; sau hoàn tất có `adapter/`, `merged/`, `profile.json`. Đây là trainer AIFlow dùng các primitive VieNeu tại commit cố định, không phải tuyên bố CLI upstream tự hỗ trợ full resume.

- Resume cùng run kiểm tra hash dataset, base model, epochs, precision và phiên bản package ghi trong cấu hình. Môi trường không khớp sẽ dừng để xử lý, không âm thầm bắt đầu lại.
- Mất runtime giữa một bước: tiếp tục từ bước optimizer hoàn tất gần nhất; phần bước chưa lưu được làm lại. Nút dừng có hiệu lực ở ranh giới file/bước hoặc sau công đoạn hiện tại, không phải kill tức thì.
- Run cũ chỉ có adapter upstream không thể biến thành checkpoint optimizer đầy đủ. Run đã đóng gói model tạo phiên bản train mới khi cần huấn luyện thêm.
- Chưa có lockfile Colab đã nghiệm thu; `environment.txt` giúp đối chiếu. Không bảo đảm kết quả bit-for-bit khi thay GPU/CUDA.
- Batch: dùng phần riêng trong notebook mới, dừng API, chọn giọng đã duyệt, load rồi dùng health/voices để cấu hình manifest theo hướng dẫn [audio](REMOTE_AUDIO_SETUP.md). Upload manifest, chạy, tải ZIP và nhập kết quả vào AIFlow. Không cần tunnel cho bước tạo audio này.

## 5. Luồng giao diện và khôi phục

Thiết kế theo `ux-flow`: operations-console / product-ui, giữ hệ thống React/Tailwind hiện tại. Screen inventory: settings, script, production, audio, training. Các section/form dùng layout co giãn và nút xuống dòng; chưa nghiệm thu hình ảnh trình duyệt 390/1440 trong đợt này.

```text
Settings → Series → Script → Approval → Project → Audio/Timeline → Production → Export
R2 scan → User selection → Send manifest → Download → Prepare → Review → Train
                                                    ↑                 ↓
                                              Edit/reapprove    Resume / Sample
                                                                      ↓
                                                             Approve → Load → TTS
```

| Trạng thái | Phục hồi |
|---|---|
| Chưa có key/API/model | Hiện cấu hình cần nhập; không tự chọn provider khác |
| Series bị sửa ở tab khác | Version conflict, tải lại trước khi lưu |
| Worker khác model đã khóa | Chặn tạo TTS; load đúng revision hoặc tạo tập mới với cấu hình mới |
| R2 scan hết hạn | Quét/chọn lại; không dùng danh sách cũ |
| Colab bận | Khóa thao tác model mới; cho yêu cầu dừng tác vụ hiện tại |
| Tunnel/runtime mất | Nhập URL/token mới, chọn bộ dữ liệu từ Drive, xem trạng thái rồi resume nếu có checkpoint |
| Transcript đã thay đổi | Hủy duyệt dataset; không resume run với dữ liệu khác |
| Reload trang training | Query `?training=<job>` giữ bộ dữ liệu; trạng thái được đọc lại từ Drive |
| Kết quả AI cũ về muộn | Không tự duyệt/xuất; kiểm tra lịch sử và dữ liệu hiện tại |

## 6. Bản đồ mã và kiểm tra

- Provider: `server/text/providers.py`, `api/routes/scripts.py`.
- Series/library/ảnh: `db/models/studio.py`, `studio/series.py`, `api/routes/studio.py`, `ui/src/pages/StudioSettings.tsx`, `components/ProductionActions.tsx`.
- Colab bridge: `api/routes/training_control.py`, `components/TrainingControl.tsx`.
- GPU: `colab/training_control.py`, `train_resumable.py`, `voice_training.py`, `audio_worker/app.py`, hai notebook fine-tune/control.

Đã qua: TypeScript, frontend production build, Ruff `F,E9` cho các module bổ sung/liên quan, cú pháp Python của hai notebook đã sửa, `git diff --check`. Không thêm/chạy test trong đợt này. Chưa gọi Gemini inference, R2 thật, train/resume GPU thật, đổi giọng thật, batch thật hoặc migration DB thật. Các kết quả test ở tài liệu đợt trước không thay thế nghiệm thu phần mới.

## 7. Cơ sở kỹ thuật

- [Gemini structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output) và [image generation](https://ai.google.dev/gemini-api/docs/generate-content/image-generation): hợp đồng provider; tên model do người dùng chọn.
- [Codex pricing](https://developers.openai.com/codex/pricing): chưa có căn cứ để bảo đảm CLI không dùng credits bổ sung trong mọi trường hợp; adapter giữ khóa.
- [VieNeu trainer tại commit ghim](https://github.com/pnnbao97/VieNeu-TTS/blob/c1390abbdb2eedcdf58eafb546966c06ce27af71/finetune/train_lora.py) và [LoRA primitives](https://github.com/pnnbao97/VieNeu-TTS/blob/c1390abbdb2eedcdf58eafb546966c06ce27af71/finetune/vieneu_lora/lora.py): đối chiếu API train/merge. Khả năng full checkpoint được bổ sung ở AIFlow.

## 8. Nghiệm thu bổ sung ngày 04/10/2026 — YouTube và clip Flow

Các kết quả dưới đây là bằng chứng của lượt chạy ngày 04/10; các giới hạn nghiệm thu trong mục trước thuộc thời điểm ghi nhận cũ.

### Audio YouTube vào dataset riêng

Tại `/voice-training`, dùng **Audio từ YouTube · Tiếng Việt**, nhập tên giọng và URL của một video, xác nhận quyền sử dụng/cùng người nói rồi bấm **Gửi URL & tải audio trên Colab**. Worker nhận HTTPS URL YouTube đơn lẻ, không nhận playlist hoặc URL tùy ý; giới hạn 3 giờ/video, 512 MiB audio và 10 phút/lượt tải. Download không dùng cookie/đăng nhập để vượt giới hạn truy cập; nếu nguồn không tải được, UI báo lỗi và có thể dùng media local có sẵn.

Luồng Client → backend → Colab → Drive đã tải [video Thuần Podcast](https://www.youtube.com/watch?v=iaPiJZeJwQk) vào job mới `17d0955b28a64ce98685f4cc1cd802f8`, độc lập với job/giọng đã duyệt trước đó:

- [Receipt nguồn live](../storage/thuan-podcast/youtube-source-live.json): audio WEBM `26.463.136` byte, thời lượng đo `1404,601` giây, stereo 48 kHz; SHA-256 `69ebea260317231a496f69ac96259301fe23b3a758f7e72524944c3844a11d47`. Metadata YouTube ghi 1405 giây; số đo media là căn cứ xử lý. URL, video ID, tiêu đề, định dạng, thời lượng và checksum được giữ trong provenance trên Drive.
- [Dataset ban đầu](../storage/thuan-podcast/youtube-review-initial.json): 341 clip, tổng thời lượng clip `1366,31` giây; nguồn được chuẩn hóa/ASR theo ba chunk bắt đầu ở 0, 600 và 1200 giây, mỗi chunk tối đa 600 giây. Tổng thời lượng clip không phải thời lượng lời nói độc lập vì các clip có phần đệm ngắn quanh từ.
- [Đối chiếu Whisper large-v3](../storage/thuan-podcast/youtube-review-verified.json) đã hoàn tất cả **341 clip**, giữ nguyên transcript gốc và lưu lời đối chiếu riêng. [Audit so sánh](../storage/thuan-podcast/preview-audit/youtube-verification-audit.json) ghi 131 đoạn khớp sau chuẩn hóa dấu câu/hoa thường, giữ dấu tiếng Việt; danh sách ưu tiên nghe có **52 clip / 197,84 giây**. Tại snapshot đối chiếu này, bộ YouTube có **0 đoạn đã duyệt**, `dataset_approved=false`; chưa train thêm hoặc duyệt giọng mới. ASR vẫn có lời nghi sai và đồng thuận giữa hai model không thay thế nghe. Trạng thái review/train mới hơn được ghi ở mục 9 bên dưới.

Rà lại yêu cầu train từ YouTube ngày 04/10: [trạng thái live](../storage/thuan-podcast/youtube-training-recheck-live.json) vẫn có 341 đoạn, 0 đoạn đã duyệt, chưa có run và nút Train khóa đúng trạng thái. Luồng production đã nối đủ YouTube → tải audio → chuẩn hóa/chép lời → duyệt dataset → `training.train` → đóng gói profile; không phát hiện nhánh train chỉ dành cho R2. Bổ sung hai regression kiểm tra luồng đã duyệt đến profile `awaiting_review`, chặn train/load sớm, chống gửi trùng và đóng gói đủ dependency trong worker/notebook. [Suite liên quan](../storage/thuan-podcast/pytest-oct04-youtube-train-path.xml) đạt **75 passed**. Các lệnh GPU/model/media bên ngoài dùng fixture CPU; kết quả này không phải một lượt train GPU thật từ bộ YouTube 341 đoạn. Hướng dẫn thao tác nằm trong [README](../README.md#fine-tune-giọng-tiếng-việt-từ-wav-local-hoặc-youtube).

### Giọng đang dùng và bản podcast chưa được duyệt

Giữ nguyên giọng A của run `aea70bd572da4e978a7d349d4b2fa094`, profile, weights và mẫu đã duyệt `09133764fa61961ac23ab16c5b993ecdaefdfac10e9874edd8d9c632e3274255`. [Lượt inference đối chứng](../storage/thuan-podcast/preview-audit/controlled-inference-live.json) tái tạo bản lời dẫn đầy đủ từng bị phản ánh khựng. Người dùng nghe B (`batch_size=1`) và C (`batch_size=1`, `max_chars=128`): cả hai hết khựng nhưng B hạ giọng ở nửa sau, C nâng giọng gần cuối; B/C không được chọn làm cấu hình cuối.

[Đối chứng prosody E/F](../storage/thuan-podcast/preview-audit/controlled-prosody-live.json) tạo [E — seed một lần, 57,81 giây](../storage/thuan-podcast/preview-audit/prosody/E-chronological-seed-once.wav) và [F — reset seed mỗi chunk, 57,11 giây](../storage/thuan-podcast/preview-audit/prosody/F-chronological-seed-each-chunk.wav), đều suy luận theo thứ tự lời đọc 1–4 thay cho thứ tự 4, 1, 3, 2 của B. Người dùng xác nhận chất lượng cả hai tốt sau khi nghe trích đoạn 24 giây [E](../storage/thuan-podcast/preview-audit/prosody/E-first24s.wav) / [F](../storage/thuan-podcast/preview-audit/prosody/F-first24s.wav). Chọn E: giữ temperature `0.8`, seed `42` một lần mỗi request, `max_chars=256`, batch một chunk theo thứ tự lời đọc; giữ cách ghép khoảng nghỉ và watermark gốc, không chỉnh pitch hoặc xử lý tín hiệu bổ sung. Sự chấp nhận này chưa xác nhận người dùng đã nghe toàn bộ phần cuối của bản 57,81 giây. [ASR E/F](../storage/thuan-podcast/preview-audit/controlled-asr-ef.json) và [cờ cần rà](../storage/thuan-podcast/preview-audit/controlled-asr-ef-qa.json) chỉ hỗ trợ kiểm tra chữ: alignment gặp IndexError; các timestamp outro vượt thời lượng file không chứng minh audio thực có lời thừa.

Policy `v3turbo-chronological-v1` đã vào helper dùng chung cho preview và production, đồng thời vào model revision/cache identity. [GPU QA của source mới](../storage/thuan-podcast/preview-audit/policy-e-runtime-live.json) kiểm tra SHA source `d491b1689cb05ca59607a8edf712e76a9b3a629f2d39b6c7d219fc801fed121f`: helper tạo full E trùng byte/hash và thời lượng `57,81` giây; mẫu A ngắn cũng trùng byte/hash và thời lượng `8,88` giây; toàn bộ file bảo vệ không đổi. Sau QA, runtime đã được unload/reload an toàn, load lại run đã duyệt qua Client và bấm **Dùng giọng đang load cho TTS trong AIFlow**. API audio báo `ready`, model revision mới `e0137d2863f002d4a1de68f2a2bcf815c401799b1a6ef138710975ee0aa50c96`; cache của policy cũ không dùng chung khóa. [Ghi nhận runtime](../storage/thuan-podcast/voice-runtime-verification.json) đã bổ sung [tác vụ TTS production 12 qua Client](../storage/thuan-podcast/preview-audit/policy-e-production-task12.json): nhập lời đọc riêng tại `/connections`, giọng A đã duyệt, speed `1`, không tạo lại mẫu training. Tác vụ thành công, một segment khóa đúng revision mới; khóa cache được tính lại theo speed `1.0` của backend và khớp. [WAV tải về](../storage/thuan-podcast/preview-audit/policy-e-production-task12.wav) là mono PCM16 24 kHz, `213120` frame / `8,88` giây, dữ liệu đầy đủ, không có sample chạm biên clipping; [QA kỹ thuật](../storage/thuan-podcast/preview-audit/policy-e-production-task12-qa.json) lưu SHA-256 `b262cca9be06d35c575dd3bfccbe468be71a0ddad87e0ae3a08aa34b899da2ee`. Chưa kiểm tra trùng byte sau resample so với A 48 kHz vì môi trường local không có soxr; checksum của hai sample rate không thể so trực tiếp. Kịch bản podcast 8 thuộc draft cũ được giữ; project 7 ở mục 9 thay thế đầu việc podcast này. Chưa có podcast có lời hoàn tất được nghiệm thu tại snapshot này.

### Cho phép Flow trả clip khi tạo âm thanh lỗi

Tại `/production`, tùy chọn **Cho phép Flow trả clip không có âm thanh khi phần tạo âm thanh lỗi** mặc định tắt. Giá trị `allow_silent_video` đi qua Client → backend → SDK → extension và được lưu trong snapshot tác vụ/provenance clip. Đổi giá trị với cùng request ID bị từ chối; request cũ thiếu trường này giữ mặc định `false`. Extension thao tác switch `return-silent-videos` trong **Cài đặt lưới ô**, xác nhận đúng trạng thái trước khi bấm tạo và dừng nếu không xác nhận được.

Trong dự án video 6 không có narration, hai lượt trước gặp lỗi tạo âm thanh của Flow khi tùy chọn còn tắt. Lượt mới `8ae6916b-ec9e-4691-bb92-e80a950042e2` với `allow_silent_video=true` đã thành công và lưu media 15: [MP4 nhận về](../storage/production/inputs/6/veo-8ae6916b-ec9e-4691-bb92-e80a950042e2.mp4). Khi trình duyệt/Bridge ngắt kết nối tạm thời, tác vụ tiếp tục nhận kết quả bằng mã Flow đã lưu, không gửi lại yêu cầu tạo. Một lượt thành công xác nhận chuỗi tùy chọn/nhận clip trên phiên này; chưa chứng minh tùy chọn luôn khắc phục mọi lỗi âm thanh, và vẫn cần kiểm tra clip trước khi duyệt. Tùy chọn này không thay đổi luồng TTS riêng hoặc renderer.

Video dự án 6 đã hoàn tất và output 3 được duyệt qua Client: [MP4 30 giây](../storage/pottery-three-characters/cung-bat-dau-lai-30s.mp4), [ZIP bàn giao](../storage/pottery-three-characters/cung-bat-dau-lai-30s-delivery.zip). ZIP đã tải xuống, có sáu file gồm manifest và kiểm tra integrity không lỗi. [Audit kỹ thuật](../storage/pottery-three-characters/delivery-audit.json) qua cả tám kiểm tra: 1280 × 720, 24 fps, 720 frame tương ứng 30,0 giây hình; container/AAC dài 30,021333 giây và im lặng có chủ ý, không có cờ black/freeze tự động. [Ghi nhận duyệt hình/provenance](../storage/pottery-three-characters/delivery-review.json) lưu rà 60 khung mẫu, ba nhân vật/trang phục giữ nhất quán; vẫn thấy cắt cảnh và thay đổi sáng nhỏ, không phải một cú máy liên tục. Thành phẩm dùng media 15, 16, 20, 24 và tham chiếu 14, 18, 23. Sau đó người dùng phản ánh hình bị nhảy tại các điểm nối 8/16 giây; bản v2 bên dưới được xuất để thay thế sau khi rà lại, hồ sơ output 3 được giữ nguyên.

Upload tham chiếu mới lần đầu đã thành công ở operation `791fb45a-4a31-42d6-b6e8-87bbfcae499a`, reference 23. [Trace lỗi cũ](../storage/pottery-three-characters/fresh-upload-timeout-trace.json) và [trace thành công](../storage/pottery-three-characters/fresh-upload-success-trace.json) ghi xử lý khoảng 10 giây; timeout xác nhận cũ 4 giây quá ngắn. Extension hiện dùng deadline chung 45 giây cho upload/xác nhận và chỉ xác nhận preview đúng file đã tải xong. Bằng chứng này xác nhận lượt mới cụ thể, không bảo đảm mọi lượt upload sau đều thành công.

### Nối cảnh bằng khung hình đầu

Tại `/production`, **Cách dùng ảnh tham chiếu** có hai giá trị `reference_mode`: `ingredients` mặc định giữ luồng tham chiếu nhân vật/trang phục cũ; `first_frame` dùng ảnh làm **Bắt đầu** trong chế độ **Khung hình** của Flow Lite. Khung hình đầu cần một PNG đã duyệt, thuộc dự án và còn khớp checksum; người dùng trích đúng khung cuối clip trước, ghi nguồn rồi chọn ảnh. Backend lưu mode, reference ID/SHA/provenance và `allow_silent_video` trong snapshot và clip; đổi mode hoặc ảnh với cùng request ID trả conflict. Request cũ thiếu mode giữ `ingredients`; nhận tiếp kết quả dùng mã Flow đã lưu, không gửi lại Generate.

Extension chọn đúng asset theo tên SHA. Asset đã có có thể tự gắn sau một lần chọn; upload mới còn xử lý có thể cần **Thêm vào câu lệnh**, chỉ bấm khi asset đúng đã được chọn và preview đúng tên đã tải xong. Cả hai đường đều phải xác nhận picker đã đóng, slot đầu có đúng một ảnh đã tải xong/không bận và slot **Kết thúc** còn trống trước Generate; upload mới dùng deadline chung 45 giây. Prompt đã duyệt và renderer cắt cảnh hiện tại được giữ nguyên.

[Receipt first-frame live](../storage/pottery-three-characters/first-frame-live.json) xác nhận ba lượt qua Client → backend → SDK/RPC → extension → Flow UI đều thành công, checksum reference/clip local khớp DB:

| Cảnh | Operation | PNG đầu | Clip nhận |
|---|---|---|---|
| 2 | `7fa28553-8c85-4363-80c6-4c2bfda9087a` | 25 | 26 |
| 3 | `be65ba01-a8fa-43d4-826f-95cab09f0e43` | 27 | 28 |
| 4 | `f2db12f8-63f9-4126-9892-f8f51d157641` | 29 | 30 |

Root rà hình đầu clip 26 khớp hình cuối clip trước; reference 27/29 kiểm chứng đường upload mới cần confirmation sau bản sửa. Client đã xuất và duyệt output 4 thành [MP4 v2](../storage/pottery-three-characters/cung-bat-dau-lai-30s-v2.mp4), hash local khớp manifest và DB ghi `approved`. Root rà 60 khung tổng quan cùng 39 khung sát ba điểm nối trong [ảnh rà nối dày](../storage/pottery-three-characters/delivery-v2-dense-joins.jpg); [playback trình duyệt](../storage/pottery-three-characters/delivery-v2-playback.json) chạy toàn bộ 30,021333 giây, không có media error và dropped frame bằng 0. Bộ đếm frame playback không thay số frame mã hóa của ffprobe. Các lượt này chứng minh điều khiển/gắn ảnh và nhận clip trên phiên hiện tại; nguồn đúng khung cuối và chất lượng chuyển động/ánh sáng/điểm nối dựa vào ghi nguồn và rà hình, không có metric tự động xác nhận liền mạch. Output 3 và hồ sơ bàn giao cũ được giữ nguyên.

[Đối chiếu nguồn cũ/mới](../storage/pottery-three-characters/continuity-qa-v2-final/continuity-report-v2.json) đo sai khác RGB trung bình tại ba điểm nối giảm từ `37,53 / 37,59 / 39,56` xuống `2,20 / 2,22 / 2,35` trên thang 0–255; SSIM mới khoảng `0,994`. [Kiểm tra trực tiếp bản xuất](../storage/pottery-three-characters/render-boundaries-v2/render-boundaries-v2.json) tại cặp frame 191/192, 383/384 và 575/576 đạt SSIM trên `0,991`, vẫn có bước đổi sáng nhỏ khoảng `1,6–1,9/255`. Đây là bằng chứng giảm nhảy hình; không bảo đảm vận tốc chuyển động hoặc cảm nhận liền mạch tuyệt đối. [Audit bàn giao v2](../storage/pottery-three-characters/delivery-audit-v2.json) qua đủ tám kiểm tra: 720 frame, 24 fps, 30 giây hình, 1280 × 720, audio im lặng có chủ ý, không có cờ black/freeze. [Ghi nhận rà v2](../storage/pottery-three-characters/delivery-review-v2.json) giữ phạm vi kiểm tra và nguồn; [ZIP v2](../storage/pottery-three-characters/cung-bat-dau-lai-30s-v2-delivery.zip) có sáu file, kiểm tra CRC đạt. Chưa có phản hồi của người dùng về bản v2.

### Kiểm tra cục bộ

[Báo cáo pytest trước phần first-frame](../storage/thuan-podcast/pytest-oct04-youtube-silent-flow.xml) ghi 3006 passed. [Lượt backend đầy đủ sau first-frame](../storage/thuan-podcast/pytest-oct04-firstframe-policy-e.xml) đạt **3018 passed**, một cảnh báo dependency; extension **77/77** test và frontend production build đã qua. Backend/frontend đã được khởi động lại khi phiên mới không còn cổng listen, nên các sửa backend hiện đã chạy. Test cục bộ và receipt live xác nhận phạm vi tương ứng; output 3/4 im lặng đã được duyệt, podcast có lời và dataset YouTube vẫn cần nghiệm thu riêng.

<a id="delivery-oct04"></a>

## 9. Bàn giao podcast 90 giây ngày 04/10/2026 — duyệt kỹ thuật qua Client

### Review giao diện và bảo vệ audio theo dự án

Đã sửa `/connections` để lựa chọn dự án theo query URL và ghi lại URL khi đổi dropdown; danh sách không đưa dự án không có cảnh vào nguồn lời đọc. `/library?project=<id>` hiện hiển thị ảnh/clip trong xưởng, trạng thái duyệt, download và link về sản xuất. Dự án legacy có đường mở Timeline, không còn nút tạo ảnh mà server luôn từ chối do chưa phân loại. `TrainingControl` chỉ hiển thị các action khi `detail.job_id` khớp job đang chọn; đổi dataset không còn dùng snapshot cũ để bật nút nhưng gửi action vào job mới. Frontend `tsc + vite build` đã qua sau sửa guard này. Kiểm tra GET các API của Overview, Script, Production, Colab/audio, training connection, series/library, voices, projects và skills trả 200. Root đã kiểm tra giao diện Library có tài nguyên Xưởng gốm; bộ lọc `cancelled` tại `/work-queue` chỉ hiện audio #3 và các link điều hướng hiển thị. Các kiểm tra này chưa xác nhận mọi nút trên UI bằng E2E.

`POST /api/audio/tasks` lấy quyền ghi transaction trước khi kiểm tra task của dự án. Nếu còn task chưa `succeeded/cancelled`, server trả 409 trước khi thay giọng hoặc xóa audio cảnh. Hai POST đồng thời không thể cùng tạo task thay thế. Regression trước sửa có sáu lỗi, gồm hai request đều được nhận; [suite ownership/production/audio/legacy](../storage/thuan-podcast/pytest-oct04-audio-ownership.xml) sau sửa đạt **66 passed**, kiểm tra 409 giữ nguyên project, task và audio đã lưu. [Suite backend đầy đủ mới nhất](../storage/thuan-podcast/pytest-oct04-final-delivery.xml) ghi **3049 passed**, không fail/error/skip, một cảnh báo dependency đã biết, thời gian console **120,98 giây**; test cục bộ không thay nghiệm thu delivery hay chất lượng giọng.

Input tốc độ tại `/connections` đổi riêng `step` từ `0.05` sang `0.01`, giữ khoảng `0.5–2.0` và khóa series hiện có. [QA audio từng cảnh task 15](../storage/pottery-three-characters/podcast90-task15-per-scene-pcm-qa.json) đo cảnh 7 dài **8,08 giây** ở speed 1, vượt slot 8 giây; bước nhập cũ chặn giá trị 1.02 bằng HTML validation trước POST và buộc thử 1.05. Backend và worker đã nhận speed float liên tục, cache khóa theo giá trị speed thực, nên không cần sửa server cho bước nhập này. Frontend build đã qua. Cả speed 1.05/task 16 và speed 1.02/task 17 đã được thử; bản chọn cuối là **task 18 speed 1**, giữ audio gốc và xử lý riêng phần đuôi rất nhỏ đã đo. Các thử tốc độ vẫn được giữ làm bằng chứng, không coi là bản delivery.

### Podcast 90 giây: project 7 / output 5 đã duyệt và bàn giao

[Script hiện tại](../storage/pottery-three-characters/podcast90-script.json) có 12 cảnh: mười cảnh 8 giây và hai cảnh 5 giây, tổng 90 giây, [lời đọc](../storage/pottery-three-characters/podcast90-narration.txt) **296 tiếng**. [Review authoring](../storage/pottery-three-characters/podcast90-authoring-review.json) ghi schema/quality không có issue. Client đã duyệt **revision 14** với ghi chú review có hỗ trợ máy và tạo **project 7**, scene ID **19–30**; GET hiện tại xác nhận `approved=true`, `editorially_approved=true`, `project_id=7`. Đây là trạng thái duyệt kỹ thuật/biên tập đã lưu, không phải xác nhận người dùng nghe toàn bộ giọng hay duyệt delivery.

Project 5/revision 8 được giữ như **draft cũ đã được thay bằng deliverable mới này**; không coi việc hoàn tất draft đó là đầu việc bàn giao riêng nữa. Project 6/output 4 vẫn là video im lặng 30 giây đã giao. Project 7 dùng các bản sao media **31–34** cho bốn cảnh đầu từ clip gốc **15/26/28/30**; clip/project cũ được giữ nguyên. **Đủ 12 visuals đã được Client duyệt**, theo thứ tự media **31/32/33/34/36/38/40/42/44/46/48/51**. Chín operation Flow đã `succeeded`: tám cảnh mới và một lượt tạo lại cảnh 12. [Media 50 bị loại](../storage/pottery-three-characters/podcast90-scene12-first-rejection.json) vì overlay chữ Binh ngoài prompt, đã archive; media 51 thay thế qua [QA lần hai](../storage/pottery-three-characters/podcast90-scene12-qa-v2/clip-audit.json). Reference cảnh 12 dùng **frame 119 tại 24 fps, 4,958333 giây** của phần 5 giây thực dùng cảnh 11, không dùng frame 191 tại 7,958333 giây của toàn clip 8 giây. Render đã tạo output 5, QA kỹ thuật và duyệt Client đã hoàn tất; ZIP bàn giao đã kiểm chứng.

TTS audio độc lập task **14** đã tạo full lời đọc mới: **83,31 giây**, ba segment. [Task 13](../storage/pottery-three-characters/podcast90-tts-task13.json) và [QA tương ứng](../storage/pottery-three-characters/podcast90-tts-qa-live.json) thuộc lời đọc trước khi rút còn 296 tiếng, không dùng làm bằng chứng timing/chất lượng cho bản hiện tại. Task 15 speed 1 dài **79,44 giây**; task 16 speed 1.05 dài **75,65717 giây**; task 17 speed 1.02 dài **77,882375 giây**. [Đối chiếu ASR](../storage/pottery-three-characters/podcast90-task15-vs16-vs17-asr-comparison.json) ghi distance lần lượt **6/296, 22/296 và 18/296**. Chọn [task 18 speed 1](../storage/pottery-three-characters/podcast90-scene-task18-status.json), `succeeded` **12/12 cảnh**, tổng **79,44 giây**; SHA256 local xác nhận cả 12 WAV cảnh và WAV tổng **byte-identical với task 15**. Vì vậy kết quả ASR task 15 áp dụng cho cùng các byte audio task 18; đây là so sánh kỹ thuật, không phải xác nhận nghe của con người.

Chỉ cảnh 7 vượt slot **80 ms**. [QA đuôi cảnh 7](../storage/pottery-three-characters/podcast90-task15-scene7-tail-qa.json) đo đoạn **8,000–8,080 giây**, peak **−51,5186 dBFS**, RMS **−66,0780 dBFS**. Render source đã có guard chỉ dùng phần vừa slot khi WAV PCM16 vượt tối đa 0,10 giây và **mọi sample bị bỏ có peak không quá −50 dBFS**, kiểm tra đầy đủ byte và thời lượng; audio nguồn được giữ nguyên. **15 test tập trung** cho guard đã qua và nằm trong suite đầy đủ 3049 test. Biên độ nhỏ không bảo đảm tuyệt đối rằng đoạn đó không chứa lời. [Manifest output 5](../storage/pottery-three-characters/podcast90-output5-manifest.json) từ render thực qua Client đã ghi nhận đúng guard này: chỉ cảnh 7 dùng 8,00 giây từ nguồn 8,08 giây, peak 87 PCM16 / −51,5186 dBFS. Điều này xác nhận đường render thực đã chạy code; không thay QA thành phẩm hay chứng minh launcher mới đã áp dụng.

**Trạng thái bàn giao cuối:** visuals **12/12 đã duyệt**; audio **task 18 E speed 1**; **output 5 đã render và duyệt qua Client** bằng ba kiểm tra, [receipt trạng thái approved](../storage/pottery-three-characters/podcast90-output5-approved.json). Video **90,000 giây**, container **90,021333 giây**. Bàn giao [MP4](../storage/pottery-three-characters/chiec-bat-chua-tron-podcast-90s.mp4), [SRT](../storage/pottery-three-characters/chiec-bat-chua-tron-podcast-90s.srt) và [ZIP](../storage/pottery-three-characters/chiec-bat-chua-tron-podcast-90s-delivery.zip). [Kiểm tra độc lập audio/phụ đề](../storage/pottery-three-characters/podcast90-output5-audio-subtitle-verification.json) đạt **70/70**: hash nguồn, timing 12 cue, chỉ cảnh 7 cắt đuôi đã đo, WAV nguồn không đổi, AAC packet không gap/overlap. [Kiểm chứng ZIP](../storage/pottery-three-characters/podcast90-delivery-zip-verification.json) đạt CRC cho **6 file**, năm hash/kích thước khớp manifest và MP4/SRT trong ZIP trùng byte với file bàn giao; ZIP **17.567.709 byte**, SHA256 **d93c010c1a84a5b02f840de88aa68d1b84f4a22f2fdf9c88a2d7fc55063bad24**. [Review bàn giao](../storage/pottery-three-characters/podcast90-delivery-review.json) ghi rõ duyệt có hỗ trợ máy; chưa có xác nhận người dùng nghe toàn bộ hay nghiệm thu cảm nhận. Không có publication.

[QA hình output 5](../storage/pottery-three-characters/podcast90-qa-final/podcast90-audit.json) xác nhận **2160 frame, video 90,000 giây, 24 fps, 1280 × 720**; PTS tăng nghiêm ngặt với khoảng lớn nhất khoảng **1/24 giây**. Mười một điểm nối của bản xuất có RGB MAE **2,5661–3,203987/255**, SSIM **0,990102–0,994209**; root đã rà contact sheet và frame cuối. Các metric mô tả sai khác hình tại điểm nối, không bảo đảm cảm nhận liền mạch tuyệt đối. [Playback trình duyệt](../storage/pottery-three-characters/podcast90-browser-playback.json) chạy tốc độ 1 từ đầu tới ended **90,021333 giây**, không có media error, không có khai báo nghe thủ công. [QA audio cuối theo PTS](../storage/pottery-three-characters/final-render-audio-qa-pts.json) kiểm tra đúng 12 slot trên timeline 90 giây: **7/296 thay thế tiếng** so với **6/296** ở nguồn, không có nhóm insert/delete hay đoạn thiếu/lặp bị phát hiện, timestamp hợp lệ cả 12 cảnh, không clipping; **cảnh 7 ASR khớp đủ 26/26 tiếng**. Đây là ASR máy, không phải nghe thủ công hay xác nhận tuyệt đối mọi từ đã phát âm đúng. WAV trích theo PTS dài **90,034667 giây** do phần dư decoder AAC; QA chỉ phân tích 90 giây nominal. Timeline packet AAC không có gap/overlap; WAV decode đơn giản 90,2827 giây là padding, không phải thời lượng bản MP4. Video vẫn **90,000 giây**, container **90,021333 giây**.

### YouTube: train và mẫu kỹ thuật đã hoàn tất, giọng mới chưa duyệt

[Review text/tín hiệu](../storage/thuan-podcast/preview-audit/youtube-text-acoustic-review.json) và [bulk edits](../storage/thuan-podcast/preview-audit/youtube-text-acoustic-review-bulk.json) chọn, đánh dấu reviewed **49 clip** bằng `text_acoustic_review`, không có khai báo nghe thủ công. [Snapshot sau train](../storage/thuan-podcast/preview-audit/youtube-train-completed-state.json) xác nhận action `58fa688a-97b6-4caf-9434-bc676276c1be` `succeeded`: run **3b995b7bfd8044bc974995ed43484ea3**, **3 epochs**, checkpoint **9/9 bước**. Trạng thái `has_sample=false` tại snapshot vừa train đã được thay bằng [receipt mẫu mới](../storage/thuan-podcast/preview-audit/youtube-sample-completed-state-pair.json).

[QA mẫu](../storage/thuan-podcast/preview-audit/youtube-training-qa.json) và [ASR](../storage/thuan-podcast/preview-audit/youtube-trained-sample-asr.json) xác nhận WAV mẫu **10,16 giây**, mono PCM16 48 kHz, đủ **487680 frame**, không clipping; **36/36 tiếng** khớp sau chuẩn hóa NFC/hoa thường/dấu câu, giữ dấu tiếng Việt, word distance 0. [Mẫu nghe](../storage/thuan-podcast/preview-audit/youtube-trained-sample-temp08-seed42.wav) vẫn có profile `awaiting_review`: chưa có xác nhận nghe/duyệt giọng mới và chưa load nó thay E. ASR/số liệu âm thanh không chứng minh độ tự nhiên hay nhận diện người nói. Client đã giữ/khôi phục giọng E cho production; QA chỉ đối chiếu các hash khai báo của profile E với baseline, không tuyên bố helper đã tính lại mọi hash file remote.

### Launcher Windows: kiểm chứng cô lập, chưa áp dụng vào runtime hiện tại

[Test shutdown/launcher](../server/tests/test_server_shutdown.py) và lượt kiểm chứng cô lập ghi nhận lượt shutdown/reload cô lập **11,331 giây** với cấu hình timeout graceful 10 giây. Lệnh kết hợp restart backend và thao tác remote Chrome đã bị automatic approval review chặn; **launcher mới chưa được áp dụng vào backend đang dùng**. Reload sau sửa render từng bị treo; hiện render output 5 thực qua Client đã xác nhận code tail guard chạy. Receipt đó không xác nhận launcher timeout mới đã áp dụng. Không stop process thủ công trong đợt này. Không coi thời gian test cô lập là thời gian reload của runtime production này; đợt cập nhật tài liệu này không restart service hay sửa server.

### Các phạm vi còn cần nghiệm thu

| Chức năng | Bằng chứng hiện có | Chưa chứng minh |
|---|---|---|
| Overview / Tác vụ / Library | GET API trả 200, source và frontend build; backend test task/cancel/ownership | Mọi thao tác UI và phục hồi browser trong một lượt E2E đầy đủ |
| Script / Production | Revision 14 đã duyệt kỹ thuật, project 7 tạo; đủ 12 visuals duyệt, media 50 archive và 51 thay thế; video 30 giây output 4 đã duyệt | Nghiệm thu cảm nhận của người dùng; không có xác nhận nghe toàn bộ |
| Colab & audio | E policy; task 18 speed 1 chọn, byte-identical task 15; ASR 6/296; guard đuôi 80 ms qua 15 test | Nghe bản đầy đủ và nghiệm thu người dùng; QA kỹ thuật output 5 đã có receipt PTS/ASR |
| Voice Training | Raw-media fixtures/checksum/resume live; YouTube train 9/9 bước và mẫu 36/36 tiếng ASR | Nghe, duyệt và load giọng YouTube; dữ liệu 5 giờ và hiệu năng upload/ASR dài |
| Connections / Series / shared library | Roundtrip/snapshot/idempotency bằng test; API đọc và dữ liệu hiện có | Inference Gemini ảnh/kịch bản và Codex/tmux trên runtime thật trong đợt này |
| Legacy / adapters / export | Test persist add/remove/reorder; short-ID subtitle/CapCut; chuyển định dạng/kích thước thực bằng FFmpeg | Nghiệm thu mọi adapter với nguồn thật và toàn bộ luồng UI export |
| Windows reload | Launcher có timeout graceful và wrapper console; test cô lập 11,331s | Launcher mới chưa có receipt áp dụng runtime; output 5 chỉ xác nhận render-tail guard đã chạy thực |

[UI audit](../storage/thuan-podcast/ui-audit-oct04.json) lưu các thao tác browser đã kiểm tra và giới hạn inference provider/runtime. `run-status.json` giữ draft podcast cũ dưới ngữ cảnh đã thay thế và video 30 giây đã giao riêng; project 7/output 5 đã bàn giao với receipt kỹ thuật/Client, giọng YouTube còn chờ nghe/duyệt. Inference các provider ngoài chưa chạy và áp dụng launcher mới chưa có receipt live; không coi các giới hạn đó là podcast 90 giây còn chưa xuất.

[Receipt UI cuối](../storage/pottery-three-characters/podcast90-final-ui-receipt.json) ghi Library project 7/output 5 approved và Production hiển thị download ZIP đã duyệt; health OK, extension connected, kết nối Colab phục hồi, giọng E không đổi. Browser giữ mở tại màn hình review output.

## 10. Cải tiến ASR và phục hồi transcript ngày 04/10/2026

[Phân tích nguồn dữ liệu](../storage/thuan-podcast/preview-audit/youtube-recovery-baseline-20261004.json)
xác nhận bộ lọc thử nghiệm trước đã giữ 49/341 đoạn, 181,92/1366,31 giây. Riêng yêu
cầu hai transcript khớp nhau giữ lại chờ xử lý 210 đoạn/920,02 giây; đây không phải
bằng chứng 210 đoạn audio đều kém. Các ngưỡng độ tin cậy, thời lượng, xác suất
không lời dùng chung theo segment và sự chưa chắc chắn về tiếng Anh/chữ số làm
tập thử nhỏ thêm. Không có kiểm chứng nghe thủ công toàn bộ tập này.

Dataset mới dùng Whisper large-v3 FP16 ngay ở bước chuẩn bị; pin và checkpoint cũ giữ
model/revision/precision cũ. Bước `recover-transcripts` xử lý cả đoạn bỏ chọn, chưa duyệt hoặc
có transcript bất đồng. Lượt thử ngữ cảnh v1 đã dừng ở 73/292 đoạn: timestamp từng
từ làm mất từ đầu câu trong nhiều đề xuất. [Đối chiếu 10 clip thực](../storage/thuan-podcast/preview-audit/asr-whole-clip-experiment.json)
xác nhận cách nhận dạng nguyên clip giữ được phần đầu bị mất; 9/10 có timestamp
segment trong giới hạn clip, riêng đoạn 160 dài 2,14 giây bị ASR sinh lời subscribe
với mốc cuối 29,98 giây. Đây là lỗi cần gắn cờ, không cắt timestamp để che lỗi.

V2 nhận dạng nguyên clip bằng FP16, không dùng VAD hay ngưỡng confidence/no-speech
để tự bỏ đoạn và không cắt lời theo căn thời gian từng từ. Timestamp segment lỗi,
lời lặp và kết quả rỗng được đánh dấu; không có cảnh báo cấu trúc không đồng nghĩa
chép đúng từng từ. Đề xuất v1 được lưu riêng theo checksum khi đổi policy. Kết quả
lưu trong `recovery-proposals.json`, không thay transcript,
include/reviewed hoặc file duyệt dataset. Cache khóa theo nguồn, clip, lời đang
lưu, ngôn ngữ, thời gian, decode policy và revision model; nguồn/clip đổi thì
không dùng lại đề xuất. Đây là gợi ý cần kiểm tra, không phải xác nhận nhãn đúng.

Client có thống kê số đoạn/thời lượng, bộ lọc transcript khác nhau, chưa đối chiếu,
vấn đề âm thanh, đã duyệt và bỏ chọn. Chép gợi ý chỉ sửa bản nháp và bỏ đánh dấu đã
duyệt; không tự chọn lại đoạn. Bản nháp chặn đổi đoạn/bộ lọc/dataset, prepare,
verify và train cho đến khi lưu hoặc bỏ sửa. Tiến độ phục hồi chỉ hiện khi tác vụ
đó đang chạy. [Kiểm tra UI](../storage/thuan-podcast/preview-audit/asr-recovery-ui-checks.json)
đã xác nhận bộ lọc 292 đoạn bỏ chọn, trạng thái rỗng, chặn train/prepare và bỏ sửa
khôi phục đúng lời cũ trên dữ liệu thật.

[Suite backend đầy đủ của v2](../storage/thuan-podcast/pytest-oct04-asr-recovery-v2.xml) đạt
**3066 passed** trong 134,63 giây, không fail/error/skip; có một cảnh báo deprecation Starlette/httpx. Frontend `tsc + vite build` qua. [Receipt nâng cấp Colab v1](../storage/thuan-podcast/preview-audit/asr-recovery-install.json)
xác nhận module SHA khớp gói tải từ backend, có backup và HTTP capability mới chạy
thực. Router wrapper cũ được gỡ đúng trước khi gắn router mới; chỉ kiểm tra module
trong bộ nhớ không đủ xác nhận HTTP đã dùng phiên bản mới.

[Tác vụ GPU v1](../storage/thuan-podcast/preview-audit/asr-recovery-action-start.json)
đã được gửi qua Client và chủ động dừng ở 73/292 vì lỗi mất từ đầu câu.
Gói v2 đã được tải lại từ backend và đối chiếu byte với source. Khi chuẩn bị cập nhật
v2, Colab mất kết nối: thực thi ô trả `Failed to fetch`, tunnel worker trả HTTP 530.
V2 chưa có receipt cài đặt hoặc chạy đủ 292 đoạn trên GPU. Tập đã duyệt vẫn là
49 đoạn/181,92 giây ở lần xác minh cuối; không tính đề xuất ASR thành dữ liệu train.
Giọng E đã unload để chạy ASR; cần load lại khi runtime Colab kết nối được.
