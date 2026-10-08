# DevLead review — 2026-10-05

Review source AIFlow theo các luồng kịch bản, nhân vật/ảnh tham chiếu, video Google Flow, audio/clone giọng và xuất thành phẩm. Ba sub-agent sửa lỗi dùng `gpt-6.1-sol`, reasoning `high`; DevLead đọc lại thay đổi, yêu cầu sửa tiếp các lỗi phát hiện ở lượt kiểm tra sau, và chạy kiểm tra tổng hợp.

Đây là kết quả kiểm tra source và các ca chạy được ghi rõ bên dưới, không phải chứng nhận mọi dòng mã hoặc chất lượng mọi đầu ra AI. Không commit/push hay cập nhật bản cài đặt của người dùng. Giữ nguyên thay đổi `.gitignore` đã staged và các artifact có sẵn.

## Phạm vi

| Nhóm | Đã kiểm tra |
| --- | --- |
| Kịch bản và prompt | Text schemas/provider; Brief và series bible; script revisions/approval; studio operations; asset snapshots; 36 public skill và `_base`; mapping style vào prompt video |
| Nhân vật và nội dung | Dedup identity và ảnh canonical; asset upload/delete/association; project deletion; NewProject; adapters, crawlers và các helper signing/native download |
| Video | Production routes, Flow SDK/client/RPC/WebSocket, pipeline submission/polling/continuity, extension reference picker/observer/callback, scene editing, render/media |
| Giọng và Colab | Voice package/import/catalog, audio worker/queue/cache, approval và checksum/resume của trainer hiện hành; notebook/cell legacy và preprocessing/training/export |
| Giao diện và xuất file | Script Studio → Production; portrait review/export; CapCut writer/exporter, SRT, CLI legacy; sự kiện WS và SSE |

Inventory ban đầu: 721 file tracked ngoài vendor/storage, 332 file Python parse AST không lỗi, 4 notebook. Skill scan đọc 257 file YAML/JSON/Markdown và loader không báo lỗi. Một số phần sâu của CapCut model/draft và quality-gate library chủ yếu được kiểm tra bằng test và các caller, chưa audit từng dòng. Không có `.codegraph/` hay feature map hiện hữu để dùng làm điểm vào.

## Lỗi đã sửa và lý do

| Nhóm | Hành vi sau sửa |
| --- | --- |
| Prompt/ngôn ngữ | Narration theo ngôn ngữ Brief; validate lại Brief sau khi áp dụng series để lỗi pacing/ngôn ngữ trả 422, không phát sinh 500 ở bước sau |
| Style | Giữ `camera_rules`, `negative_prompts`, `post` và palette dạng list của skill khi xây StyleLock; trường canonical vẫn được ưu tiên |
| Nhân vật | Merge bắc cầu giữ identity/ảnh của nhân vật xuất hiện sớm nhất, thay vì phụ thuộc thứ tự set |
| Snapshot ảnh | Kết quả provider bị đánh dấu cần kiểm tra nếu quan hệ asset thay đổi trong lúc tạo ảnh, kể cả khi nội dung file không đổi |
| Nhập sản phẩm | Form gửi tên/giá/mô tả; preview và create truyền ảnh đúng contract; ảnh phải đọc được, được copy vào storage của project và liên kết với scene |
| Crawl URL | Chọn platform theo hostname thực, không theo chuỗi xuất hiện trong query/path hoặc domain giả, tránh đưa cookie của platform sang host tùy ý |
| Cookie import | Giữ dòng Netscape `#HttpOnly_` hợp lệ khi tạo Cookie header; comment thông thường vẫn bị bỏ qua; regression chỉ dùng cookie giả |
| EPUB nhiều tập | Preview trả 400 có mã lỗi và hướng dẫn chọn khoảng chương; create giữ draft cùng parse_error, không truy cập nhầm `.scenes` gây 500 |
| Asset/project | Tên upload do server sinh; kiểm tra containment và project; xóa các quan hệ phụ thuộc đúng thứ tự; chặn xóa project đã có lịch sử/media để tránh ID tái sử dụng gắn nhầm dữ liệu cũ |
| Voice package | Chặn voice ID/path không hợp lệ, ZIP traversal/symlink/duplicate/oversize; staging riêng mỗi request; serialize catalog update; không ghi đè thư mục giọng đã có |
| Request nội bộ | Các mutation asset/voice và content preview dùng local-client guard, frontend gửi header tương ứng |
| Video retry | Không tự gửi lại khi request có thể đã được nhận hoặc lỗi xảy ra lúc poll/download; chỉ retry khi chắc chắn chưa gửi; hướng dẫn lỗi giữ handle để đối chiếu |
| Flow transport | Request từ background loop được chuyển về loop sở hữu socket; cleanup pending future khi hủy; chặn website Origin trước khi tiết lộ callback secret/thay kết nối extension |
| Media và scene | Tên clip duy nhất; chặn edit lúc công việc đang chạy; edit nội dung làm hết hiệu lực video/frame/approval cũ; narration đổi làm hết hiệu lực audio cũ |
| Callback/download | Callback theo port cấu hình; lỗi download không in signed URL; download quá nhỏ không xóa file hợp lệ đã tồn tại |
| CapCut | Thiếu clip làm export thất bại rõ ràng; không tự thay clip khác; tên draft được giữ trong thư mục đích và vẫn hỗ trợ tiếng Việt |
| WS/SSE | App và worker dùng chung EventBus; chuyển event từ worker về đúng loop; resolve short/numeric project ID; giữ event type; lọc JobLog theo project |
| Audio worker | WAV có header hợp lệ nhưng PCM bị cắt bị từ chối; STT thiếu transcript không được coi là kết quả thành công dùng được |
| Colab legacy | T4 dùng FP32 khi không hỗ trợ BF16 native; padding label là -100; không cắt ngầm token quá dài; yêu cầu speech marker; kiểm tra provenance dataset/model/config/precision trước resume |
| Colab cleanup/export | Bỏ cả tham chiếu model/trainer/tokenizer trong notebook namespace; sửa endpoint/header import và mô tả đúng việc import metadata không tự kích hoạt giọng trên worker |
| Legacy CLI/G4 | CLI rời không dùng được socket trong process server nên fail sớm, trước mutation; G4 fail khi audio không probe được và nói rõ chưa đo silence |

Contract Gemini `generationConfig.responseFormat.text.schema` đã đối chiếu [GenerateContent API](https://ai.google.dev/api/generate-content) và [structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output?hl=en); không đổi một contract hợp lệ chỉ vì nó khác dạng API cũ.

## Kiểm chứng

Kết quả tổng hợp trên source đã ổn định:

| Kiểm tra | Kết quả |
| --- | --- |
| Backend toàn bộ sau bản sửa cuối | **3184 passed**, 167.40 giây; 1 cảnh báo dependency Starlette/TestClient, không có test fail |
| Extension | **78 passed** |
| UI | TypeScript và Vite production build qua |
| Browser Script Studio | Chromium thật, API thật trên database tạm: sửa cảnh → revision mới → quality/checklist → approve → tạo project Production; không có API/JavaScript error |
| Browser Production | Tạo portrait → upload fixture → duyệt → render → duyệt thành phẩm → ZIP có thể tải; không có JavaScript error |
| Browser NewProject | React thật → validate metadata trống → preview API thật → tạo project API thật → timeline; dữ liệu preview/create khớp, header có mặt, ảnh/quan hệ được lưu trong database tạm; không có API/JavaScript error |
| Hiển thị | Desktop 1440×1000 và mobile 390×844; không tràn ngang trong các trang smoke; đã xem screenshot |
| Colab legacy | 29 cell parse syntax; các regression legacy nằm trong bộ backend; source smoke trên T4 như mô tả dưới đây |
| Diff | `git diff --check` qua; `.gitignore` staged có trước vẫn giữ nguyên |

Lệnh chạy từ `app/` (extension chạy từ `app/extension/`, build từ `app/ui/`):

```text
.venv\Scripts\python.exe -m pytest -q --allow-hosts=127.0.0.1,localhost,::1 --tb=short
node --experimental-vm-modules --test tests/bridge.test.mjs
rtk npm run build
.venv\Scripts\python.exe -m server.tests.browser_script_studio
.venv\Scripts\python.exe -m server.tests.browser_production
```

Browser smoke dùng `PLAYWRIGHT_BROWSERS_PATH=app/vendor/playwright` theo đường dẫn tuyệt đối và Vite QA port 5177. Log của lần chạy tổng hợp và receipt nằm trong `app/storage/devlead-review-20261005/`; ảnh trong `app/storage/verification/`. Test không thực hiện inference trả phí. Trên Windows không dùng `--disable-socket` đơn lẻ vì nó chặn cả socketpair nội bộ của asyncio; extension test cần cờ VM modules như trên.

Live browser: Colab đã mount Drive theo ủy quyền của người dùng; thực thi CUDA trên Tesla T4 cho tổng tensor `3.0`. Smoke chạy chính hàm `_preprocess` và `_resume_checkpoint` trích từ source mới upload, với torch thật nhưng tokenizer giả lập: padding/overflow, precision FP32 và resume match/mismatch đều qua. Không chạy model inference hay training. Runtime hiện chưa cài VieNeu.

Receipt source trên Colab:

| File | SHA-256 |
| --- | --- |
| `04e_train_loop.py` | `3d1ca36b7c389d76fdc0a1f55e77f53a80fd311acea1706967c039e6e728ff6b` |
| `04c_load_base_model.py` | `a46e7bfe74ee3b13a5a7d87260a203453b963d0088c253d19d6ac1205b2091c4` |

Google Flow: mở project hiện có và kiểm tra Flow Bridge/capability. Sau khi restart server QA với các bản sửa Flow, health trả `extension_connected=true`, capability trả `available=true`. Không tạo clip/ảnh mới hoặc sửa draft của người dùng. Local server QA dùng `storage/devlead-review-20261005`, không dùng database sản xuất.

## Giới hạn cần giữ rõ

- Chưa đánh giá clip mới, tính nhất quán nhân vật qua nhiều clip, hoặc chất lượng nghe/độ giống của giọng clone sau training. Test source, bridge preflight và CUDA smoke không thay thế các đánh giá này.
- Chưa xác minh lại full GPU ASR 292 clip từ lần làm việc trước; không thay approval transcript/voice hay tự cộng thêm phút training.
- G4 là library chưa được production gọi; chưa có phép đo silence RMS trong đường chạy đó. Sửa validator không có nghĩa production đã có silence detection.
- CLI generation legacy hiện fail-fast và chỉ dẫn sang luồng Production; chưa phục hồi khả năng chạy generation độc lập. Chưa mở CapCut desktop để xác minh import thực tế.
- Podcast/LRC có segment dài hơn giới hạn clip hiện tại vẫn bị từ chối. Không tự cắt timestamp hoặc narration để làm test qua; hỗ trợ đoạn dài cần contract phân cảnh đồng bộ audio rõ ràng.
- Remaster `AGGRESSIVE` vẫn dùng fallback burn-in subtitle đã có trong source, chưa thay TTS. Chưa xác minh live signing hoặc download từ các nền tảng ngoài.
- Cleanup Colab đã bỏ các tham chiếu source được xác định; chưa đo VRAM trước/sau với model thật.

Sau kiểm tra, đã dừng ba process QA do phiên review khởi chạy và đóng riêng tab local QA; tab Colab/Google Flow của người dùng vẫn mở. Các file tạm/browser screenshot/test cache được giữ để kiểm tra, không tự dọn phần người dùng chưa yêu cầu.

## Bổ sung: ảnh tham chiếu người và thú cưng trên Colab

Phạm vi mới do người dùng yêu cầu: giảm vẻ giả/“nhựa”, kiểm tra nguồn cài đặt, chạy GPU thật rồi tối ưu và thử lại. Ảnh sản phẩm tiếp tục lấy từ người bán. Ba sub-agent `gpt-6.1-sol high` phụ trách worker, backend và UI; các kết quả GPU dưới đây được DevLead kiểm tra riêng.

Luồng đã triển khai: chọn provider Colab → chọn người/thú cưng và 1–3 ảnh tham chiếu → gửi job có ID duy nhất → worker tạo ảnh → lấy lại kết quả và xác minh hash → người dùng duyệt → chuyển ảnh đã duyệt sang dự án video. Tải lại trang không tạo lại job; mất tunnel giữ ID để kiểm tra tiếp. Kết nối chỉ nhận HTTPS Quick Tunnel công khai, chống redirect/SSRF; token ở bộ nhớ và không được ghi vào notebook hay receipt.

Stack hiện dùng Diffusers, RealVisXL V5 FP16 và IP-Adapter Plus SDXL ViT-H. Đây là conditioning theo ảnh, không bảo đảm giữ đúng danh tính. Chưa huấn luyện LoRA, chưa benchmark FLUX, chưa thêm custom node ComfyUI. Model và adapter khóa revision cùng SHA-256 cho 21 file JSON/TXT/safetensors, không chạy Python từ model repository hoặc nạp pickle.

### Kiểm tra nguồn cài đặt

- Đã loại các phiên bản sơ bộ Diffusers 0.35.1, Transformers 4.56.2 và Pillow 11.3.0 vì có advisory; các bản được duyệt và toàn bộ dependency khóa trong `colab/image_worker/requirements-lock.txt`.
- Đã kiểm tra 51 wheel Linux/Python 3.12: origin PyPI/upstream, SHA-256, advisory PyPI/OSV, đường dẫn archive và startup `.pth`. Không tìm thấy advisory khớp trong 51 wheel được cài; `.pth` duy nhất là shim distutils của setuptools được đối chiếu upstream. Pip bắt buộc hash và binary wheel, không tự resolve hoặc build source.
- Runtime giữ Torch 2.11.0+cu128/TorchVision 0.26.0+cu128 có sẵn, theo ngoại lệ được ghi rõ cho GHSA-rrmf-rvhw-rf47 (`torch.jit.script`). Worker không gọi JIT/compile hoặc nạp mã/model tùy ý. Không được diễn đạt toàn bộ runtime là “không có lỗ hổng”.
- Cloudflared 2026.9.3 từ release chính thức, kiểm tra digest asset và file; tắt tự cập nhật. Các cờ tắt remote code, implicit token và telemetry được đặt trước import.
- Windows Defender hiện tắt; **chưa thực hiện quét antivirus**. Kiểm tra nguồn/hash/advisory và một số đường thực thi không chứng minh mọi dependency không có mã độc. Bằng chứng chi tiết: `image-supply-chain/review-summary.json`, `wheel-inspection.json`, `package-audit.json`, `osv-audit.json`.

### Kiểm thử bổ sung

- Backend toàn bộ: **3235 passed**, 167.97 giây, một cảnh báo Starlette/TestClient; các sửa tiếp theo chạy focused regression riêng.
- Browser Colab image: React/API thật trên DB tạm, chỉ giả lập HTTP worker và Flow capability; 2 POST tạo ảnh, 3 refresh, không lỗi UI/API. Kiểm tra tải lại, duyệt/chuyển ảnh, mất acknowledgement, receipt lỗi, desktop/mobile và regression phản hồi tải kết nối ghi đè URL đang nhập. UI production build qua.
- Worker dùng unit test fake engine để kiểm contract/security; các test này không chứng minh chất lượng inference. GPU thật dùng hai ảnh public-domain `astronaut` và `chelsea` của scikit-image, không phải ảnh người/thú cưng do khách hàng cung cấp.
- Lượt GPU đầu dùng CPU offload bị SIGKILL trước khi có ảnh. Kernel Colab ghi cgroup OOM với một Python process khoảng 9 GB RSS; PID ở namespace kernel khác PID notebook, nên không khẳng định mapping chỉ từ số PID. Worker phục hồi đánh dấu hai job đang dở là interrupted, không tự phát lại.
- Cấu hình phục hồi giữ FP16 weights trên T4 và VAE decode FP32 theo tile 512 px; log đã xác nhận tất cả model weights ở CUDA FP16, khoảng 9.19 GB GPU allocated và 1.17 GB host RSS khi sẵn sàng. Hai ảnh 768×1344 đã hoàn tất trên GPU, nhập về backend, xác minh hash và xem trực tiếp.
- Baseline DDIM, 30 steps, CFG 5, IP-Adapter 0.6, seed 314159: người **27.553 giây**, mèo **27.580 giây** (chỉ thời gian engine, chưa gồm tải model/queue/network). Peak allocated khoảng **9.49 GiB**, reserved khoảng **10.59 GiB**. Receipt đầy đủ: `image-supply-chain/live-baseline-receipts.json`. Ảnh: `../../storage/verification/colab-image-live/`.
- Nhận xét baseline bằng mắt: da/tóc người và lông/ria mèo có texture gần ảnh chụp; người vẫn mang màu áo và phông nền hàng không của reference, không đạt yêu cầu đổi sang áo cotton cạnh cửa sổ. Mèo bị cắt một phần tai, mắt hơi lớn. Không đánh dấu các ảnh này đã duyệt.
- Sửa sau baseline: đưa prompt bố cục của người dùng/cảnh lên đầu, bỏ boilerplate lặp; worker đếm token bằng cả hai tokenizer SDXL, từ chối prompt/negative vượt 77 token trước inference thay vì cắt ngầm. Sampler DPM++ 2M Karras không thêm dependency. Bộ focused cuối chạy gộp **90 passed**, 18.93 giây (57 backend + 33 worker); UI build và diff check qua.

### Kết quả tối ưu và kiểm tra lại trên GPU

| Ảnh / cấu hình | Thời gian engine | Đánh giá trực tiếp |
| --- | --- | --- |
| Người, DPM++ Karras, strength 0.45, CFG 4.5 | 30.327 s | Đã đổi sang cạnh cửa sổ, áo cotton đơn giản; không còn phông tàu vũ trụ/logo lỗi của baseline. Texture da/tóc gần ảnh chụp; vẫn có sai khác khuôn mặt, chưa xác nhận danh tính 1:1. |
| Mèo, DPM++ Karras, strength 0.55, CFG 4.5 | 31.318 s | Lông/ria và mắt có chi tiết; bố cục vẫn quá sát ảnh tham chiếu. |
| Mèo, prompt yêu cầu đủ tai, strength 0.45, CFG 4.5 | 34.189 s | Tăng khoảng trống trên đầu, tai cải thiện nhưng gần mép trái. |
| Mèo, prompt căn giữa, strength 0.35, CFG 5 | 32.788 s | Giữ được tai trong khung tốt hơn và texture lông; vẫn là crop gần, chưa đạt hẳn một medium shot rộng. |

Cả sáu ảnh thành công đều 768×1344, 30 steps, seed 314159; peak allocated khoảng 9.49 GiB. Thời gian không gồm tải model, hàng chờ, tunnel hoặc import. Lượt tối ưu thay đổi cả prompt/sampler/strength/CFG, nên không quy mọi cải thiện cho riêng DPM++. Đây là đánh giá bằng mắt trên hai mẫu, chưa phải benchmark mù nhiều chủ thể hoặc bằng chứng mọi ảnh đều khó nhận ra là AI.

Ảnh và gallery so sánh: [`index.html`](../../storage/verification/colab-image-live/index.html). Chọn xem nhanh [`human-optimized.png`](../../storage/verification/colab-image-live/human-optimized.png) và [`pet-optimized.png`](../../storage/verification/colab-image-live/pet-optimized.png). Raw receipt của sáu ảnh và hai job interrupted: [`live-gpu-receipts.json`](image-supply-chain/live-gpu-receipts.json). Các ảnh vẫn **chưa duyệt** trong DB QA, không tự chuyển thành nhân vật/sản phẩm sản xuất.

Đã thử trực tiếp prompt quá dài trên worker thật: job `e1240058-6084-4d0d-ba60-2a0d7c9a61e0` bị từ chối bằng `prompt_too_long` và UI nhận hướng dẫn tiếng Việt; không cắt ngầm thành ảnh thành công. Đã xem ảnh nhập về trên UI qua endpoint media thật. Model code `engine.py` trên Colab trùng SHA-256 source cuối: `3d1778dc81e14bf1b96e0b0150905687d742ed9cdac2f00521abaf822812469a`.

Mặc định cuối: IP-Adapter 0.45, CFG 4.5, 30 steps; tăng strength để bám ngoại hình hơn có thể kéo theo nền/quần áo/crop gốc. Notebook đã chặn mở trùng worker/tunnel, và phần smoke mặc định tắt để Run All không dừng API. ZIP/notebook tải từ cùng source được ghép hash; ZIP cuối `1643a41674fea83a34ffde584c4374eaf78012753757e88dea5606c4e2e0fbd2`. Lượt GPU chạy trước thay đổi default/docs/guard notebook cuối; engine không đổi, các request GPU đã truyền tham số tường minh. Không khẳng định đã chạy nguyên notebook cuối từ một runtime sạch.

Kết thúc kiểm thử đã dừng riêng worker/tunnel ảnh Colab, xóa token kết nối QA trong bộ nhớ, VRAM về **3 MiB / 15360 MiB**; không ngắt runtime Colab hoặc Drive. Đã dừng backend/Vite QA và đóng tab QA trống; giữ nguyên Colab/Google Flow của người dùng. Gallery so sánh được mở trên Playwright tại `http://127.0.0.1:8102/`, chỉ phục vụ thư mục ảnh kiểm thử (HTTP server PID 21896). Gallery đã render: 8 ảnh tải đủ, không tràn ngang; screenshot lưu cùng thư mục. Source chưa commit/push; dữ liệu thử nằm trong DB riêng, không sửa DB sản xuất. Receipt ca prompt dài: [`live-prompt-limit-receipt.json`](image-supply-chain/live-prompt-limit-receipt.json).

## Bổ sung: ảnh người chất lượng cao và tạo nhân vật hư cấu từ đầu

Đã thay ảnh astronaut 512×512 trong ca thử người bằng ảnh **Andy Coffie, Portrait of a Woman in Urban Environment**, bản gốc **4000×6000 (24 MP)**, 1.495.039 byte. Trang tác giả ghi ngày chụp 13/10/2024. [Nguồn Pexels](https://www.pexels.com/photo/portrait-of-a-woman-in-urban-environment-29134265/), [giấy phép](https://www.pexels.com/license/), [bằng chứng nguồn/hash](image-supply-chain/human-reference-v2.json). Giữ nguyên file gốc, không phóng lớn hoặc retouch. Backend tạo bản gửi worker có cạnh dài tối đa 2048 px, chuẩn hóa EXIF/RGB và giới hạn dung lượng/pixel để nhận ảnh máy ảnh lớn an toàn hơn.

Ảnh này dùng kiểm thử chất lượng; giấy phép ảnh stock không chuyển quyền sở hữu danh tính người trong ảnh, không cho phép ngụ ý họ quảng bá sản phẩm. Chưa có tài liệu model release riêng. Với nhu cầu tạo nhân vật riêng, dùng chế độ mới **Colab tạo ảnh → Nhân vật hư cấu từ mô tả**: nhập brief → sinh ảnh không cần upload → duyệt → xuất ảnh hoặc chuyển sang dự án video. Không thể cam kết tuyệt đối tránh mọi khiếu nại bản quyền/quyền hình ảnh; [giấy phép model RealVisXL](https://huggingface.co/SG161222/RealVisXL_V5.0/blob/ac93e0dda1f6d448cae19bbfab8c5e720a5e48bc/README.md) vẫn áp dụng.

### Thực hiện và kiểm tra độc lập

- Ba sub-agent `gpt-6.1-sol high` thực hiện worker, backend và UI; DevLead kiểm tra source, thử GPU và xem ảnh xuất. Chế độ `text` chỉ dành cho người, gửi `references=[]`, không tự lấy ảnh có sẵn trong dự án. Worker gỡ IP-Adapter khỏi pipeline, không truyền dummy image hoặc `ip_adapter_image`; trở lại chế độ tham chiếu sẽ nạp lại adapter/encoder đã kiểm tra.
- Receipt bắt buộc xác nhận `generation_mode=text`, `reference_count=0`, `adapter_active=false`. Xuất portrait không cần ảnh đầu vào chỉ được phép khi có operation thành công và nguồn/hash khớp; không bỏ điều kiện tham chiếu của luồng cũ. Worker cũ chưa hỗ trợ text vẫn dùng được luồng tham chiếu; UI hướng dẫn cập nhật khi chọn text.
- Không thêm package, model hoặc custom node. Lock 51 wheel và 21 file model giữ nguyên; giới hạn audit và ngoại lệ Torch đã nêu ở trên vẫn còn. Bundle/notebook cuối có SHA-256 `7a7e002cc27553b731924a355aa0b66f7e8dcbaf6539c20abf1b582379e2fcc8`. Engine chạy thật trên Colab khớp source: `bfc7b867acf93f4c07eea049a9834c705078396df531d47cf503818819b9685a`.
- Bộ kiểm thử gộp `server/tests colab/tests`: **3292 passed**, 175,92 giây, một cảnh báo Starlette/TestClient. Hai kiểm tra focused sau chỉnh tương thích worker cũ/preview prompt cũng qua. Browser harness dùng React/API/DB thật, giả lập riêng worker ngoài: tạo dự án không ảnh → sinh → reload → duyệt → chuyển ảnh/hash → chọn cho video; 4 submit/5 refresh. UI production build cuối qua; diff check sạch.

### Bốn lượt Colab GPU thật

Tất cả dùng DPM++ 2M Karras, CFG 4.5, 768×1344. Thời gian chỉ tính engine.

| Ca thử | Cấu hình | Thời gian | Kết quả |
| --- | --- | --- | --- |
| Tạo người từ mô tả, lượt đầu | seed 271828, 30 steps | 28,850 s | Da/tóc/vải có texture tự nhiên; vẫn cười hở răng dù prompt yêu cầu khép môi. |
| Tham chiếu người 24 MP | seed 314159, 30 steps, strength 0.45 | 30,818 s | Đổi sang áo sáng màu/cạnh cửa sổ; chi tiết da và tóc tốt hơn mẫu cũ. Khuôn mặt vẫn thay đổi, IP-Adapter Plus không khóa danh tính 1:1. |
| Lặp lại text sau lượt tham chiếu | cùng prompt/seed/cấu hình lượt đầu | 33,234 s | SHA-256 giống hệt lượt text đầu: `6813b0463a5634db8f0a288706aaf9eee1acff36a945e9a28f93a411b8b53ff4`. Không thấy ảnh tham chiếu lưu lại làm điều kiện trong ca thử này. |
| Tinh chỉnh biểu cảm | seed 271829, 40 steps; neutral expression/lips closed; negative plastic skin/open mouth/teeth | 42,613 s | Môi khép, chi tiết da/tóc/vải tự nhiên; chọn làm mẫu kiểm tra xuất ảnh. Đây là nhân vật khác do đổi seed, không phải bằng chứng giữ danh tính qua biến thể. |

Đã xem trực tiếp cả bốn ảnh; đây là đánh giá bằng mắt trên số mẫu nhỏ, không phải benchmark mù. Lượt cuối đổi prompt, negative, seed và steps cùng lúc; không quy cải thiện riêng cho 40 steps. [Raw GPU receipts](image-supply-chain/human-v2-live-receipts.json), [gallery so sánh](../../storage/verification/human-character-v2/index.html), [ảnh hư cấu đã tinh chỉnh](../../storage/verification/human-character-v2/fictional-optimized.png), [ảnh tham chiếu gốc](../../storage/verification/human-character-v2/reference-original.jpg).

Đã duyệt media 13 và xuất project 4 trong **DB QA riêng** qua API thật: PNG/JPG/preview/listing/manifest đều có trong ZIP, mọi hash file khớp manifest, pixel RGB của PNG giao ra bằng đúng ảnh GPU. Manifest xác nhận `generation_mode=text`, `references=[]`. Bước duyệt quyền chỉ phục vụ kiểm tra quy trình trong QA, không phải phê duyệt xuất bản hoặc chứng nhận quyền thương mại. [Biên nhận xuất file](../../storage/verification/human-character-v2/export-verification.json), [bộ ZIP kiểm thử](../../storage/verification/human-character-v2/fictional-character-qa.zip). Chưa chạy video Flow mới từ nhân vật này.

Gallery mới ở `http://127.0.0.1:8103/`: năm ảnh tải đủ, không tràn ngang; đã chụp và xem screenshot. Các ảnh/mẫu thử mới không thay ảnh trong dự án sản xuất; source chưa commit/push.

Kết thúc lượt mới đã dừng worker/tunnel Colab và xóa token tạm ở Python/browser; GPU trở về **3 MiB / 15360 MiB**. Đã dừng backend/Vite QA và đóng tab app QA; giữ Colab/Flow cùng hai gallery. HTTP server gallery mới chỉ phục vụ thư mục `human-character-v2`, PID thực 20376. Không ngắt Colab runtime hoặc Drive.

## Bổ sung 2026-10-06: VTON cho nhân vật nữ và trang phục shop

### Phạm vi đã tích hợp

Luồng hiện tại: **tạo/chọn người → tải riêng ảnh sản phẩm → chọn loại trang phục →
Colab VTON → so ba ảnh → duyệt độ đúng của sản phẩm → dùng ảnh đã duyệt cho video**.
Nhánh tạo nhân vật SDXL vẫn độc lập. Chỉnh vòng 1/eo/hông ở nhánh đó hiện là mô tả
trong prompt; seed, steps, CFG không phải số đo cơ thể. Mô tả như `slim build,
narrow waist, slightly fuller bust, natural proportions` có thể giảm xu hướng
hiểu `curvy/voluptuous` thành đầy đặn toàn thân, nhưng không khóa số đo centimet.
VTON không nhận điều kiện văn bản; giao diện ẩn prompt trong chế độ này.

- Backend tách role `garment` khỏi ảnh nhận diện, giữ thứ tự person/garment, kiểm
  tra input hash/worker/model/receipt và job bất biến qua retry hoặc mất ACK.
- UI có lựa chọn riêng ảnh người, sản phẩm, loại đồ; khóa worker thiếu capability;
  so ảnh gốc với kết quả và yêu cầu checklist `garment_fidelity` trước khi tái sử dụng.
- Worker riêng **FASHN VTON 1.5, segmentation-free + flat-lay**; không nạp SDXL
  đồng thời. Chỉ nhận ảnh một trang phục trải phẳng, nền sạch. Chưa hỗ trợ ảnh shop
  có người mẫu; API từ chối photo type đó, không tự phân loại nội dung ảnh tải lên.
- Giữ output native **576×864**; không phóng lớn để giả độ phân giải. VN01 được
  aspect-fit nên ảnh kết quả có viền đen ngang khoảng 41/42 px. Upstream cắt viền
  sau sampling; giữ/cắt viền không giải quyết vấn đề chất liệu bị biến đổi.
- Duyệt/tái sử dụng kiểm tra lại nguồn operation, input và output hash. Xuất
  tham chiếu video giữ byte ảnh gốc. Luồng Flow mới chưa chạy bằng các ảnh VTON này.

### Audit nguồn, package và model

[Bản audit máy đọc được](vton-supply-chain/review-summary.json),
[kiểm tra wheel](vton-supply-chain/wheel-audit.json),
[OSV](vton-supply-chain/osv-audit.json).
Đối chiếu nguồn chính thức, project URL, phiên bản, SHA-256 và nội dung archive của
**56 wheel Linux/Python 3.12**, gồm 5 package bổ sung: einops, opencv-python-headless,
onnxruntime CPU, protobuf, flatbuffers. Không thấy package giả mạo hoặc startup hook
bất thường trong phạm vi kiểm tra; PyPI/OSV không trả advisory khớp cho 56 bản đã
khóa tại thời điểm audit. Đây không phải chứng nhận không malware.

**Không chạy antivirus**: Windows Defender antivirus và real-time protection đang
tắt. Không bật/tắt cấu hình bảo vệ của máy. Ngoại lệ Torch runtime hiện hữu
`GHSA-rrmf-rvhw-rf47` vẫn được ghi nhận: xác minh chính xác Torch 2.11.0+cu128 /
torchvision 0.26.0+cu128; không gọi JIT/compile, không tải checkpoint pickle hoặc
remote model code. Bộ 56 wheel không cài đè Torch. Setuptools `.pth`/launcher và
pickle fixture trong test của NumPy được ghi riêng; worker không dùng fixture đó.

Nguồn FASHN khóa commit `7c0f10af3f91ad4048fe9729c470a13ef905d25a`, có LICENSE/NOTICE
và source inventory đầy đủ. Model FASHN khóa revision
`7720683168567eb5a2a4c67f15116c6e29c83ded`; DWPose khóa
`548b5df25b84d9f4aac0611dfa1c2a7a12f15571`. Chỉ tải và kiểm hash **3 file**
safetensors/ONNX, khoảng 2,295 GB; inference chạy offline. Không cài ComfyUI custom
node, không chạy install script từ repo, không gọi human parser/SegFormer.
Nhánh parser bị loại do giới hạn giấy phép; không coi giấy phép model là quyền
sử dụng ảnh shop, logo hoặc danh tính người. Nguồn:
[FASHN code](https://github.com/fashn-AI/fashn-vton-1.5),
[model](https://huggingface.co/fashn-ai/fashn-vton-1.5),
[DWPose](https://huggingface.co/fashn-ai/DWPose).

ZIP VTON cuối: `dc576fe1586d72e9c0fe1878ebf0b19f598c1ff4bf95300b6c513285fb658e3a`.
Bootstrap đối chiếu requirements/model/source-lock với phê duyệt, cài trong venv
riêng bằng wheel khóa hash, không tự resolve dependency. Shared API đổi injection
nên ZIP SDXL được ghép lại: `1d3e7cec00306f757d14d10e95dee298fcac14f4767ccc0e8d6f76c6812fffea`.

### Kiểm thử tích hợp và GPU thật

- Toàn bộ `server/tests colab/tests`: **3385 passed**, 248,98 giây. Sau khi hoàn
  tất guard cuối, chạy lại 5 file liên quan: **184 passed**, 156,91 giây. Một
  cảnh báo Starlette/TestClient deprecation, không phải lỗi VTON.
- UI production build qua. Browser harness React/API/DB thật với worker giả lập:
  upload riêng hai role → capability block → gửi → mất ACK/reload/refresh → so ảnh
  → fidelity gate → approve → chuyển đúng hash sang video; 2 download notebook/ZIP,
  1 submit/2 refresh, không lỗi trang/API, mobile không tràn ngang. Luồng Colab ảnh
  cũ cũng qua browser regression. [Screenshot](../../storage/verification/vton/desktop.png).
- Runtime Colab **L4, Python 3.12.13, BF16**, mới; cài đúng bundle/model đã audit.
  Không mount Drive hoặc sửa dữ liệu sản xuất. Token worker chỉ tồn tại trong bộ
  nhớ phiên; không in token ra output notebook hoặc lưu trong receipt.
- VN01 hư cấu là input người. Sản phẩm lấy từ ví dụ FASHN Space có revision cố
  định, chỉ dùng QA; chưa có ảnh shop riêng do người dùng cung cấp trong lượt này.
- Kết quả thật được nhập qua API vào SQLite QA riêng, kiểm SHA-256 và xem trong UI
  với ảnh nguồn. Gallery và toàn bộ biên nhận:
  [so sánh](../../storage/verification/vton-live/index.html),
  [GPU receipts](../../storage/verification/vton-live/live-gpu-receipts.json).

| Lượt | Thời gian engine | Đánh giá bằng mắt |
| --- | --- | --- |
| Áo nhún, 30 bước, guidance 1,5 | 28,659 s | Màu và tay áo thêu lỗ khá đúng; phần thân mất vải nhún, đổi eo/quần/tay. |
| Cùng ảnh/seed, 50 bước, 1,5 | 45,180 s | Không cải thiện rõ phần vải nhún; chưa đủ để duyệt sản phẩm. |
| Cùng ảnh/seed, 50 bước, 2,5 | 45,386 s | Tự thêm dây chuyền, đổi quần nhiều hơn; loại cấu hình này. |
| Ảnh áo cắt bớt nền, 50 bước, 1,5 | 45,322 s | Texture nhỉnh hơn nhẹ nhưng vẫn không đúng chất vải nhún; không xem là đã khắc phục. |
| Áo thun đơn giản, 30 bước, 1,5 | 27,568 s | Giữ màu đen, cổ/tay áo và chữ FASHNAI khá tốt; biểu tượng nhỏ, dáng và quần vẫn cần đối chiếu. |

Tất cả cùng seed 314159, output 576×864; peak allocated **2.72 GiB**, reserved
**3.50 GiB**. Thời gian không gồm tải model/hàng chờ/tunnel/import. Crop chỉ bỏ
margin trắng, giữ đủ áo, không vẽ lại hoặc phóng lớn; có
[biên nhận crop](../../storage/verification/vton-live/garment-crop.json).
Đây là 5 ảnh của một người hư cấu và hai áo mẫu, không phải benchmark đa chủ thể.
Chưa kiểm GPU T4, quần/chân váy hoặc đồ liền thân. Không có cơ sở tăng default lên
50 bước/CFG 2,5; giữ **30 bước / 1,5**. Tất cả media vẫn chưa duyệt; không xuất
ZIP thương mại, không gửi lên Flow. Sample đơn giản cho kết quả khả dụng để xem
thử, nhưng sản phẩm nhiều chi tiết chưa đạt fidelity để tự động làm affiliate.

Pipeline trên GPU có SHA `5ba8b3a0ac2b514ee6fe67187fbe69aee9598336e79a59a5a1bbbe8d6d3413eb`,
source-lock khớp phê duyệt. [Bằng chứng runtime và dừng worker](../../storage/verification/vton-live/runtime-cleanup.txt).
Sau khi tải đủ năm ảnh và kiểm hash, đã dừng riêng worker/tunnel, xóa token tạm
ở Python/browser/backend QA; GPU về **3 MiB / 23034 MiB**. Tiếp tục ngắt và xóa
runtime Colab; **Quản lý phiên xác nhận “Không có phiên nào đang hoạt động”**.
[Ảnh xác nhận](../../storage/verification/vton-live/colab-no-active-sessions.png).
Đã dừng backend QA cổng 8105. Không thay đổi DB sản xuất, không commit/push.
Gallery hiển thị đủ 15 ảnh so sánh và không tràn ngang, mở tại
`http://127.0.0.1:8106/vton-live/`; HTTP server PID 14684 chỉ phục vụ thư mục
verification trên localhost, không dùng GPU. Loại runtime của notebook đang để L4
sau lượt thử này; việc chọn L4 không tạo phiên mới sau khi đã ngắt.
