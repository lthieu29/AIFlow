# Huấn luyện giọng: chọn dữ liệu R2 trước khi tải

**Bản mới:** ưu tiên [hướng dẫn điều khiển từ web](STUDIO_COMPLETION_V2.md), dùng `control_voice_training.ipynb`. Có train/status/resume, duyệt transcript, đổi giọng cùng phiên và batch không tunnel. Phần cách dùng notebook bên dưới là phương án thủ công dự phòng.

## Phạm vi đã triển khai

Luồng được chốt: **quét metadata → người dùng chọn file của một giọng → xuất gói lựa chọn → Colab tải đúng file → duyệt dataset → fine-tune LoRA → nghe/duyệt giọng → lưu và load từ My Drive → API TTS**.

Không chạy model trên máy Windows. Quét R2 chỉ dùng `ListObjectsV2`, đọc toàn bộ các trang trong bucket/prefix; không gọi `GetObject`. Hệ thống không nhận diện người nói từ tên file. Việc chọn giọng ở bước này là chọn dữ liệu mà người dùng biết thuộc cùng một người nói.

Fine-tune sử dụng VieNeu v3 Turbo, cập nhật trọng số qua LoRA rồi merge model. Preset đi kèm chứa speaker embedding, không dùng reference codes làm phương án thay thế cho huấn luyện.

## Cách dùng

### 1. Cập nhật ứng dụng

Cài dependency bổ sung `boto3>=1.35,<2` vào đúng Python environment đang chạy server (hoặc cài lại dependencies từ `app/pyproject.toml`). Khởi động lại backend và frontend sau cập nhật.

Vào **Huấn luyện giọng**, đường dẫn `/voice-training`.

### 2. Quét và chọn trên trang quản lý

1. Nhập Account ID, bucket, jurisdiction (mặc định nếu không cấu hình riêng), prefix tùy chọn.
2. Nhập **R2 S3 Access Key ID / Secret Access Key**, quyền **Object Read**, giới hạn đúng bucket. Đây không phải chuỗi Cloudflare bearer API token.
3. Bấm **Quét danh sách • chưa tải media**. Không cần bật public access.
4. Lọc theo thư mục/tên, chọn từng file hoặc chọn nhóm theo bộ lọc. Ban đầu không có file được chọn.
5. Nhập tên giọng, ngôn ngữ `vi` hoặc `en`; xác nhận các file thuộc cùng một người nói và được phép sử dụng để huấn luyện.
6. Bấm **Chốt lựa chọn & tải gói Colab**. ZIP chỉ chứa notebook, helper, worker và `selection.json`; không chứa audio hay khóa R2.

Đuôi được hỗ trợ: mp3, wav, flac, m4a, ogg, aac, opus, mp4, mov, mkv, webm; không phân biệt hoa/thường. File rỗng bị bỏ qua.

Giới hạn một lần quét: 100.000 object / 20.000 file media. Nếu vượt giới hạn, API báo lỗi yêu cầu prefix hẹp hơn, không âm thầm trả danh sách thiếu. Một bộ chọn tối đa 5.000 file, mỗi file tối đa 2 GiB, tổng tối đa 20 GiB. Danh sách nằm trong RAM trong 1 giờ, tối đa 5 lần quét gần nhất; restart backend thì phải quét lại. Khóa không ghi vào manifest/storage, ô nhập khóa được xóa sau khi quét thành công.

### 3. Chạy Colab khi thực sự cần

Giải nén ZIP, mở `finetune_r2.ipynb` trong Colab, chọn GPU. **Chạy từng ô, không Run all.**

- Ô 1: upload chính ZIP đã tải, mount My Drive. Chưa tải media.
- Ô 2: cài môi trường Colab.
- Tạo Colab Secrets `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` và cho notebook quyền đọc. Không paste khóa vào code hoặc chat.
- Ô 3: tải file theo manifest. `HEAD` kiểm tra ETag, kích thước, LastModified; GET có `IfMatch`. Nếu file đổi sau lúc quét, quay lại quét/chọn mới. Tải dạng stream; tên file trên Drive dùng hash của object key. File đã tải được kiểm tra SHA-256 để tái sử dụng.
- Ô 4: Whisper trên Colab chép lời, FFmpeg tách audio mono 24 kHz thành đoạn 1–20 giây. Không tự phân tách danh tính người nói. Bản đầu tạo `review.json`; chạy lại không ghi đè các sửa đổi đã lưu.
- Ô 5: nghe từng đoạn được dùng, sửa transcript, bỏ đoạn sai người/nhạc/lỗi; **Lưu / đã nghe đoạn**. Cuối cùng bấm **Duyệt dataset**. Đổi transcript sẽ hủy trạng thái duyệt. Cần ít nhất 20 đoạn, nên có 10–30 phút audio sạch và đa dạng câu.
- Ô 6: prepare dataset rồi trainer AIFlow dùng các primitive LoRA tại commit `c1390abbdb2eedcdf58eafb546966c06ce27af71`. Revision base model và Whisper ghi vào Drive từ lần đầu. Batch 1, gradient accumulation 16, gradient checkpointing; chỉ bật BF16 nếu GPU hỗ trợ.
- Ô 7: tạo mẫu với câu chưa dùng trong dataset, nghe, xác nhận và duyệt giọng.
- Ô 8–10: chọn giọng đã duyệt, load model trên GPU, bật worker và Cloudflare Quick Tunnel. Copy URL/token vào **Colab & audio**, **Kiểm tra → Lưu**. Giọng xuất hiện trong bộ chọn để tạo TTS.
- Ô 11: dừng API rồi **Disconnect and delete runtime** khi xong.

**Không gửi model về máy Windows để chạy.** Worker dùng model merged trên Drive, API trả WAV 24 kHz cho pipeline hiện tại. Mỗi runtime phục vụ một model/giọng tại một thời điểm; nhiều giọng/phiên bản có thể cùng lưu trên Drive. Notebook điều khiển mới cho đổi model khi worker rảnh, sau đó cập nhật kết nối audio.

### 4. Lần sau chỉ load giọng

Dùng lại ZIP và notebook: chạy ô 1, 2, 8, 9, 10. Không chạy ô tải, ASR hoặc train. Không cần R2 Secrets nếu không tải dữ liệu. Bộ chọn ở ô 8 lấy các profile đã duyệt từ Drive.

## Cấu trúc My Drive

```text
AIFlow/voice-training/
  <job-id>/
    selection.json                 # đúng các file được chọn, không có secret
    source/                        # media đã chọn
    downloads.json                 # receipt và SHA-256
    asr-revision.json
    base-revision.json
    review.json                    # transcript, include, reviewed, checksum audio
    dataset-approved.json
    dataset/raw_audio/
    dataset/metadata.csv
    dataset/train.parquet
    runs/<run-id>/
      status.json
      review.json                  # snapshot dataset đã duyệt cho lượt train
      train.parquet                # snapshot dữ liệu đã mã hóa
      trainer-config.json
      environment.txt
      trainer-state.pt             # adapter, optimizer, scheduler, RNG, vị trí dữ liệu
      progress.json
      adapter/
      merged/                      # model đã fine-tune + preset giọng
      profile.json                 # chỉ có sau khi train/đóng gói hoàn tất
      sample.wav
      sample.json
  model-cache/
  hf-cache/
```

Profile ghi trạng thái duyệt, ngôn ngữ, hash weights/preset và revision base/code. Load giọng kiểm tra hash, không tự chuyển sang base model nếu thiếu/hỏng fine-tune.

## Trạng thái, lỗi và khôi phục

| Tình huống | Hành động |
|---|---|
| Sai khóa/quyền/bucket/jurisdiction | Sửa nguồn R2 rồi quét lại; chưa tải media |
| Quét rỗng | Kiểm tra prefix/đuôi file; không cho xuất bộ rỗng |
| Danh sách hết hạn, backend restart | Quét/chọn lại |
| Đổi nguồn hoặc dữ liệu chọn | Xóa lựa chọn/xác nhận cũ; chốt lại |
| File R2 thay đổi trước lúc tải | Dừng; quét/chọn lại để lấy snapshot mới |
| Ngắt khi tải | Chạy lại ô 3; giữ file hoàn tất đúng checksum, tải lại file chưa hoàn tất |
| Ngắt trong ASR trước khi có `review.json` | Chạy lại ô 4; bước ASR chạy lại, không có resume theo từng câu |
| ASR sai lời/khác người | Sửa hoặc bỏ đoạn ở ô 5; không train trước duyệt |
| Hết VRAM/runtime khi train | Kết nối lại notebook điều khiển, resume cùng run nếu có checkpoint và cấu hình khớp |
| Train xong chưa duyệt thì ngắt | Ô khôi phục cuối notebook chọn bản lưu, rồi chạy ô 7 |
| Tunnel ngắt | Bật lại runtime/model/API, nhập URL/token mới trong AIFlow |
| Muốn đổi giọng | Chọn profile đã duyệt trên web, load khi worker rảnh, cập nhật kết nối audio |

CLI LoRA upstream chỉ lưu adapter. Trainer AIFlow mới bổ sung optimizer/scheduler/RNG và vị trí dữ liệu ở ranh giới optimizer; chỉ run mới có checkpoint đầy đủ mới resume được. Không tự xóa run/dataset cũ; không bảo đảm kết quả bit-for-bit giữa các GPU/môi trường khác nhau.

## Bản đồ triển khai / UX

Archetype: operations-console; adapter: product-ui. Giữ React/Tailwind và style trang quản lý hiện có.

| Bề mặt | Trách nhiệm |
|---|---|
| `ui/src/pages/VoiceTraining.tsx` | nguồn R2, loading/error/empty, phân nhóm, chọn và chốt một giọng, xuất ZIP, hướng dẫn handoff |
| `server/api/routes/voice_training.py` | `POST /api/voice-training/scan`, `POST /api/voice-training/bundle`; inventory metadata và xác thực lựa chọn |
| `colab/voice_training.py` | tải có kiểm tra, ASR/cắt đoạn, duyệt transcript, CLI fine-tune, lưu/load model, nối worker |
| `colab/finetune_r2.ipynb` | từng bước GPU, Drive, Secrets, huấn luyện và tunnel |
| `colab/audio_worker/app.py` | API v1 dùng metadata/ngôn ngữ của model được load; Kokoro vẫn là mặc định |
| `AudioStudio`, `VoiceGallery`, `api/client.ts`, `audio/remote.py` | danh sách giọng remote, đường vào huấn luyện, ngôn ngữ theo giọng đã chọn |

Trang quản lý mới có bridge `/api/training-control` và hiển thị trạng thái/bước optimizer từ Colab. ZIP/notebook thủ công vẫn dùng được. Không dùng public bucket root để cố liệt kê file. Không tự phát hiện người nói hoặc tách giọng khỏi nhạc.

## Kiểm chứng và giới hạn hiện tại

- Đã đọc đối chiếu CLI và constructor inference của VieNeu ở commit cố định, kiểm tra tĩnh cú pháp Python/cell notebook và TypeScript.
- Chưa chạy thử R2 thật, GPU Colab hoặc đánh giá chất lượng giọng sau train; cần tài khoản, dữ liệu và phiên Colab của người dùng.
- Chưa chạy unit/integration/UI tests cho phần bổ sung này.
- Colab Pro không bảo đảm GPU cụ thể hoặc runtime vô hạn. Batch nhỏ không bảo đảm mọi GPU đều đủ VRAM.
- Các dependency cài bằng pip còn dùng khoảng phiên bản; code engine và model được ghim, nhưng chưa có lockfile môi trường Colab đã kiểm chứng.

## Nguồn chính thức

- [Cloudflare: S3 API compatibility / ListObjectsV2](https://developers.cloudflare.com/r2/api/s3/api/)
- [Cloudflare: R2 API tokens, quyền Object Read](https://developers.cloudflare.com/r2/api/tokens/)
- [Cloudflare: boto3 với R2](https://developers.cloudflare.com/r2/examples/aws/boto3/)
- [VieNeu fine-tune README tại commit đã ghim](https://github.com/pnnbao97/VieNeu-TTS/blob/c1390abbdb2eedcdf58eafb546966c06ce27af71/finetune/README.md)
- [CLI train_lora: tham số và cách lưu checkpoint](https://github.com/pnnbao97/VieNeu-TTS/blob/c1390abbdb2eedcdf58eafb546966c06ce27af71/finetune/train_lora.py)
- [make_voice: preset sau fine-tune](https://github.com/pnnbao97/VieNeu-TTS/blob/c1390abbdb2eedcdf58eafb546966c06ce27af71/finetune/make_voice.py)
- [Colab FAQ](https://research.google.com/colaboratory/faq.html)
