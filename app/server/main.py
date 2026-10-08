"""AIFlow FastAPI application entry point.

Startup sequence:
  1. Configure logging
  2. Load settings
  3. Bootstrap DB schema (idempotent)
  4. Start WebSocket server task (port 9223)
  5. Start quality gate checker task (Phase 0 no-op)

Ports:
  - HTTP API: 127.0.0.1:8101 (settings.port)
  - WebSocket: 127.0.0.1:9223 (settings.ws_port)

Usage:
    python -m server.main
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from loguru import logger

from server.logging_setup import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context manager.

    Startup:
      - Bootstrap DB schema
      - Start WebSocket server
      - Start quality gate checker
      - Start VideoPoller (background polling for async video operations)

    Shutdown:
      - Stop VideoPoller
      - Cancel background tasks
    """
    from server.config import load_settings
    from server.db.session import bootstrap_schema
    from server.flow.client import FlowClient
    from server.flow.ws_server import start_ws_server
    from server.pipeline.event_bus import get_event_bus
    from server.pipeline.poller import VideoPoller
    from server.pipeline.quality_gate import periodic_gate_checker

    settings = load_settings()

    # Preserve the pre-audio schema before additive upgrades. Never copy an active SQLite file raw.
    from server.audio.bootstrap import backup_before_audio_upgrade
    backup_before_audio_upgrade(settings)

    # Configure logging with the level from settings
    setup_logging(settings.log_level)

    # 1. Bootstrap DB
    logger.info("Bootstrapping database schema...")
    bootstrap_schema(settings)
    from server.audio.queue import AudioQueue
    audio_queue = AudioQueue(settings)
    audio_queue.acquire()
    from server.production.render import reconcile_interrupted
    from server.db.session import get_engine
    reconcile_interrupted(get_engine(settings))
    from server.production.flow_video import reconcile_interrupted as reconcile_flow_videos
    reconcile_flow_videos(get_engine(settings))
    audio_runner = asyncio.create_task(audio_queue.run(), name="audio_queue")
    logger.info(f"DB initialized at {settings.data_dir / 'projects.db'}")

    # 2. Create shared FlowClient singleton
    flow_client = FlowClient()

    # 3. Create EventBus singleton and expose on app.state
    event_bus = get_event_bus()
    app.state.event_bus = event_bus
    logger.info("EventBus created and attached to app.state.event_bus")

    # 4. Start WebSocket server as background task
    ws_task = asyncio.create_task(
        start_ws_server(settings, flow_client),
        name="ws_server",
    )
    logger.info(f"WebSocket server task started on port {settings.ws_port}")

    # 5. Start quality gate checker as background task
    gate_task = asyncio.create_task(
        periodic_gate_checker(),
        name="gate_checker",
    )
    logger.info("Quality gate checker task started")

    # 6. Start VideoPoller for async video generation operations
    video_poller = VideoPoller(settings=settings)
    video_poller.start()
    # Expose poller on app.state so routes/CLI can call poller.submit()
    app.state.video_poller = video_poller
    logger.info("VideoPoller started")

    # 7. Auto-discover content adapters into the shared REGISTRY so API routes
    #    (POST /api/projects, /api/content/parse) can resolve adapters by type.
    from server.content.registry import REGISTRY

    REGISTRY.auto_discover("server.content.adapters")
    logger.info(f"Content adapters discovered: {REGISTRY.list_types()}")

    yield  # Server is running

    # Shutdown: stop VideoPoller first, then cancel background tasks
    logger.info("Shutting down background tasks...")
    await audio_queue.close(audio_runner)
    await video_poller.stop()
    for task in (ws_task, gate_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("AIFlow server stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AIFlow",
        description="Personal AI video generation tool — Veo3 + Gemini + TTS pipeline",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register routers
    from server.api.routes.content import router as content_router
    from server.api.routes.export import router as export_router
    from server.api.routes.ext_callback import router as ext_callback_router
    from server.api.routes.ext_discovery import router as ext_discovery_router
    from server.api.routes.health import router as health_router
    from server.api.routes.jobs import router as jobs_router
    from server.api.routes.projects import router as projects_router
    from server.api.routes.scenes import router as scenes_router
    from server.api.routes.skills import router as skills_router
    from server.api.routes.tts import router as tts_router
    from server.api.routes.ws import router as ws_router
    from server.api.routes.assets import router as assets_router
    from server.api.routes.audio import router as audio_router
    from server.api.routes.scripts import router as scripts_router
    from server.api.routes.production import router as production_router
    from server.api.routes.voice_training import router as voice_training_router
    from server.api.routes.studio import router as studio_router
    from server.api.routes.training_control import router as training_control_router

    app.include_router(health_router)
    app.include_router(audio_router)
    app.include_router(scripts_router)
    app.include_router(production_router)
    app.include_router(voice_training_router)
    app.include_router(studio_router)
    app.include_router(training_control_router)
    app.include_router(ext_callback_router)
    app.include_router(ext_discovery_router)
    app.include_router(tts_router)
    app.include_router(export_router)
    app.include_router(projects_router)
    app.include_router(scenes_router)
    app.include_router(skills_router)
    app.include_router(content_router)
    app.include_router(jobs_router)
    app.include_router(assets_router)
    app.include_router(ws_router)

    return app


app = create_app()


if __name__ == "__main__":
    # Configure logging early (before lifespan runs)
    setup_logging("INFO")

    from server.config import load_settings

    settings = load_settings()

    logger.info(
        f"Starting AIFlow server on http://{settings.host}:{settings.port}"
    )
    uvicorn.run(
        "server.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        # Open SSE responses must not block reload before lifespan shutdown.
        timeout_graceful_shutdown=10,
    )
