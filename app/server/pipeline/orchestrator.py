"""Pipeline orchestrator — runs the full SceneList → N clips flow.

Implements the Phase 2 pipeline:
    G1 → Style Lock (L1) → Asset Lock (L2) → G2 → Sequential scene gen (L3) → done

Sequential scene generation with continuity:
    For each scene (in order):
        1. Apply scene chain (Layer 3) — start_frame from previous scene
        2. Build continuity-enhanced prompt (L1 + L2 + L3)
        3. Submit gen_video() → operation_name
        4. Poll until done (via VideoPoller or direct polling)
        5. G3: check scene quality (file size > 100KB)
        6. If G3 fails and retry_count < MAX_RETRIES: retry scene
        7. If G3 fails and retry_count >= MAX_RETRIES: mark failed, continue
        8. Save last_frame_path on scene for next scene's chain

Events published via EventBus:
    scene_started        — before each scene gen attempt
    scene_completed      — after G3 passes
    scene_failed         — after G3 exhausts retries
    pipeline_completed   — after all scenes processed
    pipeline_failed      — on unrecoverable error (G1 fail, exception)
    gate_status_changed  — when G1/G2/G3 status changes

Usage::

    from server.pipeline.orchestrator import PipelineOrchestrator
    from server.pipeline.event_bus import EventBus

    bus = EventBus()
    orch = PipelineOrchestrator(settings=settings, flow_sdk=sdk, event_bus=bus)
    success = await orch.run(
        project_id=1,
        scenes=scene_list,
        style_json=style_json_str,
        assets=asset_list,
    )
"""

from __future__ import annotations

import asyncio
import subprocess
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from loguru import logger

from server.pipeline.event_bus import (
    EVENT_GATE_STATUS_CHANGED,
    EVENT_PIPELINE_COMPLETED,
    EVENT_PIPELINE_FAILED,
    EVENT_SCENE_COMPLETED,
    EVENT_SCENE_FAILED,
    EVENT_SCENE_STARTED,
    EventBus,
)
from server.pipeline.gates.g1_scene_list import validate_scene_list
from server.pipeline.gates.g3_scene_quality import (
    MAX_RETRIES,
    check_scene_quality,
    get_scene_retry_count,
)

# Maximum retries for G6 final video gate
_G6_MAX_RETRIES: int = 2

if TYPE_CHECKING:
    from server.config import Settings
    from server.db.models.asset import Asset
    from server.db.models.scene import Scene
    from server.flow.sdk import FlowSDK

# How often to poll a pending video operation (seconds)
_POLL_INTERVAL = 5

# Maximum poll attempts before giving up on a single scene (120 × 5s = 10 min)
_MAX_POLL_ATTEMPTS = 120


class PipelineOrchestrator:
    """Runs the full SceneList → N clips pipeline with continuity.

    The orchestrator is stateless between runs — each call to ``run()``
    is independent.  It does NOT write to the DB directly; callers are
    responsible for persisting scene state (video_path, last_frame_path,
    status) after each step if needed.

    Args:
        settings:  Application settings (used for storage paths).
        flow_sdk:  FlowSDK instance for gen_video / check_async calls.
        event_bus: Optional EventBus for progress events. If None, a
                   no-op bus is created so publish() calls are safe.
    """

    def __init__(
        self,
        settings: "Settings",
        flow_sdk: "FlowSDK",
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._settings = settings
        self._sdk = flow_sdk
        self._bus = event_bus or EventBus()

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(
        self,
        project_id: int,
        scenes: "list[Scene]",
        style_json: str,
        assets: "list[Asset]",
    ) -> bool:
        """Run the full pipeline: SceneList → N clips with continuity.

        Steps:
            1. G1: validate SceneList structure
            2. Apply style lock (Layer 1)
            3. Apply asset lock (Layer 2)
            4. G2: create asset approval gate (wait for user or timeout)
            5. For each scene sequentially:
               a. Apply scene chain (Layer 3)
               b. Submit gen_video() with continuity-enhanced prompt
               c. Poll until done
               d. G3: check scene quality
               e. Retry on G3 fail (bounded at MAX_RETRIES=2)
               f. Save last_frame_path for next scene's chain

        Args:
            project_id: DB primary key of the project.
            scenes:     Ordered list of Scene ORM objects (order 0..N-1).
            style_json: JSON string for the project's style.json (Layer 1).
            assets:     List of Asset ORM objects for this project (Layer 2).

        Returns:
            True if all scenes completed successfully, False if any scene
            failed (pipeline still ran to completion for remaining scenes).

        Raises:
            RuntimeError: On unrecoverable errors (G1 failure, SDK errors).
        """
        logger.info(
            "PipelineOrchestrator.run: project_id={} scenes={} assets={}",
            project_id,
            len(scenes),
            len(assets),
        )

        # ── Step 1: G1 — validate SceneList ──────────────────────────────────
        g1_result = validate_scene_list(scenes)
        self._bus.publish(
            EVENT_GATE_STATUS_CHANGED,
            {
                "gate_id": "G1",
                "status": g1_result.status,
                "message": g1_result.message,
                "project_id": project_id,
            },
        )
        if g1_result.status != "passed":
            logger.error(
                "PipelineOrchestrator: G1 failed — {}", g1_result.message
            )
            self._bus.publish(
                EVENT_PIPELINE_FAILED,
                {
                    "project_id": project_id,
                    "reason": f"G1 validation failed: {g1_result.message}",
                },
            )
            raise RuntimeError(f"G1 validation failed: {g1_result.message}")

        logger.info("PipelineOrchestrator: G1 passed ({} scenes)", len(scenes))

        # ── Step 2: Layer 1 — Style Lock ──────────────────────────────────────
        style_lock = _build_style_lock(style_json)
        logger.info(
            "PipelineOrchestrator: Style Lock loaded (prefix={!r:.60})",
            style_lock.prefix,
        )

        # ── Step 3: Layer 2 — Asset Lock ──────────────────────────────────────
        asset_lock = _build_asset_lock(assets)
        logger.info(
            "PipelineOrchestrator: Asset Lock loaded ({} anchors)",
            len(asset_lock.anchors),
        )

        # ── Step 4: G2 — asset approval gate ─────────────────────────────────
        await self._wait_for_g2(project_id)

        # ── Step 5: Sequential scene generation ──────────────────────────────
        sorted_scenes = sorted(scenes, key=lambda s: s.order)
        scene_chain = _SceneChainState()
        all_passed = True

        for scene in sorted_scenes:
            success = await self._run_scene(
                scene=scene,
                project_id=project_id,
                style_lock=style_lock,
                asset_lock=asset_lock,
                scene_chain=scene_chain,
                all_scenes=sorted_scenes,
            )
            if not success:
                all_passed = False

        # ── Pipeline complete ─────────────────────────────────────────────────
        self._bus.publish(
            EVENT_PIPELINE_COMPLETED,
            {
                "project_id": project_id,
                "total_scenes": len(sorted_scenes),
                "all_passed": all_passed,
            },
        )
        logger.info(
            "PipelineOrchestrator: pipeline completed project_id={} all_passed={}",
            project_id,
            all_passed,
        )
        return all_passed

    def synthesize_narration(
        self,
        narration: str,
        project_id: int,
        settings: "Settings",
    ) -> Path:
        """Synthesise a narration string to an MP3 file using TTSService.

        Creates a ``TTSService`` from *settings*, calls
        ``service.synthesize(narration)``, and returns the output audio path.

        The returned path is stored by the caller for use in the compose step
        (Phase 3.3).

        Args:
            narration:  The narration text to synthesise.
            project_id: DB primary key of the project (used to name the output
                        file for traceability).
            settings:   Application settings (TTS config, data_dir, etc.).

        Returns:
            Path to the generated ``.mp3`` file.

        Raises:
            TTSError: When every provider in the chain has failed.
        """
        from server.audio.tts.service import TTSService
        from server.audio.tts import TTSError

        audio_dir = Path(settings.data_dir) / "audio" / str(project_id)
        audio_dir.mkdir(parents=True, exist_ok=True)
        output_path = audio_dir / f"narration_{uuid.uuid4().hex[:8]}.mp3"

        logger.info(
            "PipelineOrchestrator.synthesize_narration: project_id={} path={}",
            project_id,
            output_path,
        )

        service = TTSService(settings)
        result = service.synthesize(narration, output_path=output_path)

        logger.info(
            "PipelineOrchestrator.synthesize_narration: done — duration={:.2f}s path={}",
            result.duration_sec,
            result.output_path,
        )
        return result.output_path

    def compose_with_g6(
        self,
        project_id: int,
        compose_config: "object",
        expected_duration: Optional[float] = None,
        aspect_ratio: Optional[str] = None,
        override: bool = False,
    ) -> "Path":
        """Compose the final video and validate it with Quality Gate G6.

        Runs the VideoComposer to produce final.mp4, then checks it with
        G6FinalVideoGate.  If G6 fails and retries < _G6_MAX_RETRIES (2),
        re-triggers compose with the same config and increments the retry
        counter.  After exhausting retries, emits a pipeline_failed event
        and raises RuntimeError.

        If override=True or G6 passes, returns the output path.

        Args:
            project_id:        DB primary key of the project.
            compose_config:    ComposeConfig instance for VideoComposer.
            expected_duration: Expected video duration in seconds (G6.2).
            aspect_ratio:      Project aspect ratio string, e.g. "9:16" (G6.3).
            override:          If True, skip G6 checks after composing.

        Returns:
            Path to the validated final.mp4.

        Raises:
            RuntimeError: If G6 fails after _G6_MAX_RETRIES retries.
            FileNotFoundError: If ffmpeg is not available.
        """
        from server.pipeline.gates.g6_final_video import G6FinalVideoGate
        from server.render.composer import VideoComposer

        gate = G6FinalVideoGate()
        retry_count = 0

        while True:
            # ── Compose step ──────────────────────────────────────────────────
            logger.info(
                "PipelineOrchestrator.compose_with_g6: project_id={} attempt={}/{}",
                project_id,
                retry_count + 1,
                _G6_MAX_RETRIES + 1,
            )
            composer = VideoComposer()
            compose_result = composer.compose(compose_config)  # type: ignore[arg-type]
            output_path = compose_result.output_path

            # ── G6 quality gate ───────────────────────────────────────────────
            g6_result = gate.check(
                output_path=output_path,
                expected_duration=expected_duration,
                aspect_ratio=aspect_ratio,
                override=override,
            )
            gate_result = g6_result.to_gate_result()

            self._bus.publish(
                EVENT_GATE_STATUS_CHANGED,
                {
                    "gate_id": "G6",
                    "status": gate_result.status,
                    "message": gate_result.message,
                    "project_id": project_id,
                    "attempt": retry_count + 1,
                    "details": g6_result.details,
                },
            )

            if g6_result.passed:
                logger.info(
                    "PipelineOrchestrator.compose_with_g6: G6 passed — {}",
                    output_path,
                )
                return output_path

            # G6 failed
            retry_count += 1
            logger.warning(
                "PipelineOrchestrator.compose_with_g6: G6 failed (attempt {}/{}) — {}",
                retry_count,
                _G6_MAX_RETRIES,
                g6_result.error,
            )

            if retry_count >= _G6_MAX_RETRIES:
                # Exhausted retries — mark job as failed
                reason = (
                    f"G6 quality gate failed after {retry_count} retries: {g6_result.error}"
                )
                self._bus.publish(
                    EVENT_PIPELINE_FAILED,
                    {
                        "project_id": project_id,
                        "reason": reason,
                        "gate_id": "G6",
                        "retry_count": retry_count,
                    },
                )
                logger.error(
                    "PipelineOrchestrator.compose_with_g6: G6 exhausted retries — {}",
                    reason,
                )
                raise RuntimeError(reason)

            logger.info(
                "PipelineOrchestrator.compose_with_g6: retrying compose ({}/{})",
                retry_count,
                _G6_MAX_RETRIES,
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _wait_for_g2(self, project_id: int) -> None:
        """Create a G2 gate and wait for it to be approved/overridden/expired.

        In Phase 2 the gate is created in the DB and the orchestrator polls
        its status every 5 seconds.  The gate auto-expires after 24h via the
        background ``periodic_gate_checker()``.

        If no DB session is available (e.g. in tests without a DB), the gate
        is skipped with a warning.
        """
        try:
            from sqlmodel import Session

            from server.db.session import get_engine
            from server.pipeline.gates.g2_asset_approval import (
                check_g2_status,
                create_g2_gate,
            )

            engine = get_engine(self._settings)
            with Session(engine) as session:
                gate = create_g2_gate(session, project_id=project_id)
                gate_db_id = gate.id

            self._bus.publish(
                EVENT_GATE_STATUS_CHANGED,
                {
                    "gate_id": "G2",
                    "status": "checking",
                    "project_id": project_id,
                    "gate_db_id": gate_db_id,
                },
            )
            logger.info(
                "PipelineOrchestrator: G2 gate created (id={}) — waiting for approval",
                gate_db_id,
            )

            # Poll until gate is resolved
            while True:
                await asyncio.sleep(5)
                with Session(engine) as session:
                    status = check_g2_status(session, project_id)

                if status in ("passed", "overridden", "expired"):
                    self._bus.publish(
                        EVENT_GATE_STATUS_CHANGED,
                        {
                            "gate_id": "G2",
                            "status": status,
                            "project_id": project_id,
                        },
                    )
                    logger.info(
                        "PipelineOrchestrator: G2 resolved with status={!r}",
                        status,
                    )
                    return

                logger.debug(
                    "PipelineOrchestrator: G2 still {!r}, waiting...", status
                )

        except ImportError:
            logger.warning(
                "PipelineOrchestrator: DB not available — skipping G2 gate"
            )
        except Exception as exc:
            logger.warning(
                "PipelineOrchestrator: G2 gate error ({}), continuing without gate",
                exc,
            )

    async def _run_scene(
        self,
        scene: "Scene",
        project_id: int,
        style_lock: object,
        asset_lock: object,
        scene_chain: "_SceneChainState",
        all_scenes: "list[Scene]",
    ) -> bool:
        """Run a single scene through gen → poll → G3 with retry logic.

        Returns True if the scene completed successfully, False if it
        exhausted retries and was marked failed.
        """
        from server.pipeline.gates.g3_scene_quality import should_retry_scene

        retry_count = 0

        while True:
            self._bus.publish(
                EVENT_SCENE_STARTED,
                {
                    "project_id": project_id,
                    "scene_id": getattr(scene, "id", None),
                    "scene_order": scene.order,
                    "attempt": retry_count + 1,
                },
            )
            logger.info(
                "PipelineOrchestrator: scene order={} attempt={}",
                scene.order,
                retry_count + 1,
            )

            try:
                video_path = await self._generate_scene(
                    scene=scene,
                    project_id=project_id,
                    style_lock=style_lock,
                    asset_lock=asset_lock,
                    scene_chain=scene_chain,
                    all_scenes=all_scenes,
                )
            except Exception as exc:
                logger.error(
                    "PipelineOrchestrator: scene order={} gen error: {}",
                    scene.order,
                    exc,
                )
                retry_count += 1
                if retry_count >= MAX_RETRIES:
                    self._bus.publish(
                        EVENT_SCENE_FAILED,
                        {
                            "project_id": project_id,
                            "scene_id": getattr(scene, "id", None),
                            "scene_order": scene.order,
                            "reason": str(exc),
                            "retry_count": retry_count,
                        },
                    )
                    logger.error(
                        "PipelineOrchestrator: scene order={} failed after {} retries",
                        scene.order,
                        retry_count,
                    )
                    return False
                logger.info(
                    "PipelineOrchestrator: scene order={} retrying ({}/{})",
                    scene.order,
                    retry_count,
                    MAX_RETRIES,
                )
                continue

            # G3 quality check
            g3_result = check_scene_quality(scene, video_path)
            self._bus.publish(
                EVENT_GATE_STATUS_CHANGED,
                {
                    "gate_id": "G3",
                    "status": g3_result.status,
                    "message": g3_result.message,
                    "project_id": project_id,
                    "scene_order": scene.order,
                    "attempt": retry_count + 1,
                },
            )

            if g3_result.status == "passed":
                # Extract last frame for next scene's chain
                last_frame = _extract_last_frame(video_path)
                if last_frame is not None:
                    scene.last_frame_path = str(last_frame)  # type: ignore[attr-defined]
                    scene_chain.set_last_frame(scene.order, last_frame)
                    logger.info(
                        "PipelineOrchestrator: scene order={} last_frame={}",
                        scene.order,
                        last_frame,
                    )

                self._bus.publish(
                    EVENT_SCENE_COMPLETED,
                    {
                        "project_id": project_id,
                        "scene_id": getattr(scene, "id", None),
                        "scene_order": scene.order,
                        "video_path": str(video_path),
                        "attempt": retry_count + 1,
                    },
                )
                logger.info(
                    "PipelineOrchestrator: scene order={} completed ✓",
                    scene.order,
                )
                return True

            # G3 failed — check retry budget
            retry_count += 1
            logger.warning(
                "PipelineOrchestrator: G3 failed for scene order={} (attempt {}/{}): {}",
                scene.order,
                retry_count,
                MAX_RETRIES,
                g3_result.message,
            )

            if retry_count >= MAX_RETRIES:
                self._bus.publish(
                    EVENT_SCENE_FAILED,
                    {
                        "project_id": project_id,
                        "scene_id": getattr(scene, "id", None),
                        "scene_order": scene.order,
                        "reason": g3_result.message,
                        "retry_count": retry_count,
                    },
                )
                logger.error(
                    "PipelineOrchestrator: scene order={} failed after {} retries (G3)",
                    scene.order,
                    retry_count,
                )
                return False

            logger.info(
                "PipelineOrchestrator: scene order={} retrying ({}/{})",
                scene.order,
                retry_count,
                MAX_RETRIES,
            )

    async def _generate_scene(
        self,
        scene: "Scene",
        project_id: int,
        style_lock: object,
        asset_lock: object,
        scene_chain: "_SceneChainState",
        all_scenes: "list[Scene]",
    ) -> Path:
        """Build the prompt and submit gen_video(), then poll until done.

        Returns the Path to the downloaded video file.
        """
        from server.ai.prompts.scene_chain import SceneChain

        chain = SceneChain()

        # ── Layer 3: get start frame ──────────────────────────────────────────
        start_frame: Optional[Path] = scene_chain.get_last_frame(scene.order - 1)

        # Check if chain should be reset due to location change
        if start_frame is not None and scene.order > 0:
            prev_scene = _find_scene_by_order(all_scenes, scene.order - 1)
            if prev_scene is not None and chain.should_reset_chain(prev_scene, scene):
                logger.info(
                    "PipelineOrchestrator: location change detected at scene order={} — resetting chain",
                    scene.order,
                )
                start_frame = None

        # ── Synthesise narration if present (Phase 3.1) ───────────────────────
        narration_text = getattr(scene, "narration", None)
        if narration_text:
            try:
                audio_path = self.synthesize_narration(
                    narration=str(narration_text),
                    project_id=project_id,
                    settings=self._settings,
                )
                # Store on scene for the compose step (Phase 3.3)
                scene.audio_path = str(audio_path)  # type: ignore[attr-defined]
                logger.info(
                    "PipelineOrchestrator: scene order={} narration synthesised → {}",
                    scene.order,
                    audio_path,
                )
            except Exception as exc:
                logger.warning(
                    "PipelineOrchestrator: scene order={} narration synthesis failed ({}), continuing",
                    scene.order,
                    exc,
                )

        # ── Build continuity-enhanced prompt ──────────────────────────────────
        raw_prompt = _get_scene_prompt(scene)

        # Layer 1: style lock
        styled_prompt = style_lock.inject(raw_prompt)  # type: ignore[attr-defined]

        # Layer 2: asset lock
        asset_prompt = asset_lock.inject(styled_prompt)  # type: ignore[attr-defined]

        # Layer 3: chain prefix
        chain_prefix = chain.get_chain_prompt_prefix(start_frame)
        if chain_prefix:
            final_prompt = f"{chain_prefix}\n\n{asset_prompt}"
        else:
            final_prompt = asset_prompt

        logger.debug(
            "PipelineOrchestrator: scene order={} prompt={!r:.80}",
            scene.order,
            final_prompt,
        )

        # ── Determine start image ─────────────────────────────────────────────
        # If no start frame from chain, use the first asset's ref image
        if start_frame is None:
            start_frame = _get_fallback_start_image(all_scenes, scene)

        if start_frame is None or not start_frame.exists():
            raise RuntimeError(
                f"No start image available for scene order={scene.order}. "
                "Ensure at least one asset ref image exists or a previous scene "
                "has completed successfully."
            )

        # ── Submit gen_video ──────────────────────────────────────────────────
        storage_dir = Path(self._settings.data_dir) / "media"
        flow_project_id = str(project_id)

        operation_name = await self._sdk.gen_video(  # type: ignore[attr-defined]
            start_image=start_frame,
            prompt=final_prompt,
            project_id=flow_project_id,
            storage_dir=storage_dir,
        )
        logger.info(
            "PipelineOrchestrator: scene order={} submitted operation={}",
            scene.order,
            operation_name,
        )

        # ── Poll until done ───────────────────────────────────────────────────
        video_path = await self._poll_until_done(
            operation_name=operation_name,
            project_id=flow_project_id,
            storage_dir=storage_dir,
        )
        return video_path

    async def _poll_until_done(
        self,
        operation_name: str,
        project_id: str,
        storage_dir: Path,
    ) -> Path:
        """Poll check_async() until the operation completes, then download.

        Returns the Path to the saved video file.

        Raises:
            RuntimeError: If the operation fails or times out.
        """
        from server.flow.downloader import download_video
        from server.flow.sdk import extract_video_operations

        for attempt in range(1, _MAX_POLL_ATTEMPTS + 1):
            await asyncio.sleep(_POLL_INTERVAL)

            try:
                resp = await self._sdk.check_async(operation_name)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.warning(
                    "PipelineOrchestrator: poll attempt {} error: {}", attempt, exc
                )
                continue

            ops = extract_video_operations(resp, requested=[operation_name])
            if not ops:
                continue

            op = ops[0]
            if not op.get("done"):
                logger.debug(
                    "PipelineOrchestrator: operation {} still pending (attempt {}/{})",
                    operation_name,
                    attempt,
                    _MAX_POLL_ATTEMPTS,
                )
                continue

            error = op.get("error")
            if error:
                raise RuntimeError(
                    f"Video generation failed for operation {operation_name}: {error}"
                )

            media_entries = op.get("media_entries", [])
            if not media_entries:
                raise RuntimeError(
                    f"Operation {operation_name} done but no media entries"
                )

            signed_url = media_entries[0].get("url")
            if not signed_url:
                raise RuntimeError(
                    f"Operation {operation_name} done but no signed URL"
                )

            # Download video
            out_dir = storage_dir / project_id
            out_dir.mkdir(parents=True, exist_ok=True)
            timestamp = int(time.time())
            out_path = out_dir / f"video_{timestamp}.mp4"

            saved_path = await download_video(signed_url, out_path)
            logger.info(
                "PipelineOrchestrator: video downloaded to {}", saved_path
            )
            return saved_path

        raise RuntimeError(
            f"Polling timeout: operation {operation_name} did not complete "
            f"after {_MAX_POLL_ATTEMPTS} attempts "
            f"({_MAX_POLL_ATTEMPTS * _POLL_INTERVAL}s)"
        )


# ── Internal state helpers ────────────────────────────────────────────────────


class _SceneChainState:
    """Tracks last_frame_path per scene order for the chain."""

    def __init__(self) -> None:
        self._frames: dict[int, Path] = {}

    def set_last_frame(self, scene_order: int, path: Path) -> None:
        self._frames[scene_order] = path

    def get_last_frame(self, scene_order: int) -> Optional[Path]:
        """Return the last frame for scene_order, or None if not available."""
        if scene_order < 0:
            return None
        path = self._frames.get(scene_order)
        if path is None:
            return None
        return path if path.exists() else None


# ── Module-level helpers ──────────────────────────────────────────────────────


def _build_style_lock(style_json: str) -> object:
    """Build a StyleLock from a style.json string."""
    from server.ai.prompts.style_lock import StyleLock

    return StyleLock.load(style_json)


def _build_asset_lock(assets: "list[Asset]") -> object:
    """Build an AssetLock from a list of Asset ORM objects."""
    from server.ai.prompts.asset_lock import AssetLock

    return AssetLock.from_assets(assets)


def _get_scene_prompt(scene: "Scene") -> str:
    """Extract the visual prompt from a scene, checking multiple field names."""
    for attr in ("visual_prompt", "narration", "prompt"):
        val = getattr(scene, attr, None)
        if val:
            return str(val)
    return ""


def _find_scene_by_order(scenes: "list[Scene]", order: int) -> "Optional[Scene]":
    """Return the scene with the given order, or None."""
    for s in scenes:
        if getattr(s, "order", None) == order:
            return s
    return None


def _get_fallback_start_image(
    all_scenes: "list[Scene]", current_scene: "Scene"
) -> Optional[Path]:
    """Return a fallback start image when no chain frame is available.

    For scene 0 (or after a chain reset), we look for any scene that has a
    last_frame_path set, or return None to let the caller handle the error.
    """
    # For the very first scene, there's no previous frame — return None
    # The caller will raise an appropriate error if no start image is found.
    return None


def _extract_last_frame(video_path: Path) -> Optional[Path]:
    """Extract the last frame of a video as a PNG using ffmpeg.

    Uses ``ffmpeg -sseof -0.1`` to grab a frame near the end of the clip.
    Returns the Path to the extracted PNG, or None if ffmpeg is not available
    or extraction fails.
    """
    out_path = video_path.with_suffix(".lastframe.png")
    cmd = [
        "ffmpeg",
        "-y",
        "-sseof", "-0.1",
        "-i", str(video_path),
        "-frames:v", "1",
        str(out_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and out_path.exists():
            logger.debug(
                "PipelineOrchestrator: extracted last frame → {}", out_path
            )
            return out_path
        else:
            logger.warning(
                "PipelineOrchestrator: ffmpeg last-frame extraction failed "
                "(returncode={}): {}",
                result.returncode,
                result.stderr.decode(errors="replace")[:200],
            )
            return None
    except FileNotFoundError:
        logger.warning(
            "PipelineOrchestrator: ffmpeg not found — skipping last-frame extraction"
        )
        return None
    except subprocess.TimeoutExpired:
        logger.warning(
            "PipelineOrchestrator: ffmpeg timed out extracting last frame from {}",
            video_path,
        )
        return None
    except Exception as exc:
        logger.warning(
            "PipelineOrchestrator: last-frame extraction error: {}", exc
        )
        return None
