# AIFlow audio worker v1

Chỉ cài worker này trong Colab/GPU runtime từ xa. Backend AIFlow trên Windows không cài các dependency tại đây.

## Chạy theo phiên

1. Mở AIFlow `/connections`, tải notebook và `aiflow-audio-worker.zip`.
2. Mở Colab, Upload notebook, chọn GPU.
3. Chạy các cell upload bundle, mount Drive, cài dependency và nạp model.
4. Nếu sử dụng API phù hợp điều khoản Colab, chạy cell API/tunnel và lấy URL + token.
5. Dán vào AIFlow, Kiểm tra kết nối, chọn tác vụ, Lưu và tiếp tục.
6. Khi xong, dừng API rồi Disconnect and delete runtime trong Colab.

Token chỉ tồn tại theo phiên; notebook không chứa token sẵn. Không lưu/chia sẻ cell output có token. Không bật notebook khi chỉ sửa kịch bản.

## Batch không cần tunnel

- Sao chép JSON profile từ cell nạp model vào phần Batch của trang kết nối.
- Tạo tác vụ AIFlow, tải JSON bằng Xuất batch JSON.
- Upload JSON trong cell Batch. Notebook dùng cùng input hash/checkpoint như API.
- Nhập ZIP kết quả vào đúng tác vụ AIFlow. Không cần GPU local hoặc đường truyền API.
- ZIP nhập tối đa 128 MiB, tổng dữ liệu giải nén tối đa 256 MiB. Chia tác vụ dài nếu vượt ngưỡng.

## Hợp đồng

- `GET /v1/health`, `GET /v1/voices`.
- `POST /v1/tts/jobs` trả 202; `Idempotency-Key` bằng SHA256 của JSON canonical (sort keys, UTF-8, ensure_ascii=False, separators comma/colon).
- Input: text, voice_id, language=en, speed (float), model_revision, output_format=wav.
- `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/result`, `POST /v1/jobs/{id}/cancel`.
- POST với `retry=true` chỉ khi người dùng chủ động tiếp tục; polling thông thường không chạy lại job lỗi.
- Mọi endpoint dùng Bearer token. API docs bị tắt. Không có upload model hoặc thực thi lệnh qua API.

## Phiên bản và giới hạn

- Kokoro package 0.9.4; model HF được khóa theo commit SHA ở lần tải đầu, lưu `kokoro-revision.txt` trên Drive. Giữ file này khi chạy lại.
- Chỉ tiếng Anh, bốn giọng có sẵn; không STT, không clone giọng, không tự đổi model.
- Một GPU job chạy mỗi lần; queue remote tối đa 16.
- File WAV PCM16/24kHz và manifest lưu dưới `MyDrive/AIFlow/audio-worker/jobs`.
- Dừng giữa chừng không có checkpoint bên trong một đoạn; lần tiếp theo tạo lại đoạn chưa hoàn tất.
- Chưa benchmark hoặc xác nhận runtime/driver Colab thực tế. Các phiên bản cài đặt có thể cần điều chỉnh sau khi người dùng chạy notebook.

Nguồn: [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), [Colab FAQ](https://research.google.com/colaboratory/faq.html), [Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).
