# Rà soát logic và mapping trong AIFlow/app

**Ngày:** 29/09/2026  
**Phạm vi:** `D:\Project\AIFlow\app` — UI, API, adapter, DB, pipeline, remote audio, render/export và các điểm nối với Studio.  
**Mốc mã nguồn:** HEAD `2fe36f3`, cộng toàn bộ thay đổi đang có trong working tree, kể cả các file mới chưa được Git theo dõi. Đây không phải báo cáo chỉ dành cho phiên bản đã commit.  
**Thao tác:** đọc mã nguồn, build, kiểm tra tĩnh, chạy test và tái hiện cục bộ; không sửa mã nguồn ứng dụng.

## 1. Kết luận

Phát hiện **20 vấn đề: 9 P1 và 11 P2**. Các điểm cần sửa trước tập trung ở việc lưu Timeline, giữ đúng phiên bản dữ liệu khi sinh video/audio, truyền dữ liệu adapter sang pipeline, và điều phối Flow qua nhiều event loop.

Giao diện build thành công và phần lớn test backend chạy qua. Tuy nhiên, nhiều test chỉ kiểm tra từng module; chúng chưa bảo vệ các hợp đồng dữ liệu giữa UI → API → DB → pipeline → export.

- **P1:** có thể mất thao tác chỉnh sửa, tạo kết quả sai phiên bản, chặn hàng đợi hoặc làm hỏng luồng tạo nội dung chính. Nên sửa trước khi dùng luồng bị ảnh hưởng.
- **P2:** một tính năng/loại đầu vào bị chặn hoặc dữ liệu xuất ra không khớp. Sửa trước khi coi tính năng đó hoàn chỉnh.
- **Tái hiện cục bộ:** đã chạy đúng hàm/route với SQLite và file tạm; các dịch vụ mạng được thay bằng mock khi cần. Không có nghĩa đã kiểm chứng với Google Flow hay Colab thật.
- **Đối chiếu mã nguồn:** đường đi dữ liệu cho thấy lỗi, nhưng chưa thực hiện thao tác trên trình duyệt hoặc dịch vụ thật.

### Danh sách phát hiện

| ID | Mức | Vấn đề | Bằng chứng |
|---|---|---|---|
| F01 | P1 | Timeline thêm/xóa/đổi thứ tự scene nhưng không lưu cấu trúc xuống backend | Đối chiếu mã nguồn |
| F02 | P1 | Lưu scene lỗi nhưng nút Generate vẫn tiếp tục | Đối chiếu mã nguồn |
| F03 | P2 | G1 đọc narration rỗng thay cho visual prompt hợp lệ | Tái hiện cục bộ |
| F04 | P1 | FlowClient dùng Future/WebSocket qua nhiều event loop không an toàn | Tái hiện độ trễ callback + đối chiếu mã nguồn |
| F05 | P1 | Adapter → DB bỏ mất start_image và metadata cần cho pipeline | Tái hiện mất trường + đối chiếu consumer |
| F06 | P1 | Project đang generating vẫn cho sửa scene | Tái hiện API |
| F07 | P1 | Tạo lại scene thất bại nhưng clip cũ vẫn có thể được ghép | Tái hiện nhánh lỗi |
| F08 | P1 | Audio task chờ hủy có thể chặn toàn bộ task phía sau | Tái hiện hàng đợi |
| F09 | P1 | Audio task cũ có thể ghi đè kết quả mới khác speed/model | Tái hiện ghi đè với speed khác nhau |
| F10 | P2 | Preview và Create không dùng cùng quy tắc đọc đầu vào adapter | Tái hiện API |
| F11 | P2 | Form ecommerce không gửi các trường adapter bắt buộc | Tái hiện payload UI qua API |
| F12 | P2 | location_hint bị chuẩn hóa mất thông tin, sai quyết định nối cảnh | Tái hiện mapping và quyết định reset |
| F13 | P2 | NewProject gửi voice nhưng bỏ language | Tái hiện giá trị lưu DB + đối chiếu queue |
| F14 | P2 | Save không đổi nội dung vẫn hủy duyệt media của Studio | Tái hiện API |
| F15 | P2 | Export nhận ID số trong khi UI truyền short_id | Tái hiện trên app router thật |
| F16 | P2 | Hai route SRT trùng nhau; route cũ che phụ đề theo render | Tái hiện route/discovery + đối chiếu timing |
| F17 | P2 | CapCut tìm audio/SRT ở thư mục khác nơi pipeline ghi ra | Tái hiện discovery + đối chiếu exporter |
| F18 | P2 | Video remaster tạo scene tối đa 30 giây nhưng validator chỉ cho 8 giây | Test hiện có thất bại + đối chiếu mã nguồn |
| F19 | P1 | Video remaster trả đường dẫn đã bị cleanup xóa | Tái hiện vòng đời file |
| F20 | P2 | Podcast/remaster vẫn gọi STT local đã bị vô hiệu hóa | Đối chiếu caller/callee và test thất bại |

## 2. Các điểm nối đang không khớp

| Điểm nối | Bên gửi/ghi | Bên nhận/đọc | Hậu quả |
|---|---|---|---|
| Timeline → scenes API | Thêm, xóa, đổi thứ tự trong state | PATCH chỉ cập nhật trường của scene đã tồn tại | DB khác màn hình |
| NewProject → content preview | script/url/object của adapter | Chỉ lấy raw_content | Preview lỗi trong khi Create có thể chạy |
| Adapter → Scene DB | start_image, hint chi tiết, metadata passthrough | Chỉ giữ vài trường văn bản và hint giới hạn | Mất chỉ dẫn ảnh, chuyển cảnh, video remaster |
| Project/scene → audio task | Nhiều yêu cầu khác speed/model | Kiểm tra chủ yếu text/order/voice/language | Task cũ vẫn được coi là hiện hành |
| Worker Flow → callback HTTP | Future thuộc loop ở thread chạy generation | Callback hoàn tất Future từ loop khác | Callback không đánh thức loop kịp thời |
| Render → export | output/{id}/narration.wav và subtitle.srt | Discovery trong audio/{id} | Thiếu track hoặc phụ đề sai timing |

## 3. Phát hiện chi tiết

### F01 — P1 — Timeline không lưu thêm/xóa/đổi thứ tự scene

**Vị trí:** [Timeline.tsx:632–693](../ui/src/pages/Timeline.tsx); [scenes.py:69–79](../server/api/routes/scenes.py).

`handleMoveUp`, `handleMoveDown`, `handleRemove` và `handleAddScene` chỉ thay đổi state phía UI. Scene mới mang ID `local_...`. Khi Save, code lọc bỏ tất cả scene có ID này và chỉ PATCH `duration`, `narration`, `prompt` của các scene còn lại. Không có request tạo, xóa hoặc cập nhật `order`; schema PATCH cũng không nhận `order`.

- **Tái hiện từ luồng mã:** mở Timeline có A/B/C → xóa B, đổi C lên đầu, thêm D → Save → tải lại hoặc Generate. Backend vẫn có A/B/C theo thứ tự cũ; D chưa từng được tạo.
- **Ảnh hưởng:** người dùng tin đã lưu cấu trúc mới, nhưng pipeline chạy danh sách scene cũ. Đây là lỗi mất thao tác, không chỉ lỗi hiển thị.
- **Hướng sửa:** có một API lưu danh sách scene theo transaction, hỗ trợ tạo/xóa/thứ tự và version; hoặc tạm ngừng hiển thị các thao tác chưa được backend hỗ trợ.
- **Kiểm tra cần có:** thêm/xóa/reorder → Save → GET lại phải khớp UI; snapshot đầu vào generation phải khớp danh sách đã lưu.

### F02 — P1 — Save thất bại vẫn khởi động Generate

**Vị trí:** [Timeline.tsx:673–709](../ui/src/pages/Timeline.tsx).

`handleSave()` bắt lỗi của `Promise.all(patches)` rồi chỉ gọi `setSaveError(...)`; hàm không throw lại hoặc trả kết quả thất bại. `handleGenerate()` gọi `await handleSave()` và tiếp tục POST `/generate`.

- **Điều kiện:** một PATCH bị backend từ chối hoặc lỗi mạng. Các PATCH khác có thể đã thành công, vì chúng chạy riêng rẽ.
- **Ảnh hưởng:** Generate vẫn chạy trên dữ liệu cũ hoặc dữ liệu mới được lưu một phần; có thể tiêu tốn lượt tạo video cho nội dung chưa được người dùng xác nhận.
- **Hướng sửa:** Save trả kết quả rõ ràng hoặc ném lỗi; Generate dừng nếu lưu chưa hoàn tất. Kết hợp F01 để lưu toàn bộ chỉnh sửa một cách nguyên tử.
- **Kiểm tra cần có:** chủ động làm một PATCH trả 4xx/5xx; xác nhận không có request Generate và thông báo lỗi vẫn hiện.

### F03 — P2 — G1 kiểm tra nhầm trường prompt

**Vị trí:** [g1_scene_list.py:43–55,94–103](../server/pipeline/gates/g1_scene_list.py); [scene.py:48–49](../server/db/models/scene.py); [schemas.py:35–39](../server/text/schemas.py).

Hàm lấy prompt của G1 lần lượt kiểm tra `visual_prompt`, `narration`, `prompt`, và trả ngay trường đầu tiên tồn tại. ORM `Scene` luôn có `narration`, kể cả giá trị rỗng. Vì vậy, visual `prompt` hợp lệ có thể không bao giờ được đọc. Trong khi đó schema kịch bản cho phép scene không có lời thoại.

- **Bằng chứng:** `Scene(prompt='A valid visual prompt', narration='')` đưa vào `validate_scene_list()` trả `status='failed'`.
- **Ảnh hưởng:** scene im lặng có mô tả hình ảnh đầy đủ vẫn bị chặn trước generation. Với narration không rỗng, gate lại kiểm tra văn bản lời thoại thay vì đầu vào hình ảnh.
- **Hướng sửa:** G1 phải kiểm tra đúng trường visual prompt mà generator sử dụng; không chọn trường chỉ dựa trên `hasattr`.
- **Kiểm tra cần có:** prompt hợp lệ + narration rỗng phải qua; prompt thực sự thiếu phải bị chặn dù narration có nội dung.

### F04 — P1 — FlowClient dùng chung qua nhiều event loop

**Vị trí:** [projects.py:523–564](../server/api/routes/projects.py); [queue.py:284–285](../server/audio/queue.py); [main.py:74–85](../server/main.py); [client.py:153–161,210–227](../server/flow/client.py); [ext_callback.py:51–57](../server/api/routes/ext_callback.py).

Generation chạy trong thread và dùng `asyncio.run(...)`, tạo loop riêng. `FlowClient._send()` tạo Future trên loop đang chạy này, trong khi WebSocket dùng chung và endpoint callback được xử lý trên loop của server. `resolve_callback()` gọi trực tiếp `fut.set_result(...)`; nhánh disconnect cũng trực tiếp hoàn tất Future. Không có bước chuyển việc về loop sở hữu Future.

- **Tái hiện:** đặt timeout thử nghiệm 0,5 giây; callback được gửi từ thread khác sau khoảng 0,05 giây. `_send()` chỉ trả kết quả sau **0,505 giây**, khi timer đánh thức loop. Mock WebSocket được dùng để tách riêng vấn đề đồng bộ.
- **Ảnh hưởng:** callback đã đến nhưng worker chờ lâu; việc gửi WebSocket/hoàn tất Future khác loop còn có thể gây lỗi tùy đường chạy. Chưa đo độ trễ với Chrome thật; không kết luận mọi request đều timeout.
- **Hướng sửa:** giữ orchestration và FlowClient trên cùng loop, hoặc chuyển cả thao tác WebSocket và hoàn tất Future về loop sở hữu bằng API thread-safe.
- **Kiểm tra cần có:** callback/disconnect từ luồng server phải đánh thức request ở worker ngay, không phụ thuộc timer; chạy thêm một lượt generation qua extension thật.

### F05 — P1 — Adapter → DB làm mất dữ liệu cần để tạo nội dung

**Vị trí:** [base.py:92–120](../server/content/base.py); [projects.py:303–321,683–698](../server/api/routes/projects.py); [scene.py:42–60](../server/db/models/scene.py); [orchestrator.py:698–708,923–933](../server/pipeline/orchestrator.py); [video_remaster/adapter.py:367–373](../server/content/adapters/video_remaster/adapter.py).

`SceneSpec` hỗ trợ `start_image`; `SceneList` có metadata và các tham chiếu bổ sung. `_parse_and_persist_scenes()` chỉ lưu project/order/duration/prompt/narration/location_hint/status. Ảnh đầu vào và metadata không được lưu theo một hợp đồng để pipeline đọc lại. ORM Scene không có `start_image`; fallback trong orchestrator hiện trả `None` trước khi thử các Asset khác.

- **Bằng chứng:** adapter fixture trả hai scene có `start_image`; sau Create/đọc DB, cả hai scene đều không có trường đó.
- **Ảnh hưởng 1:** ảnh từng scene do storyboard/photo/product cung cấp không được dùng đúng; scene đầu có thể báo thiếu ảnh hoặc dùng ảnh chung không đúng chỉ định.
- **Ảnh hưởng 2:** remaster trả `passthrough=True`, `output_path`, `translated_srt` trong metadata, nhưng cùng đường lưu này bỏ metadata. Luồng generation không nhận được chỉ dẫn dùng trực tiếp video đã remaster.
- **Hướng sửa:** định nghĩa dữ liệu runtime cần lưu qua DB, gồm tham chiếu ảnh từng scene và artifact của chế độ passthrough; chọn đúng pipeline theo chế độ đó.
- **Kiểm tra cần có:** adapter → Create → DB → generation phải giữ nguyên nguồn ảnh; remaster phải sử dụng artifact đã tạo thay vì coi là scene cần sinh mới.

### F06 — P1 — Scene vẫn sửa được khi project đang tạo video

**Vị trí:** [scenes.py:178–220](../server/api/routes/scenes.py); [projects.py:497,699–707](../server/api/routes/projects.py); [orchestrator.py:486](../server/pipeline/orchestrator.py).

API sửa scene chỉ chặn khi `scene.status == 'generating'`. Luồng khởi động lại đặt trạng thái trên **Project**; event `scene_started` không đồng thời đảm bảo trạng thái Scene trong DB là generating. Vì thế scene vẫn có thể mang draft/ready trong lúc project đang chạy.

- **Bằng chứng:** tạo project `generating`, scene `draft`, gọi PATCH scene → **HTTP 200**.
- **Ảnh hưởng:** nội dung/duration/location có thể đổi trong lúc request video đang xử lý. Callback có kiểm tra một phần prompt/narration, nhưng việc này xảy ra muộn và không bao phủ các trường còn lại; có thể lãng phí lượt tạo hoặc ghép dữ liệu không cùng phiên bản.
- **Hướng sửa:** API kiểm tra trạng thái job/project và version của scene trong transaction; xác định rõ cơ chế cho phép chỉnh sửa bản nháp khi một snapshot đang chạy.
- **Kiểm tra cần có:** thay prompt, narration, duration và location khi job đang chạy; mọi kết quả phải gắn với đúng snapshot hoặc được từ chối rõ ràng.

### F07 — P1 — Clip cũ có thể được ghép sau khi tạo lại thất bại

**Vị trí:** [scenes.py:208–214](../server/api/routes/scenes.py); [orchestrator.py:511–565,599–615](../server/pipeline/orchestrator.py); [projects.py:699–705,730–734](../server/api/routes/projects.py).

Sửa prompt không vô hiệu hóa `video_path`/`last_frame_path` cũ. Khi `_run_scene()` hết retry hoặc không qua G3, hàm trả thất bại nhưng đường dẫn cũ có thể vẫn tồn tại trên scene. Bước chọn `successful` để render dựa vào `video_path` có file, không dựa vào kết quả thành công của lần chạy hiện tại.

- **Tái hiện:** scene có file clip cũ, mock generation luôn lỗi → `_run_scene()` trả `False`, nhưng scene vẫn thỏa điều kiện chọn clip để render.
- **Ảnh hưởng:** video cuối có thể chứa hình ảnh cũ dù người dùng đã đổi prompt; trạng thái/tiến độ có thể gây hiểu nhầm rằng clip đáp ứng yêu cầu mới.
- **Hướng sửa:** theo dõi output được chấp nhận theo run/version; lịch sử clip cũ tách khỏi output hiện hành. Không dùng sự tồn tại của một file làm điều kiện duy nhất cho thành công.
- **Kiểm tra cần có:** lần đầu thành công → đổi prompt → lần hai thất bại; clip cũ không được tự động coi là output mới.

### F08 — P1 — Audio task chờ hủy chặn task sau khi mất worker

**Vị trí:** [queue.py:149–162,208–214](../server/audio/queue.py); [remote.py:59–63](../server/audio/remote.py); [audio.py:144,165](../server/api/routes/audio.py).

Mỗi tick chọn task cũ nhất trong nhóm queued/running/cancel_requested. Với task chờ hủy có `active_key`, queue cần thông tin kết nối remote để hủy. Nếu thiếu token/kết nối, `AudioUnavailable` khiến task vẫn ở `cancel_requested`; tick sau lại chọn chính task đó. API resume cũng từ chối trạng thái này.

- **Bằng chứng:** task đầu `cancel_requested` có active key, không có remote token; task sau `queued`. Sau hai tick, trạng thái vẫn là `['cancel_requested', 'queued']`.
- **Ảnh hưởng:** task cũ chặn cả hàng đợi, kể cả công việc phía sau có thể dùng cache cục bộ. Hủy một job không làm hàng đợi thoát khỏi tình trạng này.
- **Hướng sửa:** tách hủy logic tại local khỏi cleanup remote; kết thúc/supersede task local mà không chặn task khác, đồng thời bảo đảm callback muộn không gắn kết quả của task đã hủy.
- **Kiểm tra cần có:** worker mất kết nối → hủy → task dùng cache phía sau vẫn hoàn thành; khi worker trở lại, kết quả cũ không được gắn vào project.

### F09 — P1 — Audio task cũ ghi đè kết quả của yêu cầu mới

**Vị trí:** [audio.py:119–127](../server/api/routes/audio.py); [queue.py:81–86,245–248](../server/audio/queue.py).

Tạo task mới cập nhật voice/language của project và xóa các audio path, nhưng không đánh dấu task cũ là superseded. `inputs_current()` chỉ đối chiếu voice/language và snapshot scene/text/order; không phân biệt yêu cầu mới nhất, speed hoặc model. `finish()` cũng không kiểm tra task nào được quyền gắn output.

- **Tái hiện:** hai task cùng text/voice/language nhưng speed 1,0 và 1,5 đều được coi là current. Sau khi task mới đã succeeded, gọi finish task cũ: audio path của scene bị thay bằng file mang ID task cũ.
- **Ảnh hưởng:** preview/render có thể dùng giọng đọc sai tốc độ hoặc mô hình so với yêu cầu mới nhất. Điều kiện điển hình là resume task cũ sau khi task mới hoàn tất.
- **Hướng sửa:** có revision/active task ID của yêu cầu audio; chỉ task tương ứng được attach kết quả. Lưu và so sánh đầy đủ model, voice, language, speed và snapshot.
- **Kiểm tra cần có:** hoàn tất hai task theo thứ tự ngược nhau; kết quả cuối phải thuộc yêu cầu hiện hành, không phụ thuộc thứ tự callback.

### F10 — P2 — Preview và Create đọc cùng payload theo hai cách khác nhau

**Vị trí:** [NewProject.tsx:234–249](../ui/src/pages/NewProject.tsx); [ScenePreviewModal.tsx:49](../ui/src/components/ScenePreviewModal.tsx); [client.ts:259–266](../ui/src/api/client.ts); [content.py:107](../server/api/routes/content.py); [projects.py:269–285](../server/api/routes/projects.py).

UI gửi các payload dạng `{script: ...}`, `{url: ...}` hoặc object theo adapter. Preview chuyển nguyên object tới `/api/content/parse`, nhưng endpoint này chỉ lấy `input_data.raw_content`. Create lại hỗ trợ các alias script/url/text/content và fallback JSON. Skill đang chọn cũng không được truyền tương đương qua đường preview.

- **Bằng chứng:** cùng payload narrative `{script: ...}` → Preview **400**, Create **201**, project ready với hai scene.
- **Ảnh hưởng:** không thể tin rằng bước xem trước phản ánh đầu vào và lựa chọn dùng khi tạo project; một số luồng bị chặn ngay ở preview.
- **Hướng sửa:** dùng chung hàm chuẩn hóa `AdapterInput` cho hai endpoint, bao gồm raw content, options, assets và skill.
- **Kiểm tra cần có:** kiểm thử cùng payload UI qua cả Preview và Create cho narrative, URL, storyboard và ecommerce; không chỉ test adapter với input dựng tay.

### F11 — P2 — Form ecommerce không khớp schema adapter, lỗi parse bị bỏ qua

**Vị trí:** [NewProject.tsx:235–236,276–287,308–319](../ui/src/pages/NewProject.tsx); [ecommerce_product/adapter.py:150–199](../server/content/adapters/ecommerce_product/adapter.py); [projects.py:281–297](../server/api/routes/projects.py).

UI ecommerce chỉ gửi `product_image_path`. Adapter bắt buộc có `product_name`, `price`, `description` trong JSON; ảnh sản phẩm được đọc từ `input.assets['product_image']`, không phải option `product_image_path`. Create đã lưu project trước khi parse; khi parse lỗi, response vẫn 201 và chứa `parse_error`. UI chuyển sang Timeline mà không xử lý trường này.

- **Bằng chứng:** payload đúng như form gửi trả project `draft`, `scene_count=0`, lỗi thiếu cả ba trường bắt buộc.
- **Ảnh hưởng:** người dùng thực hiện theo form nhưng nhận project rỗng; không có thông tin đủ để sửa đầu vào tại chỗ.
- **Hướng sửa:** bổ sung dữ liệu sản phẩm cần thiết, ánh xạ/upload ảnh sang assets đúng hợp đồng, hiển thị lỗi parse và cho sửa/retry.
- **Kiểm tra cần có:** đi từ payload form thực tế tới scene đã lưu có nội dung sản phẩm và ảnh đúng; không chỉ gọi adapter trực tiếp bằng JSON đầy đủ.

### F12 — P2 — location_hint bị mất trước khi quyết định nối cảnh

**Vị trí:** [projects.py:304–315](../server/api/routes/projects.py); [ecommerce_product/adapter.py:56](../server/content/adapters/ecommerce_product/adapter.py); [scene_chain.py:86–93](../server/ai/prompts/scene_chain.py).

Route persist chỉ chấp nhận indoor/outdoor/transition/unspecified. Adapter lại có các hint như indoor_home, outdoor_nature hoặc indoor_cafe. Giá trị không thuộc whitelist bị thay bằng unspecified. `SceneChain.should_reset_chain()` trả không reset khi một bên unspecified.

- **Bằng chứng:** adapter trả indoor_home → outdoor_nature; DB lưu unspecified → unspecified, quyết định reset trả `False`.
- **Ảnh hưởng:** cảnh chuyển không gian vẫn có thể nối ảnh cuối của cảnh trước, làm sai tính liên tục hình ảnh theo ý định adapter.
- **Hướng sửa:** thống nhất kiểu dữ liệu location_hint; nếu cần rút gọn, dùng mapping có chủ đích và giữ thông tin chuyển bối cảnh. Không âm thầm đưa mọi giá trị lạ về unspecified.
- **Kiểm tra cần có:** đổi indoor_home → outdoor_nature phải đi đúng nhánh reset; giữ nguyên địa điểm phải đi đúng nhánh nối.

### F13 — P2 — NewProject lưu language=en dù đã chọn voice tiếng Việt

**Vị trí:** [NewProject.tsx:279–285,311–317](../ui/src/pages/NewProject.tsx); [projects.py:67–68,217–218](../server/api/routes/projects.py); [queue.py:35–42,66–68](../server/audio/queue.py); đối chiếu [AudioStudio.tsx:139–141](../ui/src/pages/AudioStudio.tsx).

NewProject gửi voice_id nhưng không gửi language. API mặc định language là en, không suy ra từ voice. Queue lấy ngôn ngữ của project để gửi worker và kiểm tra capability. AudioStudio đã có logic suy ra ngôn ngữ từ voice, nhưng NewProject chưa dùng tương đương.

- **Bằng chứng:** Create với voice fixture tiếng Việt và không có language lưu project `language='en'`.
- **Ảnh hưởng:** worker chỉ hỗ trợ tiếng Việt có thể bị coi là không tương thích; worker đa ngôn ngữ nhận tham số khác lựa chọn người dùng mong đợi. Chưa kiểm tra chất lượng phát âm trên worker thật.
- **Hướng sửa:** gửi language tương ứng voice/ngôn ngữ người dùng chọn; backend kiểm tra cặp voice-language thay vì mặc định âm thầm.
- **Kiểm tra cần có:** chọn voice tiếng Việt ở NewProject → audio task phải mang vi; kiểm tra cả voice mặc định và voice đã huấn luyện.

### F14 — P2 — Save không đổi nội dung vẫn hủy duyệt media

**Vị trí:** [scenes.py:216–220](../server/api/routes/scenes.py); [Timeline.tsx:676–684](../ui/src/pages/Timeline.tsx).

API chuyển `ProductionMedia.approved=False` chỉ cần request chứa prompt hoặc narration, không kiểm tra giá trị có thực sự thay đổi. Timeline Save gửi cả hai trường cho mọi scene đã có.

- **Bằng chứng:** PATCH lại đúng prompt/narration hiện tại trả 200, media đang approved chuyển thành false.
- **Ảnh hưởng:** chỉ bấm Save hoặc Generate từ Timeline cũng có thể làm mất lượt duyệt media trong Studio; bước render yêu cầu duyệt lại dù nội dung giữ nguyên.
- **Hướng sửa:** so sánh trước/sau và chỉ vô hiệu hóa approval khi dữ liệu ảnh hưởng tới media thực sự đổi.
- **Kiểm tra cần có:** no-op PATCH giữ approval; thay nội dung liên quan mới hủy approval.

### F15 — P2 — Export không nhận short_id mà UI đang dùng

**Vị trí:** [NewProject.tsx:287](../ui/src/pages/NewProject.tsx); [Export.tsx:83–87,109](../ui/src/pages/Export.tsx); [export.py:81–85,252–255](../server/api/routes/export.py).

Project mới được điều hướng bằng `short_id` dạng `p_....`. Export tiếp tục dùng route param đó cho CapCut và SRT. Hai endpoint trong export router khai báo `project_id: int`, trong khi các endpoint project thông thường có bước tìm theo chuỗi/short ID.

- **Bằng chứng:** TestClient trên `create_app()` thật: POST CapCut bằng short_id → **422**; GET SRT bằng cùng short_id → **422**.
- **Ảnh hưởng:** nút export không hoạt động khi truy cập project qua đường điều hướng mặc định.
- **Hướng sửa:** thống nhất cách resolve public project ID giữa các endpoint; hoặc dùng ID số đã resolve tại UI một cách nhất quán.
- **Kiểm tra cần có:** tạo project → mở Timeline → Export bằng short_id; CapCut/SRT phải trả artifact hoặc lỗi nghiệp vụ phù hợp, không phải lỗi kiểu dữ liệu.

### F16 — P2 — Route SRT bị đăng ký trùng và không trả timing của bản render

**Vị trí:** [main.py:164–165](../server/main.py); [export.py:214–255,325–357](../server/api/routes/export.py); [projects.py:718–762,1036–1072](../server/api/routes/projects.py); [media.py:65–84](../server/production/media.py).

Cả export router và projects router đều đăng ký GET `/{project_id}/export/srt`. Export router được include trước, nên route trong projects trả file `output/{id}/subtitle.srt` bị che. Route chạy trước tìm SRT trong `audio/{id}`, rồi fallback dựng phụ đề bằng duration/narration của scene trong DB.

Pipeline render lại căn duration theo audio thực tế, có thể chỉ render các scene thành công, và ghi SRT trong output. Việc cập nhật duration khi align diễn ra sau lượt lưu scene; fallback SRT không bảo đảm cùng timing/danh sách scene với video cuối.

- **Bằng chứng:** app có hai route SRT theo đúng thứ tự export → projects. Fixture audio 10 giây trên scene 8 giây tạo subtitle kết thúc ở 10 giây trong output, nhưng discovery của export trả `None`.
- **Ảnh hưởng:** sửa lỗi short_id ở F15 vẫn chưa đủ; tải SRT bằng ID số có thể nhận phụ đề lệch hoặc chứa scene không có trong video.
- **Hướng sửa:** giữ một route lấy phụ đề từ artifact/manifest của lần render hiện hành. Fallback trước khi render cần được xác định riêng, không mạo nhận là phụ đề của video cuối.
- **Kiểm tra cần có:** narration dài hơn duration khai báo và một scene render thất bại; SRT tải về phải đúng với bản video cuối.

### F17 — P2 — CapCut không tự tìm được narration/SRT do pipeline tạo

**Vị trí:** [export.py:149–154,214–230](../server/api/routes/export.py); [queue.py:233–248](../server/audio/queue.py); [media.py:82–84](../server/production/media.py); [capcut_exporter.py:171–190,217–227](../server/export/capcut_exporter.py); [Export.tsx:109](../ui/src/pages/Export.tsx).

UI gọi CapCut mà không gửi đường dẫn media. Backend tự tìm trong `audio/{project_id}`. Remote audio ghi file task/scene dưới `audio/tasks`; bước render ghi narration hợp nhất và SRT dưới `output/{project_id}`. CapCut exporter chỉ thêm các track này khi được truyền path, không tự chuyển sang đọc `scene.audio_path`.

- **Bằng chứng:** fixture đã có `output/{id}/narration.wav` và `subtitle.srt`, nhưng `_discover_audio(..., 'narration')` và `_discover_srt(...)` đều trả `None`.
- **Ảnh hưởng:** sau khi sửa F15, gói CapCut vẫn có thể thiếu track narration/SRT riêng mà người dùng cần chỉnh sửa; không khẳng định video nguồn hoàn toàn không có âm thanh nhúng.
- **Hướng sửa:** export đọc các artifact chính thức của run/render hiện hành, thay vì đoán thư mục theo quy ước cũ.
- **Kiểm tra cần có:** tạo audio → render → export không truyền path thủ công; mở cấu trúc gói để xác nhận đủ track audio, subtitles và timing.

### F18 — P2 — Video remaster bị áp giới hạn clip generation 8 giây

**Vị trí:** [video_remaster/adapter.py:69,265,353–365](../server/content/adapters/video_remaster/adapter.py); [base.py:159](../server/content/base.py); [duration_estimator.py:36–61](../server/content/duration_estimator.py).

Adapter remaster gom video vào một scene và clamp duration tối đa 30 giây. Sau đó vẫn gọi `SceneList.validate()` dùng giới hạn mặc định 8 giây cho clip sinh mới. Video nguồn dài hơn 8 giây tạo scene không hợp lệ dù chế độ remaster dự định dùng trực tiếp video đã xử lý.

- **Bằng chứng:** các test remaster hiện có với fixture 12/15 giây thất bại ở validation `ADAPTER_INVALID_OUTPUT`; không phải do download/model thật.
- **Ảnh hưởng:** một nhóm đầu vào remaster thông thường bị từ chối ngay trong adapter. Đây là lỗi độc lập với file bị xóa ở F19 và metadata bị mất ở F05.
- **Hướng sửa:** tách validation cho passthrough/remaster khỏi giới hạn clip generation. Không chỉ clamp xuống 8 giây vì sẽ làm sai thời lượng nội dung gốc.
- **Kiểm tra cần có:** remaster video 5, 12, 30 và trên 30 giây theo hợp đồng đã chọn; giữ đúng duration/artifact, không mất phần video.

### F19 — P1 — Remaster trả đường dẫn file đã bị xóa

**Vị trí:** [video_remaster/adapter.py:209–218,281–285,367–373](../server/content/adapters/video_remaster/adapter.py).

Nếu không truyền workdir, adapter tạo `TemporaryDirectory`, tải và xử lý video trong đó, rồi trả các đường dẫn vào metadata. Khối `finally` cleanup thư mục trước khi caller có thể dùng kết quả. Video/SRT không được chuyển sang vùng lưu bền vững.

- **Tái hiện:** mock download/remaster tạo file video và SRT thật trong thư mục tạm, duration 5 giây để tránh F18. `adapt()` trả thành công; ngay sau đó cả `output_path.exists()` và `translated_srt.exists()` đều **False**.
- **Ảnh hưởng:** API có thể báo adapter thành công nhưng artifact không còn tồn tại. Chỉ sửa mapping ở F05 sẽ chưa làm remaster chạy được.
- **Hướng sửa:** ghi output vào thư mục job/project có vòng đời rõ ràng hoặc chuyển artifact ra ngoài trước cleanup; chỉ xóa file trung gian.
- **Kiểm tra cần có:** sau khi adapt trả về, đọc được video/SRT; cleanup job chỉ xóa khi hết vòng đời sử dụng.

### F20 — P2 — Caller cũ vẫn gọi STT local đã bị vô hiệu hóa

**Vị trí:** [transcribe.py:112–130](../server/audio/transcribe.py); [podcast_caption/adapter.py:129–159](../server/content/adapters/podcast_caption/adapter.py); [stream_merger.py:236–253](../server/content/crawlers/stream_merger.py); [remaster.py:428–489](../server/content/crawlers/remaster.py); đối chiếu [production/transcribe.py](../server/production/transcribe.py) và [render.py:172–174](../server/production/render.py).

STT local trong `audio/transcribe.py` hiện luôn ném `RuntimeError`. Podcast caption vẫn gọi API đó và chuyển lỗi thành `AdapterError`. Nhánh lấy lời thoại cho remaster cũng đi qua `transcribe_audio`; khi không có subtitle nhúng, lỗi bị chuyển thành không có transcript và rơi vào nhánh SRT rỗng. Trong khi đó luồng Production đã có implementation STT remote khác.

- **Ảnh hưởng:** podcast caption không hoạt động qua nhánh transcribe hiện tại; video không có phụ đề nhúng không được tự tạo transcript như luồng remaster mong đợi. Không kết luận mọi video remaster đều lỗi, vì video có subtitle sẵn có thể đi nhánh khác.
- **Bằng chứng:** caller/callee xác nhận đường gọi vào hàm luôn raise; test transcribe/stream merger cũ cũng thất bại tại điểm chuyển đổi này. Chưa chạy worker STT thật.
- **Hướng sửa:** nối các caller còn lại sang cùng cơ chế remote STT/job; nếu chưa hỗ trợ, UI/API phải phản ánh capability đó rõ ràng.
- **Kiểm tra cần có:** podcast hợp lệ và video không subtitle phải có transcript khi worker hỗ trợ; khi worker vắng, báo trạng thái chờ/lỗi rõ ràng thay vì tạo SRT rỗng như kết quả thành công.

## 4. Kết quả kiểm tra đã chạy

### Build và kiểm tra tĩnh

| Kiểm tra | Kết quả |
|---|---|
| UI: `npm run build` trong app/ui | Qua TypeScript và Vite; 4.652 module |
| Parse AST Python trong server, colab, codex_tmux, scripts | 299 file hợp lệ cú pháp |
| `node --check` cho JavaScript extension | 7 file qua |
| `python -m ruff check server --select F821,F823 --exclude tests` trong app | Qua kiểm tra tên chưa định nghĩa/biến cục bộ trước khi gán |
| Pytest backend | 2.643 passed, 74 failed, 5 skipped, 1 warning trong 86,79 giây |

Pytest chạy bằng Python 3.14.0 với thư mục dữ liệu/working directory tạm và chặn kết nối mạng ngoài localhost. Đặt `PYTHON_DOTENV_DISABLED=1` để không dùng cấu hình thực của ứng dụng. Điều này làm **một** test kiểm tra việc tự nạp `.env` thất bại; chạy riêng test đó với chức năng dotenv được bật lại đã **passed**. Vì vậy còn **73 test thất bại khác chưa được xử lý**, không phải 74 lỗi ứng dụng độc lập.

### Phân loại các test thất bại còn lại

| Nhóm | Số ca | Nhận định |
|---|---:|---|
| Ecommerce 10, narrative 1, script_direct 4, storyboard 2, base adapter 1, pipeline_limits 4, shared adapter logic 3 | 25 | Nhiều kỳ vọng scene count/duration cũ không còn khớp cơ chế chia scene và giới hạn 8 giây. Cần xác nhận hợp đồng trước khi sửa test. |
| Video remaster 7 + remaster E2E 1 | 8 | Xung đột duration remaster với validator 8 giây; liên quan F18. |
| TTS service | 16 | Test còn kỳ vọng chain/provider local và đuôi .mp3; code đã chuyển remote/.wav. Không suy ra remote TTS thật bị lỗi từ các test này. |
| Transcribe 15 + stream merger 4 | 19 | Test còn dùng STT local đã bị vô hiệu hóa; đồng thời có caller sản phẩm chưa chuyển đổi, xem F20. |
| Quality gates | 4 | Fixture/kỳ vọng kiểm tra kích thước file cũ không khớp G3 hiện tại; cần fixture media hợp lệ và tiêu chí chất lượng mới. |
| Phase B routes / voice catalog | 1 | Kỳ vọng catalog giọng local cũ không khớp catalog remote hiện tại. |
| **Tổng** | **73** | Không gộp cơ học thành 73 phát hiện sản phẩm. |

Các test trong nhóm remote audio, Script Studio và Production đã chạy qua trong bộ test trên. Điều này chưa chứng minh các đường nối từ NewProject/Timeline hoặc các dịch vụ ngoài hoạt động đầy đủ.

### Bằng chứng tái hiện nổi bật

```text
preview_vs_create:          preview=400, create=201, ready, 2 scenes
product_ui_payload:         draft, 0 scenes, missing product_name/price/description
lost_mapping:               hints=[unspecified, unspecified], start_image absent
edit_generating:            PATCH=200 while project.status=generating
noop_patch_approval:        approved=true -> false
g1_silent:                  valid visual prompt + empty narration -> failed
failed_regeneration:        success=false, old clip still matches render selection
cancel_blocks_queue:        [cancel_requested, queued] unchanged after 2 ticks
audio_version_not_checked:  old speed=1 and new speed=1.5 both considered current
late_audio_overwrite:       old task output replaces newer task scene.audio_path
cross_thread_callback:      callback after ~0.05s, result after 0.505s (timeout=0.5s)
actual_app_export_routes:   CapCut short_id=422, SRT short_id=422, duplicate SRT routes
export_discovery:           rendered SRT/audio exist, both discovery results=None
remaster_artifact_lifetime: video_exists=false, srt_exists=false after adapt returns
```

Script kiểm chứng chỉ dùng thư mục tạm, SQLite tạm và các mock cần thiết; không được thêm vào source ứng dụng. Kết quả số dòng trong báo cáo là theo working tree lúc rà soát, có thể dịch chuyển khi code được sửa.

## 5. Thứ tự xử lý đề xuất

1. **Bảo toàn chỉnh sửa và phiên bản kết quả:** F01, F02, F06, F07, F09. Tiêu chí: không tạo video từ trạng thái chưa lưu, không ghép/attach output sai revision.
2. **Gỡ các điểm chặn runtime:** F04, F08; xử lý F03 để scene im lặng hợp lệ không bị gate chặn.
3. **Thống nhất hợp đồng adapter và đầu vào UI:** F05, F10–F13. Dùng test đi qua route và DB, không chỉ test từng adapter.
4. **Khôi phục remaster/podcast:** F18–F20 cùng metadata passthrough ở F05. Cần kiểm tra một video có subtitle và một video không có subtitle.
5. **Hoàn thiện vòng duyệt và export:** F14–F17. Export phải lấy đúng artifact/timing của bản render đã chọn.
6. **Cập nhật test theo hợp đồng đã thống nhất:** xử lý các kỳ vọng local audio, duration, G3 cũ; giữ test tái hiện lỗi thực để tránh quay lại tình trạng hiện tại.

## 6. Giới hạn của lần rà soát

- Không gọi Google Flow/Gemini/OpenRouter, Colab audio worker, R2 hoặc job huấn luyện thật; không phát sinh lượt tạo nội dung trả phí.
- Đã đọc các vùng chính và chạy bộ test backend; chưa kiểm tra thủ công mọi màn hình, notebook hoặc mọi tổ hợp cấu hình. Không coi những phần không xuất hiện trong danh sách là đã được chứng nhận không lỗi.
- Các phát hiện UI như F01/F02 được xác định bằng đường gọi mã nguồn; chưa thực hiện E2E bằng trình duyệt. Các reproduction khác nêu rõ mock hoặc fixture khi có.
- Hướng dẫn repo khai báo có GitNexus, nhưng CLI tại thời điểm rà soát báo repository chưa được index; không có `.codegraph/` để tra. Việc rà soát chuyển sang đọc mã, truy caller/callee và kiểm tra cục bộ; không tạo index mới.
- Working tree đã có nhiều thay đổi trước khi rà soát. Báo cáo mô tả trạng thái hiện tại, không quy kết phát hiện cho một commit hoặc tác giả cụ thể.
- Không sửa mã nguồn hay test trong repo. Build tạo artifact UI thông thường; script/log/DB tái hiện nằm trong TEMP. File Markdown này là tài liệu kết quả rà soát.
