"""VideoRemasterAdapter — wraps VideoRemaster + DownloadManager as a ContentAdapter.

Input (``AdapterInput.raw_content``): A well-formed video URL (http/https).

Options (``AdapterInput.options``):
    - ``preset``          (str)  — ``"light"`` | ``"aggressive"`` | ``"translate_only"``
                                   (default: ``"light"``)
    - ``workdir``         (str)  — working directory for downloads/output
                                   (default: system temp dir)
    - ``source_language`` (str)  — source language code (default: ``"zh"``)
    - ``target_language`` (str)  — target language code (default: ``"vi"``)
    - ``project_id``      (str)  — project identifier for the SceneList
    - ``cookies``         (str)  — path to a Netscape cookies file (optional)

Output: ``SceneList`` with 1 scene (passthrough marker set in metadata).

The single scene carries:
    - ``prompt``    — human-readable description of the remastered video
    - ``duration``  — clamped to [3, 30] (from DownloadResult.duration or 8.0)
    - ``narration`` — empty string (no TTS narration for remastered video)

``SceneList.metadata`` carries:
    - ``passthrough``   — ``True`` (orchestrator must NOT generate Veo3 clips)
    - ``source_kind``   — ``"remastered_video"``
    - ``output_path``   — absolute path to the remastered video file
    - ``preset``        — preset that was applied
    - ``translated_srt``— path to the translated SRT file

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.9, 2.10, 2.11, 2.12, 2.13,
              6.7, 7.10
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from server.content.base import (
    AdapterError,
    AdapterInput,
    SceneList,
    SceneSpec,
)
from server.content.crawlers.base import DownloadError
from server.content.crawlers.manager import DownloadManager
from server.content.crawlers.remaster import (
    RemasterConfig,
    RemasterPreset,
    VideoRemaster,
)
from server.content.pipeline_limits import enforce_pipeline_limits

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_PRESET = "light"
_DEFAULT_SOURCE_LANGUAGE = "zh"
_DEFAULT_TARGET_LANGUAGE = "vi"

# Retry configuration (R7.10)
_DEFAULT_RETRIES = 2          # total attempts = 1 + retries
_DEFAULT_SLEEP_SEC = 1.0      # fixed sleep between retries

# Duration clamp bounds (SceneList.validate() requires [3, 30])
_DURATION_MIN = 3.0
_DURATION_MAX = 30.0
_DURATION_DEFAULT = 8.0       # Veo3_Clip_Duration fallback

# Preset string → RemasterPreset mapping
_PRESET_MAP: dict[str, RemasterPreset] = {
    "light": RemasterPreset.LIGHT,
    "aggressive": RemasterPreset.AGGRESSIVE,
    "translate_only": RemasterPreset.TRANSLATE_ONLY,
}


# ─── Retry helper ─────────────────────────────────────────────────────────────


def download_with_retry(
    manager: DownloadManager,
    url: str,
    workdir: Path,
    *,
    cookies: Optional[Path] = None,
    retries: int = _DEFAULT_RETRIES,
    sleep_sec: float = _DEFAULT_SLEEP_SEC,
) -> object:
    """Download *url* with a fixed-sleep retry policy.

    Wraps :meth:`~server.content.crawlers.manager.DownloadManager.download`
    with a simple retry loop.  On exhausting all attempts, raises
    :class:`~server.content.base.AdapterError` with code
    ``"ADAPTER_DOWNLOAD_FAILED"`` and ``details={"url": url, "code": ...}``.

    Args:
        manager:    :class:`~server.content.crawlers.manager.DownloadManager`
                    instance to delegate to.
        url:        Video URL to download.
        workdir:    Directory where the downloaded file will be saved.
        cookies:    Optional path to a Netscape-format cookies file.
        retries:    Number of *additional* attempts after the first failure
                    (total attempts = ``retries + 1``).
        sleep_sec:  Fixed sleep in seconds between attempts.  Pass ``0`` in
                    tests to avoid slowing down the test suite.

    Returns:
        :class:`~server.content.crawlers.base.DownloadResult` on success.

    Raises:
        :class:`~server.content.base.AdapterError`: With code
            ``"ADAPTER_DOWNLOAD_FAILED"`` after all attempts are exhausted.
    """
    last_err: Optional[DownloadError] = None

    for attempt in range(retries + 1):  # total = 1 + retries
        try:
            return manager.download(url, workdir, cookies=cookies)
        except DownloadError as exc:
            last_err = exc
            logger.warning(
                "Download attempt %d/%d failed for %r: [%s] %s",
                attempt + 1,
                retries + 1,
                url,
                exc.code,
                exc.reason,
            )
            if attempt < retries:
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

    # All attempts exhausted
    assert last_err is not None  # always set after at least one attempt
    raise AdapterError(
        "ADAPTER_DOWNLOAD_FAILED",
        f"Download failed after {retries + 1} attempt(s): {last_err.reason}",
        details={"url": url, "code": last_err.code},
    )


# ─── VideoRemasterAdapter ─────────────────────────────────────────────────────


class VideoRemasterAdapter:
    """ContentAdapter that wraps VideoRemaster + DownloadManager.

    Accepts a video URL, downloads it (with retry), runs the full
    translate + remaster pipeline, and returns a passthrough
    :class:`~server.content.base.SceneList`.

    Attributes:
        adapter_type: Registry key — ``"video_remaster"``.
    """

    adapter_type: str = "video_remaster"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Download, remaster, and return a passthrough SceneList.

        Processing order:
        1. ``validate_input()`` — URL well-formed? (raises on failure)
        2. Resolve preset from ``options`` (default ``"light"``)
        3. Resolve working directory (``options["workdir"]`` or temp dir)
        4. ``download_with_retry()`` — download video (timeout + retry)
        5. Build :class:`~server.content.crawlers.remaster.RemasterConfig`
        6. ``VideoRemaster(cfg).remaster(video_path, workdir)``
        7. Map :class:`~server.content.crawlers.remaster.RemasterResult`
           → :class:`~server.content.base.SceneList` (1 scene, passthrough)
        8. ``SceneList.validate()`` + ``enforce_pipeline_limits()``

        Args:
            input: Adapter input with URL in ``raw_content``.

        Returns:
            A passthrough :class:`~server.content.base.SceneList` with 1 scene.

        Raises:
            :class:`~server.content.base.AdapterError`: On any failure.
        """
        # 1. Validate input
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid video_remaster input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        url = input.raw_content.strip()

        # 2. Resolve preset (R2.11 / R2.12)
        preset_str = input.options.get("preset", _DEFAULT_PRESET)
        if isinstance(preset_str, str):
            preset_str = preset_str.lower()
        preset = _PRESET_MAP.get(preset_str, RemasterPreset.LIGHT)
        if preset_str not in _PRESET_MAP:
            logger.warning(
                "Unknown preset %r — falling back to 'light'", preset_str
            )

        # 3. Resolve working directory
        workdir_opt = input.options.get("workdir")
        if workdir_opt:
            workdir = Path(workdir_opt)
            workdir.mkdir(parents=True, exist_ok=True)
            _tmp_ctx = None
        else:
            import contextlib
            _tmp_ctx = tempfile.TemporaryDirectory(prefix="video_remaster_")
            workdir = Path(_tmp_ctx.name)

        try:
            # 4. Download with retry (R7.10)
            cookies_opt = input.options.get("cookies")
            cookies: Optional[Path] = Path(cookies_opt) if cookies_opt else None

            manager = DownloadManager()
            download_result = download_with_retry(
                manager,
                url,
                workdir,
                cookies=cookies,
            )

            video_path: Path = download_result.output_path  # type: ignore[union-attr]
            video_duration: float = getattr(download_result, "duration", 0.0) or 0.0

            # 5. Build RemasterConfig
            gemini_client = input.options.get("gemini_client")
            source_language = input.options.get(
                "source_language", _DEFAULT_SOURCE_LANGUAGE
            )
            target_language = input.options.get(
                "target_language", _DEFAULT_TARGET_LANGUAGE
            )

            cfg = RemasterConfig(
                preset=preset,
                source_language=source_language,
                target_language=target_language,
                gemini_client=gemini_client,
            )

            # 6. Run VideoRemaster (R2.4 / R2.6 / R6.7)
            remaster = VideoRemaster(cfg)
            result = await remaster.remaster(video_path, workdir)

            # 7. Map RemasterResult → SceneList
            scene_list = self._build_scene_list(
                result=result,
                video_duration=video_duration,
                input=input,
                preset_str=preset_str,
            )

            # 8. Validate + enforce limits (R2.7)
            ok, validation_errors = scene_list.validate()
            if not ok:
                raise AdapterError(
                    "ADAPTER_INVALID_OUTPUT",
                    f"Generated SceneList failed validation: {'; '.join(validation_errors)}",
                    details={"errors": validation_errors},
                )
            enforce_pipeline_limits(scene_list)

            logger.info(
                "VideoRemasterAdapter: remaster complete → %s (preset=%s)",
                result.output_path,
                preset.value,
            )
            return scene_list

        finally:
            # Clean up temp dir if we created one
            if _tmp_ctx is not None:
                try:
                    _tmp_ctx.cleanup()
                except Exception:  # noqa: BLE001
                    pass

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Validate the adapter input without downloading or calling any API.

        Checks that ``raw_content`` is a well-formed URL with an http/https
        scheme and a non-empty netloc.  Does NOT attempt to download the URL
        or call any external service (R2.8).

        Args:
            input: The adapter input to validate.

        Returns:
            A list of human-readable error strings.  Empty list = valid.
        """
        errors: list[str] = []

        url = (input.raw_content or "").strip()
        if not url:
            errors.append("raw_content must not be empty — expected a video URL")
            return errors

        try:
            parsed = urlparse(url)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"raw_content is not a valid URL: {exc}")
            return errors

        if parsed.scheme not in ("http", "https"):
            errors.append(
                f"URL scheme must be 'http' or 'https', got {parsed.scheme!r}"
            )

        if not parsed.netloc:
            errors.append("URL must have a non-empty host (netloc)")

        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_scene_list(
        self,
        result: object,
        video_duration: float,
        input: AdapterInput,  # noqa: A002
        preset_str: str,
    ) -> SceneList:
        """Map a :class:`~server.content.crawlers.remaster.RemasterResult`
        to a passthrough :class:`~server.content.base.SceneList`.

        The SceneList contains exactly one scene.  Duration is clamped to
        [3, 30] to satisfy ``SceneList.validate()``.

        Args:
            result:         The remaster result.
            video_duration: Duration from the download result (seconds).
            input:          Original adapter input (for project_id / voice).
            preset_str:     Preset string that was applied.

        Returns:
            A :class:`~server.content.base.SceneList` with 1 passthrough scene.
        """
        from server.content.crawlers.remaster import RemasterResult  # local import

        assert isinstance(result, RemasterResult)

        # Clamp duration to [3, 30] (R2.7 / SceneList.validate requirement)
        raw_duration = video_duration if video_duration > 0 else _DURATION_DEFAULT
        duration = max(_DURATION_MIN, min(_DURATION_MAX, raw_duration))

        output_path = result.output_path
        translated_srt = result.translated_srt

        scene = SceneSpec(
            order=0,
            prompt=f"Remastered video: {output_path.name}",
            duration=duration,
            narration="",
        )

        metadata: dict = {
            "passthrough": True,                          # orchestrator: skip Veo3
            "source_kind": "remastered_video",
            "output_path": str(output_path),
            "translated_srt": str(translated_srt),
            "preset": preset_str,
            "adapter": self.adapter_type,
        }

        if result.original_srt is not None:
            metadata["original_srt"] = str(result.original_srt)

        return SceneList(
            project_id=input.options.get("project_id", "video_remaster"),
            scenes=[scene],
            voice=input.options.get("voice"),
            metadata=metadata,
        )


# ─── Module-level auto-discovery exports ─────────────────────────────────────

#: Shared instance used by :class:`~server.content.registry.AdapterRegistry`
#: auto-discovery (``ADAPTER`` convention).
ADAPTER: VideoRemasterAdapter = VideoRemasterAdapter()

#: Class reference for registry ``ADAPTER_CLASS`` convention.
ADAPTER_CLASS = VideoRemasterAdapter
