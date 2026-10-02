# AIFlow

Công cụ tạo video AI cá nhân — kết hợp Google **Veo 3** (qua Flow), **Gemini** và **TTS** thành một pipeline.

> Chỉ dùng cá nhân. Chạy native trên Windows. Không phải dịch vụ hosting — nó chạy
> cục bộ và điều khiển phiên Google Flow (đã đăng nhập) của bạn thông qua một
> extension Chrome.

---

## Mục lục

- [AIFlow làm được gì](#aiflow-làm-được-gì)
- [Cách hoạt động](#cách-hoạt-động)
- [Yêu cầu trước khi cài](#yêu-cầu-trước-khi-cài)
- [Cài đặt](#cài-đặt)
- [Cấu hình (`.env`)](#cấu-hình-env)
- [Nạp extension Chrome](#nạp-extension-chrome)
- [Kiểm tra nhanh (smoke test)](#kiểm-tra-nhanh-smoke-test)
- [Tạo video thật](#tạo-video-thật)
- [Tính năng tùy chọn](#tính-năng-tùy-chọn)
- [Trạng thái dự án — cái gì thực sự chạy được](#trạng-thái-dự-án--cái-gì-thực-sự-chạy-được)
- [Xử lý sự cố](#xử-lý-sự-cố)

---

## AIFlow làm được gì

- **Đầu vào**: một ảnh khởi đầu + câu lệnh (prompt) văn bản (đang chạy được qua CLI),
  hoặc — thông qua các content adapter — ảnh sản phẩm, kịch bản, bài viết, tài liệu,
  RSS, v.v.
- **Đầu ra**: một file MP4 do Veo 3 tạo ra, tải về thư mục `storage/output/`.

Luồng end-to-end nhỏ nhất hiện chạy được là:

```
ảnh khởi đầu + prompt  →  Veo 3 (image-to-video)  →  poll  →  file .mp4 cuối
```

chạy bằng lệnh CLI `aiflow gen-clip`.

---

## Cách hoạt động

```
┌──────────────┐   HTTP :8101 / WS :9223   ┌─────────────────────┐
│ Chrome +     │ <───────────────────────> │  AIFlow server      │
│ extension    │                            │  (FastAPI, Python)  │
│ AIFlow Bridge│  bắt Bearer token          │                     │
└──────┬───────┘  từ labs.google            │  - Flow SDK (Veo3)  │
       │                                     │  - Gemini client   │
       ▼                                     │  - TTS / Whisper    │
┌──────────────┐                             │  - Adapters        │
│ Google Flow  │   request video đã ký       │  - SQLite + storage│
│ (Veo 3)      │ <───────────────────────────┤                    │
└──────────────┘                             └─────────────────────┘
```

1. **Server** chạy cục bộ tại `127.0.0.1:8101` (HTTP) và `:9223` (WebSocket).
2. **Extension Chrome** ("AIFlow Bridge") kết nối tới WebSocket; khi bạn mở tab Flow,
   nó bắt Bearer token của Google + giải reCAPTCHA ngay trong ngữ cảnh trang.
3. Server dùng token đó để gửi yêu cầu tạo video Veo 3 và tải kết quả về — nên bạn cần
   một **gói Flow Pro/Ultra đang hoạt động và đã đăng nhập trong Chrome**.

> Server chỉ bind vào `127.0.0.1`. API cục bộ **không có xác thực** vì nó không mở ra
> mạng. Đừng port-forward nó ra ngoài.

---

## Yêu cầu trước khi cài

| Yêu cầu | Ghi chú |
|---------|---------|
| **Python 3.12+** | Khuyến nghị 3.12 (cho TTS GPU LMDeploy nhanh). Python 3.14 chạy được mọi thứ trừ LMDeploy. |
| **Google Chrome** (hoặc Edge) | Cho extension + đăng nhập Flow. |
| **Google Flow Pro/Ultra** | $20/tháng tại [labs.google/fx/tools/flow](https://labs.google/fx/tools/flow). Bắt buộc cho Veo 3. |
| **Gemini API key** | Bản free tại [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey). |
| **FFmpeg + ffprobe** | Trên `PATH`, hoặc đặt `ffmpeg.exe`/`ffprobe.exe` vào `vendor/`. Cần cho compose/remaster, không cần cho `gen-clip`. |

---

## Cài đặt

```powershell
cd D:\Project\AIFlow\app

# 1. Tạo môi trường ảo (ưu tiên 3.12)
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
#   Nếu dùng cmd.exe thay vì PowerShell:  .venv\Scripts\activate.bat

# 2. Cài package + công cụ dev
pip install -e ".[dev]"
```

### Các nhóm phụ thuộc tùy chọn

Chỉ cài thứ bạn cần:

```powershell
pip install -e ".[audio]"      # edge-tts + faster-whisper (TTS + phụ đề)
pip install -e ".[visual]"     # Playwright (lớp overlay đồ họa)
pip install -e ".[content]"    # pypdf / python-docx / feedparser / Pillow (adapter tài liệu/feed/ảnh)
pip install -e ".[remaster]"   # yt-dlp + browser-cookie3 + gmssl (remaster Bilibili/Douyin)

# Cài tất cả cùng lúc:
pip install -e ".[dev,audio,visual,content,remaster]"
```

> `gmssl` (trong `[remaster]`) là thứ bật signing A-Bogus gốc cho Douyin.
> Nếu thiếu nó, việc tải remaster sẽ tự động fallback sang yt-dlp.

### Binary trong vendor

`aria2c.exe` đã đóng gói sẵn trong `vendor/`. FFmpeg được tìm từ `PATH` trước, rồi
mới đến `vendor/`. Để tải/kiểm tra binary:

```powershell
python scripts/download_vendor.py
```

---

## Cấu hình (`.env`)

```powershell
copy .env.example .env
notepad .env
```

Chỉ **một** giá trị bắt buộc để khởi động server:

```dotenv
AIFLOW_GEMINI_API_KEY=AIza...        # bắt buộc — server từ chối chạy nếu thiếu
AIFLOW_FLOW_PLAN=Pro                 # Pro | Ultra
```

Một vài tùy chọn hữu ích (danh sách đầy đủ + chú thích trong `.env.example`):

```dotenv
AIFLOW_LOG_LEVEL=INFO                # DEBUG để xem log chi tiết khi gỡ lỗi
AIFLOW_FLOW_DEFAULT_ASPECT=9:16      # 9:16 | 16:9
AIFLOW_TTS_PRIMARY=vieneu            # vieneu | edge_tts
```

> File `.env` đã được git bỏ qua. Tuyệt đối không commit key thật.

---

## Nạp extension Chrome

1. Mở `chrome://extensions`.
2. Bật **Chế độ nhà phát triển** (Developer mode, góc trên bên phải).
3. Bấm **Tải tiện ích đã giải nén** (Load unpacked) và chọn `D:\Project\AIFlow\app\extension`.
4. Ghim extension "AIFlow Bridge" để dễ nhìn thấy popup.

Popup hiển thị **Mất kết nối** (Disconnected) cho tới khi server chạy, rồi chuyển sang
**Đã kết nối** (Connected).

---

## Kiểm tra nhanh (smoke test)

Mở server ở một cửa sổ terminal:

```powershell
.venv\Scripts\Activate.ps1
python -m server.main
```

Bạn sẽ thấy nó khởi tạo DB và chạy trên `:8101` / `:9223`.

Trong Chrome, mở [labs.google/fx/tools/flow](https://labs.google/fx/tools/flow) và đảm
bảo đã đăng nhập. Popup extension sẽ chuyển sang **Đã kết nối** và bắt được token.

Sau đó, ở terminal thứ hai:

```powershell
.venv\Scripts\Activate.ps1

# Kiểm tra cấu hình server + khả năng kết nối Gemini (không cần Flow)
python scripts/test_gemini.py

# Nghiệm thu đầy đủ Phase 0 (config, DB, server, extension, token, Gemini, ảnh Veo3)
python server/scripts/smoke_phase0.py
```

`smoke_phase0.py` in ra bảng ✅/❌ từng mục và thoát với mã khác 0 nếu có lỗi — hãy chạy
nó trước để xác nhận luồng extension + token khỏe mạnh trước khi tạo video.

---

## Tạo video thật

Luồng end-to-end chạy được là CLI **`gen-clip`**: một ảnh khởi đầu + một prompt → một
clip Veo 3.

**Kiểm tra trước** (cả ba điều phải đúng):
1. `python -m server.main` đang chạy.
2. Tab Flow đang mở và extension hiển thị **Đã kết nối**.
3. Gói Flow Pro/Ultra của bạn đang hoạt động.

Sau đó:

```powershell
# Dùng entry point đã cài
aiflow gen-clip `
  --prompt "A serene mountain lake at sunrise, cinematic, 4K" `
  --start-image path\to\start.png `
  --output storage\output `
  --aspect 16:9 `
  --quality fast

# Hoặc chạy dạng module (tương đương):
python -m server.cli gen-clip --prompt "..." --start-image path\to\start.png
```

Các tùy chọn:

| Cờ | Mặc định | Ghi chú |
|----|----------|---------|
| `--prompt` | (bắt buộc) | Prompt văn bản cho Veo 3. |
| `--start-image` | (bắt buộc) | Đường dẫn ảnh khung đầu tiên (PNG/JPG). |
| `--output` | `storage/output/` | Thư mục đầu ra. |
| `--aspect` | `9:16` | `9:16` hoặc `16:9`. |
| `--model` | `VEO3` | `VEO3`, `VEO3_LITE`, `VEO3_QUALITY`. |
| `--quality` | `fast` | `lite` \| `fast` \| `quality`. |

CLI sẽ chờ extension + token, gửi yêu cầu, poll mỗi 5 giây (tối đa ~10 phút), rồi ghi
`video_<id>_<timestamp>.mp4` vào thư mục đầu ra và lưu job vào SQLite
(`storage/projects.db`).

**Chưa có ảnh khởi đầu?** Script này tự tạo một ảnh (PNG màu đơn sắc, không cần thư viện
ngoài), chạy toàn bộ pipeline và kiểm tra file MP4:

```powershell
python scripts/test_gen_clip.py
```

Nó tải về `storage/output/test_gen_clip_<timestamp>.mp4`. Mở bằng trình phát để xem
chuyển động/chất lượng (Veo 3 cũng tạo cả âm thanh nền).

---

## Tính năng tùy chọn

### Chuyển văn bản thành giọng nói (TTS)

```powershell
pip install -e ".[audio]"
python scripts/test_tts_smoke.py
```

Giọng mặc định là `Binh` (VieNeu, nam tiếng Việt) với `vi-VN-HoaiMyNeural` (edge-tts)
làm dự phòng. Khi server chạy, nó cung cấp `GET /api/tts/voices` và
`POST /api/tts/synthesize`.

### Remaster video (Bilibili / Douyin → phụ đề đã dịch)

```powershell
pip install -e ".[remaster]"     # yt-dlp + gmssl + browser-cookie3
```

Tải qua API gốc dùng signing chống bot thật (Douyin A-Bogus, Bilibili WBI) và tự động
fallback sang yt-dlp. Để chạy thật end-to-end cần cookie hợp lệ của nền tảng — hãy kiểm
tra offline trước:

```powershell
python server/scripts/verify_video_remaster.py --local-file path\to\video.mp4 --preset light
```

### Xuất CapCut / SRT

Khi server đang chạy và project đã có scene:

- `POST /api/projects/{id}/export/capcut` — tạo draft CapCut.
- `GET  /api/projects/{id}/export/srt` — tải phụ đề.

---

## Trạng thái dự án — cái gì thực sự chạy được

| Khả năng | Trạng thái |
|----------|------------|
| Tạo clip đơn (`aiflow gen-clip`) | ✅ Chạy được end-to-end |
| Gemini text + ảnh Veo 3 (`smoke_phase0`) | ✅ Chạy được |
| TTS (VieNeu / edge-tts) + phụ đề Whisper | ✅ Chạy được (cài `[audio]`) |
| Content adapter (parse → SceneList) qua `POST /api/content/parse` | ✅ Trả về scene |
| Signing chống bot + tải gốc Bilibili/Douyin | ✅ Đã hiện thực (`[remaster]`) |
| Xuất CapCut / SRT | ✅ Chạy được |
| **Pipeline đa-cảnh** (orchestrator: nhiều clip + continuity + compose) | ⚠️ Đã có code nhưng **chưa nối vào trigger API/CLI** |
| **Giao diện React** (`ui/`) | ⚠️ Các trang đã có nhưng luồng tạo/sinh chưa nối với backend |

Nếu bạn chỉ muốn "tạo video ngay", dùng **`gen-clip`** — đó là luồng chạy được hoàn
chỉnh. Luồng đa-cảnh có orchestrator và giao diện vẫn cần được nối thêm.

---

## Xử lý sự cố

**Server không khởi động: `AIFLOW_GEMINI_API_KEY is required`**
→ Điền key hợp lệ vào `.env`. Lấy tại aistudio.google.com/app/apikey.

**Popup extension cứ hiện "Mất kết nối"**
→ Chạy `python -m server.main` trước. Extension hỏi
`http://127.0.0.1:8101/api/ext/discovery`; nếu server chưa chạy thì nó không tìm được
cổng WebSocket.

**CLI treo ở "Waiting for Bearer token"**
→ Mở [labs.google/fx/tools/flow](https://labs.google/fx/tools/flow) trong đúng profile
Chrome đã nạp extension, và đảm bảo đã đăng nhập. Token được bắt từ request của trang đó.

**`gen-clip` báo lỗi quota / paygate**
→ Xác nhận gói Flow Pro/Ultra đang hoạt động và còn credit trong ngày.

**Tải remaster thất bại**
→ Cài `[remaster]` và đảm bảo có `ffmpeg`. Nếu không có cookie hợp lệ, video bị tường
đăng nhập sẽ bị từ chối; cung cấp cookie qua extension hoặc file cookie Netscape (xem
`AIFLOW_COOKIES_SOURCE` trong `.env`).

**Không tìm thấy FFmpeg**
→ Thêm `ffmpeg.exe`/`ffprobe.exe` vào `PATH` hoặc đặt vào `vendor/`, hoặc chạy
`python scripts/download_vendor.py`.

---

## Tài liệu

- Thiết kế + spec đầy đủ: [`docs/PLAN.md`](docs/PLAN.md) và `docs/00`–`docs/11`.
- Giấy phép bên thứ ba: [`LICENSE_NOTICES.md`](LICENSE_NOTICES.md).
- Giấy phép dùng cá nhân: [`LICENSE`](LICENSE).
