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

- **Đầu vào**: kịch bản thủ công, prompt văn bản, ảnh khởi đầu,
  hoặc — thông qua các content adapter — ảnh sản phẩm, bài viết, tài liệu,
  RSS, v.v.
- **Đầu ra**: một file MP4 do Veo 3 tạo ra, tải về thư mục `storage/output/`.

Với giao diện Flow hiện tại, luồng tạo clip là:

```
kịch bản đã duyệt → Client → BE → extension điều khiển UI Flow → nhận MP4 vào cảnh
```

Extension có luồng điều khiển composer hiện tại: chọn Veo 3.1 Lite / 720p / 8 giây,
điền prompt và bấm nút tạo của trang. Luồng UI được kiểm tra riêng với RPC và không
can thiệp captcha; có yêu cầu xác minh người dùng thì dừng. Một clip đã được kiểm tra
thật qua Client → BE → extension → Flow Lite → polling → MP4 (8 giây, 1280×720, 24 fps).
Luồng ảnh tham chiếu Thành phần cũng đã chạy đủ chuỗi này: PNG đã duyệt → upload/chọn
đúng asset SHA qua extension → clip cảnh 3; kiểm tra bốn khung hình giữ đúng nhân vật,
áo kem, áo ngoài olive và túi nâu. Kết quả này xác nhận clip đã thử, từng cảnh tiếp theo
vẫn cần duyệt người/trang phục và chất lượng.
Nhánh CLI image-to-video
cũ chưa được xác minh end-to-end với phiên Flow mới.

---

## Cách hoạt động

```
┌──────────────┐   HTTP :8101 / WS :9223   ┌─────────────────────┐
│ Chrome +     │ <───────────────────────> │  AIFlow server      │
│ extension    │                            │  (FastAPI, Python)  │
│ AIFlow Bridge│  UI / RPC trong phiên trang│                     │
└──────┬───────┘  flow.google.com           │  - Flow SDK (Veo3)  │
       │                                     │  - Gemini client   │
       ▼                                     │  - TTS / Whisper    │
┌──────────────┐                             │  - Adapters        │
│ Google Flow  │   kiểm tra / nhận kết quả   │  - SQLite + storage│
│ (Veo 3)      │ <───────────────────────────┤                    │
└──────────────┘                             └─────────────────────┘
```

1. **Server** chạy cục bộ tại `127.0.0.1:8101` (HTTP) và `:9223` (WebSocket).
2. **Extension Chrome** ("AIFlow Bridge") kết nối tới WebSocket và đọc dự án Flow đang
   mở. RPC mới chạy trong trang đã đăng nhập; CSRF và captcha ở lại trong trang.
3. Extension điền prompt và bấm điều khiển tạo video của Flow; lấy media ID từ phản hồi
   khớp đúng prompt/dự án rồi nhận MP4. Tạo video dùng credit của tài khoản đang đăng nhập.
   Nhánh REST cũ tiếp tục hỗ trợ phiên có Bearer token.

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

### Lớp đồ họa HTML/GSAP

Sau khi cài nhóm `[visual]`, chạy từ thư mục `app` trong môi trường ảo:

```powershell
python -c "from server.render.visual_layer.gsap_bundle import get_gsap_bundle_path; print(get_gsap_bundle_path(auto_download=True))"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD "vendor/playwright"
python -m playwright install chromium --only-shell
```

GSAP 3.12.5 nằm trong `vendor/visual_layer`. Renderer tự tìm Chromium đúng revision
trong `vendor/playwright` khi chưa đặt `PLAYWRIGHT_BROWSERS_PATH`; nếu đã đặt biến này,
renderer giữ nguyên lựa chọn đó. Khi nâng Playwright, chạy lại lệnh cài Chromium để
có revision tương ứng. Các binary này chỉ phục vụ dựng đồ họa, không đóng hoặc dùng
lại cửa sổ Google Flow đang đăng nhập.

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

Server chờ tối đa 10 giây để hoàn tất HTTP request khi dừng hoặc reload; sau đó
hủy request còn mở (như SSE) và chạy shutdown của ứng dụng. Khi chạy trực tiếp
bằng Uvicorn, dùng cùng giới hạn để tránh reload chờ kết nối SSE kéo dài:

```powershell
python scripts/dev_server.py --host 127.0.0.1 --port 8101 --reload --reload-dir server
```

Launcher này mặc định giới hạn shutdown HTTP là 10 giây và nhận các tham số CLI
Uvicorn thông thường. Trên Windows khi redirect stdout, nó giữ thao tác ghi console
mà supervisor Uvicorn dùng để đánh thức xử lý Ctrl+C trước reload. Khi chạy nền,
dùng `Start-Process -WindowStyle Hidden` để giữ console ẩn cho cơ chế này.

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

### Nhập kịch bản thủ công trong giao diện

Ở trang **Kịch bản & phiên bản** (`/scripts`), chọn **Nhập kịch bản thủ công**.
Nhập tên tập, ngôn ngữ, lời dẫn và prompt hình ảnh cho từng cảnh (4–8 giây,
tổng tối đa 360 giây), rồi bấm **Lưu kịch bản thủ công**. Bước lưu không gọi AI.
Hệ thống lưu brief và kịch bản cùng một giao dịch, kiểm tra thời lượng/lời đọc,
rồi cho phép duyệt checklist để tạo dự án trong Xưởng sản xuất. Cảnh không lời
có thể để trống lời dẫn. Việc lưu hoặc duyệt chưa tạo video; tiếp tục tạo tài
nguyên trong dự án. Xưởng sản xuất kiểm tra trang Flow trước khi gửi yêu cầu tạo.
**Tạo video Veo Lite qua Bridge** dùng extension điều khiển composer của Flow. Draft
khác hoặc reference cũ phải được xử lý trước; xác minh người dùng cần người dùng tiếp quản.
Để giữ người/trang phục giữa các cảnh, thêm PNG tối đa 5 MiB trong **Ảnh tham chiếu
xuyên suốt các cảnh**, ghi nguồn ảnh, duyệt checklist rồi chọn ảnh cho lượt tạo tiếp theo.
Backend lưu checksum và nguồn ảnh cùng lượt tạo; extension chọn đúng asset theo SHA
trong chế độ **Thành phần**, không nhận ảnh được chọn mặc định của Flow.
Clip cần được duyệt trước khi xuất. Tạo qua extension
dùng credit của tài khoản; khi đã có mã tác vụ, **Tiếp tục nhận clip** chỉ nhận kết
quả cũ, không tạo lại.

### Tạo clip bằng CLI

CLI **`gen-clip`** giữ nhánh image-to-video cũ: một ảnh khởi đầu + một prompt → một
clip Veo 3. Nhánh này chưa được xác minh với phiên Flow mới; phiên yêu cầu nút gốc
sẽ trả lỗi `FLOW_UI_GENERATION_REQUIRED` trước khi gửi yêu cầu tạo.

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

### Fine-tune giọng tiếng Việt từ WAV local hoặc YouTube

Mở `/voice-training`, tải notebook điều khiển và gói worker mới nhất, rồi chạy trên
Colab GPU và kết nối URL/token phiên về AIFlow. Trong **Gửi media local sang Colab / Drive**,
nhập tên giọng, chọn audio/video và gửi sang Drive. Hỗ trợ MP3, WAV, FLAC, M4A,
OGG, AAC, OPUS, MP4, MOV, MKV và WEBM; tối đa **2 GiB/file, 20 GiB/lượt và 5000 file**
có tên riêng. UI gửi từng phần 8 MiB; Colab xác nhận offset và SHA256 toàn file
trước khi bật bước chuẩn hóa mono 24 kHz, tách đoạn và chép lời. Gửi lại cùng lựa
chọn/tên giọng tiếp tục phần upload chưa hoàn tất; sau reload, chọn lại đúng các
file để đọc checkpoint trên Drive. Endpoint WAV cũ vẫn giữ giới hạn 32 MiB/file
và 512 MiB/bộ, không phải giới hạn của luồng media mới.

Nguồn **Audio từ YouTube · Tiếng Việt** nhận URL HTTPS của một video công khai.
Nhập tên giọng, xác nhận quyền sử dụng/cùng người nói rồi bấm **Gửi URL & tải audio
trên Colab**. Colab giữ URL/metadata/checksum trên Drive, sau đó dùng cùng bước tách
audio, chép lời và duyệt dataset. Giới hạn 3 giờ/video, 512 MiB audio và 10 phút/lượt
tải; nguồn yêu cầu đăng nhập hoặc bị chặn sẽ báo lỗi. Worker/notebook cần phiên bản
mới hỗ trợ YouTube. Tải và chép lời không tự duyệt hoặc bắt đầu huấn luyện.

Với bộ nguồn YouTube đã chọn, bấm **3. Mở / cập nhật dataset để duyệt**, sửa transcript/bỏ
đoạn không dùng rồi duyệt dataset. Sau đó bấm **4. Train phiên bản mới** để Colab
chạy LoRA và lưu run/checkpoint trên Drive. Bản train mới cần sinh mẫu, duyệt và
load riêng; không tự thay giọng TTS đang dùng.

Sau khi chép lời, kiểm tra các đoạn và khai báo cách duyệt: nghe thủ công hoặc rà
transcript cùng số liệu tín hiệu. Cách thứ hai không xác nhận đã nghe hay xác minh
người nói. Chỉ các đoạn được chọn và duyệt mới tham gia LoRA VieNeu v3 Turbo. Bước
chuẩn bị dataset mới dùng Whisper large-v3 FP16; dataset/checkpoint đã có giữ model,
revision và precision trong `asr-revision.json` (pin cũ thiếu precision dùng
`int8_float16`), không nhận dạng lại hoặc ghi đè bản sửa cũ. Bước
**Đối chiếu các đoạn được dùng bằng Whisper large-v3** nhận dạng lại nguyên clip
được chọn, lưu transcript đối chiếu riêng và không tự sửa hay duyệt lời gốc. Có
thể tiếp tục phần đối chiếu chưa hoàn tất khi bị ngắt.

Nếu có nhiều đoạn bị bỏ chọn vì ASR bất đồng, dùng **Đề xuất sửa transcript cho
đoạn cần kiểm tra**. Worker nhận dạng nguyên clip bằng Whisper large-v3 FP16,
không tự bỏ lời theo VAD/confidence và không cắt transcript theo timestamp từng từ.
Timestamp ngoài thời lượng clip, lời lặp hoặc transcript rỗng được đánh dấu để
kiểm tra. Gợi ý lưu riêng trên Drive. Bước này chạy được với cả đoạn đang bỏ chọn, giữ nguyên transcript,
lựa chọn và trạng thái duyệt đã lưu. Chạy lại tiếp tục các gợi ý còn thiếu khi
nguồn, clip, transcript, cấu hình và phiên bản model vẫn khớp. Đổi cách nhận dạng
sẽ lưu bản đề xuất cũ theo checksum trước khi tạo lại, không trộn hai cách xử lý.

Màn hình duyệt hiển thị số đoạn/thời lượng tổng, được dùng, đã duyệt và bỏ chọn;
có bộ lọc bất đồng transcript, chưa đối chiếu và vấn đề tín hiệu. Chép gợi ý vào
ô sửa chỉ tạo bản nháp chưa duyệt. Kiểm tra audio, sửa lời, chọn **Dùng đoạn này**
nếu phù hợp, khai báo cách duyệt rồi lưu. Điểm ASR thấp, từ tiếng Anh hoặc chữ số
không tự động chứng minh audio kém; gợi ý ASR cũng không tự trở thành nhãn đúng.
Worker cũ cần tải lại gói worker để có nút đề xuất phục hồi.

Bước chuẩn bị lưu checkpoint từng file; train lưu trạng thái optimizer để resume cùng
cấu hình. Dataset, model và checkpoint nằm trong `MyDrive/AIFlow/voice-training`.
Sinh mẫu sau train, nghe và duyệt giọng, rồi load và chọn **Dùng giọng đang load cho
TTS trong AIFlow**. Không cài dependency model lên backend Windows.

Tại `/production`, có thể nhập URL dự án Flow hiện có để mở/chọn đúng tab qua
backend và extension. Preflight vẫn kiểm tra khả năng tạo trước khi gửi Veo; nếu
composer không phù hợp hoặc xuất hiện xác minh người dùng, bridge dừng và không tự
gửi lại. RPC guard vẫn được giữ; khả năng điều khiển UI được kiểm tra riêng.

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
