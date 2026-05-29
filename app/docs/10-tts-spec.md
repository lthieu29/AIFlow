# 10 — TTS Spec (Phase 3)

> **Status**: Draft for review
> **Depends on**: 01-config, 02-db-schema (Job table), 06-continuity (Lớp 4 audio), 07-quality-gate (G4)
> **Used by**: pipeline orchestrator (Phase 3.1), API `/api/tts/*`
> **Phase mapping**: 3.1 — provider abstraction + edge_tts; 3.2 — VieNeu-TTS local; 3.3 — UI selector

## Mục đích

Phase 3 cần biến `SceneList.full_narration` thành `audio.mp3` để Whisper transcribe + ffmpeg compose. Spec này định nghĩa cách AIFlow gọi 2 backend TTS song song:

- **`edge_tts`** — primary, online, không cần GPU, dùng cho test nhanh và fallback
- **`vieneu`** (VieNeu-TTS local) — high quality, offline, hỗ trợ GPU/CPU, hỗ trợ voice cloning, dùng cho final output

User chọn backend qua **UI dropdown** hoặc **`.env`**, AIFlow auto-detect CUDA và fallback theo chuỗi rõ ràng.

## Provider strategy

```
Pipeline (Phase 3.1) gọi: tts_service.synthesize(text=full_narration, voice=...)
                                       │
                                       ▼
                    ┌──────────────────────────────────┐
                    │  TTSService (orchestrator)       │
                    │  - load preference từ skill +    │
                    │    project + .env                │
                    │  - thử primary → fallback        │
                    └─────────┬────────────────────────┘
                              │
            ┌─────────────────┼──────────────────┐
            ▼                 ▼                  ▼
      VieNeuProvider    EdgeTTSProvider    (future: Azure)
       (vieneu_gpu /     (edge_tts)
        vieneu_cpu)
```

### Khi nào chọn provider nào

| Use case | Backend khuyến nghị |
|----------|---------------------|
| Phase 0–2 dev/smoke test | `edge_tts` (cài 1 dòng, không cần model) |
| Phase 3+ final output, có CUDA ≥ 8GB VRAM | `vieneu_gpu` (LMDeploy hoặc GGUF offload) |
| Phase 3+ final output, không có GPU | `vieneu_cpu` (Turbo GGUF) — nhanh, chất lượng đủ cho narration |
| Voice clone từ user-provided sample | `vieneu` (chỉ VieNeu hỗ trợ zero-shot) |
| Network unreliable / production offline | `vieneu` |
| Câu < 5 từ (intro flash, transition) | `edge_tts` (Turbo VieNeu có warning ngắn không ổn định) |

### Fallback chain (default)

```
preference: vieneu_gpu
  ↓ nếu CUDA không khả dụng / load fail / OOM
preference: vieneu_cpu
  ↓ nếu model download fail / llama-cpp không init
preference: edge_tts
  ↓ nếu network fail
ERROR: TTS_ALL_FAILED
```

User có thể đặt `AIFLOW_TTS_PRIMARY=edge_tts` để đảo ngược (online-first).

## Interface thống nhất

```python
# server/audio/tts/__init__.py
from typing import Protocol, Literal, Optional
from pathlib import Path
from dataclasses import dataclass


@dataclass
class TTSResult:
    """Kết quả 1 lần synth. Feed thẳng vào G4 + Whisper transcribe."""
    output_path: Path             # File audio đã ghi (.mp3 hoặc .wav)
    duration_sec: float           # Đo bằng ffprobe sau khi save
    sample_rate: int              # 24000 (vieneu) | 24000 (edge mp3) → resample về 24000
    backend_used: BackendName     # cho audit log
    voice_id: str                 # human-readable
    rtf: Optional[float] = None   # real-time factor đo được run này
    metadata: dict = None         # raw provider info, vd lmdeploy stats


BackendName = Literal[
    "vieneu_gpu_lmdeploy",
    "vieneu_gpu_gguf",       # llama-cpp với n_gpu_layers
    "vieneu_cpu_standard",   # GGUF + ONNX codec
    "vieneu_cpu_turbo",      # Turbo GGUF + ONNX codec
    "edge_tts",
]


class TTSProvider(Protocol):
    """Tất cả provider phải tuân interface này. Sync wrapper bên ngoài, async/thread bên trong."""
    
    name: BackendName
    
    async def is_available(self) -> bool:
        """Cheap pre-flight: import OK + (cho vieneu) device detect OK."""
        ...
    
    async def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
        *,
        speed: float = 1.0,         # 1.0 = native; 0.8 = slow; 1.2 = fast
        emotion: str = "natural",   # "natural" | "storytelling" (vieneu only)
        ref_audio: Optional[Path] = None,  # voice clone (vieneu only)
        ref_text: Optional[str] = None,
    ) -> TTSResult:
        """Sinh 1 file audio hoàn chỉnh. Phải đảm bảo:
        - File ghi xong và đóng handle trước khi return (Whisper sẽ đọc ngay)
        - duration_sec đo từ file thật (ffprobe), không từ token count
        - sample_rate = 24000 (resample nếu khác)
        - format = mp3 192kbps mono (chuẩn AIFlow, ffmpeg-compatible)
        - Raise TTSError với code rõ ràng nếu fail
        """
        ...
    
    async def close(self) -> None:
        """Release model + KV cache (đặc biệt VieNeu giữ vài GB RAM/VRAM)."""
        ...


class TTSError(Exception):
    """Friendly TTS errors."""
    def __init__(self, code: str, message: str, backend: Optional[str] = None):
        self.code = code
        self.message = message
        self.backend = backend
        super().__init__(message)


# Error codes cho /api/* surface lên UI
TTS_ERRORS = {
    "TTS_BACKEND_UNAVAILABLE",      # Backend không init được
    "TTS_VOICE_NOT_FOUND",          # Voice id không tồn tại
    "TTS_NETWORK_ERROR",            # edge_tts mất mạng
    "TTS_MODEL_DOWNLOAD_FAIL",      # vieneu HF download fail
    "TTS_OOM",                      # VRAM/RAM hết
    "TTS_TEXT_EMPTY",
    "TTS_OUTPUT_INVALID",           # File 0 bytes / không decode được
    "TTS_ALL_FAILED",               # Toàn fallback chain fail
}
```

## Module layout — `server/audio/`

> **REVIEW-02 #9** — `probe_duration` và `run_ffmpeg` là audio-specific helper
> nằm tại `server/audio/ffmpeg_utils.py`, **KHÔNG NHẦM** với
> `server/render/ffmpeg_utils.py` (subprocess wrapper cho video composer Phase 3.5).
> 2 module có overlap nhỏ về subprocess.run() invocation nhưng khác audience:
>
> - `audio/ffmpeg_utils.py` — audio probe/encode (mp3 lameenc, ffprobe duration)
> - `render/ffmpeg_utils.py` — video composer (concat, overlay alpha, crop, atempo)

```python
# server/audio/ffmpeg_utils.py — Phase 3.1 implement
import subprocess
from pathlib import Path


def probe_duration(audio_path: Path) -> float:
    """ffprobe duration của file audio. Trả về seconds (float)."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path),
    ]
    out = subprocess.check_output(cmd, encoding="utf-8").strip()
    return float(out)


def run_ffmpeg(args: list[str], *, timeout: int = 60) -> None:
    """Run ffmpeg với args list. Raise CalledProcessError nếu fail.
    
    Path resolve theo settings.ffmpeg_path → vendor/ → system PATH.
    """
    from server.config import load_settings
    settings = load_settings()
    
    ffmpeg = str(settings.ffmpeg_path) if settings.ffmpeg_path else "ffmpeg"
    cmd = [ffmpeg] + args
    subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
```



`server/audio/tts/vieneu_provider.py`:

```python
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from server.audio.tts import TTSProvider, TTSResult, TTSError, BackendName
from server.audio.ffmpeg_utils import run_ffmpeg
from server.config import Settings

log = logging.getLogger(__name__)


class VieNeuTTSProvider:
    """Wrapper quanh `vieneu.Vieneu` factory.
    
    Auto-detect device:
        AIFLOW_TTS_DEVICE=auto  →  cuda nếu torch.cuda.is_available() else cpu
        AIFLOW_TTS_DEVICE=cuda  →  ép cuda, raise nếu fail
        AIFLOW_TTS_DEVICE=cpu   →  ép cpu kể cả khi có GPU
    
    Auto-select mode (khi device đã quyết):
        cuda + lmdeploy_ok        →  mode="fast"   → name="vieneu_gpu_lmdeploy"
        cuda + lmdeploy_fail      →  mode="standard" với GGUF + n_gpu_layers=-1 → "vieneu_gpu_gguf"
        cpu  + AIFLOW_TTS_QUALITY=high   →  mode="standard" → "vieneu_cpu_standard"
        cpu  + AIFLOW_TTS_QUALITY=fast   →  mode="turbo"   → "vieneu_cpu_turbo"
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self._engine = None  # Lazy init — model load tốn ~2-4GB
        self._mode = None
        self._device = None
        self._init_lock = asyncio.Lock()
    
    @property
    def name(self) -> BackendName:
        if self._mode is None:
            return "vieneu_cpu_turbo"  # default before init
        return {
            ("standard", "cuda"): "vieneu_gpu_gguf",
            ("fast",     "cuda"): "vieneu_gpu_lmdeploy",
            ("standard", "cpu"):  "vieneu_cpu_standard",
            ("turbo",    "cpu"):  "vieneu_cpu_turbo",
            ("turbo",    "cuda"): "vieneu_gpu_gguf",  # Turbo GGUF với GPU offload
        }.get((self._mode, self._device), "vieneu_cpu_turbo")
    
    async def is_available(self) -> bool:
        try:
            import vieneu  # noqa: F401
            return True
        except ImportError:
            return False
    
    async def _ensure_engine(self):
        """Lazy load. Idempotent + thread-safe."""
        if self._engine is not None:
            return
        async with self._init_lock:
            if self._engine is not None:
                return
            
            device = self._resolve_device(self.settings.tts.vieneu_device)
            mode = self._resolve_mode(device)
            
            log.info(f"Loading VieNeu-TTS — mode={mode} device={device}")
            t0 = time.time()
            
            # Load model trong thread vì factory blocking + có thể tải 2-4GB từ HF
            from vieneu import Vieneu
            
            kwargs = {"emotion": self.settings.tts.vieneu_emotion}
            if mode == "standard":
                kwargs.update({
                    "backbone_repo": self.settings.tts.vieneu_backbone_repo,
                    "backbone_device": device,
                    "codec_repo": self.settings.tts.vieneu_codec_repo,
                    "codec_device": "cpu",  # ONNX codec luôn CPU
                })
            elif mode == "fast":
                kwargs.update({
                    "backbone_device": "cuda",
                    "codec_device": "cuda",
                    "max_batch_size": 4,
                })
            elif mode == "turbo":
                kwargs["device"] = device
            
            try:
                self._engine = await asyncio.to_thread(Vieneu, mode=mode, **kwargs)
                self._mode = mode
                self._device = device
                log.info(f"VieNeu-TTS ready in {time.time()-t0:.1f}s — backend={self.name}")
            except Exception as e:
                if mode == "fast":
                    # LMDeploy fail → fallback sang standard GGUF + GPU offload
                    log.warning(f"LMDeploy load fail ({e}) — fallback standard GGUF GPU")
                    self._mode = "standard"
                    self._device = device
                    self._engine = await asyncio.to_thread(
                        Vieneu, mode="standard",
                        backbone_device=device, codec_device="cpu",
                        emotion=self.settings.tts.vieneu_emotion,
                    )
                else:
                    raise TTSError("TTS_BACKEND_UNAVAILABLE",
                                   f"VieNeu init fail: {e}", backend=self.name) from e
    
    def _resolve_device(self, requested: str) -> str:
        if requested == "cpu":
            return "cpu"
        if requested == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    raise TTSError("TTS_BACKEND_UNAVAILABLE",
                                   "AIFLOW_TTS_DEVICE=cuda nhưng CUDA không khả dụng. "
                                   "Đặt 'auto' hoặc 'cpu' trong .env.",
                                   backend="vieneu")
                return "cuda"
            except ImportError as e:
                raise TTSError("TTS_BACKEND_UNAVAILABLE",
                               "torch chưa cài — pip install vieneu[gpu]",
                               backend="vieneu") from e
        # auto
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
    
    def _resolve_mode(self, device: str) -> str:
        quality = self.settings.tts.vieneu_quality  # "high" | "fast"
        if device == "cuda":
            # Thử LMDeploy nếu user cho phép + Python 3.12
            import sys
            if (quality == "high"
                and self.settings.tts.vieneu_use_lmdeploy
                and sys.version_info[:2] == (3, 12)):
                try:
                    import lmdeploy  # noqa: F401
                    return "fast"
                except ImportError:
                    pass
            return "standard"  # GGUF với GPU offload
        # cpu
        return "standard" if quality == "high" else "turbo"
    
    async def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
        *,
        speed: float = 1.0,
        emotion: str = "natural",
        ref_audio: Optional[Path] = None,
        ref_text: Optional[str] = None,
    ) -> TTSResult:
        if not text.strip():
            raise TTSError("TTS_TEXT_EMPTY", "Empty text", backend=self.name)
        
        await self._ensure_engine()
        
        # Resolve voice — preset hoặc clone
        if ref_audio is not None:
            voice_data = None
            ref_audio_path = str(ref_audio)
            ref_text_str = ref_text or ""
        else:
            try:
                voice_data = await asyncio.to_thread(self._engine.get_preset_voice, voice)
            except (KeyError, ValueError) as e:
                raise TTSError("TTS_VOICE_NOT_FOUND",
                               f"Voice '{voice}' không có. Available: "
                               f"{[v for _, v in self._engine.list_preset_voices()]}",
                               backend=self.name) from e
            ref_audio_path = None
            ref_text_str = None
        
        t0 = time.time()
        try:
            audio_np: np.ndarray = await asyncio.to_thread(
                self._engine.infer,
                text=text,
                voice=voice_data,
                ref_audio=ref_audio_path,
                ref_text=ref_text_str,
                temperature=self.settings.tts.vieneu_temperature,
                top_k=50,
                apply_watermark=False,  # AIFlow personal, không cần watermark
                show_progress=False,
            )
        except Exception as e:
            err_msg = str(e).lower()
            if "out of memory" in err_msg or "cuda" in err_msg and "memory" in err_msg:
                raise TTSError("TTS_OOM",
                               f"VRAM hết khi gen {len(text)} chars. "
                               "Giảm AIFLOW_TTS_QUALITY hoặc đổi sang CPU.",
                               backend=self.name) from e
            raise TTSError("TTS_BACKEND_UNAVAILABLE",
                           f"VieNeu infer fail: {e}", backend=self.name) from e
        
        elapsed = time.time() - t0
        sample_rate = self._engine.sample_rate  # = 24000
        
        # Apply speed (đơn giản qua resample — sửa được nếu Phase 3+ cần atempo)
        if abs(speed - 1.0) > 0.01:
            audio_np = self._apply_speed(audio_np, speed)
        
        # Save: VieNeu trả float32 mono — AIFlow chuẩn dùng mp3 192k mono
        await asyncio.to_thread(self._save_as_mp3, audio_np, sample_rate, output_path)
        
        if not output_path.exists() or output_path.stat().st_size < 1024:
            raise TTSError("TTS_OUTPUT_INVALID",
                           f"Output file invalid: {output_path}", backend=self.name)
        
        duration_sec = len(audio_np) / sample_rate
        rtf = elapsed / duration_sec if duration_sec > 0 else None
        
        return TTSResult(
            output_path=output_path,
            duration_sec=duration_sec,
            sample_rate=sample_rate,
            backend_used=self.name,
            voice_id=voice,
            rtf=rtf,
            metadata={"mode": self._mode, "device": self._device, "elapsed_sec": elapsed},
        )
    
    def _apply_speed(self, audio: np.ndarray, speed: float) -> np.ndarray:
        """Phase 3.1 — naive resample. Phase 3.2 chuyển sang ffmpeg atempo (giữ pitch)."""
        # Naive: drop/repeat samples → pitch sẽ shift. Acceptable cho speed ∈ [0.8, 1.2]
        new_len = int(len(audio) / speed)
        idx = np.linspace(0, len(audio) - 1, new_len).astype(np.int64)
        return audio[idx]
    
    def _save_as_mp3(self, audio: np.ndarray, sr: int, output_path: Path):
        """VieNeu trả numpy → soundfile chỉ ghi WAV trực tiếp.
        Để có mp3, ghi WAV temp rồi ffmpeg encode."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".wav":
            sf.write(str(output_path), audio, sr, subtype="PCM_16")
            return
        
        # mp3 path
        wav_temp = output_path.with_suffix(".temp.wav")
        sf.write(str(wav_temp), audio, sr, subtype="PCM_16")
        try:
            run_ffmpeg([
                "-y", "-i", str(wav_temp),
                "-codec:a", "libmp3lame", "-b:a", "192k", "-ac", "1",
                str(output_path),
            ])
        finally:
            wav_temp.unlink(missing_ok=True)
    
    async def close(self):
        if self._engine is not None:
            await asyncio.to_thread(self._engine.close)
            self._engine = None
            # Trigger GC để release VRAM/RAM
            import gc
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
```

## EdgeTTSProvider — implementation

`server/audio/tts/edge_provider.py`:

```python
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

import edge_tts

from server.audio.tts import TTSProvider, TTSResult, TTSError
from server.audio.ffmpeg_utils import probe_duration

log = logging.getLogger(__name__)


# Voice catalog tiếng Việt + một số bilingual hữu ích
EDGE_VI_VOICES = {
    "vi-VN-HoaiMyNeural": "Nữ, ấm, neutral — default",
    "vi-VN-NamMinhNeural": "Nam, trẻ, năng lượng",
    "en-US-AriaNeural":   "Nữ EN — narration bilingual",
    "en-US-GuyNeural":    "Nam EN",
}


class EdgeTTSProvider:
    name = "edge_tts"
    
    async def is_available(self) -> bool:
        # edge_tts không có pre-flight thực — nó chỉ fail khi gọi
        return True
    
    async def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
        *,
        speed: float = 1.0,
        emotion: str = "natural",          # ignored
        ref_audio: Optional[Path] = None,  # ignored — edge không hỗ trợ
        ref_text: Optional[str] = None,
    ) -> TTSResult:
        if not text.strip():
            raise TTSError("TTS_TEXT_EMPTY", "Empty text", backend=self.name)
        
        if voice not in EDGE_VI_VOICES:
            raise TTSError("TTS_VOICE_NOT_FOUND",
                           f"edge_tts không có voice '{voice}'. Available: {list(EDGE_VI_VOICES)}",
                           backend=self.name)
        
        # edge_tts dùng SSML rate format: "+0%" / "-10%" / "+20%"
        rate_pct = round((speed - 1.0) * 100)
        rate = f"{'+' if rate_pct >= 0 else ''}{rate_pct}%"
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        
        try:
            communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
            await communicate.save(str(output_path))
        except edge_tts.exceptions.NoAudioReceived as e:
            raise TTSError("TTS_OUTPUT_INVALID",
                           "edge_tts trả 0 bytes — voice/text có thể bị Microsoft block",
                           backend=self.name) from e
        except Exception as e:
            raise TTSError("TTS_NETWORK_ERROR",
                           f"edge_tts fail: {e}", backend=self.name) from e
        
        if not output_path.exists() or output_path.stat().st_size < 1024:
            raise TTSError("TTS_OUTPUT_INVALID",
                           f"Output invalid: {output_path}", backend=self.name)
        
        elapsed = time.time() - t0
        duration_sec = await asyncio.to_thread(probe_duration, output_path)
        
        return TTSResult(
            output_path=output_path,
            duration_sec=duration_sec,
            sample_rate=24000,           # edge mp3 default
            backend_used=self.name,
            voice_id=voice,
            rtf=elapsed / duration_sec if duration_sec > 0 else None,
            metadata={"rate": rate, "elapsed_sec": elapsed},
        )
    
    async def close(self):
        pass  # stateless
```

## Fallback chain — TTSService

`server/audio/tts/service.py`:

```python
import logging
from pathlib import Path
from typing import Optional, List

from server.audio.tts import TTSProvider, TTSResult, TTSError, BackendName
from server.audio.tts.vieneu_provider import VieNeuTTSProvider
from server.audio.tts.edge_provider import EdgeTTSProvider
from server.config import Settings

log = logging.getLogger(__name__)


class TTSService:
    """Singleton orchestrator. Init 1 lần ở lifespan, share giữa request."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self._providers: dict[str, TTSProvider] = {
            "vieneu": VieNeuTTSProvider(settings),
            "edge_tts": EdgeTTSProvider(),
        }
        # Provider order = primary → fallbacks
        self._chain: List[str] = self._build_chain(settings.tts.primary)
    
    def _build_chain(self, primary: str) -> List[str]:
        if primary == "vieneu":
            return ["vieneu", "edge_tts"]
        if primary == "edge_tts":
            return ["edge_tts", "vieneu"]
        # auto
        return ["vieneu", "edge_tts"]
    
    async def synthesize(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        output_path: Path,
        speed: float = 1.0,
        emotion: str = "natural",
        ref_audio: Optional[Path] = None,
        ref_text: Optional[str] = None,
        force_backend: Optional[str] = None,
    ) -> TTSResult:
        """Try providers theo chain. Return result đầu tiên success.
        
        Args:
            voice: Nếu None, dùng default theo backend đầu tiên trong chain
            force_backend: Override chain, chỉ thử 1 backend (UI override)
        """
        chain = [force_backend] if force_backend else self._chain
        last_error: Optional[TTSError] = None
        
        for backend_key in chain:
            provider = self._providers[backend_key]
            if not await provider.is_available():
                log.warning(f"[tts] {backend_key} unavailable, skip")
                continue
            
            chosen_voice = voice or self._default_voice_for(backend_key)
            
            try:
                log.info(f"[tts] try {backend_key} voice={chosen_voice}")
                result = await provider.synthesize(
                    text=text, voice=chosen_voice, output_path=output_path,
                    speed=speed, emotion=emotion,
                    ref_audio=ref_audio, ref_text=ref_text,
                )
                log.info(f"[tts] {backend_key} OK rtf={result.rtf:.2f} "
                         f"dur={result.duration_sec:.1f}s")
                return result
            except TTSError as e:
                log.warning(f"[tts] {backend_key} fail: {e.code} — {e.message}")
                last_error = e
                # OOM cho VieNeu → close để release VRAM trước khi fallback
                if e.code == "TTS_OOM":
                    await provider.close()
                continue
        
        raise TTSError(
            "TTS_ALL_FAILED",
            f"All TTS backends failed. Last: {last_error.message if last_error else 'unknown'}",
            backend=last_error.backend if last_error else None,
        )
    
    def _default_voice_for(self, backend: str) -> str:
        if backend == "edge_tts":
            return self.settings.tts.edge_default_voice  # vi-VN-HoaiMyNeural
        return self.settings.tts.vieneu_default_voice    # Binh
    
    async def close_all(self):
        for p in self._providers.values():
            await p.close()
```

`main.py` lifespan thêm:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... bootstrap_schema, ws_server ...
    app.state.tts = TTSService(settings)
    yield
    await app.state.tts.close_all()
```

## GPU/CPU selection logic chi tiết

Quyết định device theo flowchart:

```
AIFLOW_TTS_DEVICE = ?
│
├── "cpu"  ──────────────────►  device = cpu
│
├── "cuda" ──┐
│            ├── torch.cuda.is_available() = True ──►  device = cuda
│            └── False ──►  RAISE TTS_BACKEND_UNAVAILABLE
│                          (user explicit ép cuda nhưng không có)
│
└── "auto" (default)
             ├── torch.cuda.is_available() = True ──►  device = cuda
             └── False ──────────────────────────────►  device = cpu
```

Sau khi có device, chọn mode:

```
device == "cuda":
   AIFLOW_TTS_QUALITY=high + USE_LMDEPLOY=true + Python 3.12 + lmdeploy import OK
       → mode = "fast"  (LMDeploy Turbomind, batch size 4, ~2-3GB VRAM)
   else
       → mode = "standard" (GGUF + n_gpu_layers=-1, ~1GB VRAM)

device == "cpu":
   AIFLOW_TTS_QUALITY=high
       → mode = "standard" (Q4-K-M GGUF, RAM ~3-4GB, RTF 0.5-1.0×)
   AIFLOW_TTS_QUALITY=fast (default cho CPU)
       → mode = "turbo"   (Turbo GGUF, RAM ~1-2GB, RTF 0.2-0.4×)
```

Quy ước UI:
- Dropdown "Backend" có 4 lựa chọn user-friendly:
  - **Auto** (dựa device + quality)
  - **GPU — High Quality** (force LMDeploy hoặc fail)
  - **GPU — Fast** (force standard GGUF GPU)
  - **CPU — High Quality** (force standard CPU)
  - **CPU — Fast** (force Turbo CPU)
  - **Online (edge_tts)**
- Backend → mapped sang `(AIFLOW_TTS_DEVICE, AIFLOW_TTS_QUALITY, AIFLOW_TTS_PRIMARY)` qua API endpoint `/api/tts/preference`

## Config — thêm vào `.env.example`

```dotenv
# ─── TTS (Phase 3) ───────────────────────────────────────────────────
AIFLOW_TTS_PRIMARY=vieneu                      # vieneu | edge_tts
AIFLOW_TTS_DEVICE=auto                         # auto | cpu | cuda
AIFLOW_TTS_QUALITY=high                        # high | fast (cho VieNeu)

# VieNeu-TTS local
AIFLOW_TTS_VIENEU_BACKBONE_REPO=pnnbao-ump/VieNeu-TTS-v2
AIFLOW_TTS_VIENEU_CODEC_REPO=neuphonic/neucodec-onnx-decoder-int8
AIFLOW_TTS_VIENEU_DEFAULT_VOICE=Binh           # Voice id từ voices.json
AIFLOW_TTS_VIENEU_EMOTION=natural              # natural | storytelling
AIFLOW_TTS_VIENEU_TEMPERATURE=1.0
AIFLOW_TTS_VIENEU_USE_LMDEPLOY=true            # Yêu cầu Python 3.12 + CUDA 12.8
AIFLOW_TTS_VIENEU_MODELS_DIR=./storage/models/vieneu  # HF cache override

# edge-tts (online fallback)
AIFLOW_TTS_EDGE_DEFAULT_VOICE=vi-VN-HoaiMyNeural
```

`server/config.py` thêm:

```python
class TTSSettings(BaseSettings):
    primary: Literal["vieneu", "edge_tts"] = "vieneu"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    quality: Literal["high", "fast"] = "high"
    
    # VieNeu
    vieneu_backbone_repo: str = "pnnbao-ump/VieNeu-TTS-v2"
    vieneu_codec_repo: str = "neuphonic/neucodec-onnx-decoder-int8"
    vieneu_default_voice: str = "Binh"
    vieneu_emotion: Literal["natural", "storytelling"] = "natural"
    vieneu_temperature: float = 1.0
    vieneu_use_lmdeploy: bool = True
    vieneu_models_dir: Path = Path("./storage/models/vieneu")
    
    # Edge
    edge_default_voice: str = "vi-VN-HoaiMyNeural"
    
    @property
    def vieneu_device(self) -> str:
        return self.device
    
    @model_validator(mode="after")
    def check_quality_device(self):
        # Cảnh báo combination không khôn ngoan
        if self.device == "cpu" and self.quality == "high":
            import warnings
            warnings.warn(
                "AIFLOW_TTS_DEVICE=cpu + QUALITY=high → RTF ~0.5-1.0× (chậm). "
                "Khuyến nghị QUALITY=fast cho CPU."
            )
        return self


class Settings(BaseSettings):
    # ... existing fields ...
    tts: TTSSettings = Field(default_factory=TTSSettings)
```

`pyproject.toml` thêm vào extras:

```toml
[project.optional-dependencies]
audio-edge = [
    "edge-tts>=7.0",
]
audio-vieneu-cpu = [
    "vieneu>=2.7.0",
    # llama-cpp Windows pre-built wheel — install riêng theo doc
]
audio-vieneu-gpu = [
    "vieneu[gpu]>=2.7.0",
    # Cần Python 3.12 + CUDA 12.8 cho LMDeploy
]
```

User Phase 3 install theo nhu cầu:
```powershell
# Tối thiểu (online fallback)
pip install -e .[dev,audio-edge]

# CPU local
pip install -e .[dev,audio-edge,audio-vieneu-cpu] `
    --extra-index-url https://pnnbao97.github.io/llama-cpp-python-v0.3.16/cpu/

# GPU local (yêu cầu Python 3.12)
pip install -e .[dev,audio-edge,audio-vieneu-gpu] `
    --extra-index-url https://download.pytorch.org/whl/cu128
```

## API endpoints — UI selection

`server/api/routes/tts.py`:

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter()


class TTSBackendInfo(BaseModel):
    key: str                 # "vieneu_cpu_turbo", ...
    label: str               # User-facing
    available: bool
    requires: list[str]      # ["CUDA", "Python 3.12"]
    estimated_rtf: str       # "0.2-0.4×"
    quality: str             # "high" | "medium" | "low"


@router.get("/api/tts/backends")
async def list_backends() -> list[TTSBackendInfo]:
    """UI populate dropdown. Probe device 1 lần."""
    import torch
    has_cuda = torch.cuda.is_available() if _torch_available() else False
    is_py312 = sys.version_info[:2] == (3, 12)
    
    return [
        TTSBackendInfo(key="auto", label="Auto (recommend)", available=True,
                       requires=[], estimated_rtf="—", quality="high"),
        TTSBackendInfo(key="vieneu_gpu_lmdeploy", label="VieNeu GPU — High Quality",
                       available=has_cuda and is_py312,
                       requires=["NVIDIA GPU (≥6GB VRAM)", "Python 3.12", "CUDA 12.8"],
                       estimated_rtf="~0.05×", quality="high"),
        TTSBackendInfo(key="vieneu_gpu_gguf", label="VieNeu GPU — Fast",
                       available=has_cuda,
                       requires=["NVIDIA GPU (≥4GB VRAM)"],
                       estimated_rtf="~0.1-0.2×", quality="high"),
        TTSBackendInfo(key="vieneu_cpu_standard", label="VieNeu CPU — High Quality",
                       available=True,
                       requires=["RAM ≥6GB"],
                       estimated_rtf="~0.5-1.0×", quality="high"),
        TTSBackendInfo(key="vieneu_cpu_turbo", label="VieNeu CPU — Fast",
                       available=True,
                       requires=["RAM ≥4GB"],
                       estimated_rtf="~0.2-0.4×", quality="medium"),
        TTSBackendInfo(key="edge_tts", label="Online (Microsoft Edge)",
                       available=True,
                       requires=["Internet"],
                       estimated_rtf="network-bound", quality="medium"),
    ]


@router.get("/api/tts/voices")
async def list_voices(backend: str = "auto") -> list[dict]:
    """Trả voice list theo backend."""
    if backend.startswith("vieneu") or backend == "auto":
        engine = await _get_or_load_vieneu()
        return [{"id": vid, "label": desc} for desc, vid in engine.list_preset_voices()]
    if backend == "edge_tts":
        return [{"id": k, "label": v} for k, v in EDGE_VI_VOICES.items()]
    return []


class TTSPreferenceRequest(BaseModel):
    backend: str             # key từ /backends
    voice: str
    quality: str = "high"


@router.post("/api/tts/preference")
async def set_preference(req: TTSPreferenceRequest):
    """UI lưu preference vào DB Config table — applies cho project mới."""
    backend_to_settings = {
        "auto":                ("auto", "high",  "vieneu"),
        "vieneu_gpu_lmdeploy": ("cuda", "high",  "vieneu"),
        "vieneu_gpu_gguf":     ("cuda", "fast",  "vieneu"),
        "vieneu_cpu_standard": ("cpu",  "high",  "vieneu"),
        "vieneu_cpu_turbo":    ("cpu",  "fast",  "vieneu"),
        "edge_tts":            ("auto", "high",  "edge_tts"),
    }
    device, quality, primary = backend_to_settings[req.backend]
    # Persist vào Config table (vd "tts.preference.backend")
    # ...
    return {"ok": True, "applied": req.backend}


@router.post("/api/tts/test")
async def test_synthesis(backend: str, voice: str, text: str = "Xin chào, đây là test."):
    """UI play sample 1 câu để user nghe trước khi commit."""
    output = settings.data_dir / "tmp" / f"tts_test_{int(time.time())}.mp3"
    result = await app.state.tts.synthesize(
        text=text, voice=voice, output_path=output,
        force_backend=_map_ui_to_provider(backend),
    )
    return {
        "url": f"/api/tts/test/audio/{output.name}",
        "duration_sec": result.duration_sec,
        "rtf": result.rtf,
        "backend_used": result.backend_used,
    }
```

UI flow:
```
1. User mở project settings
2. Frontend GET /api/tts/backends → render dropdown với label + availability badge
3. User chọn backend → GET /api/tts/voices?backend=... → populate voice dropdown
4. User chọn voice → click "Test" → POST /api/tts/test với text mẫu → play audio
5. Click "Save" → POST /api/tts/preference
```

## Quality Gate G4 integration

G4 (spec 07) check audio sau TTS. KHÔNG cần thay đổi rule G4, chỉ note:

| G4 check | Source value |
|----------|--------------|
| G4.1 file size > 10KB | từ filesystem, độc lập backend |
| G4.2 duration ≈ estimate | dùng `TTSResult.duration_sec` thay vì ffprobe lại (tránh I/O double) |
| G4.3 RMS > -60 dBFS | librosa load lại |
| G4.5 sample_rate ≥ 16kHz | `TTSResult.sample_rate` |

`pipeline/orchestrator.py` Phase 3.1:

```python
result: TTSResult = await app.state.tts.synthesize(
    text=project.full_narration,
    voice=skill.voice_id,
    output_path=output_dir / "audio.mp3",
    emotion=skill.emotion,
)

# Persist vào Job/Project metadata
project.audio_path = result.output_path
project.audio_duration_sec = result.duration_sec
project.audio_backend_used = result.backend_used

# G4 check
g4_result = await quality_gate.run("G4", project=project, tts_result=result)
if not g4_result.passed:
    if g4_result.critical_failures:
        raise PipelineError(f"G4 critical: {g4_result.critical_failures}")
```

`tts_result` được pass vào G4 runner — runner dùng `tts_result.duration_sec` cho G4.2, vẫn ffprobe verify cho G4.3/G4.5.

## Windows path handling

### Path bắt buộc dùng `pathlib.Path`

VieNeu nội bộ dùng `pathlib.Path`, edge_tts cần string. Convention AIFlow:
- API/storage: `Path` xuyên suốt
- Convert `str(path)` chỉ khi gọi `edge_tts.Communicate.save()`, `subprocess.run([..., str(path)])`

### Long path

Phase 3 file output có dạng:
```
storage/output/p_a3f9k2/audio.mp3
storage/output/p_a3f9k2/scenes/s_xx_audio_chunk.wav
```

→ Tổng < 100 chars, KHÔNG cần `\\?\` long-path prefix.

### File handle release trên Windows

`soundfile.write` mở file → ghi → đóng synchronously. Tuy nhiên VieNeu warmup tạo `output_path.with_suffix(".temp.wav")` — phải chắc unlink trước khi ffmpeg encode mp3 cùng base name (đã handle trong `_save_as_mp3` với `try/finally` + `unlink(missing_ok=True)`).

### HF cache override

`huggingface_hub` mặc định cache vào `%USERPROFILE%\.cache\huggingface\hub`. Để model VieNeu (~3-4GB) không nuốt ổ C, set:

```dotenv
AIFLOW_TTS_VIENEU_MODELS_DIR=D:/Project/AIFlow/app/storage/models/vieneu
```

`config.py` set env var lúc init:
```python
if settings.tts.vieneu_models_dir:
    os.environ["HF_HOME"] = str(settings.tts.vieneu_models_dir.absolute())
```

### LMDeploy + Windows

`lmdeploy` Windows wheel chỉ build cho Python **3.12**. Nếu user dùng Python 3.11 (default AIFlow):
- `_resolve_mode` skip `mode="fast"`, fallback sang `"standard"` GGUF GPU offload
- Log warning rõ ràng: "LMDeploy yêu cầu Python 3.12. Hiện đang dùng standard mode."

User muốn GPU LMDeploy phải:
1. Cài Python 3.12 song song
2. Tạo venv riêng `.venv-py312` chỉ cho TTS
3. Hoặc bump `requires-python` AIFlow lên 3.12

→ Khuyến nghị: AIFlow giữ Python 3.11, chấp nhận GGUF GPU offload (~0.1× RTF) là đủ. LMDeploy dành cho Phase 3.5+ nếu cần boost batch lớn.

### Triton optional

`triton-windows` cài tự động khi `pip install vieneu[gpu]`. Nếu fail, codec compile silently bị skip (`_compile_codec_with_triton` trong `utils.py` return False). Không phải blocker.

## Acceptance criteria

- [ ] `TTSProvider` Protocol định nghĩa rõ, 2 implementation pass mypy
- [ ] `TTSResult` chứa đủ field cho G4 + Whisper input + UI display
- [ ] Auto-detect device hoạt động: máy có CUDA → `vieneu_gpu_*`; không có → `vieneu_cpu_*`
- [ ] Force backend qua `force_backend` param + `/api/tts/preference` set runtime preference
- [ ] Fallback chain test: kill network → vieneu_cpu_turbo work; force vieneu+OOM → fallback edge_tts
- [ ] `AIFLOW_TTS_DEVICE=cuda` trên máy không CUDA → friendly `TTSError` message
- [ ] Voice list endpoint trả đúng voices theo backend
- [ ] Test endpoint sinh sample 1 câu < 5s (ngoại trừ first-load của VieNeu lazy init)
- [ ] Output luôn là mp3 192kbps mono 24kHz, ffprobe-decodeable
- [ ] G4.2 duration check dùng `TTSResult.duration_sec` không cần ffprobe lại
- [ ] HF cache nằm trong `storage/models/vieneu/`, không ô nhiễm `%USERPROFILE%`
- [ ] VieNeu engine close release VRAM (verify `nvidia-smi` sau `close_all()`)
- [ ] LMDeploy fallback path tested khi Python ≠ 3.12
- [ ] Spec đủ chi tiết để 1 dev khác implement `server/audio/tts/*.py` không hỏi thêm

## Phase mapping

| Component | Phase |
|-----------|-------|
| `TTSProvider` Protocol + `TTSResult` + `TTSError` | 3.1 |
| `EdgeTTSProvider` | 3.1 |
| `TTSService` orchestrator + fallback chain | 3.1 |
| Pipeline integration (Lớp 4 audio gọi service) | 3.1 |
| `VieNeuTTSProvider` standard mode + warmup | 3.2 |
| Auto-detect device + mode selection | 3.2 |
| `/api/tts/*` endpoints | 3.2 |
| LMDeploy fast mode (optional) | 3.3 |
| UI dropdown + voice selector + test playback | 5.x (Phase 5 UI) |
| Voice cloning UI flow (upload ref) | 5.x |

## Open questions

1. **Voice cloning UX**: Phase 5 hay defer Phase 6+? Hiện spec chỉ expose API param `ref_audio` + `ref_text`, không có UI flow.
2. **Concurrency**: 1 instance VieNeu engine giữ 2-4GB. Có cần queue requests không? Phase 3.1 giả định pipeline gọi sequential (1 project 1 lần synth full narration). Phase 3.5+ nếu cho user gen nhiều project song song → cần worker pool / mutex.
3. **Sub-narration mode**: Spec 06 Lớp 4 mention split scene > 16s thành scene_a/scene_b. TTS có cần API render từng segment riêng không? Hiện spec assume render full_narration 1 lần rồi reconcile với Whisper segments — đây là cách rẻ nhất + ít drift pitch nhất.


---

# Addendum A — Voice Gallery (preview audio + custom voice import)

> **Status**: Draft addendum to spec 10
> **Phase mapping**: pre-gen demo → Phase 3.2; custom import endpoints + UI flow → Phase 5.x
> **Depends on**: 10-tts-spec (mọi section trên), 11-custom-voice-training (file zip schema)
> **Backwards compat**: section này KHÔNG modify mọi section trên. Endpoint `/api/tts/voices` được mở rộng với field mới + cho phép field cũ tồn tại — client cũ vẫn parse được.

## Mục đích

Cho user **nghe thử giọng** trước khi chọn (thay vì đoán qua text label). Mở rộng catalog để frontend Phase 5 build UI Voice Gallery dạng grid card. Đồng thời unify path cho custom voice user-trained từ Colab notebook (xem spec 11).

## A.1 — `VoiceInfo` Pydantic model

`server/audio/tts/voice_catalog.py` (file mới):

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field


VoiceGender = Literal["male", "female", "neutral"]
VoiceStyle = Literal["narrative", "conversational", "news", "child"]
VoiceLanguage = Literal["vi", "en", "vi-en"]


class VoiceInfo(BaseModel):
    """Unified voice descriptor cho catalog + preview.
    
    Trả từ GET /api/tts/voices, cũng dùng làm response cho custom import.
    """
    voice_id: str                       # "Binh", "vi-VN-HoaiMyNeural", "phuong-anh-female"
    label: str                          # User-facing display name, vd "Bình (nam miền Bắc)"
    description: Optional[str] = None   # 1-2 câu mô tả style/use case
    
    # Categorization
    gender: VoiceGender = "neutral"
    style: VoiceStyle = "conversational"
    language: VoiceLanguage = "vi"
    
    # Backend compatibility — voice nào hỗ trợ với backend nào
    # vd vieneu preset chỉ chạy được trên backend bắt đầu "vieneu_*"
    supported_backends: list[str] = Field(default_factory=list)
    
    # Demo
    demo_url: Optional[str] = None      # /api/tts/voices/{voice_id}/demo (None nếu chưa gen)
    demo_text: Optional[str] = None     # Câu mẫu đã dùng để gen demo
    demo_duration_sec: Optional[float] = None
    
    # Source tag
    source: Literal["preset", "custom_lora", "custom_embedding"] = "preset"
    is_custom: bool = False             # Computed: source != "preset"
    
    # Custom-only metadata
    created_at: Optional[str] = None    # ISO 8601, chỉ custom
    author: Optional[str] = None        # "user-provided" | None
    
    # Generic extension
    metadata: dict = Field(default_factory=dict)
    
    @classmethod
    def for_preset(cls, voice_id: str, label: str, **kwargs) -> "VoiceInfo":
        return cls(voice_id=voice_id, label=label, source="preset", is_custom=False, **kwargs)
    
    @classmethod
    def for_custom(cls, voice_id: str, label: str, source: str, **kwargs) -> "VoiceInfo":
        assert source in ("custom_lora", "custom_embedding")
        return cls(voice_id=voice_id, label=label, source=source, is_custom=True, **kwargs)
```

### Static metadata cho preset voices

VieNeu preset không có metadata gender/style/language sẵn — phải hard-code 1 lần dựa trên `voices.json` của VieNeu repo:

```python
# server/audio/tts/voice_metadata.py — static lookup table

PRESET_VOICE_METADATA: dict[str, dict] = {
    # VieNeu presets (lấy từ voices.json description)
    "Binh":   {"gender": "male",   "language": "vi", "style": "conversational",
               "description": "Bình — nam miền Bắc, ấm, mặc định khuyên dùng cho narration"},
    "Tuyen":  {"gender": "male",   "language": "vi", "style": "narrative",
               "description": "Tuyên — nam miền Bắc, trầm, phù hợp đọc sách"},
    "Vinh":   {"gender": "male",   "language": "vi", "style": "conversational",
               "description": "Vĩnh — nam miền Nam, ấm, narration tự nhiên"},
    "Doan":   {"gender": "female", "language": "vi", "style": "conversational",
               "description": "Đoan — nữ miền Nam, mềm, podcast/storytelling"},
    "Ly":     {"gender": "female", "language": "vi", "style": "narrative",
               "description": "Ly — nữ miền Bắc, neutral, explainer"},
    "Ngoc":   {"gender": "female", "language": "vi", "style": "conversational",
               "description": "Ngọc — nữ miền Bắc, tươi, vlog/social media"},
    
    # edge_tts presets
    "vi-VN-HoaiMyNeural":  {"gender": "female", "language": "vi", "style": "conversational",
                            "description": "HoàiMy — nữ ấm, neutral, default fallback"},
    "vi-VN-NamMinhNeural": {"gender": "male",   "language": "vi", "style": "conversational",
                            "description": "NamMinh — nam trẻ, năng lượng"},
    "en-US-AriaNeural":    {"gender": "female", "language": "en", "style": "narrative",
                            "description": "Aria — bilingual narration EN"},
    "en-US-GuyNeural":     {"gender": "male",   "language": "en", "style": "conversational",
                            "description": "Guy — bilingual EN, casual"},
}


def supported_backends_for(voice_id: str, source: str = "preset") -> list[str]:
    """Voice nào chạy trên backend nào."""
    if source == "preset":
        if voice_id.startswith("vi-VN-") or voice_id.startswith("en-"):
            return ["edge_tts"]
        # Mọi VieNeu preset chạy trên cả 4 vieneu backend
        return ["vieneu_gpu_lmdeploy", "vieneu_gpu_gguf",
                "vieneu_cpu_standard", "vieneu_cpu_turbo"]
    # Custom voices chỉ chạy được trên VieNeu backend
    return ["vieneu_gpu_gguf", "vieneu_cpu_standard"]  # safe set
```

## A.2 — Updated `/api/tts/voices` endpoint

**Backwards-compatible**: response giờ là `list[VoiceInfo]` thay vì `list[{id, label}]`. Field cũ (`id`, `label`) vẫn có (qua alias) — client chưa update vẫn đọc được.

```python
@router.get("/api/tts/voices", response_model=list[VoiceInfo])
async def list_voices(
    backend: str = "auto",
    source: Optional[Literal["preset", "custom"]] = None,
) -> list[VoiceInfo]:
    """List voice catalog. Hỗ trợ filter theo backend + source.
    
    Args:
        backend: "auto" trả union mọi voice; "vieneu_*" hoặc "edge_tts" trả voice tương thích
        source: "preset" | "custom" | None (cả 2)
    
    Backward-compat: thêm `id` alias cho `voice_id`. Client cũ dùng `.id` vẫn ok.
    """
    voices: list[VoiceInfo] = []
    
    # 1. Preset voices từ engine.list_preset_voices()
    if source in (None, "preset"):
        if backend.startswith("vieneu") or backend == "auto":
            engine = await _get_or_load_vieneu()
            for desc, vid in engine.list_preset_voices():
                meta = PRESET_VOICE_METADATA.get(vid, {})
                voices.append(VoiceInfo.for_preset(
                    voice_id=vid,
                    label=meta.get("label", desc),
                    description=meta.get("description", desc),
                    gender=meta.get("gender", "neutral"),
                    style=meta.get("style", "conversational"),
                    language=meta.get("language", "vi"),
                    supported_backends=supported_backends_for(vid, "preset"),
                    demo_url=_demo_url_if_exists(vid),
                    demo_text=_demo_text_if_exists(vid),
                ))
        
        if backend == "edge_tts" or backend == "auto":
            for vid, desc in EDGE_VI_VOICES.items():
                meta = PRESET_VOICE_METADATA.get(vid, {})
                voices.append(VoiceInfo.for_preset(
                    voice_id=vid,
                    label=meta.get("label", desc),
                    description=meta.get("description", desc),
                    gender=meta.get("gender", "neutral"),
                    style=meta.get("style", "conversational"),
                    language=meta.get("language", "vi"),
                    supported_backends=["edge_tts"],
                    demo_url=_demo_url_if_exists(vid),
                    demo_text=_demo_text_if_exists(vid),
                ))
    
    # 2. Custom voices từ catalog.json
    if source in (None, "custom"):
        catalog = await _load_custom_catalog()
        for entry in catalog.get("voices", []):
            voices.append(VoiceInfo(**entry))
    
    # 3. Filter compatible backend
    if backend != "auto":
        voices = [v for v in voices if backend in v.supported_backends]
    
    return voices


def _demo_url_if_exists(voice_id: str) -> Optional[str]:
    """Return URL nếu file demo đã pre-gen."""
    demo_path = settings.data_dir / "voice_demos" / f"{voice_id}.mp3"
    return f"/api/tts/voices/{voice_id}/demo" if demo_path.exists() else None


def _demo_text_if_exists(voice_id: str) -> Optional[str]:
    """Đọc demo_text từ file metadata bên cạnh demo.mp3."""
    meta_path = settings.data_dir / "voice_demos" / f"{voice_id}.meta.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8")).get("demo_text")
```

## A.3 — Demo audio endpoints

### `GET /api/tts/voices/{voice_id}/demo`

```python
from fastapi import HTTPException
from fastapi.responses import FileResponse


@router.get("/api/tts/voices/{voice_id}/demo")
async def get_voice_demo(voice_id: str):
    """Stream pre-generated demo mp3.
    
    Cache-Control: 7 ngày (demo bất biến giữa lần gen).
    404 nếu chưa pre-gen — kèm hint chạy script.
    """
    demo_path = settings.data_dir / "voice_demos" / f"{voice_id}.mp3"
    
    if not demo_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "DEMO_NOT_GENERATED",
                "message": f"Demo audio chưa tồn tại cho voice '{voice_id}'.",
                "hint": (
                    "Chạy: python scripts/generate_voice_demos.py\n"
                    "Hoặc force regenerate qua: "
                    f"POST /api/tts/voices/{voice_id}/demo/regenerate"
                ),
                "voice_id": voice_id,
            },
        )
    
    return FileResponse(
        path=demo_path,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "public, max-age=604800, immutable",  # 7 ngày
            "Content-Disposition": f'inline; filename="{voice_id}.mp3"',
        },
    )
```

### `POST /api/tts/voices/{voice_id}/demo/regenerate`

```python
@router.post("/api/tts/voices/{voice_id}/demo/regenerate")
async def regenerate_voice_demo(voice_id: str, request: Request):
    """Force re-gen 1 demo. Yêu cầu backend tương thích phải available.
    
    Use case:
    - User vừa import custom voice → auto trigger
    - User update VieNeu model → invalidate cache
    - Demo cũ corrupt
    """
    # 1. Validate voice_id tồn tại
    voices = await list_voices(backend="auto", source=None)
    target = next((v for v in voices if v.voice_id == voice_id), None)
    if target is None:
        raise HTTPException(status_code=404,
                            detail={"error": "VOICE_NOT_FOUND", "voice_id": voice_id})
    
    # 2. Pick backend khả dụng cho voice này
    tts: TTSService = request.app.state.tts
    backend_key = None
    for candidate in target.supported_backends:
        provider_key = "vieneu" if candidate.startswith("vieneu") else candidate
        provider = tts._providers.get(provider_key)
        if provider and await provider.is_available():
            backend_key = provider_key
            break
    
    if backend_key is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "TTS_BACKEND_UNAVAILABLE",
                "message": f"Không backend nào khả dụng để gen demo cho '{voice_id}'.",
                "supported_backends": target.supported_backends,
            },
        )
    
    # 3. Gen demo
    display_name = _extract_display_name(target)
    demo_text = f"Xin chào! Tôi là {display_name}. Đây là ví dụ giọng đọc của tôi."
    
    demo_dir = settings.data_dir / "voice_demos"
    demo_dir.mkdir(parents=True, exist_ok=True)
    output_path = demo_dir / f"{voice_id}.mp3"
    
    try:
        result = await tts.synthesize(
            text=demo_text, voice=voice_id, output_path=output_path,
            force_backend=backend_key,
        )
    except TTSError as e:
        raise HTTPException(status_code=500,
                            detail={"error": e.code, "message": e.message})
    
    # 4. Persist meta để future GET trả demo_text
    meta_path = demo_dir / f"{voice_id}.meta.json"
    meta_path.write_text(json.dumps({
        "demo_text": demo_text,
        "duration_sec": result.duration_sec,
        "backend_used": result.backend_used,
        "regenerated_at": datetime.utcnow().isoformat() + "Z",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return {
        "ok": True,
        "voice_id": voice_id,
        "demo_url": f"/api/tts/voices/{voice_id}/demo",
        "demo_text": demo_text,
        "duration_sec": result.duration_sec,
        "backend_used": result.backend_used,
    }


def _extract_display_name(voice: VoiceInfo) -> str:
    """Lấy tên ngắn từ label (vd 'Bình (nam miền Bắc)' → 'Bình')."""
    label = voice.label or voice.voice_id
    return label.split(" (")[0].split(" -")[0].strip()
```

## A.4 — Custom voice import / delete

Tương ứng với output zip của Colab notebook spec 11. Reuse schema `metadata.json` đã định nghĩa trong spec 11.

### `POST /api/tts/voices/custom/import`

```python
import zipfile, shutil, json, hashlib
from fastapi import UploadFile, File, HTTPException


@router.post("/api/tts/voices/custom/import", response_model=VoiceInfo)
async def import_custom_voice(
    file: UploadFile = File(...),
    overwrite: bool = False,
    request: Request = None,
):
    """Import zip từ Colab notebook. Auto-gen demo sau import.
    
    Body: multipart/form-data với field 'file' = zip ≤ 200 MB
    """
    # 1. Size + magic check
    if file.size and file.size > 200 * 1024 * 1024:
        raise HTTPException(400, detail={"error": "FILE_TOO_LARGE",
                                          "max_mb": 200})
    
    tmp_zip = settings.data_dir / "tmp" / f"upload_{int(time.time())}.zip"
    tmp_zip.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # 2. Save upload
        async with aiofiles.open(tmp_zip, "wb") as f:
            content = await file.read()
            await f.write(content)
        
        # 3. Extract vào tmp + validate metadata.json
        tmp_extract = settings.data_dir / "tmp" / f"extract_{int(time.time())}"
        tmp_extract.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(tmp_zip, "r") as z:
                # Anti zip-bomb: check uncompressed size + member paths
                total = sum(zi.file_size for zi in z.infolist())
                if total > 500 * 1024 * 1024:
                    raise HTTPException(400, detail={"error": "ZIP_BOMB"})
                for zi in z.infolist():
                    # Path traversal protection
                    if zi.filename.startswith("/") or ".." in zi.filename:
                        raise HTTPException(400, detail={"error": "ZIP_PATH_INVALID"})
                z.extractall(tmp_extract)
        except zipfile.BadZipFile:
            raise HTTPException(400, detail={"error": "ZIP_CORRUPT"})
        
        meta_file = tmp_extract / "metadata.json"
        if not meta_file.exists():
            raise HTTPException(400, detail={
                "error": "METADATA_MISSING",
                "message": "Zip thiếu metadata.json. Đây không phải package AIFlow custom voice.",
            })
        
        try:
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise HTTPException(400, detail={"error": "METADATA_INVALID_JSON",
                                              "message": str(e)})
        
        # 4. Schema validate
        if metadata.get("spec") != "aiflow.custom_voice":
            raise HTTPException(400, detail={
                "error": "METADATA_WRONG_SPEC",
                "expected": "aiflow.custom_voice",
                "got": metadata.get("spec"),
            })
        
        voice_id = metadata.get("voice_id")
        if not voice_id or not _validate_voice_id(voice_id):
            raise HTTPException(400, detail={
                "error": "VOICE_ID_INVALID",
                "message": "voice_id phải kebab-case [a-z][a-z0-9-]{1,40}",
            })
        
        approach = metadata.get("approach")
        if approach not in ("lora_finetune", "persistent_embedding"):
            raise HTTPException(400, detail={
                "error": "APPROACH_INVALID",
                "valid": ["lora_finetune", "persistent_embedding"],
            })
        
        # 5. Required artifacts theo approach
        if not (tmp_extract / "voices.json").exists():
            raise HTTPException(400, detail={"error": "VOICES_JSON_MISSING"})
        
        if approach == "lora_finetune":
            lora_dir = tmp_extract / "lora"
            if not lora_dir.exists() or not (lora_dir / "adapter_config.json").exists():
                raise HTTPException(400, detail={
                    "error": "LORA_FOLDER_INCOMPLETE",
                    "required_files": ["lora/adapter_config.json", "lora/adapter_model.safetensors"],
                })
        
        # 6. Conflict check
        target_dir = settings.data_dir / "voice_gallery" / voice_id
        if target_dir.exists() and not overwrite:
            raise HTTPException(409, detail={
                "error": "VOICE_ALREADY_EXISTS",
                "voice_id": voice_id,
                "hint": "Thêm ?overwrite=true để ghi đè, hoặc đổi voice_id trước khi import.",
            })
        
        # 7. Move vào storage chính + register catalog
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(tmp_extract), str(target_dir))
        
        source = "custom_lora" if approach == "lora_finetune" else "custom_embedding"
        voice_info = VoiceInfo(
            voice_id=voice_id,
            label=metadata.get("display_name", voice_id),
            description=metadata.get("description"),
            gender=metadata.get("gender", "neutral"),
            language=metadata.get("language", "vi"),
            style=metadata.get("style", "conversational"),
            source=source,
            is_custom=True,
            supported_backends=supported_backends_for(voice_id, source),
            created_at=metadata.get("created_at"),
            author=metadata.get("author", "user-provided"),
            metadata={"approach_details": metadata.get("approach_details", {})},
        )
        
        await _register_custom_voice(voice_info)
        
        # 8. Auto-gen demo (best effort, không block import nếu fail)
        try:
            await regenerate_voice_demo(voice_id, request)
            voice_info.demo_url = f"/api/tts/voices/{voice_id}/demo"
            voice_info.demo_text = (
                f"Xin chào! Tôi là {_extract_display_name(voice_info)}. "
                "Đây là ví dụ giọng đọc của tôi."
            )
        except HTTPException as e:
            log.warning(f"Demo gen skip cho {voice_id}: {e.detail}")
        
        return voice_info
    
    finally:
        # Cleanup tmp
        tmp_zip.unlink(missing_ok=True)
        if tmp_extract.exists():
            shutil.rmtree(tmp_extract, ignore_errors=True)


def _validate_voice_id(vid: str) -> bool:
    import re
    return bool(re.match(r"^[a-z][a-z0-9-]{1,40}$", vid))


async def _register_custom_voice(voice: VoiceInfo):
    """Append vào catalog.json + ghi metadata.json gallery."""
    gallery_dir = settings.data_dir / "voice_gallery"
    gallery_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = gallery_dir / "catalog.json"
    
    catalog = json.loads(catalog_path.read_text("utf-8")) if catalog_path.exists() else {
        "schema_version": "1.0", "voices": []
    }
    catalog["voices"] = [v for v in catalog["voices"] if v["voice_id"] != voice.voice_id]
    catalog["voices"].append(voice.model_dump(exclude_none=True))
    catalog["updated_at"] = datetime.utcnow().isoformat() + "Z"
    
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), "utf-8")
```

### `DELETE /api/tts/voices/custom/{voice_id}`

```python
@router.delete("/api/tts/voices/custom/{voice_id}")
async def delete_custom_voice(voice_id: str):
    """Xoá custom voice + cleanup. Refuse preset voices."""
    # 1. Reject preset
    if voice_id in PRESET_VOICE_METADATA:
        raise HTTPException(403, detail={
            "error": "CANNOT_DELETE_PRESET",
            "message": f"'{voice_id}' là preset, không xoá được. Chỉ ẩn qua UI.",
        })
    
    # 2. Path check
    target_dir = settings.data_dir / "voice_gallery" / voice_id
    if not target_dir.exists():
        raise HTTPException(404, detail={"error": "VOICE_NOT_FOUND",
                                          "voice_id": voice_id})
    
    # 3. Remove gallery folder
    shutil.rmtree(target_dir)
    
    # 4. Remove demo
    demo_path = settings.data_dir / "voice_demos" / f"{voice_id}.mp3"
    demo_meta = settings.data_dir / "voice_demos" / f"{voice_id}.meta.json"
    demo_path.unlink(missing_ok=True)
    demo_meta.unlink(missing_ok=True)
    
    # 5. Remove from catalog
    catalog_path = settings.data_dir / "voice_gallery" / "catalog.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text("utf-8"))
        catalog["voices"] = [v for v in catalog["voices"] if v["voice_id"] != voice_id]
        catalog["updated_at"] = datetime.utcnow().isoformat() + "Z"
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), "utf-8")
    
    return {"ok": True, "voice_id": voice_id, "deleted": True}
```

## A.5 — `storage/voice_gallery/` schema

```
storage/
├── voice_gallery/                           ← Custom voices imported by user
│   ├── catalog.json                         ← Index file (auto-rebuild OK)
│   ├── phuong-anh-female/                   ← 1 folder per voice
│   │   ├── metadata.json                    ← Schema từ spec 11 §Output format
│   │   ├── voices.json                      ← VieNeu preset codes
│   │   ├── demo.mp3                         ← Auto-gen sau import
│   │   ├── README.md
│   │   └── lora/                            ← Chỉ approach=lora_finetune
│   │       ├── adapter_model.safetensors
│   │       ├── adapter_config.json
│   │       └── tokenizer*.json
│   └── narrator-male-deep/
│       └── ...
│
└── voice_demos/                             ← Pre-gen preset demos (separate from custom)
    ├── Binh.mp3
    ├── Binh.meta.json                       ← {"demo_text", "duration_sec", "backend_used"}
    ├── vi-VN-HoaiMyNeural.mp3
    └── ...
```

`catalog.json` format:

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-05-27T11:30:00Z",
  "voices": [
    {
      "voice_id": "phuong-anh-female",
      "label": "Phương Anh",
      "description": "Nữ miền Bắc, ấm, narration",
      "gender": "female",
      "style": "narrative",
      "language": "vi",
      "source": "custom_lora",
      "is_custom": true,
      "supported_backends": ["vieneu_gpu_gguf", "vieneu_cpu_standard"],
      "demo_url": "/api/tts/voices/phuong-anh-female/demo",
      "demo_text": "Xin chào! Tôi là Phương Anh. Đây là ví dụ giọng đọc của tôi.",
      "demo_duration_sec": 3.4,
      "created_at": "2026-05-27T10:30:00+07:00",
      "author": "user-provided",
      "metadata": {
        "approach_details": {
          "base_model": "pnnbao-ump/VieNeu-TTS-0.3B",
          "training_steps": 3000,
          "dataset_total_seconds": 1842
        }
      }
    }
  ]
}
```

Catalog rebuild policy: nếu user xoá thủ công folder `voice_gallery/{voice_id}/` ngoài API, lần tiếp theo `/api/tts/voices?source=custom` đọc thấy entry trỏ folder không tồn tại → silently filter ra. Background task `scripts/rebuild_voice_catalog.py` (Phase 5.1) sẽ rescan và rewrite catalog.json sạch.

## A.6 — `scripts/generate_voice_demos.py`

Script chạy 1 lần sau khi VieNeu model download xong (Phase 3.2 setup) hoặc anytime sau khi update model.

```python
"""Pre-generate demo audio cho mọi preset voice.

Idempotent: skip voice nếu file demo đã tồn tại + meta khớp.
Use case:
    - Phase 3.2 setup: chạy sau khi `python -m server.main` lần đầu (HF download xong)
    - Sau khi đổi AIFLOW_TTS_VIENEU_BACKBONE_REPO: xoá storage/voice_demos/* rồi chạy lại
    - Cron daily/weekly không cần thiết (demo bất biến)

Usage:
    python scripts/generate_voice_demos.py                # gen all
    python scripts/generate_voice_demos.py --voice Binh   # 1 voice
    python scripts/generate_voice_demos.py --force        # re-gen kể cả khi đã có
    python scripts/generate_voice_demos.py --backend edge_tts  # chỉ edge voices
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from server.config import load_settings
from server.audio.tts import TTSError
from server.audio.tts.service import TTSService
from server.audio.tts.voice_metadata import PRESET_VOICE_METADATA, supported_backends_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gen_voice_demos")

DEMO_TEMPLATE = "Xin chào! Tôi là {name}. Đây là ví dụ giọng đọc của tôi."


def _display_name(voice_id: str) -> str:
    meta = PRESET_VOICE_METADATA.get(voice_id, {})
    desc = meta.get("description", "")
    if " — " in desc:
        return desc.split(" — ")[0].strip()
    return voice_id.split("-Neural")[0].replace("vi-VN-", "").replace("en-US-", "")


async def _enumerate_voices(svc: TTSService, backend_filter: str | None) -> list[tuple[str, str]]:
    """Trả [(voice_id, primary_backend), ...]."""
    out = []
    
    # VieNeu preset
    if backend_filter is None or backend_filter.startswith("vieneu"):
        provider = svc._providers.get("vieneu")
        if provider and await provider.is_available():
            try:
                await provider._ensure_engine()
                for desc, vid in provider._engine.list_preset_voices():
                    out.append((vid, "vieneu"))
            except Exception as e:
                log.warning(f"VieNeu enumerate fail: {e}")
    
    # Edge presets — luôn có
    if backend_filter is None or backend_filter == "edge_tts":
        from server.audio.tts.edge_provider import EDGE_VI_VOICES
        for vid in EDGE_VI_VOICES:
            out.append((vid, "edge_tts"))
    
    return out


async def _gen_one(svc: TTSService, voice_id: str, backend_key: str, demo_dir: Path,
                   force: bool) -> bool:
    """Trả True nếu thành công (gen mới HOẶC skip vì đã có)."""
    out_path = demo_dir / f"{voice_id}.mp3"
    meta_path = demo_dir / f"{voice_id}.meta.json"
    
    if out_path.exists() and not force:
        log.info(f"  ⏭️  Skip {voice_id} (đã có)")
        return True
    
    name = _display_name(voice_id)
    text = DEMO_TEMPLATE.format(name=name)
    
    try:
        result = await svc.synthesize(
            text=text, voice=voice_id, output_path=out_path,
            force_backend=backend_key,
        )
    except TTSError as e:
        log.error(f"  ❌ {voice_id} fail: {e.code} — {e.message}")
        return False
    except Exception as e:
        log.error(f"  ❌ {voice_id} unexpected error: {e}")
        return False
    
    meta_path.write_text(json.dumps({
        "voice_id": voice_id,
        "demo_text": text,
        "duration_sec": result.duration_sec,
        "backend_used": result.backend_used,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    
    size_kb = out_path.stat().st_size / 1024
    log.info(f"  ✅ {voice_id} ({size_kb:.0f} KB, {result.duration_sec:.1f}s, "
             f"backend={result.backend_used})")
    return True


async def main_async(args):
    settings = load_settings()
    demo_dir = settings.data_dir / "voice_demos"
    demo_dir.mkdir(parents=True, exist_ok=True)
    
    svc = TTSService(settings)
    
    voices = await _enumerate_voices(svc, args.backend)
    if args.voice:
        voices = [(vid, bk) for vid, bk in voices if vid == args.voice]
        if not voices:
            log.error(f"Voice '{args.voice}' không có trong catalog")
            return 1
    
    log.info(f"📋 Sẽ gen demo cho {len(voices)} voice(s)")
    
    success, failed = 0, 0
    for i, (voice_id, backend_key) in enumerate(voices, 1):
        log.info(f"[{i}/{len(voices)}] Generating demo for voice: {voice_id}")
        ok = await _gen_one(svc, voice_id, backend_key, demo_dir, args.force)
        if ok:
            success += 1
        else:
            failed += 1
    
    await svc.close_all()
    
    log.info("")
    log.info("=" * 60)
    log.info(f"🎉 Done: {success} ok, {failed} failed")
    log.info(f"   Output: {demo_dir}")
    log.info("=" * 60)
    return 0 if failed == 0 else 2


def main():
    p = argparse.ArgumentParser(description="Pre-generate voice demo audio")
    p.add_argument("--voice", help="Chỉ gen 1 voice cụ thể")
    p.add_argument("--backend", choices=["vieneu", "edge_tts"], help="Filter")
    p.add_argument("--force", action="store_true", help="Re-gen kể cả khi đã có")
    args = p.parse_args()
    
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
```

Behavior summary:
- Idempotent: file đã tồn tại → skip (trừ `--force`)
- Per-voice progress log: `[i/Y] Generating demo for voice: {voice_id}`
- Failure isolation: 1 voice fail không block voice còn lại
- Exit code: 0 nếu mọi voice OK, 2 nếu có ít nhất 1 fail
- Persist `.meta.json` bên cạnh để `/api/tts/voices` đọc được `demo_text` + `duration_sec`

## A.7 — Frontend UI flow (chỉ spec endpoint)

```
┌─────────────────────────────────────────────────────────────┐
│ Voice Gallery panel                                          │
│                                                              │
│ Tab: [ All voices ] [ Custom voices ]                       │
│                                                              │
│ ┌─────────┬─────────┬─────────┬─────────┐                   │
│ │ 🎤      │ 🎤      │ 🎤      │ 🎤      │                   │
│ │ Bình    │ Tuyên   │ Đoan    │ Phương Anh │ ← is_custom   │
│ │ ♂ 🇻🇳 vi│ ♂ 🇻🇳 vi│ ♀ 🇻🇳 vi│ ♀ 🇻🇳 vi+✨│                   │
│ │ ▶ Nghe  │ ▶ Nghe  │ ▶ Nghe  │ ▶ Nghe   │                   │
│ │ ✓ Chọn  │ ✓ Chọn  │ ✓ Chọn  │ ✓ Chọn   │                   │
│ └─────────┴─────────┴─────────┴─────────┘                   │
│                                                              │
│ Tab "Custom voices":                                         │
│   [ 📁 Import từ file ] [ 🎓 Train giọng mới (Colab) ]      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

API contract per UI action:

| UI action | Method | Endpoint | Notes |
|-----------|--------|----------|-------|
| Mở Voice Gallery | `GET` | `/api/tts/voices` | Lấy tất cả, filter trong UI bằng `source`/`is_custom` |
| Filter "All / Custom" tab | `GET` | `/api/tts/voices?source=preset` hoặc `?source=custom` | |
| Click ▶ "Nghe thử" | `GET` | `/api/tts/voices/{voice_id}/demo` | Audio element src trực tiếp; browser cache nhờ Cache-Control 7d |
| `demo_url=null` → "Generate demo" | `POST` | `/api/tts/voices/{voice_id}/demo/regenerate` | Backend phải available; UI show loading 5-15s |
| Click ✓ "Chọn" | `POST` | `/api/tts/preference` | (đã có ở section trên) |
| Click "Import từ file" | `POST` | `/api/tts/voices/custom/import` | Multipart upload zip |
| Click "Xoá" trên custom card | `DELETE` | `/api/tts/voices/custom/{voice_id}` | UI confirm dialog trước |
| "Train giọng mới (Colab)" | — | Mở link `https://colab.research.google.com/...` tới notebook spec 11 | Static link, không cần backend |

Card props từ `VoiceInfo`:
- Avatar: emoji theo gender (`♂` male / `♀` female / `◯` neutral) + flag theo language
- Badge: `✨` nếu `is_custom=true`
- Tooltip: `description` field
- Style chip: `style` field (narrative/conversational/news/child)

## A.8 — Acceptance criteria (bổ sung spec 10)

- [ ] `VoiceInfo` Pydantic model validate được mọi field, có alias `id` cho `voice_id` (backwards-compat)
- [ ] `GET /api/tts/voices` trả `list[VoiceInfo]` đầy đủ field gender/style/language; client cũ vẫn parse được nhờ alias
- [ ] `GET /api/tts/voices/{voice_id}/demo` trả mp3 với Cache-Control 7 ngày; 404 kèm hint khi chưa pre-gen
- [ ] `POST /api/tts/voices/{voice_id}/demo/regenerate` chạy < 15s cho VieNeu preset (sau khi engine warmed up)
- [ ] `scripts/generate_voice_demos.py` idempotent: chạy lần 2 không gen lại; `--force` re-gen; log progress `[i/Y]` rõ
- [ ] `POST /api/tts/voices/custom/import` reject zip không có `metadata.json` với `aiflow.custom_voice` spec, reject path-traversal, reject zip bomb (>500 MB uncompressed)
- [ ] Import auto-trigger demo gen ngay sau extract; nếu demo fail (vd OOM) vẫn return 200 với `demo_url=null`
- [ ] `DELETE /api/tts/voices/custom/{voice_id}` cleanup hoàn toàn `voice_gallery/{voice_id}/` + `voice_demos/{voice_id}.*`; refuse với HTTP 403 nếu voice là preset
- [ ] `catalog.json` rebuildable: xoá file → next API call vẫn list đúng voices từ folder scan

## A.9 — Phase mapping (bổ sung)

| Component | Phase |
|-----------|-------|
| `VoiceInfo` model + `PRESET_VOICE_METADATA` lookup | 3.2 |
| `/api/tts/voices` mở rộng schema | 3.2 |
| `scripts/generate_voice_demos.py` | 3.2 (chạy sau setup) |
| `GET /api/tts/voices/{id}/demo` | 3.2 |
| `POST /api/tts/voices/{id}/demo/regenerate` | 3.3 |
| `POST /api/tts/voices/custom/import` | 5.1 |
| `DELETE /api/tts/voices/custom/{id}` | 5.1 |
| Voice Gallery UI grid + tabs | 5.2 |
| "Train giọng mới" link → Colab | 5.2 |

## A.10 — Open questions (bổ sung)

1. **Demo voice text per language**: hiện template tiếng Việt. Cho voice EN/bilingual có nên có template "Hello! I am {name}. This is a sample of my voice."? → Phase 3.3 có thể detect `voice.language` và pick template tương ứng.
2. **Demo audio length**: ~3-5s đủ preview hay nên 8-10s để user nghe đa dạng prosody hơn? Trade-off: file size + gen time.
3. **Preset hide**: User muốn "ẩn" preset voice khỏi Gallery (vd dislike). Cần thêm `hidden_voices` list trong DB Config — defer Phase 5.2.
4. **Multi-language voice card**: voice bilingual `vi-en` hiển thị 2 flag hay 1 flag tổng hợp? UI/UX decision Phase 5.2.

## A.11 — Helpers full implementation (REVIEW-02 #10)

Các helper được mention trong A.2/A.4 nhưng chỉ stub. Phase 3.2/5.1 implement đầy đủ:

```python
# server/audio/tts/voice_catalog.py — phần helpers

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from server.config import load_settings

log = logging.getLogger(__name__)

_settings = load_settings()
_VIENEU_LOCK = asyncio.Lock()
_VIENEU_PROVIDER = None  # Singleton


async def _get_or_load_vieneu():
    """Lazy-load VieNeu provider. Idempotent + thread-safe.
    
    Dùng trong /api/tts/voices để list preset voice. Engine load 30-60s lần đầu
    nên cache singleton. Subsequent call instant.
    """
    global _VIENEU_PROVIDER
    if _VIENEU_PROVIDER is not None and _VIENEU_PROVIDER._engine is not None:
        return _VIENEU_PROVIDER._engine
    
    async with _VIENEU_LOCK:
        if _VIENEU_PROVIDER is None:
            from server.audio.tts.vieneu_provider import VieNeuTTSProvider
            _VIENEU_PROVIDER = VieNeuTTSProvider(_settings)
        await _VIENEU_PROVIDER._ensure_engine()
        return _VIENEU_PROVIDER._engine


_CATALOG_CACHE: Optional[dict] = None
_CATALOG_MTIME: float = 0.0


async def _load_custom_catalog() -> dict:
    """Load + cache catalog.json. Re-read khi file modified.
    
    Tránh re-read mỗi request: cache theo mtime. Khi user import voice mới,
    catalog.json update → mtime thay đổi → next call re-read.
    """
    global _CATALOG_CACHE, _CATALOG_MTIME
    
    catalog_path = _settings.data_dir / "voice_gallery" / "catalog.json"
    if not catalog_path.exists():
        return {"schema_version": "1.0", "voices": []}
    
    current_mtime = catalog_path.stat().st_mtime
    if _CATALOG_CACHE is not None and current_mtime == _CATALOG_MTIME:
        return _CATALOG_CACHE
    
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error(f"catalog.json corrupt: {e} — fallback empty")
        return {"schema_version": "1.0", "voices": []}
    
    # Filter voices có folder thực sự tồn tại (defensive cho user xoá thủ công)
    valid_voices = []
    for entry in catalog.get("voices", []):
        vid = entry.get("voice_id")
        if vid and (_settings.data_dir / "voice_gallery" / vid).exists():
            valid_voices.append(entry)
    
    catalog["voices"] = valid_voices
    _CATALOG_CACHE = catalog
    _CATALOG_MTIME = current_mtime
    return catalog


def invalidate_catalog_cache() -> None:
    """Gọi sau import/delete để force re-read next time.
    
    Tránh stale cache khi /api/tts/voices/custom/import vừa update catalog.json
    nhưng cache vẫn giữ phiên bản cũ.
    """
    global _CATALOG_CACHE, _CATALOG_MTIME
    _CATALOG_CACHE = None
    _CATALOG_MTIME = 0.0
```

`/api/tts/voices/custom/import` và `delete_custom_voice` PHẢI gọi `invalidate_catalog_cache()` sau khi update file.

```python
# Trong _register_custom_voice:
def _register_custom_voice(voice: VoiceInfo):
    # ... write catalog.json ...
    invalidate_catalog_cache()  # ← Force re-read next /api/tts/voices

# Trong delete_custom_voice:
async def delete_custom_voice(voice_id: str):
    # ... cleanup ...
    invalidate_catalog_cache()
```
