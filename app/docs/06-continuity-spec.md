# 06 — Continuity Engine 4 Lớp Spec

> **Status**: Draft for review
> **Depends on**: 02-db-schema (Style, Asset, Scene), 05-content-adapter
> **Used by**: pipeline orchestrator, Veo3 dispatcher

## Mục đích

Đảm bảo **video output liền mạch** dù tạo từ N clip Veo3 8s độc lập. Đây là module quan trọng nhất của project, tỉ lệ thành công của tool quyết định bởi spec này.

**Bài toán khó**: Veo3 mỗi clip = 1 LLM call độc lập, model không có "memory" giữa clip 1 và clip 2. Nếu để mặc định, 8 clip sẽ ra 8 nhân vật khác nhau, 8 phong cách khác nhau, nối nhau thành 1 video bừa bộn.

**Giải pháp**: 4 lớp ràng buộc xếp chồng. Mỗi lớp giải quyết 1 dimension của continuity.

```
┌─────────────────────────────────────────────────────────┐
│ Lớp 1 — Style Lock      (1 project = 1 visual identity) │
├─────────────────────────────────────────────────────────┤
│ Lớp 2 — Asset Lock      (cùng character/product xuyên N)│
├─────────────────────────────────────────────────────────┤
│ Lớp 3 — Scene Chain     (clip N+1 nối tiếp clip N)      │
├─────────────────────────────────────────────────────────┤
│ Lớp 4 — Audio Continuity (1 audio track, không gap)     │
└─────────────────────────────────────────────────────────┘
```

---

## Lớp 1 — Style Lock

### Vấn đề

Mỗi clip Veo3 độc lập → có thể ra style khác nhau: clip 1 cinematic, clip 2 anime, clip 3 photo realistic. Không thể chấp nhận trong 1 video.

### Cơ chế

**1 project = 1 file `style.json` cố định**, prepend vào MỌI prompt gửi Veo3.

### Data flow

```
Project created
   ↓
load skills/{skill_id}/style.json
   ↓
Save into Style table (project_id FK)
   ↓
Generate text từ style.json:
   "art_style: {art_style}. lighting: {lighting}. lens: {lens}. ..."
   ↓
Cached as Style.prefix_text
   ↓
Mỗi gen request:
   final_prompt = Style.prefix_text + "\n\n" + scene.visual_prompt
```

### Schema `style.json`

```json
{
  "schema_version": "1",
  
  "art_style": "editorial fashion photography",
  "color_palette": "muted earth tones with cream highlights",
  "lighting": "soft even key light",
  "lens": "85mm portrait, shallow depth of field",
  "camera_style": "locked-off static frame",
  "post_processing": "slight film grain, warm tone curve",
  
  "negative_prompt": "no anime, no cartoon, no oversaturation, no harsh shadows",
  
  "aspect_constraints": {
    "9:16": "subject centered, knees-up to chest framing",
    "16:9": "rule of thirds, environment readable",
    "1:1": "centered composition, close-up to medium shot"
  },
  
  "metadata": {
    "skill_id": "ecommerce-fashion",
    "version": "1.0.0"
  }
}
```

### Generated `prefix_text` (cached)

```
Photoreal editorial fashion photography. Soft even key light.
85mm portrait lens with shallow depth of field. Locked-off static
frame. Slight film grain, warm tone curve. Muted earth tones with
cream highlights.

Avoid: anime, cartoon, oversaturation, harsh shadows.
```

→ Prepend vào MỌI scene.visual_prompt + asset.ref_prompt.

### Override per project

User có thể edit `style.json` riêng cho project, override skill default. Stored in DB `Style.style_json`. Skill manifest = template, project = thực tế.

### Test

Gen 5 scene khác nhau, kiểm tra:
- Color palette nhất quán (eye-test)
- Lighting nhất quán
- Không có drift sang cartoon style

### Edge case

- Style xung đột với scene mood (vd style "sweet romance" nhưng scene có "fight"): nâng style → fall back. Không hỗ trợ multi-style trong 1 project ở Phase 2; defer.

---

## Lớp 2 — Asset Lock

### Vấn đề

Veo3 mỗi gen tạo identity mới. Không có cách nào nói "vẫn là cô gái đó". Không có "seed lock" cho character ở Veo3 i2v.

### Cơ chế

**Generate ref image 1 LẦN** cho mỗi asset (character/product/location), reuse `mediaId` xuyên scenes.

Cho mọi scene N, request Veo3:
```
batchAsyncGenerateVideoStartImage(
   start_image_media_id = ref_image.media_id,
   reference_images = [character.media_id, product.media_id, location.media_id],
   prompt = scene.visual_prompt
)
```

→ Veo3 dùng `IMAGE_INPUT_TYPE_REFERENCE` keep identity stable.

### Data flow

```
SceneList.assets  →  Job.gen_image cho mỗi asset
   ↓
Wait all done (G2 quality gate)
   ↓
User review + approve refs
   ↓
For each scene:
   Look up asset_ids → fetch media_ids
   Build i2v request với references
   ↓
Job.gen_video
```

### Hard constraints lúc gen ref image

Lift từ flowboard prompt_synth `_SYNTH_SYSTEM_IMAGE`:

**Character ref MUST BE:**
- Frontal, face engaging camera
- Neutral closed-mouth expression (NO teeth, NO smile)
- Studio lighting, neutral background (overrides scene location nếu là character ref)
- Knees-up portrait framing
- Reason: open-mouth smile bị Veo3 i2v warp → identity drift across clip

**Product ref MUST BE:**
- Studio shot trên neutral background
- Centered, flat-lay nếu là object nhỏ
- High detail, sharp focus
- KHÔNG có người trong shot (clean product)

**Location ref MUST BE:**
- Wide establishing shot
- KHÔNG có người (clean environment)
- Match thời điểm trong ngày dự kiến (sáng/chiều/đêm)

### Asset role assignment

Mỗi scene có `asset_ids` + role:

| Role | Có ý nghĩa cho Veo3 |
|------|---------------------|
| `main_character` | Identity anchor — Veo3 ưu tiên match face/body |
| `product` | Object cần xuất hiện trong frame, giữ details |
| `bg_location` | Environment — màu sắc, background |
| `extra` | Ref bổ sung, weight thấp hơn |

### Pinning per-edge variant

Như flowboard đã làm: nếu user gen ref image với 4 variants, pin variant nào (idx 0-3) để dùng cho từng downstream scene.

DB: `SceneAsset.metadata.variant_idx`.

### Edge case: cross-asset references

Scene "Hùng và Lan đi café": cần 2 character refs + 1 location ref.

Veo3 hỗ trợ tối đa **3-4 reference images** mỗi i2v call (theo experiment, không document chính thức).

→ Adapter phải prioritize: main_character > product > bg_location > extra. Drop extras nếu vượt limit.

### Test

- Gen ref Hùng → 5 scene khác nhau dùng Hùng
- Eye-test: face identity nhất quán ≥ 90%? (manual review)
- Drift acceptable: < 10% scenes có "trông khác người"

---

## Lớp 3 — Scene Chain

### Vấn đề

Lớp 2 giữ identity. Nhưng motion giữa clip vẫn đứt: clip 1 kết thúc Hùng đứng, clip 2 mở đầu Hùng ngồi → jump cut.

### Cơ chế

**Frame cuối scene N → start image scene N+1.**

Veo3 i2v hỗ trợ `start_image` (đã có trong flow_sdk.py: `batchAsyncGenerateVideoStartImage`).

```
Scene N gen done → ffprobe extract frame cuối → save last_frame_path
   ↓
Scene N+1 dispatch:
   start_image = scene_N.last_frame_path  (upload vào Flow nếu cần)
   reference_images = [character refs, product refs]  (Lớp 2)
   prompt = scene_N+1.visual_prompt
```

### Frame extraction

```python
def extract_last_frame(video_path: Path) -> Path:
    """Extract frame cuối (timestamp = duration - 0.05s) thành PNG."""
    out = video_path.with_suffix(".lastframe.png")
    cmd = [
        "ffmpeg", "-y", "-sseof", "-0.1",
        "-i", str(video_path),
        "-frames:v", "1",
        str(out)
    ]
    subprocess.run(cmd, check=True)
    return out
```

### Upload last_frame lên Flow

Veo3 i2v cần `media_id`, không nhận file local. Phải upload qua Flow API:
```
POST /v1/flow/uploadImage
→ trả về media_id
```

(Đã có `UPLOAD_IMAGE_URL` trong flow_sdk.py.)

### Prompt template per chain

Khi build prompt scene N+1, hint LLM rằng đây là continuation:

```
[Scene context]
This is scene 4 of 8 in a sequence. Previous scene ended with:
"{scene_3.last_frame_description}"  (LLM trước đó describe frame cuối scene 3)

[Action]
{scene_4.visual_prompt}

[Continuity rules]
- Maintain pose/position from previous frame
- Do not change wardrobe / hair / location mid-clip
- Camera is locked-off, no zoom or pan unless explicitly stated
```

### Last frame description (LLM vision)

Sau khi extract last_frame, gọi Gemini Vision:
```python
last_frame_desc = await ctx.vision.describe(
    last_frame_path,
    focus="pose, position, expression, lighting"
)
# Output: "Subject standing center-frame, slight smile, weight on right leg, golden hour lighting"
```

→ Cache vào `Scene.metadata.last_frame_description`.

### Edge case: scene đầu (không có previous)

`scene[0].start_image_media_id = None` → Veo3 fallback text-to-video, không có start frame.

Trong trường hợp này, **dùng `main_character.ref_image` làm start frame** thay thế:
```
start_image_media_id = scene[0].asset_ids.main_character.ref_media_id
```

### Edge case: scene fail, retry

Nếu scene N retry → frame cuối scene N có thể đổi → scene N+1 cũng phải re-gen.

→ Quality gate G3 (xem spec 07): scene fail → cascade re-run downstream scenes.

### Edge case: location đổi giữa scenes

Scene 3 ở studio, scene 4 ở Seoul street. Frame cuối studio không match start Seoul.

**Giải pháp**: detect `location_change` qua enum `LocationCategory` (spec 05, REVIEW-02 #6).
Logic check phải **defensive với `unspecified`** — adapter chưa detect được không nên trigger reset:

```python
def location_changed(scene_n: Scene, scene_prev: Scene) -> bool:
    """REVIEW-02 #6 — chỉ reset chain khi cả 2 scene CÓ location category xác định
    VÀ khác nhau. unspecified ở 1 trong 2 → giữ chain (default behavior)."""
    if scene_n.location_hint == "unspecified":
        return False
    if scene_prev.location_hint == "unspecified":
        return False
    return scene_n.location_hint != scene_prev.location_hint


# Trong scene chain dispatch:
if location_changed(scene_n, scene_prev):
    scene_n.start_image_media_id = None  # Reset, dùng character ref thay
    insert_crossfade(scene_prev, scene_n, duration=0.3)  # Visual transition
```

→ Insert visual transition (cross-fade 0.3s) giữa 2 scene khác location.

### Test

- Gen 5 scene cùng location
- Visual review: motion liên tục? Không jump cut?
- Acceptable drift: pose nhỏ (đầu lệch nhẹ) OK; pose lớn (đứng→ngồi) = fail

---

## Lớp 4 — Audio Continuity

### Vấn đề

Mỗi scene 8s, nếu mỗi scene TTS riêng, sẽ có:
- Pitch drift giữa segment
- Gap silence giữa segments
- Pacing không đều (TTS engine restart mỗi câu)

### Cơ chế

**1 audio track liên tục** cho cả project, KHÔNG phải per-scene.

```
Step 1: Gather full narration
   full_narration = "\n\n".join(s.narration for s in scenes)
   ↓
Step 2: TTS 1 lần
   audio_full = tts(full_narration, voice=skill.voice)
   → audio.mp3
   ↓
Step 3: Whisper transcribe để có exact-timing
   segments = whisper.transcribe(audio.mp3)
   → list of (start_ts, end_ts, text)
   ↓
Step 4: Map segments → scenes (theo paragraph break)
   scene[i].audio_start = ...
   scene[i].audio_end = ...
   ↓
Step 5: Adjust scene durations để khớp audio
   scene[i].duration_sec = audio_end - audio_start
   (ROUND lên multiple của 0.5s vì Veo3 trim được)
```

### Vấn đề: Veo3 fixed 8s vs audio dynamic length

Veo3 mỗi clip = 8s cố định. Audio per scene có thể 3s hoặc 12s. Mismatch.

**Giải pháp**:

| Audio length per scene | Action |
|------------------------|--------|
| ≤ 8s | Padding silence cuối scene HOẶC freeze last frame video |
| 8-16s | Split thành 2 Veo3 clips (scene "8a" + "8b" cùng start frame) |
| > 16s | Báo adapter chia lại scene smaller (bảo "narration quá dài") |

### Pseudo-code

```python
def reconcile_durations(scene_list: SceneList, audio_segments: list[Segment]):
    """
    Match audio segments với scenes. Adjust scene.duration_sec.
    Trả về list scenes_to_render (có thể split 1 scene thành 2).
    """
    rendered = []
    for scene, audio_seg in zip(scene_list.scenes, audio_segments):
        audio_dur = audio_seg.end - audio_seg.start
        
        if audio_dur <= 8.0:
            scene.duration_sec = math.ceil(audio_dur * 2) / 2  # Round to 0.5
            rendered.append(scene)
        
        elif audio_dur <= 16.0:
            # Split thành 2 sub-scenes 8s
            scene_a = scene.copy()
            scene_a.scene_id += "a"
            scene_a.duration_sec = 8.0
            scene_a.narration = ""  # Audio không split
            
            scene_b = scene.copy()
            scene_b.scene_id += "b"
            scene_b.duration_sec = audio_dur - 8.0
            scene_b.start_image_media_id = "PENDING"  # Sẽ là last frame của scene_a
            
            rendered.extend([scene_a, scene_b])
        
        else:
            raise ContinuityError(
                "AUDIO_TOO_LONG",
                f"Scene {scene.scene_id} narration too long ({audio_dur}s). "
                "Adapter must split into smaller scenes."
            )
    
    return rendered
```

### Subtitle alignment

Whisper output có sẵn subtitles. Format thành SRT:
```
1
00:00:00,000 --> 00:00:03,200
Chào mọi người, hôm nay mình review áo này.

2
00:00:03,200 --> 00:00:06,800
Áo có chất liệu cotton 100%...
```

Subtitle render lên video bằng ffmpeg `subtitles=` filter.

### Background music

Optional layer:
```
audio_final = mix(
    voice = audio.mp3 (volume = 1.0),
    bgm = bgm.mp3 (volume = 0.15, loop)
)
```

→ Module `audio/mixer.py` (Phase 3).

### Edge case: voice clone giữ nhất quán

edge_tts mỗi call riêng, có thể pitch drift nhẹ.

**Mitigation**: dùng cùng 1 voice profile + concatenate trước khi normalize. KHÔNG TTS từng scene rồi concat.

### Test

- Tạo project 8 scenes
- Listen audio: có gap nào không? Pitch nhất quán?
- Subtitle sync với audio (Whisper conf > 0.7)

---

## Tích hợp 4 lớp vào pipeline

```
1. Adapter.parse() → SceneList
2. Apply Lớp 1: prepend Style.prefix_text vào mọi prompt
3. Lớp 4 — generate full audio TRƯỚC:
   - TTS full_narration
   - Whisper transcribe → segments
   - Reconcile scene durations
4. Lớp 2 — gen ref images cho mọi asset:
   - Job per asset (parallel)
   - G2 gate: user approve refs
5. Lớp 3 — gen scenes serially:
   - Scene 0: start_image = main_character.ref_media_id
   - Scene N (N>0): start_image = scene[N-1].last_frame.media_id (after upload)
   - Refs = [main_character, product, bg_location] (Lớp 2)
   - Prompt = Style.prefix + last_frame_desc + scene.visual_prompt + continuity_rules
6. Compose:
   - Concat scenes mp4 với cross-fade 0.3s (nếu location_change)
   - Overlay audio_full
   - Burn subtitle SRT
   - Add intro/outro (visual layer Phase 3.5)
```

## Continuity functions API

```python
# server/ai/prompts/continuity.py

class ContinuityEngine:
    def __init__(self, style: Style, llm: GeminiClient, vision: VisionClient):
        self.style = style
        self.llm = llm
        self.vision = vision
    
    def apply_layer1_style(self, raw_prompt: str) -> str:
        """Lớp 1: prepend style."""
        return f"{self.style.prefix_text}\n\n{raw_prompt}\n\nAvoid: {self.style.style_json['negative_prompt']}"
    
    def select_layer2_refs(self, scene: Scene, assets: list[Asset]) -> list[str]:
        """Lớp 2: pick top 3-4 refs by role priority."""
        ...
    
    async def build_layer3_chain_prompt(self, scene: Scene, prev_scene: Optional[Scene]) -> str:
        """Lớp 3: add continuation hints from prev frame."""
        ...
    
    async def reconcile_layer4_durations(
        self, scenes: list[Scene], audio_segments: list[Segment]
    ) -> list[Scene]:
        """Lớp 4: split/merge scenes by audio."""
        ...
    
    async def build_full_prompt(self, scene: Scene, ctx: dict) -> str:
        """Compose all 4 layers into final Veo3 prompt."""
        prompt = self.apply_layer1_style(scene.visual_prompt)
        prompt = await self.build_layer3_chain_prompt(scene, ctx.get("prev_scene"))
        return prompt
```

## Acceptance criteria

- [ ] Mỗi lớp có file Python riêng trong `server/ai/prompts/` (style_lock.py, asset_lock.py, scene_chain.py, audio_continuity.py)
- [ ] 4 lớp orthogonal: thay đổi 1 lớp không break lớp khác
- [ ] Edge cases được spec rõ (location change, scene fail retry, audio quá dài)
- [ ] Có test plan visual (manual eye-test) + automated (duration sync, segment count)
- [ ] Spec đủ chi tiết để implement Phase 2 mà không hỏi thêm
- [ ] Không phụ thuộc vào việc Veo3 release tính năng mới (dùng API hiện tại của flow_sdk.py)

## Phase mapping

| Lớp | Phase |
|-----|-------|
| Lớp 1 (Style) | 2.1 |
| Lớp 2 (Asset) | 2.2 |
| Lớp 3 (Scene chain) | 2.3 |
| Lớp 4 (Audio) | 2.4 + 3.1 |
| Tích hợp full | 2.5 |
