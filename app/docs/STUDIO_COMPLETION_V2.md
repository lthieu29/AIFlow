# Bàn giao mục 1 và 2 — Xưởng sản xuất và fine-tune

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
