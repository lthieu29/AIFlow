# Codex qua CAO + tmux trong WSL

Ngày triển khai: 28/09/2026. Provider trong xưởng giữ ID `codex_cli` để tương thích dữ liệu, nhưng đường thực thi mới là **Codex tương tác qua CAO/tmux**, không gọi `codex exec` hay OpenAI API key.

## Trạng thái thực tế

- Đã nối cấu hình, chạy từng bước biên tập, lưu receipt, theo dõi, hủy, timeout, nhận JSON và kiểm tra schema/rubric vào Script Studio.
- Đã thêm launcher bắt buộc ChatGPT login, workspace-write, không tự chấp nhận nâng quyền; từ chối `--yolo`. Dùng bản CAO trong `cli-agent-orchestrator`, không sửa source CAO.
- Máy Windows hiện chỉ liệt kê distro `docker-desktop`. **Chưa cài Ubuntu, chưa đăng nhập Codex trong WSL, chưa chạy CAO/tmux thật hoặc inference.**
- TypeScript/Ruff đã qua; xem mục kiểm tra cuối tài liệu. Không có tuyên bố nghiệm thu vận hành từ các kiểm tra tĩnh.

## 1. Cài một lần

Trong PowerShell:

```powershell
wsl --install -d Ubuntu
```

Làm theo yêu cầu Windows nếu cần quyền quản trị/restart. Mở Ubuntu và tạo user Linux thông thường. Không dùng distro `docker-desktop` và không chạy CAO bằng root.

Trong Ubuntu, cài Node.js LTS bằng cách bạn đang quản lý Node, kiểm tra `node --version` và `npm --version`. Cài Codex CLI cho user đó; phiên Windows được đọc ở đợt trước là `0.156.1`, có thể ghim cùng phiên bản để hạn chế thay đổi TUI:

```bash
npm install -g @openai/codex@0.156.1
cd /mnt/d/Project/AIFlow/app/codex_tmux
bash setup.sh
codex login
```

Chọn đăng nhập **ChatGPT**. Việc đăng nhập trên Windows không tự chứng minh phiên Ubuntu đã đăng nhập. Setup không sao chép `auth.json`, không sửa config Codex toàn cục. Nếu repo được chuyển ổ/thư mục, thay đường dẫn trên và chạy setup lại.

`setup.sh` dùng sudo cho apt để cài Python/venv/build tools/tmux; tạo venv CAO từ source repo hiện có. Setup không chạy prompt. Cài Node/Codex trước khi chạy setup; npm global phải thuộc quyền user Linux, không dùng root cho phiên đăng nhập.

## 2. Mỗi lần dùng

Trong Ubuntu:

```bash
cd /mnt/d/Project/AIFlow/app/codex_tmux
python3 bridge.py serve
```

Giữ cửa sổ này chạy. CAO chỉ bind `127.0.0.1:9891`, có token cục bộ tự tạo, không cần public API/tunnel. AIFlow gọi bridge bằng `wsl.exe --distribution ... --exec python3 ...`; prompt truyền qua stdin, không nội suy vào câu lệnh shell. Tmux dùng socket riêng dưới thư mục dữ liệu AIFlow và shell không đọc rc để giữ đúng launcher PATH (kể cả khi dùng nvm); không sửa tmux server/config của các phiên cá nhân. Session `aiflow-control` chỉ giữ server, không chạy model.

1. Khởi động lại AIFlow sau cập nhật source.
2. Mở `/studio-settings` → **Codex qua tmux / WSL**.
3. Nhập đúng tên distro (`wsl --list --quiet`), timeout 120–3600 giây; mặc định 1200 giây.
4. Kiểm tra điều kiện credits của tài khoản và xác nhận trên giao diện. Bấm **Kiểm tra & bật cho phiên AIFlow này**. Kiểm tra chỉ đọc login status và CAO sessions, không tạo lượt AI.
5. Vào `/scripts`, tạo/chọn brief, chọn **Codex · ChatGPT qua tmux**, model `default` hoặc tên model có trong tài khoản. `default` giữ model cấu hình ở Codex WSL; ứng dụng ghi đây là model yêu cầu, không giả nhận biết model thực tế.
6. Bấm tạo dàn ý/kịch bản/review/revise. Có tối đa một lượt Codex chưa đóng trong bridge. Muốn lượt khác phải đồng bộ/dừng lượt cũ.

**Ngừng nhận tác vụ mới** không hủy lượt đang chạy. Mỗi lần restart backend cần kiểm tra/bật lại để tạo lượt mới. Đồng bộ/hủy lượt cũ dùng distro được lưu cùng tác vụ, không bị đổi theo cấu hình mới.

## 3. Subscription và credits

Launcher bỏ các biến môi trường OpenAI/Codex có thể mang credential/endpoint, kiểm tra `codex login status`, ép `forced_login_method="chatgpt"` và provider OpenAI khi khởi chạy. Không tự chuyển API key/provider/model khi lỗi, không mua credits, không tự trả lời đề nghị mua/nâng cấp.

**Đây không phải cơ chế khóa chi tiêu ở phía OpenAI.** Nếu tài khoản có credits bổ sung khả dụng thì ChatGPT auth/tmux vẫn có thể sử dụng chúng sau hạn mức gói. Để giữ yêu cầu subscription-only, người dùng phải kiểm tra không có credits bổ sung khả dụng và không bật tự nạp; AIFlow không tự xác minh được thiết lập billing đó. Checkbox trên UI ghi rõ giới hạn này, không biến nó thành bảo đảm kỹ thuật.

Tài liệu chính thức: [Authentication](https://learn.chatgpt.com/docs/auth), [Pricing](https://learn.chatgpt.com/docs/pricing), [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference). Tên `exec` hay `tmux` không quyết định nguồn tính phí; phương thức xác thực và thiết lập tài khoản mới có liên quan.

## 4. Lượt chạy, dừng và khôi phục

```text
Chọn provider → kiểm tra cấu hình → lưu ScriptRevision
    → lưu receipt WSL → CAO tạo một phiên tmux và gửi một prompt
    → Codex đọc input.json → ghi result.json → kiểm tra mã tác vụ
    → đóng phiên → AIFlow kiểm tra schema/rubric → lưu checkpoint kịch bản

Mất kết nối → giữ mã lượt → đồng bộ lượt cũ (không gửi lại)
Chờ thao tác → attach tmux / dừng
Hết timeout → đóng riêng phiên → giữ file/log để xem
```

- Trên phiên bản đang chạy có lệnh `python3 .../bridge.py attach <id>`. Dùng lệnh đó trong terminal Ubuntu đúng distro để mở đúng socket/session và xử lý yêu cầu. `Ctrl+B`, sau đó `D` để detach, giữ phiên tiếp tục.
- UI tự đồng bộ khoảng 5 giây/lần khi mở phiên bản đang chạy; có nút đồng bộ thủ công. Một watchdog WSL tiếp tục kiểm tra/timeout khi đóng trình duyệt. Nếu cả WSL dừng, cần bật lại CAO và đồng bộ; không tự tạo lại phiên/prompt.
- `Dừng Codex` đóng đúng session `cao-aiflow-<request UUID>`, không kill tmux server hay session của bạn. Khi CAO offline, bridge cố đóng session trực tiếp bằng tmux; nếu không xác nhận được, báo lỗi và giữ tác vụ chưa đóng.
- Timeout không thu hồi quota đã tiêu. Tắt cửa sổ CAO không phải cách hủy Codex: hãy bấm Dừng tác vụ trước.
- Mất phản hồi khi tạo phiên: bridge tra session tên cố định, không retry POST tạo phiên. Một lượt chưa rõ kết quả vẫn chặn lượt mới.
- Kết quả phải có envelope `{"request_id":"...","content":{...}}`. Thiếu file dù Codex đã trả lời → chờ người dùng xử lý. JSON/schema/rubric sai → lỗi, giữ file để sửa/nhập tay, không tự dùng thêm quota để sửa.
- Thành công đóng phiên để giải phóng giới hạn một terminal; muốn chỉnh sửa tiếp dùng bước biên tập mới. Không reuse conversation cũ giữa các dự án.

## 5. Dữ liệu và quyền

```text
~/.local/share/aiflow-codex/
  installation.json       # đường dẫn Codex, phiên bản; không credential
  token                   # token CAO private, không trả về UI
  venv/                   # CAO runtime
  bin/codex               # launcher có kiểm tra ChatGPT
  cao/                    # cấu hình/data/log riêng của CAO
  jobs/<request UUID>/
    state.json            # receipt, terminal/session, deadline, kết quả
    chatgpt-launch.json   # xác nhận launcher đã qua kiểm tra login
    terminal.log          # snapshot nếu đọc được trước khi đóng
    watch.log
    work/
      input.json          # prompt/schema của lượt
      result.json         # envelope kết quả
```

Workspace của agent chỉ là `work/`. Receipt ở bên ngoài vùng ghi của agent. Profile CAO chỉ định marker `aiflow_script`; launcher bỏ marker và truyền chính sách trực tiếp, không tạo profile trong `.codex/config.toml` toàn cục. Nếu không đi qua launcher thì marker thiếu sẽ làm Codex từ chối khởi động thay vì âm thầm chạy mặc định; chỉ kết quả có receipt launcher mới được nhận. Không cấu hình `allowedTools: ["*"]` vì CAO sẽ ép `--yolo` và launcher từ chối.

Không dùng cơ chế tự động multi-agent/memory của CAO. Lịch sử kịch bản dùng bảng `ScriptRevision` và `usage_json` sẵn có; không cần migration mới.

## 6. Bản đồ thay đổi và kiểm tra

| File | Vai trò |
|---|---|
| `codex_tmux/setup.sh`, `aiflow_script.md` | môi trường WSL và profile riêng |
| `codex_tmux/launcher.py` | chốt auth/quyền trước Codex |
| `codex_tmux/bridge.py` | CAO REST, receipt, watchdog, file kết quả, dừng |
| `server/text/codex_tmux.py` | nối SQLite với WSL, kiểm tra schema/rubric |
| `server/api/routes/scripts.py` | configure/step/sync/cancel |
| `ui/src/components/CodexTmuxSettings.tsx` | cấu hình và trạng thái môi trường |
| `ui/src/pages/ScriptStudio.tsx` | chọn model, chạy và khôi phục lượt |

Kiểm tra đợt này: TypeScript, Ruff `F,E9`, frontend production build, Python AST, `git diff --check`. Không thêm/chạy tests. Chưa nghiệm thu WSL/CAO/tmux/Codex thật hoặc giao diện browser; chưa sửa billing, đăng nhập tài khoản hay tiêu quota. CAO nhận biết trạng thái dựa trên TUI nên cập nhật Codex CLI cần nghiệm thu lại. Các kiểm tra trước trong tài liệu khác không áp dụng thay cho luồng mới này.
