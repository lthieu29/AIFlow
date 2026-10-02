# Rà soát và tối ưu Xưởng kịch bản — 27/09/2026

## 1. Kết luận

Bản đầu mới bảo đảm hình dạng JSON và lịch sử. Để phục vụ video tốt, cần phân biệt ba lớp: **ý tưởng/cấu trúc truyện**, **bản lời dẫn và hình ảnh có thể dựng**, **duyệt biên tập và kiểm tra kỹ thuật**. Đợt này đã triển khai cả ba lớp trong phạm vi Xưởng kịch bản; chưa tuyên bố AI tạo ra truyện hay hơn khi chưa so sánh đầu ra model thật.

Không dùng điểm tổng “chất lượng 90/100” vì số đó dễ che lỗi nghiêm trọng và không có cơ sở dự báo retention. Giao diện hiển thị lỗi, cảnh báo và nhận xét có dẫn chứng theo từng tiêu chí.

## 2. Nguồn và cách áp dụng

| Nguồn chính thức | Điều rút ra | Đã áp dụng |
|---|---|---|
| [YouTube: audience retention](https://support.google.com/youtube/answer/9314415?hl=en) | Đọc hành vi 30 giây đầu; mở đầu nên khớp kỳ vọng từ tiêu đề/thumbnail; phần hấp dẫn ở cuối có thể cần được gợi sớm hơn. Spike cũng có thể do khó hiểu, không luôn là tốt. | Brief có viewer promise; outline có hook; prompt/review đối chiếu lời hứa với mở đầu. Không đặt tỷ lệ retention “chuẩn” chung cho mọi kênh. |
| [BBC: screenplay format](https://downloads.bbc.co.uk/writersroom/scripts/screenplay.pdf) | Viết hành động thể hiện được trên màn hình; giữ cách gọi tên nhân vật nhất quán. | Tách lời dẫn khỏi visual prompt; review continuity; yêu cầu cảnh mô tả bằng chứng/hành động, không chỉ suy nghĩ vô hình. |
| [Google DeepMind: Veo prompt guide](https://deepmind.google/models/veo/prompt-guide/) | Mô tả framing/motion, style, ánh sáng, ngoại hình nhân vật, nơi chốn và hành động để điều khiển cảnh rõ hơn. | Prompt mỗi shot tự đủ ngữ cảnh, lặp chi tiết nhận diện cần thiết; một hành động chính, một bố trí máy quay. Không giả định text prompt bảo đảm giữ khuôn mặt; reference assets là công việc pipeline tiếp theo. |
| [Google Cloud: Veo 3.1 prompting](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1/) | Khung mô tả gồm cinematography, subject, action, context, style/ambiance. | Dùng khung này làm hướng dẫn viết visual prompt; không suy diễn rằng project đã tích hợp đầy đủ khả năng Vertex/Veo từ bài viết. |
| [OpenRouter: structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs) | JSON schema cần endpoint có hỗ trợ; hỗ trợ có thể khác giữa các provider của cùng model. | Giữ `require_parameters`, strict schema, lọc catalog và kiểm tra giá mỗi lần gọi; validate bằng Pydantic. JSON đúng không được coi là câu chuyện tốt. |

Các lựa chọn như 135 từ/phút, 0,35 giây nghỉ, dung sai 10%, một vòng sửa, bảy tiêu chí review là **quyết định thiết kế của AIFlow**, không phải tiêu chuẩn bắt buộc của các nguồn trên. Cần điều chỉnh theo dữ liệu TTS và biên tập thực tế sau này.

## 3. Luồng biên tập mới

### Brief

- Khán giả cụ thể, tone, ý tưởng, câu hỏi/lời hứa với người xem.
- Những điều phải giữ/cần tránh; bible về nhân vật, ngoại hình, đạo cụ, nơi chốn, quy tắc thế giới.
- Thời lượng 30–360 giây; nhịp đọc dự kiến 100–180 từ/phút.
- Chép brief để sửa/tạo tập mới mà không thay lịch sử cũ. Cần cập nhật bible với trạng thái cuối tập trước; chưa có tự đồng bộ canon.

### Outline trước khi chia shot

- Logline: nhân vật, mục tiêu, trở ngại và cái giá nếu thất bại.
- Hook khơi câu hỏi cụ thể, không chỉ câu giật gân chung chung.
- Các nhịp truyện có quan hệ nhân quả và dự kiến thời gian. Một nhịp truyện có thể gồm nhiều shot; không nhồi toàn bộ biến cố vào một clip 8 giây.
- Clue ledger: manh mối được gieo ở đâu, được hiểu lại/payoff thế nào. Kết thúc không cứu truyện bằng một thông tin xuất hiện đột ngột.

### Script

- Mỗi shot 4–8 giây: một hành động chính và một góc/bố trí máy quay nhất quán.
- Visual prompt tự mô tả chủ thể, nhận diện, hành động, nơi/thời gian và ánh sáng/style; không chỉ ghi “giống cảnh trước”.
- Lời dẫn là văn nói tự nhiên; bổ sung ý nghĩa thay vì đọc lại tất cả những gì hình ảnh đã thể hiện.
- Cho phép cảnh không lời có chủ ý. Không gửi lời dẫn để model video tự nói lại hoặc sinh phụ đề lên hình.
- `story_beat` và `purpose` giúp người biên tập hỏi “bỏ cảnh này thì mất thông tin/quyết định/cảm xúc gì?”. Nhãn hook/payoff chỉ là ghi chú, không chứng minh cảnh đã làm tốt nhiệm vụ đó.

### Review

Bảy tiêu chí: hook, nhân quả, nhất quán, payoff, khả năng đọc thành tiếng, khả năng dựng hình, tính nguyên bản. Mỗi mục có pass/revise/uncertain, số cảnh, dẫn chứng và hướng sửa. Không dùng “looks good” chung chung. AI không có cơ sở dữ liệu đối chiếu toàn bộ tác phẩm, nên prompt yêu cầu tính nguyên bản ở trạng thái chưa xác minh.

Review chỉ nhận bản script mới nhất cùng brief/outline liên quan và preflight; không nhét mọi bản cũ vào context khiến AI trộn những sự kiện đã bị thay. Sửa tối đa một vòng trên mỗi nhánh, trả về bản đầy đủ. Nếu cần chỉnh tiếp, dùng editor thủ công.

## 4. Quy tắc preflight có thể kiểm tra

| Quy tắc | Xử lý |
|---|---|
| Tổng thời lượng lệch mục tiêu hơn `max(8 giây, 10% mục tiêu)` | Chặn duyệt; sửa tổng thời lượng hoặc tạo brief mới phù hợp |
| `ước tính lời đọc = số từ × 60 / WPM + 0,35s` với cảnh có lời | Làm số tham chiếu; cảnh không lời = 0 |
| Ước tính vượt thời lượng cảnh trên 35% | Chặn duyệt, rút lời/chia cảnh |
| Ước tính vượt thời lượng nhưng chưa quá 35% | Cảnh báo, cần đọc thử/TTS |
| Câu trên 25 từ, lời/prompt lặp, prompt quá ngắn, thiếu purpose/hook/payoff | Cảnh báo cụ thể và số cảnh; người dùng có thể xác nhận lựa chọn có chủ ý |
| NaN/infinity, duration ngoài 4–8s, chuỗi bắt buộc rỗng | Từ chối dữ liệu |

Không tự khẳng định tiếng Anh tự nhiên, hook hấp dẫn, manh mối công bằng hoặc nhân vật nhất quán chỉ bằng regex. Những phần đó cần review có dẫn chứng và con người đọc lại.

## 5. Duyệt và phục hồi

- Sáu mục bắt buộc: hook/lời hứa; nhân quả/payoff; continuity; đã đọc thành tiếng; dựng hình; nguyên bản.
- Lỗi chặn phải sửa; cảnh báo còn lại phải được xác nhận. Ghi chú quyết định được lưu cùng bản duyệt.
- Approval lưu hash nội dung, phiên bản quy tắc, checklist, cảnh báo, ghi chú và thời điểm. Bản chỉnh mới không kế thừa duyệt.
- Dữ liệu cũ vẫn đọc được. Dấu duyệt boolean cũ chưa đủ điều kiện; người dùng duyệt lại theo checklist v2 trước sản xuất.
- Sinh/tải model không tự retry hoặc chuyển trả phí; lỗi nhà cung cấp lưu trạng thái thất bại mà không lộ exception chứa secret.
- Request UUID trùng nhưng nội dung/stage khác bị chặn; kết quả trả muộn không hồi sinh một checkpoint đã bị đánh dấu gián đoạn.
- Đã sửa lỗi validation có `ValueError` trong context: trả 422 sạch thay vì lỗi serialize 500.

## 6. Bằng chứng kiểm tra

### Offline

`python -m pytest server/tests/test_script_studio.py -q`: **35 passed**.

Bao phủ schema cũ/mới, số không hữu hạn, silent shot, thời lượng/lời quá tải, lời lặp, checklist/cảnh báo, hash bị sửa, project bị đổi cảnh, idempotency, quota/response hỏng/không retry, exception không lộ secret, kết quả muộn, context mới nhất, giới hạn một vòng sửa, toàn bộ workflow AI với provider giả lập và migration 0005 chạy lặp trên database tạm.

### UI và build

- `npm run build`: qua TypeScript và Vite. Bỏ một import `btnDanger` không dùng trong Timeline để gỡ lỗi build có sẵn.
- Ruff nhóm F trên phần Python mới/sửa: qua.
- `python -m server.tests.browser_script_studio`: Chromium, React thật/API scripts thật, SQLite tạm, không gọi inference. Luồng sửa cảnh → lưu bản mới → preflight → checklist → duyệt → tạo project qua.
- Viewport desktop 1440×1000 và mobile 390×844: không lỗi JavaScript trong flow kiểm tra, không tràn ngang mobile. Đã xem ảnh chụp. Editor chỉ mở một cảnh tại một thời điểm để không kéo dài hàng chục biểu mẫu.
- Ảnh: `storage/verification/script-studio/desktop.png`, `mobile.png`.
- Có cảnh báo deprecation Starlette/httpx trong môi trường kiểm thử; không có test thất bại.

### Catalog thật, không inference

GET catalog OpenRouter công khai tại 27/09/2026 qua bộ lọc hiện có cho 4 ID: `qwen/qwen3.8-27b:free`, `dots-studio/dots-3-note-preview:free`, `liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3-super-120b-a12b:free`. Đây chỉ là ảnh chụp tính khả dụng/metadata, không phải xếp hạng chất lượng; runtime luôn kiểm tra lại.

## 7. Phần chưa được chứng minh

- Chưa chạy inference bằng key thật; chưa so sánh chất lượng truyện hoặc tỷ lệ JSON thành công của bốn model.
- Chưa đo TTS cho từng câu, dựng media hay kiểm tra retention video đã xuất bản.
- Chưa nâng cấp database thật. Khởi động lại backend theo quy trình hiện có để bootstrap thêm bảng approval; Alembic có migration 0005 tương ứng.
- Kiểm thử trình duyệt dùng API trong tiến trình test, chưa kiểm chứng reverse proxy/deployment hoặc toàn bộ phần Timeline sau khi chuyển trang.

Đề xuất đánh giá model khi có dữ liệu thật: dùng cùng 4 brief (mystery một địa điểm, truyện có vật chứng, tập tiếp nối series, bản ngắn), cùng runtime và rubric; so bản ẩn tên model theo hook, tính nhân quả, continuity, payoff và công sửa thực tế. Ghi số scene phải viết lại, lỗi thời lượng, lỗi schema/quota và số lần gọi. Không chọn model chỉ theo kích thước hoặc lời tự đánh giá của nó.
