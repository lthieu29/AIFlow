# Xưởng kịch bản — P3, ngày 27/09/2026

**Cập nhật biên tập v2:** đã nghiên cứu nguồn chính thức, bổ sung preflight/checklist, editor từng cảnh và kiểm thử. Xem [báo cáo nghiên cứu, thay đổi và bằng chứng](SCRIPT_STUDIO_REVIEW.md).

## Phạm vi đã viết source

- Trang `/scripts`: brief, bối cảnh series, dàn ý, kịch bản chia cảnh, nhận xét, một vòng AI sửa, duyệt thủ công và chuyển sang Timeline.
- OpenRouter: key chỉ trong bộ nhớ tiến trình server; phải nhập lại khi khởi động. Nút lưu key không gọi model và không xác nhận key hợp lệ.
- Danh sách model lấy trực tiếp từ OpenRouter, chỉ nhận ID cụ thể có hậu tố `:free`, công bố mọi trường giá bằng 0 và hỗ trợ `structured_outputs`. Kiểm tra lại catalog trước mỗi inference.
- Request dùng JSON schema strict, `require_parameters=true`, `allow_fallbacks=false`, giới hạn giá prompt/completion/request/image bằng 0. Không router `auto`, không plugin tìm kiếm, không tự chuyển model hay mua credits.
- Checkpoint SQLite bất biến sau thành công; lưu nguồn, model phản hồi, usage khi được trả về, lỗi và quan hệ phiên bản. Usage thiếu được ghi `null`, không giả định bằng 0.
- Cùng request UUID không gọi lại model. Lỗi 429/timeout không tự retry. Server ngắt giữa chừng giữ checkpoint pending/running; sau 3 phút có thể đánh dấu gián đoạn, quay về checkpoint trước để thử lại có chủ ý.
- Duyệt kịch bản gồm 6 xác nhận biên tập, xác nhận cảnh báo và ghi chú quyết định; lưu hash nội dung trong `ScriptApproval`. Đề xuất `approve` từ AI không thay thế người dùng duyệt.
- Tạo project và scenes trong một transaction, gọi lại trả cùng project. Bản sửa mới cần duyệt lại. So khớp cảnh với bản đã duyệt trước khi nhận yêu cầu video và trước khi worker chạy sau thời gian chờ audio.
- Migration `0004` tạo checkpoint, `0005` tạo bảng duyệt. Bootstrap hiện tại cũng đăng ký hai bảng. Phiên bản JSON cũ vẫn đọc được; bản đã duyệt theo boolean cũ cần duyệt checklist mới trước sản xuất.

## Cách dùng

1. Khởi động backend/UI theo quy trình hiện có. Vào **Trang chủ → Kịch bản & phiên bản**.
2. Nhập tên tập, ý tưởng, khán giả, tone, lời hứa với người xem, ràng buộc, bối cảnh/nhân vật và thời lượng 30–360 giây. Chọn nhịp đọc dự kiến 100–180 từ/phút (mặc định 135, chưa đo TTS). **Lưu brief** không gọi AI.
3. Mở **Nguồn AI**, nhập OpenRouter key, lưu cho phiên này rồi tải model miễn phí. Nếu không có model đủ điều kiện, dùng nhánh nhập thủ công.
4. Chọn model và bấm **AI: Dàn ý**, tiếp theo **AI: Kịch bản**. Mỗi nút gọi đúng một bước; không tự chạy tiếp hoặc bật Colab.
5. Đọc từng cảnh và lời dẫn. Có thể gọi **AI: Nhận xét**, sau đó **AI: Bản AI sửa**. Mỗi nhánh lịch sử tối đa một bước `revise`; sau đó sửa tay nếu cần.
6. Mở **Sửa từng cảnh trực tiếp**: chọn cảnh, sửa lời dẫn/hình ảnh/vai trò/thời lượng, thêm/bỏ/đổi thứ tự. **Lưu bản sửa mới** giữ bản gốc. JSON nâng cao vẫn dùng được. Lưu trước khi rời trang; bản chỉnh chưa lưu chỉ nằm trong bộ nhớ trình duyệt.
7. Đọc **Kiểm tra trước sản xuất**, sửa các lỗi chặn, đọc thử thành tiếng, xác nhận 6 mục và các cảnh báo còn lại. **Duyệt phiên bản**, chọn tỉ lệ rồi **Tạo dự án**. Mặc định dùng `cinematic-thriller`, tiếng Anh và giọng `af_heart`; chưa phát sinh tác vụ audio/video ở nút này.
8. Tại Timeline, bước tạo video tiếp tục dùng hàng đợi audio từ P2. Khi cần giọng đọc, bật Colab và nhập URL/token ở trang Kết nối.

### Nhập thủ công, kể cả kết quả từ Codex

- Ở checkpoint, chọn **Tải prompt để làm thủ công**. File chứa toàn bộ ngữ cảnh và JSON schema của bước tiếp theo.
- Tự thực hiện trong công cụ/tài khoản bạn lựa chọn, rồi dán JSON vào phần nhập, chọn đúng loại **… từ prompt** và lưu.
- Có thể nhập trực tiếp kịch bản hoàn chỉnh vào một brief bằng loại **Kịch bản sửa tay**. Mẫu trong ô nhập chỉ có một cảnh để minh họa, không phải kịch bản 4–6 phút đã hoàn chỉnh.
- Nguồn bản nhập được ghi `manual`; AIFlow không tự nhận là kết quả Codex đã được xác minh và không xác minh chi phí của thao tác ngoài ứng dụng.
- Bối cảnh series được lưu cùng brief và truyền vào các bước con. Dùng **Chép brief để chỉnh / tạo tập mới**, cập nhật ý tưởng và các trạng thái nhân vật sau tập trước. Chưa có kho series bible dùng chung tự đồng bộ.

## Khôi phục và các giới hạn

- Lỗi request phía trình duyệt: xem Lịch sử trước khi bấm lại; kết quả có thể đã được lưu dù mất phản hồi HTTP.
- Hết quota: đợi và chọn checkpoint cha để gọi lại, không bấm liên tiếp. Không có hàng đợi tự thử lại.
- Sau restart, key mất; checkpoint và kết quả vẫn còn. Tác vụ gián đoạn không tự tiếp tục inference.
- Trang lịch sử hiển thị 300 checkpoint gần nhất; database giữ toàn bộ. Chưa có phân trang/tìm kiếm cho thư viện lớn.
- Sửa cảnh trong Timeline làm nó khác bản duyệt sẽ chặn generation. Hiện cần chuyển phần sửa về JSON trong Xưởng kịch bản, lưu/duyệt bản mới và tạo project mới; chưa có nút đồng bộ ngược Timeline → kịch bản.
- Project không xuất phát từ Xưởng kịch bản giữ workflow cũ. Project liên kết với checkpoint của Xưởng cần bản duyệt checklist v2 hợp lệ.
- Preflight đối chiếu tổng thời lượng và ước tính lời đọc 4–8 giây/cảnh. Đây là quy tắc biên tập có ngưỡng minh bạch, không phải phép đo TTS hay dự đoán độ hay/retention.
- Codex đã có luồng **CAO/tmux trong WSL**; chỉ bật sau kiểm tra đăng nhập ChatGPT và xác nhận điều kiện credits. Xem [cài đặt và giới hạn](CODEX_TMUX.md). Không gọi `codex exec`, không chuyển API key, không cam kết tmux tự khóa chi phí bổ sung.
- Gemini cũ vẫn là tùy chọn ở các adapter cũ. Xưởng kịch bản mới chưa bật Gemini, không tự fallback sang nó.
- P4–P6 (pipeline media hoàn chỉnh, ngách chân dung thú cưng, website thương hiệu cá nhân và các phần bàn giao tương ứng) chưa thuộc mốc source này.

## Ngữ cảnh UX và bản đồ triển khai

- Actor: chủ dự án cá nhân; mục tiêu: một script tiếng Anh được duyệt, chuyển được thành project.
- Grammar `operations-console`, adapter `product-ui`: lịch sử bên trái, nội dung/quyết định của checkpoint bên phải; giao diện nhỏ xếp thành một cột.
- Luồng: `/scripts` → brief → outline → script → review → [revise tối đa 1] → người dùng duyệt → Timeline.
- Nhánh lỗi: checkpoint lỗi → checkpoint cha → thử lại có chủ ý; không mất phiên bản trước. Nhánh thủ công dùng cùng schema và lịch sử.
- Global navigation: Trang chủ / Dự án / Colab. Local navigation: checkpoint cha và lịch sử. Deep link: `/scripts?revision=<id>`. Rời trang không hủy request server đang xử lý.
- Trạng thái: loading, trống, chưa nhập key, không có model miễn phí, pending/running, lỗi, thành công, đã duyệt; lỗi có `role=alert`, tiến độ có vùng thông báo, ô nhập có nhãn.
- Backend: `server/text/`, API scripts, models `ScriptRevision`/`ScriptApproval`, migrations `0004`/`0005`.
- Frontend: `ScriptStudio.tsx`, `ScriptQuality.tsx`, `ScriptSceneEditor.tsx`, `ScriptEditorialContent.tsx`. Kế thừa token màu/nút/ô nhập hiện có.

## Kiểm tra đã thực hiện và còn lại

35 kiểm thử offline qua (SQLite tạm, provider giả lập), bao gồm workflow AI đầy đủ, idempotency, quota/lỗi, schema, chất lượng, duyệt, migration lặp, hash nội dung và so khớp cảnh. Ruff nhóm F qua; `npm run build` đầy đủ qua sau khi bỏ import `btnDanger` thừa đang chặn build.

Chromium đã chạy React thực + API thật với database tạm qua luồng sửa cảnh → lưu bản mới → checklist → duyệt → tạo project. Viewport 1440×1000 và 390×844; không lỗi JavaScript trong luồng kiểm tra, không tràn ngang mobile. Ảnh ở `storage/verification/script-studio/`. Catalog OpenRouter công khai đã được gọi, thấy 4 model hợp bộ lọc tại ngày kiểm tra; danh sách có thể đổi.

Chưa chạy inference bằng tài khoản thật, TTS/Colab, migration database thật hoặc xuất video hoàn chỉnh. Chưa có bằng chứng so sánh chất lượng văn chương giữa các model. Cảnh báo deprecation Starlette/httpx trong môi trường test không làm test thất bại.

GitNexus được refresh và gọi impact trước sửa. Schema có cảnh báo CRITICAL với đồ thị mở rộng sang nhiều project tham khảo; một số symbol khác UNKNOWN. Đã báo trước và đối chiếu source trực tiếp, kiểm thử đường liên quan; không coi thiếu cạnh là bằng chứng an toàn.

## Tài liệu dịch vụ đã đối chiếu

- [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection): `max_price`, `require_parameters`, `allow_fallbacks`.
- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs): JSON schema và giới hạn model hỗ trợ.
- [Codex pricing](https://learn.chatgpt.com/docs/pricing): sau hạn mức bao gồm, credits khả dụng có thể dùng để tiếp tục. Vì vậy ChatGPT auth không tự chứng minh chỉ dùng quota subscription.
