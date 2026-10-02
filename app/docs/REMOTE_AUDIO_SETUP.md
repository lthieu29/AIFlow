# Bàn giao P0–P2: audio từ xa và nhập URL Colab

Ngày: 27/09/2026. Đây là trạng thái thi công mã nguồn, không phải chứng nhận đã chạy thành công trên Colab.

## Cách mở

Chạy backend/UI theo quy trình sẵn có của dự án. Với môi trường đã cài dependency:

```powershell
cd D:\Project\AIFlow\app
python -m server.main
```

Trong terminal khác:

```powershell
cd D:\Project\AIFlow\app\ui
npm run dev
```

Mở địa chỉ Vite in ra, vào **Colab & giọng đọc** (`/connections`). Không cần domain hay API key Gemini để khởi động phần audio. Chạy đúng một backend process; khóa OS ngăn hai scheduler nhận việc đồng thời.

## Lần đầu dùng Colab

1. Tải **notebook** và **gói worker** ngay trên trang kết nối.
2. Mở Colab, tải notebook lên, chọn GPU.
3. Chạy phần setup, mount Drive và nạp Kokoro. Model chỉ tải trong Colab.
4. Chạy phần API nếu phù hợp điều khoản dịch vụ. Dán URL `https://....trycloudflare.com` và token từ notebook.
5. **Kiểm tra kết nối** chỉ đọc health/voices, không tạo audio.
6. Lưu kết nối. Chọn tác vụ chờ rồi **Tiếp tục**, hoặc chọn trước và **Lưu và tiếp tục**.
7. Khi audio xong, tải WAV/nghe trực tiếp. Sau khi hết việc, Disconnect and delete runtime trong Colab.

URL/token đổi thì kiểm tra và lưu lại. Token chỉ giữ trong bộ nhớ backend; sau khi restart backend cần nhập token lại. URL cuối và profile model/voice được lưu để có thể dùng cache khi Colab tắt.

## Tạo giọng và nối vào project

- Nhập lời đọc tiếng Anh riêng hoặc chọn project đã có narration lưu trong Timeline.
- Chọn giọng từ catalog worker, tốc độ; tạo tác vụ.
- Tác vụ thiếu kết nối được giữ trong SQLite, không thất bại ngay.
- Lựa chọn project sẽ lưu voice/language trên project và chụp snapshot narration/scene order.
- Kết quả chia đoạn lưu ngay vào cache; khi đủ mới ghép WAV và gắn audio vào scene.
- Nếu sửa narration/voice sau khi đã tạo task, task cũ cần xử lý và không được gắn thành phiên bản mới. Tạo task mới; đoạn trùng input có thể tái sử dụng cache.
- Nhấn Tạo video ở Timeline sẽ tạo job audio trước nếu có narration. Khi audio đầy đủ, job video đã được người dùng khởi chạy mới được tiếp tục.
- Đây chưa phải bản sửa toàn bộ pipeline video: hạn chế start image, quality gate và timing đã ghi ở kế hoạch P4 còn cần xử lý. Không coi audio hoàn thành là video đã hoàn thành.

## Khi tunnel không dùng được

1. Trong notebook, lấy JSON profile không chứa token sau bước nạp model.
2. Trong AIFlow, mở **Dùng batch khi không có tunnel**, dán profile và lưu.
3. Tạo task, **Xuất batch JSON**, upload JSON vào cell Batch.
4. Notebook chạy và cho tải ZIP; **Nhập ZIP kết quả** vào task tương ứng trong AIFlow.
5. App kiểm tra key/checksum, chỉ dùng file WAV thuộc task, rồi ghép audio.

Đường batch không cần công khai API, không cần domain. Không có cách né quota/keep-alive trong notebook.

## Lưu dữ liệu / phục hồi

| Dữ liệu | Vị trí |
|---|---|
| Queue + snapshot | Bảng `audiotask` trong `storage/projects.db` |
| Profile không secret | `storage/audio-connection.json` |
| Cache WAV + SHA256 | `storage/audio/cache/` |
| Audio ghép từng task/scene | `storage/audio/tasks/` |
| Backup DB trước nâng cấp | `storage/backups/before-remote-audio-*.db` |
| Checkpoint remote | `MyDrive/AIFlow/audio-worker/jobs/` |

Schema nâng cấp theo cơ chế additive hiện có lúc startup; thêm revision Alembic `0003` cho luồng migration. Không chạy migration trên DB người dùng trong phiên thi công. Startup tự backup bằng SQLite backup API trước khi thêm trường audio đầu tiên.

- Restart backend: task audio đang chạy chuyển sang chờ thao tác; cache vẫn dùng được. Tác vụ video đã vào `running` không tự replay để tránh tiêu thêm credit.
- Mất response submit: gửi lại cùng key, worker tra manifest và không tạo bản inference mới khi job còn chạy/đã xong.
- Đổi runtime: giữ nguyên Drive và model revision để nhận lại kết quả. Đổi model revision thì tạo task mới hoặc dùng lại revision đã khóa.
- Hủy: không gửi thêm đoạn mới; nếu remote đang xử lý thì chờ xác nhận hủy tại ranh giới chunk. Hủy khi mất kết nối có thể chờ tới khi nhập lại kết nối.
- Cache là dữ liệu sản xuất, không xóa cùng cache trình duyệt. Không xóa file Drive trước khi tải và xác nhận kết quả local.

## Phần đã thay đổi

- Provider TTS chính chỉ còn remote, giá trị cấu hình cũ được chuyển sang remote; không fallback VieNeu/Edge.
- VieNeu constructor bị chặn, Whisper local không suy luận; bỏ `faster-whisper`/Edge khỏi extra audio local.
- Worker Colab Kokoro, API có token, job bền vững, hash idempotency, checksum và batch.
- Trang kết nối/hàng đợi, tải notebook/bundle, trạng thái chờ/tiếp tục/hủy, nghe và tải audio.
- Đường nghe thử cũ của Timeline dùng queue mới.
- Voice/language project được lưu; auto-continue generation sau bước audio.

## Giới hạn và việc chưa hoàn thành

- Worker v1 chỉ TTS tiếng Anh. STT từ xa, tiếng Việt/OmniVoice và clone giọng chưa triển khai. Phụ đề tự động từ Whisper local đã tắt.
- Chưa triển khai text provider Codex/OpenRouter (P3), các sửa pipeline hai ngách (P4), toàn bộ redesign quản lý (P5), website cá nhân (P6).
- Chưa truy cập Colab/billing của người dùng; chưa khẳng định tunnel phù hợp mọi tài khoản hoặc hoạt động ổn định.
- Chưa chạy inference, migration trên DB thật, unit/integration tests hoặc nghiệm thu UI trong trình duyệt.
- Đã kiểm tra cú pháp Python/notebook, lint F trên module mới. TypeScript mặc định vướng import `btnDanger` dư có sẵn tại `ui/src/pages/Timeline.tsx`; kiểm tra với `--noUnusedLocals false` không báo lỗi kiểu. Không sửa import cũ ngoài phạm vi.

## Mốc nghiệm thu còn cần thực hiện

Chạy một đoạn tiếng Anh, nhận WAV; ngắt tunnel giữa hai đoạn rồi đổi URL/resume; restart backend; gửi sai token; hủy job; đổi script giữa lúc chạy; xuất/nhập một batch. Chỉ đánh dấu P1/P2 nghiệm thu sau khi có kết quả thực, không dựa vào lint/typecheck.


## Cập nhật hoàn thiện plan: STT tùy chọn

Notebook có `ENABLE_STT = False`. Bật khi cần phụ đề nhận dạng en/vi, chờ queue rảnh rồi nạp model GPU trên Colab. Kiểm tra/lưu lại kết nối sau khi bật. TTS Kokoro vẫn chỉ tiếng Anh; STT không bổ sung giọng đọc tiếng Việt. Chọn chế độ phụ đề trong `/production`. Xem [bàn giao production](PRODUCTION_HANDOVER.md) cho hợp đồng, giới hạn và phần chưa nghiệm thu live.
