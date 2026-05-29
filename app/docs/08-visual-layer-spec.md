# 08 — Visual Layer (Mini-Hyperframes) Spec

> **Status**: Draft for review
> **Depends on**: 02-db-schema, 03-api-contract
> **Used by**: render/composer.py

## Mục đích

Render các overlay HTML/CSS+GSAP thành mp4 chunk (có alpha) để overlay lên video chính từ Veo3. Thay thế ffmpeg drawtext thô bằng visual đẹp.

**KHÔNG port hyperframes framework** (quá nặng). Tự build mini version Python ~300 dòng, lift idea HfProtocol.

## Use cases

| Overlay | Khi dùng | Duration |
|---------|----------|----------|
| `intro_card` | Đầu video | 3-5s |
| `outro_card` | Cuối video, CTA | 3s |
| `lower_third` | Giữa video, name+title 1 person | 5s |
| `chapter_title` | Phân chia chapter trong video dài | 3s |
| `product_card` | E-commerce: card sản phẩm với price | 4-6s |

## Architecture

```
Adapter outputs SceneList với optional `suggested_intro` / `suggested_outro` / overlay per scene
   ↓
Composer.compose() detect overlay needs
   ↓
For each overlay:
   playwright_renderer.render(template_html, vars, duration) → overlay.webm (alpha)
   ↓
ffmpeg overlay onto Veo3 video at correct timestamp
```

## Stack

- **Playwright Python** — control headless Chromium qua CDP
- **GSAP 3** — animation engine, **bundled trong vendor/** (REVIEW-01 #4 — không CDN)
- **Tailwind CSS** — KHÔNG dùng. Lý do: Tailwind CDN runtime ~3MB load mỗi lần render quá chậm. Dùng inline CSS thay (templates đơn giản, không cần utility-first).
- **HTML5 Canvas Capture** — không cần, dùng CDP screenshot API thay
- Python: `pip install playwright` + `playwright install chromium`

### Vendor assets (REVIEW-01 #4)

```
app/vendor/visual_layer/
├── gsap.min.js              # GSAP 3.12.5 download một lần, ~70KB
├── README.md                # Source URL + version + license note
└── (optional) fonts/        # Self-host fonts nếu muốn nhất quán cross-machine
```

Templates load qua placeholder:
```html
<script src="{{__VENDOR_GSAP__}}"></script>
```

Renderer thay placeholder thành `file:///D:/Project/AIFlow/app/vendor/visual_layer/gsap.min.js` (absolute path) trước khi save HTML temp.

### Lợi ích offline bundle

- Render được khi máy offline (use case: render trong container không network)
- Không phụ thuộc CDN uptime / latency
- Version GSAP cố định → animation behavior reproducible
- Render time giảm ~500ms/template (CDN không cần resolve)

### Trade-off

- Repo size +70KB (GSAP) — chấp nhận được
- Phải update GSAP thủ công nếu muốn version mới
- Mỗi machine clone repo có sẵn vendor/, không cần `npm install`

## HfProtocol — Page contract

Mỗi template HTML phải expose:

```javascript
window.__hf = {
  duration: 5.0,                 // Total seconds
  seek(t) {                      // 0 ≤ t ≤ duration
    // Set page state to time t. Must be deterministic.
    timeline.seek(t);
  }
};
```

Renderer logic:
```python
total_frames = int(duration * fps)
for i in range(total_frames):
    t = i / fps
    page.evaluate(f"window.__hf.seek({t})")
    screenshot = page.screenshot(type="png", omit_background=True)
    save(screenshot, f"frame_{i:05d}.png")

# Then ffmpeg PNG sequence → webm with alpha
```

## File structure

```
server/render/visual_layer/
├── __init__.py
├── playwright_renderer.py       ← Core renderer
├── hf_protocol.py                ← Type definitions
├── overlay_compositor.py         ← FFmpeg overlay onto base video
└── templates/
    ├── intro_card.html
    ├── outro_card.html
    ├── lower_third.html
    ├── chapter_title.html
    └── product_card.html
```

## Renderer interface

```python
# server/render/visual_layer/playwright_renderer.py

@dataclass
class RenderRequest:
    template_path: Path                    # HTML template
    template_vars: dict                    # Vars để substitute {{TITLE}}, etc.
    duration_sec: float
    width: int = 1080
    height: int = 1920
    fps: int = 30
    background: Literal["transparent", "black", "color"] = "transparent"
    output_path: Path

class PlaywrightRenderer:
    async def render(self, req: RenderRequest) -> Path:
        """Render HTML → webm with alpha. Return path."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": req.width, "height": req.height},
                device_scale_factor=1,
            )
            page = await context.new_page()
            
            # 1. Substitute vars
            html = req.template_path.read_text(encoding="utf-8")
            
            # 1a. Vendor placeholder (REVIEW-01 #4 — bundle GSAP local, không CDN)
            vendor_dir = Path(__file__).parent.parent.parent / "vendor" / "visual_layer"
            gsap_path = vendor_dir / "gsap.min.js"
            if not gsap_path.exists():
                raise RuntimeError(
                    f"Missing vendor: {gsap_path}\n"
                    f"Run: curl -L https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js "
                    f"-o {gsap_path}"
                )
            html = html.replace("{{__VENDOR_GSAP__}}", f"file:///{gsap_path.absolute().as_posix()}")
            
            # 1b. User vars
            for key, val in req.template_vars.items():
                html = html.replace(f"{{{{{key}}}}}", str(val))
            
            # 2. Save to temp + load
            temp_html = req.output_path.parent / "temp.html"
            temp_html.write_text(html, encoding="utf-8")
            await page.goto(f"file://{temp_html.absolute()}")
            
            # 3. Wait for window.__hf
            await page.wait_for_function("window.__hf && typeof window.__hf.seek === 'function'", timeout=10000)
            
            # 4. Capture frames
            total_frames = int(req.duration_sec * req.fps)
            frames_dir = req.output_path.parent / "frames"
            frames_dir.mkdir(exist_ok=True)
            
            for i in range(total_frames):
                t = i / req.fps
                await page.evaluate(f"window.__hf.seek({t})")
                # Wait 1 frame để GSAP repaint
                await page.evaluate("new Promise(r => requestAnimationFrame(r))")
                
                await page.screenshot(
                    path=frames_dir / f"frame_{i:05d}.png",
                    omit_background=True,  # alpha
                    type="png",
                )
            
            await browser.close()
        
        # 5. ffmpeg PNG sequence → webm với alpha (vp9)
        cmd = [
            "ffmpeg", "-y",
            "-r", str(req.fps),
            "-i", str(frames_dir / "frame_%05d.png"),
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuva420p",  # alpha
            "-b:v", "2M",
            str(req.output_path),
        ]
        subprocess.run(cmd, check=True)
        
        # Cleanup frames
        shutil.rmtree(frames_dir)
        return req.output_path
```

## Template — `intro_card.html`

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <script src="{{__VENDOR_GSAP__}}"></script>
  <style>
    body { margin: 0; padding: 0; background: transparent; font-family: 'Inter', -apple-system, sans-serif; }
    #stage {
      width: 1080px; height: 1920px;
      display: flex; align-items: center; justify-content: center; flex-direction: column;
      color: #fff; text-align: center;
      background: linear-gradient(180deg, rgba(10,10,10,0.85) 0%, rgba(10,10,10,0.6) 100%);
    }
    #title {
      font-size: 96px; font-weight: 800;
      opacity: 0; transform: translateY(40px);
      letter-spacing: -2px; line-height: 1.1;
      max-width: 900px;
    }
    #subtitle {
      font-size: 42px; opacity: 0;
      margin-top: 32px; color: #aaa;
      transform: translateY(20px);
    }
    #accent {
      width: 80px; height: 4px;
      background: #FF6F00; margin: 40px 0 0 0;
      transform: scaleX(0); transform-origin: left;
    }
  </style>
</head>
<body>
  <div id="stage">
    <div id="title">{{TITLE}}</div>
    <div id="accent"></div>
    <div id="subtitle">{{SUBTITLE}}</div>
  </div>
  
  <script>
    const tl = gsap.timeline({ paused: true });
    tl.to('#title',    { opacity: 1, y: 0, duration: 0.8, ease: 'power3.out' })
      .to('#accent',   { scaleX: 1, duration: 0.5, ease: 'power2.out' }, '-=0.2')
      .to('#subtitle', { opacity: 1, y: 0, duration: 0.6, ease: 'power2.out' }, '-=0.3')
      .to(['#title', '#accent', '#subtitle'], {
        opacity: 0, duration: 0.4, ease: 'power2.in'
      }, '+=2.0');
    
    window.__hf = {
      duration: tl.duration(),
      seek(t) { tl.seek(t); }
    };
  </script>
</body>
</html>
```

## Template — `lower_third.html`

```html
<!DOCTYPE html>
<html>
<head>
  <script src="{{__VENDOR_GSAP__}}"></script>
  <style>
    body { margin: 0; background: transparent; font-family: 'Inter', sans-serif; }
    #stage { width: 1080px; height: 1920px; position: relative; }
    #card {
      position: absolute;
      bottom: 200px; left: 80px;
      background: rgba(20,20,20,0.92);
      backdrop-filter: blur(12px);
      padding: 24px 36px;
      border-left: 6px solid {{ACCENT_COLOR}};
      transform: translateX(-120%);
    }
    #name { color: white; font-size: 48px; font-weight: 700; }
    #title { color: #999; font-size: 28px; margin-top: 6px; }
  </style>
</head>
<body>
  <div id="stage">
    <div id="card">
      <div id="name">{{NAME}}</div>
      <div id="title">{{TITLE}}</div>
    </div>
  </div>
  <script>
    const tl = gsap.timeline({ paused: true });
    tl.to('#card', { x: 0, duration: 0.6, ease: 'power3.out' })
      .to('#card', { x: '-120%', duration: 0.5, ease: 'power3.in' }, '+=4.0');
    
    window.__hf = {
      duration: tl.duration(),
      seek(t) { tl.seek(t); }
    };
  </script>
</body>
</html>
```

## Template — `product_card.html`

```html
<!-- Product card với price + rating + CTA. Vars: PRODUCT_NAME, PRICE, RATING, IMG_URL -->
<!DOCTYPE html>
<html>
<head>
  <script src="{{__VENDOR_GSAP__}}"></script>
  <style>
    body { margin: 0; background: transparent; font-family: 'Inter', sans-serif; }
    #stage { width: 1080px; height: 1920px; }
    #card {
      position: absolute; bottom: 80px; left: 50px; right: 50px;
      background: white; border-radius: 24px;
      padding: 32px; display: flex; align-items: center; gap: 24px;
      transform: translateY(150%);
      box-shadow: 0 20px 60px rgba(0,0,0,0.3);
    }
    #img { width: 160px; height: 160px; border-radius: 16px; background-size: cover; background-position: center; flex-shrink: 0; }
    #info { flex: 1; }
    #name { font-size: 36px; font-weight: 700; color: #111; }
    #price { font-size: 48px; font-weight: 800; color: #FF6F00; margin-top: 8px; }
    #rating { color: #FFD700; font-size: 24px; }
    #cta { background: #FF6F00; color: white; padding: 18px 36px; border-radius: 12px; font-size: 28px; font-weight: 700; }
  </style>
</head>
<body>
  <div id="stage">
    <div id="card">
      <div id="img" style="background-image: url('{{IMG_URL}}')"></div>
      <div id="info">
        <div id="name">{{PRODUCT_NAME}}</div>
        <div id="price">{{PRICE}}</div>
        <div id="rating">★★★★★ {{RATING}}</div>
      </div>
      <div id="cta">Xem ngay</div>
    </div>
  </div>
  <script>
    const tl = gsap.timeline({ paused: true });
    tl.to('#card', { y: 0, duration: 0.7, ease: 'back.out(1.4)' })
      .to('#cta', { scale: 1.05, duration: 0.4, ease: 'power2.inOut', yoyo: true, repeat: 3 }, '-=0.3')
      .to('#card', { y: '150%', duration: 0.5, ease: 'power3.in' }, '+=3.0');
    
    window.__hf = {
      duration: tl.duration(),
      seek(t) { tl.seek(t); }
    };
  </script>
</body>
</html>
```

## OverlayCompositor

```python
# server/render/visual_layer/overlay_compositor.py

class OverlayCompositor:
    async def overlay_on_video(
        self,
        base_video: Path,
        overlay_webm: Path,
        timestamp_sec: float,
        output: Path,
    ) -> Path:
        """Overlay với alpha tại thời điểm cụ thể."""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(base_video),
            "-i", str(overlay_webm),
            "-filter_complex",
            f"[1:v]setpts=PTS+{timestamp_sec}/TB[ovr];"
            f"[0:v][ovr]overlay=enable='between(t,{timestamp_sec},{timestamp_sec+10})'",
            "-c:a", "copy",
            str(output),
        ]
        subprocess.run(cmd, check=True)
        return output
    
    async def prepend_intro(self, intro_webm: Path, base_video: Path, output: Path):
        """Concat intro + base."""
        # Convert intro webm → mp4 trước
        intro_mp4 = intro_webm.with_suffix(".mp4")
        subprocess.run([
            "ffmpeg", "-y", "-i", str(intro_webm), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(intro_mp4)
        ])
        
        # Concat
        list_file = output.parent / "concat.txt"
        list_file.write_text(f"file '{intro_mp4.absolute()}'\nfile '{base_video.absolute()}'")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(output)
        ])
```

## Performance budget

| Operation | Target | Note |
|-----------|--------|------|
| Render 5s @ 30fps card | < 30s | 150 frames × 0.2s/frame |
| Total visual layer cho 1 video (intro + outro + 2 lower thirds) | < 120s | < 5% tổng pipeline time |
| Memory | < 1GB Chrome | 1 process per render, không spawn parallel |

Tối ưu khả thi:
- Tận dụng `requestAnimationFrame` thay sleep cố định
- Reuse browser instance qua multiple renders
- Cache compiled HTML

## Failure modes

| Failure | Cause | Mitigation |
|---------|-------|-----------|
| Playwright timeout | Chrome không launch | Pre-flight check, install nếu missing |
| `window.__hf` undefined | Template lỗi GSAP | Linter check templates lúc startup |
| FFmpeg merge alpha fail | Codec mismatch | Force `libvpx-vp9` + `yuva420p` |
| Frame missing trong sequence | Disk full | Quality gate G6 catch |
| Font không render đúng | System font missing | Bundle fonts trong template (`@font-face`) hoặc skip |

## Linting templates lúc startup

```python
async def lint_templates():
    """Check mọi template HTML có expose window.__hf đúng."""
    for tpl in TEMPLATES_DIR.glob("*.html"):
        # Render thử 1 frame
        result = await renderer.render(RenderRequest(
            template_path=tpl,
            template_vars={"TITLE": "test", ...},  # Fill với placeholder
            duration_sec=0.1,
            output_path=Path("/tmp/lint.webm"),
        ))
        if not result.exists():
            log.error(f"Template {tpl.name} failed lint")
```

Chạy lúc startup nếu Phase 3.5+, fail-fast nếu template broken.

## Acceptance criteria

- [ ] HfProtocol contract clear (window.__hf duration + seek)
- [ ] 5 templates HTML+GSAP self-contained, render được standalone trong browser
- [ ] Renderer Python ~300 dòng, không phụ thuộc hyperframes framework
- [ ] Output webm có alpha channel, overlay được lên mp4
- [ ] Compositor có 3 method: overlay, prepend, append
- [ ] Performance < 5% tổng pipeline time
- [ ] Có linter cho templates, fail-fast lúc startup
- [ ] Templates dùng được 5 use cases: intro/outro/lower_third/chapter/product

## Phase mapping

| Component | Phase |
|-----------|-------|
| HfProtocol + renderer skeleton | 3.5.1 |
| 5 templates HTML | 3.5.2 |
| OverlayCompositor | 3.5.3 |
| Tích hợp vào composer.py | 3.5.4 |
| Linter | 3.5 (cuối phase) |
