---

# 🔐 BÁO CÁO PHÂN TÍCH BẢO MẬT — 5 PROJECT

---

## PROJECT 1: MoneyPrinterTurbo

### 1. Tổng quan
- **Loại**: Web App + API (Python FastAPI + Streamlit WebUI)
- **Runtime**: Python ≥3.11, uvicorn, streamlit
- **Chức năng**: Tạo video ngắn từ AI prompt, TTS, subtitle

### 2. Dependencies
| Package | Nhận xét |
|---|---|
| `g4f==0.5.2.2` | **Đáng chú ý** — thư viện truy cập GPT-4 không chính thức (reverse-engineered), gửi request đến server bên thứ 3 không kiểm soát được |
| `socksio==1.0.0` | SOCKS proxy support — không độc hại nhưng cho phép route traffic qua proxy ẩn danh |
| `litellm==1.60.0` | Bình thường — LLM proxy layer |
| Các package còn lại | Tất cả đều là package nổi tiếng, version được pin hợp lệ |

Không phát hiện typosquatting, lifecycle scripts, hay git URL.

### 3. Code nguy hiểm
- **`ast.literal_eval()`** tại `@d:\Project\AIFlow\MoneyPrinterTurbo\app\services\state.py:135` — **SAFE**: `literal_eval` chỉ parse Python literal, không thực thi code tùy ý.
- **[subprocess.run()](cci:1://file:///d:/Project/AIFlow/daihuo-jianshou/src/lib/script-engine/generator.ts:243:2-278:4)** tại `@d:\Project\AIFlow\MoneyPrinterTurbo\app\services\video.py:116` — dùng array (không phải `shell=True`), không có user-input trực tiếp vào command. **SAFE**.
- **Default `listen_host = "0.0.0.0"`** tại `@d:\Project\AIFlow\MoneyPrinterTurbo\app\config\config.py:60` — bind toàn bộ network interface, không có auth middleware.

### 4. Logic đặc biệt
Không phát hiện trigger điều kiện đặc biệt, persistence mechanism, hay anti-debug.

### 5. Verdict: ⚠️ SUSPICIOUS (LOW risk)

| Mức độ | Số lượng | Mô tả |
|---|---|---|
| CRITICAL | 0 | |
| HIGH | 0 | |
| MEDIUM | 1 | `listen_host=0.0.0.0` không có auth |
| LOW | 1 | `g4f` gửi request đến third-party server không kiểm soát |
| INFO | 1 | `socksio` SOCKS proxy support |

**Top issues:**
1. `@d:\Project\AIFlow\MoneyPrinterTurbo\app\config\config.py:60` — Server bind `0.0.0.0` mặc định, API không có authentication — **MEDIUM**
2. `requirements.txt:12` — `g4f==0.5.2.2`: package không chính thức, gửi request đến server bên thứ 3 — **LOW**

---

## PROJECT 2: Toonflow-app

### 1. Tổng quan
- **Loại**: Desktop App (Electron) + Backend API (Node.js/TypeScript/Express)
- **Runtime**: Node.js, Electron ≥40, TypeScript, SQLite
- **Chức năng**: Tool tạo manga/webtoon AI, chạy AI vendor script

### 2. Dependencies

```@d:\Project\AIFlow\Toonflow-app\package.json:74
"vm2": "^3.10.5",
```

> ⚠️ **`vm2` đã bị ABANDONED** — maintainer đã tuyên bố không thể fix sandbox escape và archive repo năm 2023. Có ít nhất 3 CVE nghiêm trọng: **CVE-2023-29017**, **CVE-2023-32314**, **CVE-2023-37466**.

| Package | Nhận xét |
|---|---|
| `vm2@3.10.5` | **CRITICAL** — deprecated, known sandbox escapes |
| `vercel-minimax-ai-provider@0.0.2` | Version cực thấp, ít được review |
| `qwen-ai-provider-v5@2.1.0` | Package không nằm trong Vercel AI SDK chính thức |
| Các package còn lại | Bình thường |

### 3. Code nguy hiểm

**[CRITICAL] vm2 sandbox chạy user-provided code:**

```@d:\Project\AIFlow\Toonflow-app\src\utils\vm.ts:45-53
const vm = new VM({
    timeout: 0,       // ← KHÔNG có timeout!
    sandbox,
    compiler: "javascript",
    eval: false,
    wasm: false,
  });

  vm.run(code);
```

- `timeout: 0` = không có giới hạn thời gian → có thể tạo infinite loop
- Sandbox được cấp: `fetch`, `axios`, `FormData`, `jsonwebtoken` → code trong sandbox có **full network access**
- Code được compile từ TypeScript rồi chạy trực tiếp trong vm2

**[HIGH] Route mở cho phép inject code tùy ý:**

```@d:\Project\AIFlow\Toonflow-app\src\routes\setting\vendorConfig\addVendor.ts:68-69
const jsCode = transform(tsCode, { transforms: ["typescript"] }).code;
    const exports = u.vm(jsCode);
```

Bất kỳ user nào gọi được API `/setting/vendorConfig/addVendor` đều có thể:
1. Submit TypeScript code tùy ý
2. Code được compile rồi chạy trong vm2 sandbox bị broken
3. Escape sandbox để thực thi code trên host OS

**[MEDIUM] Password plain-text:**

```@d:\Project\AIFlow\Toonflow-app\src\routes\login\login.ts:29
if (data!.password == password && data!.name == username) {
```

Password không được hash, so sánh plain text trực tiếp với DB.

### 4. Logic đặc biệt
Không có trigger điều kiện đặc biệt, nhưng việc dùng vm2 để chạy user-code là persistence vector nếu bị khai thác.

### 5. Verdict: 🔴 DANGEROUS

| Mức độ | Số lượng | Mô tả |
|---|---|---|
| CRITICAL | 1 | vm2 sandbox escape → RCE |
| HIGH | 1 | User code execution qua API endpoint |
| MEDIUM | 2 | timeout:0, password plain-text |
| LOW | 1 | JWT key trong DB |

**Top issues:**
1. `@d:\Project\AIFlow\Toonflow-app\src\utils\vm.ts:1` — `vm2` deprecated với CVE sandbox escape — **CRITICAL**
2. `@d:\Project\AIFlow\Toonflow-app\src\routes\setting\vendorConfig\addVendor.ts:68-69` — User TypeScript chạy trong broken sandbox — **HIGH**
3. `@d:\Project\AIFlow\Toonflow-app\src\utils\vm.ts:46` — `timeout: 0` + full network access trong sandbox — **HIGH**
4. `@d:\Project\AIFlow\Toonflow-app\src\routes\login\login.ts:29` — Password plain-text — **MEDIUM**

**Khuyến nghị:** Thay `vm2` bằng `isolated-vm` (dùng V8 isolate thực sự) hoặc Node.js `--experimental-vm-modules` + Worker Thread isolation.

---

## PROJECT 3: VectCutAPI

### 1. Tổng quan
- **Loại**: REST API + MCP Server (Python Flask)
- **Runtime**: Python, Flask, ffmpeg
- **Chức năng**: API tạo draft video cho CapCut/JianYing

### 2. Dependencies
[requirements.txt](cci:7://file:///d:/Project/AIFlow/VectCutAPI/requirements.txt:0:0-0:0) không pin version → có thể lấy bản mới nhất với breaking changes hoặc supply chain inject.

```@d:\Project\AIFlow\VectCutAPI\requirements.txt:1-6
imageio
psutil
flask
requests
oss2
json5
```

### 3. Code nguy hiểm

**[HIGH/SUSPICIOUS] Domain bên thứ 3 hardcoded trong source code:**

```@d:\Project\AIFlow\VectCutAPI\settings\local.py:15
DRAFT_DOMAIN = "https://www.install-ai-guider.top"
```

```@d:\Project\AIFlow\VectCutAPI\mcp_server.py:310
"draft_url": f"https://www.install-ai-guider.top/draft/downloader?draft_id={draft_id}"
```

Domain `install-ai-guider.top` (TLD `.top` phổ biến trong malicious domains) xuất hiện ở **2 file khác nhau** như default value. Nếu user không config `config.json`, tất cả preview URL đều trỏ đến server này. Đây có thể là:
- Server của dev để track usage
- Hoặc server độc hại để thu thập `draft_id`

**[HIGH] SSRF via ffmpeg — URL không được validate:**

```@d:\Project\AIFlow\VectCutAPI\downloader.py:31-37
command = [
    'ffmpeg',
    '-i', video_url,    # ← user-provided URL, không validate
    '-c', 'copy',
    local_path
]
subprocess.run(command, check=True, capture_output=True)
```

`video_url` đến từ request body (`data.get('video_url')`) và được truyền thẳng vào ffmpeg. ffmpeg hỗ trợ nhiều protocol: `file://`, `rtmp://`, `http://internal-ip/` → SSRF tiềm năng để scan internal network.

**[MEDIUM] Flask API không có authentication:**
Không có middleware auth nào trong [capcut_server.py](cci:7://file:///d:/Project/AIFlow/VectCutAPI/capcut_server.py:0:0-0:0). Bất kỳ ai biết IP:port đều có thể gọi toàn bộ API.

### 4. Verdict: ⚠️ SUSPICIOUS

| Mức độ | Số lượng | Mô tả |
|---|---|---|
| CRITICAL | 0 | |
| HIGH | 2 | External domain tracking + SSRF via ffmpeg |
| MEDIUM | 1 | No API authentication |
| LOW | 1 | requirements.txt không pin version |

**Top issues:**
1. `@d:\Project\AIFlow\VectCutAPI\settings\local.py:15` & `mcp_server.py:310,352` — Hardcoded third-party domain `install-ai-guider.top` — **HIGH**
2. `@d:\Project\AIFlow\VectCutAPI\downloader.py:31-37` — SSRF via unvalidated URL passed to ffmpeg — **HIGH**
3. [capcut_server.py](cci:7://file:///d:/Project/AIFlow/VectCutAPI/capcut_server.py:0:0-0:0) — Không có authentication — **MEDIUM**

---

## PROJECT 4: daihuo-jianshou

### 1. Tổng quan
- **Loại**: Web App (Next.js 16 + SQLite)
- **Runtime**: Node.js, Next.js, React 19, TypeScript
- **Chức năng**: Tool tạo script video bán hàng (AI-powered)

### 2. Dependencies
```@d:\Project\AIFlow\daihuo-jianshou\package.json:22-24
"next": "16.2.1",
"react": "19.2.4",
"react-dom": "19.2.4",
```

Tất cả packages đều là tên chuẩn, không có typosquatting. Không có `postinstall`/`preinstall` scripts. Dependencies bình thường — `fluent-ffmpeg`, `drizzle-orm`, `better-sqlite3`, `openai` đều là packages phổ biến.

### 3. Code nguy hiểm

Không phát hiện `eval()`, `exec()`, hay dynamic import nguy hiểm. Script engine ([generator.ts](cci:7://file:///d:/Project/AIFlow/daihuo-jianshou/src/lib/script-engine/generator.ts:0:0-0:0)) chỉ gọi OpenAI API chuẩn, không thực thi code động.

```@d:\Project\AIFlow\daihuo-jianshou\src\lib\script-engine\generator.ts:93-97
function createClient(config: LLMConfig): OpenAI {
  return new OpenAI({
    baseURL: config.baseUrl,
    apiKey: config.apiKey,
  });
}
```

`baseURL` đến từ user config — **MEDIUM**: nếu user bị trick nhập malicious LLM endpoint, data có thể bị exfiltrate.

### 4. Verdict: ✅ SAFE (với 1 lưu ý nhỏ)

| Mức độ | Số lượng | Mô tả |
|---|---|---|
| CRITICAL | 0 | |
| HIGH | 0 | |
| MEDIUM | 1 | User-controlled `baseURL` cho LLM client |
| LOW | 0 | |
| INFO | 1 | `next@16.2.1` — verify đây là version chính thức |

---

## PROJECT 5: flowboard

### 1. Tổng quan
- **Loại**: AI Agent Framework (Python FastAPI backend + Vite/React frontend)
- **Runtime**: Python ≥3.11, FastAPI, SQLModel, WebSocket, Claude CLI
- **Chức năng**: Visual workflow board tích hợp AI agent (Claude)

### 2. Dependencies
```@d:\Project\AIFlow\flowboard\agent\requirements.txt:1-7
fastapi>=0.115
uvicorn[standard]>=0.30
sqlmodel>=0.0.22
pydantic>=2.8
websockets>=12.0
python-multipart>=0.0.9
httpx>=0.27
```
Không pin version (dùng `>=`) — nếu có supply chain attack ở tương lai, sẽ tự update. LOW risk.

### 3. Code nguy hiểm

**[HIGH] CORS wildcard + credentials:**

```@d:\Project\AIFlow\flowboard\agent\flowboard\main.py:77-83
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,   # ← INVALID kết hợp với wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Kết hợp `allow_origins=["*"]` với `allow_credentials=True` là CORS misconfiguration theo CORS spec (browser sẽ block), nhưng non-browser clients hoặc khi deploy sai context có thể bị abuse.

**[MEDIUM] Claude CLI bypass permissions:**

```@d:\Project\AIFlow\flowboard\agent\flowboard\services\claude_cli.py:152
args += ["--permission-mode", "bypassPermissions"]
```

Khi có attachments, CLI được gọi với `bypassPermissions` — Claude có thể đọc/ghi file system không cần xác nhận.

**[LOW] WebSocket server unauthenticated (documented):**

```@d:\Project\AIFlow\flowboard\agent\flowboard\main.py:21-25
if WS_HOST not in ("127.0.0.1", "localhost", "::1"):
    raise RuntimeError(
        f"FLOWBOARD_WS_HOST must be loopback ..."
    )
```

Dev đã có guard rail — chỉ cho phép loopback. **Chấp nhận được**.

### 4. Verdict: ⚠️ SUSPICIOUS (LOW-MEDIUM risk)

| Mức độ | Số lượng | Mô tả |
|---|---|---|
| CRITICAL | 0 | |
| HIGH | 1 | CORS wildcard + credentials |
| MEDIUM | 1 | Claude CLI bypassPermissions |
| LOW | 1 | requirements không pin version |

---

## TỔNG HỢP TOÀN BỘ 5 PROJECT

| Project | Verdict | Vấn đề nghiêm trọng nhất |
|---|---|---|
| MoneyPrinterTurbo | ⚠️ SUSPICIOUS (LOW) | `g4f` third-party + no auth |
| **Toonflow-app** | 🔴 **DANGEROUS** | **vm2 CVE sandbox escape + user code execution** |
| VectCutAPI | ⚠️ SUSPICIOUS | Hardcoded external domain + SSRF via ffmpeg |
| daihuo-jianshou | ✅ SAFE | Không có vấn đề nghiêm trọng |
| flowboard | ⚠️ SUSPICIOUS | CORS misconfiguration |

---

## KHUYẾN NGHỊ ƯU TIÊN

**Xử lý ngay (CRITICAL/HIGH):**

1. **Toonflow-app**: Thay `vm2` bằng `isolated-vm` hoặc `worker_threads` + `vm.SyntheticModule`. Đây là lỗ hổng **RCE thực sự**.
2. **Toonflow-app**: Hash password với `bcrypt` trước khi lưu DB.
3. **VectCutAPI**: Validate `video_url` scheme whitelist (`https://` only), block `file://`, `rtmp://`, `ftp://` trước khi truyền vào ffmpeg.
4. **VectCutAPI**: Xác nhận `install-ai-guider.top` là server hợp lệ của developer, hoặc thay bằng config bắt buộc người dùng cung cấp domain.

**Cải thiện (MEDIUM):**

5. **MoneyPrinterTurbo**: Thêm authentication middleware (API key hoặc JWT) nếu deploy trên server.
6. **flowboard**: Đổi `allow_origins=["*"]` thành danh sách domain cụ thể.
7. **VectCutAPI**: Thêm API key authentication cho Flask endpoints.