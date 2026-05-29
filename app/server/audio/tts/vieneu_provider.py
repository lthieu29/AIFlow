"""VieNeuProvider — VieNeu-TTS local backend (offline, GPU/CPU).

Implements the ``TTSProvider`` Protocol defined in ``server/audio/tts/__init__.py``.
Supports 4 backends selected automatically based on device availability and
Python version:

    vieneu_gpu_lmdeploy  — GPU + LMDeploy (Python 3.12+ only)
    vieneu_gpu_gguf      — GPU + GGUF (llama-cpp with n_gpu_layers=-1)
    vieneu_cpu_standard  — CPU standard (Q4-K-M GGUF, higher quality)
    vieneu_cpu_turbo     — CPU turbo (faster, lower quality)

Device auto-detection:
    torch.cuda.is_available() → cuda, else cpu

Model download is lazy — happens on the first ``synthesize()`` call.
LMDeploy is only attempted when Python >= 3.12.

Output format: MP3 192kbps mono 24kHz (AIFlow standard per spec 10).

Phase 3.2 — Task 3.2.1
"""

import logging
import sys
import threading
from pathlib import Path
from typing import Optional

from server.audio.tts import TTSError, TTSResult
from server.audio.ffmpeg_utils import probe_duration, run_ffmpeg
from server.config import Settings

log = logging.getLogger(__name__)

# ─── Backend name constants ───────────────────────────────────────────────────

BACKEND_GPU_LMDEPLOY = "vieneu_gpu_lmdeploy"
BACKEND_GPU_GGUF = "vieneu_gpu_gguf"
BACKEND_CPU_STANDARD = "vieneu_cpu_standard"
BACKEND_CPU_TURBO = "vieneu_cpu_turbo"

# Default voice — VieNeu Vietnamese male preset
DEFAULT_VOICE = "Binh"

# ─── Availability helpers ─────────────────────────────────────────────────────


def _vieneu_importable() -> bool:
    """Return True if the ``vieneu`` package can be imported."""
    try:
        import vieneu  # noqa: F401
        return True
    except ImportError:
        return False


def _torch_cuda_available() -> bool:
    """Return True if torch is installed and CUDA is available."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _lmdeploy_importable() -> bool:
    """Return True if lmdeploy can be imported."""
    try:
        import lmdeploy  # noqa: F401
        return True
    except ImportError:
        return False


# ─── VieNeuProvider ───────────────────────────────────────────────────────────


class VieNeuProvider:
    """Synchronous VieNeu-TTS provider implementing the ``TTSProvider`` Protocol.

    Wraps the VieNeu-TTS library with lazy model loading, GPU/CPU auto-detection,
    and automatic backend selection.  All heavy operations (model load, inference)
    are performed synchronously; threading is handled internally.

    Backend selection logic:
        cuda + Python 3.12+ + lmdeploy importable  →  vieneu_gpu_lmdeploy
        cuda (otherwise)                           →  vieneu_gpu_gguf
        cpu  + quality == "high"                   →  vieneu_cpu_standard
        cpu  + quality == "fast"                   →  vieneu_cpu_turbo
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = None          # Lazy — loaded on first synthesize()
        self._engine_lock = threading.Lock()
        self._resolved_device: Optional[str] = None   # "cuda" | "cpu"
        self._resolved_mode: Optional[str] = None     # "fast" | "standard" | "turbo"
        self._active_backend: Optional[str] = None    # one of the 4 BACKEND_* constants

    # ── Protocol methods ──────────────────────────────────────────────────────

    def backend_name(self) -> str:
        """Return the public backend identifier.

        Before the engine is loaded this returns the *expected* backend based on
        the current environment so the fallback chain can log it correctly.
        """
        if self._active_backend is not None:
            return self._active_backend
        # Pre-init: compute expected backend without loading the model
        device = self._detect_device()
        return self._select_backend(device)

    def is_available(self) -> bool:
        """Return True when the vieneu package is importable.

        Deliberately does NOT attempt to load the model — that happens lazily
        on the first ``synthesize()`` call.  Returns False gracefully when
        VieNeu-TTS is not installed.
        """
        available = _vieneu_importable()
        if not available:
            log.debug("[vieneu] package not importable — is_available=False")
        return available

    def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
        speed: float = 1.0,
    ) -> TTSResult:
        """Synthesise *text* with VieNeu-TTS and write an MP3 to *output_path*.

        Lazy-loads the model on the first call.  Output is encoded to the
        AIFlow standard format: MP3 192kbps mono 24kHz.

        Args:
            text: Narration text to synthesise.
            voice: VieNeu preset voice identifier (e.g. ``"Binh"``).
                   Falls back to ``DEFAULT_VOICE`` if empty.
            output_path: Destination ``.mp3`` file path.
            speed: Playback speed multiplier (1.0 = native).

        Returns:
            TTSResult with success=True, output_path, duration_sec, backend.

        Raises:
            TTSError: On any synthesis or encoding failure.
        """
        if not text.strip():
            raise TTSError(
                message="Empty text provided to VieNeuProvider",
                backend=self.backend_name(),
            )

        resolved_voice = voice.strip() if voice.strip() else DEFAULT_VOICE
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        log.info(
            "[vieneu] synthesize voice=%s speed=%.2f → %s",
            resolved_voice,
            speed,
            output_path,
        )

        # Lazy-load the engine (thread-safe)
        self._ensure_engine()

        # Perform inference
        try:
            audio_np, sample_rate = self._infer(text, resolved_voice, speed)
        except TTSError:
            raise
        except Exception as exc:
            err_msg = str(exc).lower()
            if "out of memory" in err_msg or ("cuda" in err_msg and "memory" in err_msg):
                raise TTSError(
                    message=(
                        f"VRAM exhausted while generating {len(text)} chars. "
                        "Reduce quality or switch to CPU backend."
                    ),
                    backend=self._active_backend or "vieneu",
                ) from exc
            raise TTSError(
                message=f"VieNeu inference failed: {exc}",
                backend=self._active_backend or "vieneu",
            ) from exc

        # Save as MP3 via temp WAV → ffmpeg encode
        try:
            self._save_as_mp3(audio_np, sample_rate, output_path)
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(
                message=f"Audio encoding failed: {exc}",
                backend=self._active_backend or "vieneu",
            ) from exc

        if not output_path.exists() or output_path.stat().st_size < 512:
            raise TTSError(
                message=f"Output file invalid after encoding: {output_path}",
                backend=self._active_backend or "vieneu",
            )

        try:
            duration_sec = probe_duration(output_path)
        except Exception as exc:
            raise TTSError(
                message=f"ffprobe duration check failed: {exc}",
                backend=self._active_backend or "vieneu",
            ) from exc

        log.info(
            "[vieneu] done — backend=%s duration=%.2fs path=%s",
            self._active_backend,
            duration_sec,
            output_path,
        )

        return TTSResult(
            success=True,
            output_path=output_path,
            duration_sec=duration_sec,
            backend=self._active_backend or "vieneu",
        )

    # ── Device / backend selection ────────────────────────────────────────────

    def _detect_device(self) -> str:
        """Resolve the compute device based on settings and environment.

        Respects ``settings.tts.device``:
            "cpu"  → always cpu
            "cuda" → cuda if available, else raise TTSError
            "auto" → cuda if torch.cuda.is_available(), else cpu
        """
        requested = getattr(self._settings.tts, "device", "auto")

        if requested == "cpu":
            return "cpu"

        if requested == "cuda":
            if not _torch_cuda_available():
                raise TTSError(
                    message=(
                        "AIFLOW_TTS_DEVICE=cuda but CUDA is not available. "
                        "Set 'auto' or 'cpu' in .env."
                    ),
                    backend="vieneu",
                )
            return "cuda"

        # "auto" (default)
        return "cuda" if _torch_cuda_available() else "cpu"

    def _select_backend(self, device: str) -> str:
        """Choose the appropriate backend constant for *device*.

        For GPU:
            Python 3.12+ AND lmdeploy importable  →  BACKEND_GPU_LMDEPLOY
            otherwise                              →  BACKEND_GPU_GGUF

        For CPU:
            quality == "high"  →  BACKEND_CPU_STANDARD
            quality == "fast"  →  BACKEND_CPU_TURBO
        """
        if device == "cuda":
            use_lmdeploy = getattr(self._settings.tts, "vieneu_use_lmdeploy", True)
            quality = getattr(self._settings.tts, "quality", "high")
            if (
                use_lmdeploy
                and quality == "high"
                and sys.version_info >= (3, 12)
                and _lmdeploy_importable()
            ):
                return BACKEND_GPU_LMDEPLOY
            return BACKEND_GPU_GGUF

        # cpu
        quality = getattr(self._settings.tts, "quality", "high")
        if quality == "high":
            return BACKEND_CPU_STANDARD
        return BACKEND_CPU_TURBO

    def _backend_to_mode(self, backend: str) -> str:
        """Map a backend constant to the VieNeu-TTS ``mode`` argument."""
        return {
            BACKEND_GPU_LMDEPLOY: "fast",
            BACKEND_GPU_GGUF: "standard",
            BACKEND_CPU_STANDARD: "standard",
            BACKEND_CPU_TURBO: "turbo",
        }.get(backend, "turbo")

    # ── Lazy engine loading ───────────────────────────────────────────────────

    def _ensure_engine(self) -> None:
        """Load the VieNeu-TTS engine if not already loaded (thread-safe)."""
        if self._engine is not None:
            return

        with self._engine_lock:
            if self._engine is not None:
                return  # Another thread loaded it while we waited

            device = self._detect_device()
            backend = self._select_backend(device)
            mode = self._backend_to_mode(backend)

            log.info(
                "[vieneu] loading engine — backend=%s device=%s mode=%s",
                backend,
                device,
                mode,
            )

            models_dir = getattr(
                self._settings.tts,
                "vieneu_models_dir",
                Path("./storage/models/vieneu"),
            )
            models_dir = Path(models_dir)
            models_dir.mkdir(parents=True, exist_ok=True)

            try:
                # Import inside synthesize() so the module loads even without vieneu
                from vieneu import Vieneu  # type: ignore[import]

                kwargs: dict = {}

                if mode == "fast":
                    # LMDeploy backend — GPU only, Python 3.12+
                    kwargs = {
                        "backbone_device": "cuda",
                        "codec_device": "cuda",
                        "max_batch_size": 4,
                    }
                elif mode == "standard":
                    backbone_repo = getattr(
                        self._settings.tts,
                        "vieneu_backbone_repo",
                        "pnnbao-ump/VieNeu-TTS-v2",
                    )
                    codec_repo = getattr(
                        self._settings.tts,
                        "vieneu_codec_repo",
                        "neuphonic/neucodec-onnx-decoder-int8",
                    )
                    kwargs = {
                        "backbone_repo": backbone_repo,
                        "backbone_device": device,
                        "codec_repo": codec_repo,
                        "codec_device": "cpu",  # ONNX codec always on CPU
                    }
                elif mode == "turbo":
                    kwargs = {"device": device}

                emotion = getattr(self._settings.tts, "vieneu_emotion", "natural")
                kwargs["emotion"] = emotion

                engine = Vieneu(mode=mode, **kwargs)

            except ImportError as exc:
                raise TTSError(
                    message=(
                        "VieNeu-TTS is not installed. "
                        "Install with: pip install vieneu  (CPU) "
                        "or pip install vieneu[gpu]  (GPU)"
                    ),
                    backend=backend,
                ) from exc
            except Exception as exc:
                if backend == BACKEND_GPU_LMDEPLOY:
                    # LMDeploy failed — fall back to GGUF GPU
                    log.warning(
                        "[vieneu] LMDeploy load failed (%s) — falling back to GGUF GPU",
                        exc,
                    )
                    backend = BACKEND_GPU_GGUF
                    mode = "standard"
                    try:
                        from vieneu import Vieneu  # type: ignore[import]
                        backbone_repo = getattr(
                            self._settings.tts,
                            "vieneu_backbone_repo",
                            "pnnbao-ump/VieNeu-TTS-v2",
                        )
                        codec_repo = getattr(
                            self._settings.tts,
                            "vieneu_codec_repo",
                            "neuphonic/neucodec-onnx-decoder-int8",
                        )
                        emotion = getattr(self._settings.tts, "vieneu_emotion", "natural")
                        engine = Vieneu(
                            mode="standard",
                            backbone_repo=backbone_repo,
                            backbone_device="cuda",
                            codec_repo=codec_repo,
                            codec_device="cpu",
                            emotion=emotion,
                        )
                    except Exception as fallback_exc:
                        raise TTSError(
                            message=f"VieNeu engine init failed (GGUF fallback): {fallback_exc}",
                            backend=backend,
                        ) from fallback_exc
                else:
                    raise TTSError(
                        message=f"VieNeu engine init failed: {exc}",
                        backend=backend,
                    ) from exc

            self._engine = engine
            self._resolved_device = device
            self._resolved_mode = mode
            self._active_backend = backend

            log.info("[vieneu] engine ready — backend=%s", backend)

    # ── Inference ─────────────────────────────────────────────────────────────

    def _infer(self, text: str, voice: str, speed: float):
        """Run VieNeu-TTS inference and return (audio_np, sample_rate).

        Args:
            text: Text to synthesise.
            voice: Preset voice identifier.
            speed: Speed multiplier.

        Returns:
            Tuple of (numpy.ndarray float32 mono, int sample_rate).

        Raises:
            TTSError: On voice-not-found or inference failure.
        """
        import numpy as np  # noqa: F401 — available in vieneu environment

        try:
            voice_data = self._engine.get_preset_voice(voice)
        except (KeyError, ValueError, AttributeError) as exc:
            raise TTSError(
                message=(
                    f"Voice '{voice}' not found in VieNeu preset catalog. "
                    "Check available voices with engine.list_preset_voices()."
                ),
                backend=self._active_backend or "vieneu",
            ) from exc

        temperature = getattr(self._settings.tts, "vieneu_temperature", 1.0)

        audio_np = self._engine.infer(
            text=text,
            voice=voice_data,
            temperature=temperature,
            top_k=50,
            apply_watermark=False,
            show_progress=False,
        )

        sample_rate: int = getattr(self._engine, "sample_rate", 24000)

        # Apply speed via naive resampling (acceptable for speed ∈ [0.8, 1.2])
        if abs(speed - 1.0) > 0.01:
            audio_np = self._apply_speed(audio_np, speed)

        return audio_np, sample_rate

    @staticmethod
    def _apply_speed(audio, speed: float):
        """Naive speed change via index resampling.

        Phase 3.2 — acceptable for speed ∈ [0.8, 1.2].
        Phase 3.3+ should use ffmpeg atempo to preserve pitch.
        """
        import numpy as np

        new_len = int(len(audio) / speed)
        idx = np.linspace(0, len(audio) - 1, new_len).astype(np.int64)
        return audio[idx]

    # ── Audio encoding ────────────────────────────────────────────────────────

    def _save_as_mp3(self, audio, sample_rate: int, output_path: Path) -> None:
        """Encode numpy audio array to MP3 192kbps mono 24kHz.

        Writes a temporary WAV file then re-encodes via ffmpeg to the AIFlow
        standard format.  The temp WAV is always cleaned up.

        Args:
            audio: numpy float32 mono array.
            sample_rate: Sample rate of *audio* (typically 24000).
            output_path: Destination .mp3 path.

        Raises:
            TTSError: If soundfile or ffmpeg encoding fails.
        """
        import soundfile as sf  # type: ignore[import]

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # If caller wants a WAV, write directly
        if output_path.suffix.lower() == ".wav":
            sf.write(str(output_path), audio, sample_rate, subtype="PCM_16")
            return

        wav_temp = output_path.with_suffix(".vieneu_temp.wav")
        try:
            sf.write(str(wav_temp), audio, sample_rate, subtype="PCM_16")

            run_ffmpeg([
                "-y",
                "-i", str(wav_temp),
                "-codec:a", "libmp3lame",
                "-b:a", "192k",
                "-ac", "1",
                "-ar", "24000",
                str(output_path),
            ])
        except Exception as exc:
            raise TTSError(
                message=f"ffmpeg MP3 encoding failed: {exc}",
                backend=self._active_backend or "vieneu",
            ) from exc
        finally:
            wav_temp.unlink(missing_ok=True)
