"""Content adapter API routes.

Endpoints:
    POST /api/content/parse — dispatch to matching ContentAdapter, return SceneList JSON

Task 5.3 — Phase 5.3
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from server.content.base import AdapterError, AdapterInput, SceneList

router = APIRouter(prefix="/api/content", tags=["content"])


# ─── Request / Response models ────────────────────────────────────────────────


class ContentParseRequest(BaseModel):
    """Request body for POST /api/content/parse."""

    adapter: str
    input_data: dict[str, Any]


class SceneSpecOut(BaseModel):
    """Serialisable representation of a SceneSpec."""

    order: int
    prompt: str
    duration: float
    location_hint: Optional[str] = None
    narration: Optional[str] = None
    start_image: Optional[str] = None  # Path serialised as string


class SceneListOut(BaseModel):
    """Serialisable representation of a SceneList."""

    project_id: str
    scenes: list[SceneSpecOut]
    style_ref: Optional[str] = None
    voice: Optional[str] = None
    metadata: dict[str, Any] = {}
    scene_count: int
    estimated_cost: dict[str, Any]


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.post("/parse", response_model=SceneListOut)
async def parse_content(body: ContentParseRequest) -> SceneListOut:
    """Dispatch input to the matching ContentAdapter and return a SceneList.

    Looks up the adapter by ``body.adapter`` in the shared REGISTRY,
    constructs an ``AdapterInput`` from ``body.input_data``, calls
    ``adapter.adapt()``, and returns the resulting SceneList as JSON.

    The ``input_data`` dict is mapped to ``AdapterInput`` fields:
    - ``raw_content`` (str) — required
    - ``source_type`` (str) — defaults to ``body.adapter``
    - ``skill_name`` (str) — optional
    - ``options`` (dict) — optional extra options

    Args:
        body: Parse request with adapter name and input data.

    Returns:
        SceneListOut with scenes, metadata, and cost estimate.

    Raises:
        HTTPException 400: If the adapter rejects the input or input is invalid.
        HTTPException 404: If no adapter is registered for the given name.
        HTTPException 500: If the adapter raises an unexpected error.
    """
    logger.info(
        "[content] POST /api/content/parse — adapter=%r input_keys=%s",
        body.adapter,
        list(body.input_data.keys()),
    )

    from server.content.registry import REGISTRY

    # Resolve adapter
    try:
        adapter = REGISTRY.get(body.adapter)
    except AdapterError as exc:
        logger.warning("[content] adapter not found: %s", exc.message)
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                }
            },
        ) from exc

    # Build AdapterInput from input_data
    raw_content = body.input_data.get("raw_content", "")
    if not isinstance(raw_content, str):
        raw_content = str(raw_content)

    adapter_input = AdapterInput(
        source_type=body.input_data.get("source_type", body.adapter),
        raw_content=raw_content,
        skill_name=body.input_data.get("skill_name"),
        options={
            k: v
            for k, v in body.input_data.items()
            if k not in ("raw_content", "source_type", "skill_name")
        },
    )

    # Pre-flight validation
    errors = adapter.validate_input(adapter_input)
    if errors:
        logger.warning("[content] adapter validation failed: %s", errors)
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "ADAPTER_INVALID_INPUT",
                    "message": "Input validation failed.",
                    "details": {"errors": errors},
                }
            },
        )

    # Run adapter
    try:
        scene_list: SceneList = await adapter.adapt(adapter_input)
    except AdapterError as exc:
        logger.error("[content] adapter error: %s", exc.message)
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        ) from exc
    except Exception as exc:
        logger.error("[content] unexpected adapter error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "ADAPTER_INTERNAL_ERROR",
                    "message": f"Adapter '{body.adapter}' raised an unexpected error: {exc}",
                }
            },
        ) from exc

    logger.info(
        "[content] adapter %r returned %d scenes",
        body.adapter,
        len(scene_list.scenes),
    )

    return SceneListOut(
        project_id=scene_list.project_id,
        scenes=[
            SceneSpecOut(
                order=s.order,
                prompt=s.prompt,
                duration=s.duration,
                location_hint=s.location_hint,
                narration=s.narration,
                start_image=str(s.start_image) if s.start_image is not None else None,
            )
            for s in scene_list.scenes
        ],
        style_ref=scene_list.style_ref,
        voice=scene_list.voice,
        metadata=scene_list.metadata,
        scene_count=len(scene_list.scenes),
        estimated_cost=scene_list.estimate_cost(),
    )
