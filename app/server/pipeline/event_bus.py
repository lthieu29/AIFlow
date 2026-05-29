"""Simple in-process event bus for pipeline UI updates.

Provides a lightweight publish/subscribe mechanism so the pipeline orchestrator
can broadcast progress events to any registered listeners (e.g. WebSocket
handlers, CLI progress bars, test observers) without coupling to them directly.

Event types:
    "scene_started"        — a scene has begun generation
    "scene_completed"      — a scene finished successfully
    "scene_failed"         — a scene failed (may be retried)
    "pipeline_completed"   — all scenes finished (some may have failed)
    "pipeline_failed"      — pipeline aborted (G1 failed, unrecoverable error)
    "gate_status_changed"  — a quality gate changed status (G1/G2/G3)

Usage::

    bus = EventBus()

    def on_scene(data: dict) -> None:
        print(f"Scene {data['scene_order']} started")

    bus.subscribe("scene_started", on_scene)
    bus.publish("scene_started", {"scene_order": 0, "project_id": 1})
    bus.unsubscribe("scene_started", on_scene)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from loguru import logger

# Recognised event type strings (informational — bus accepts any string)
EVENT_SCENE_STARTED = "scene_started"
EVENT_SCENE_COMPLETED = "scene_completed"
EVENT_SCENE_FAILED = "scene_failed"
EVENT_PIPELINE_COMPLETED = "pipeline_completed"
EVENT_PIPELINE_FAILED = "pipeline_failed"
EVENT_GATE_STATUS_CHANGED = "gate_status_changed"

_KNOWN_EVENTS: frozenset[str] = frozenset(
    [
        EVENT_SCENE_STARTED,
        EVENT_SCENE_COMPLETED,
        EVENT_SCENE_FAILED,
        EVENT_PIPELINE_COMPLETED,
        EVENT_PIPELINE_FAILED,
        EVENT_GATE_STATUS_CHANGED,
    ]
)


class EventBus:
    """In-process publish/subscribe event bus.

    Thread-safety: callbacks are invoked synchronously in the publishing
    thread/coroutine. For async callbacks, wrap them in asyncio.create_task()
    before subscribing.

    Attributes:
        _subscribers: Mapping from event_type → list of callbacks.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[dict], None]]] = defaultdict(list)

    # ── Public API ────────────────────────────────────────────────────────────

    def subscribe(self, event_type: str, callback: Callable[[dict], None]) -> None:
        """Register a callback for an event type.

        The same callback can be registered multiple times; each registration
        results in one additional invocation per publish.

        Args:
            event_type: Event type string (e.g. "scene_started").
            callback:   Callable that accepts a single ``dict`` argument.
        """
        self._subscribers[event_type].append(callback)
        logger.debug(
            "EventBus.subscribe: event={!r} callback={!r}",
            event_type,
            getattr(callback, "__name__", repr(callback)),
        )

    def unsubscribe(self, event_type: str, callback: Callable[[dict], None]) -> None:
        """Remove a previously registered callback.

        Silently ignores the call if the callback is not registered for the
        given event type (no-op rather than raising).

        Args:
            event_type: Event type string.
            callback:   The exact callable object that was passed to subscribe().
        """
        listeners = self._subscribers.get(event_type)
        if not listeners:
            return
        try:
            listeners.remove(callback)
        except ValueError:
            pass  # Not registered — ignore
        logger.debug(
            "EventBus.unsubscribe: event={!r} callback={!r}",
            event_type,
            getattr(callback, "__name__", repr(callback)),
        )

    def publish(self, event_type: str, data: dict) -> None:
        """Invoke all callbacks registered for an event type.

        Callbacks are called in registration order. Exceptions raised by
        individual callbacks are caught and logged so that one bad subscriber
        cannot prevent others from receiving the event.

        Args:
            event_type: Event type string.
            data:       Payload dict passed to each callback.
        """
        if event_type not in _KNOWN_EVENTS:
            logger.warning("EventBus.publish: unknown event type {!r}", event_type)

        listeners = list(self._subscribers.get(event_type, []))
        logger.debug(
            "EventBus.publish: event={!r} listeners={} data_keys={}",
            event_type,
            len(listeners),
            list(data.keys()),
        )

        for callback in listeners:
            try:
                callback(data)
            except Exception as exc:
                logger.error(
                    "EventBus: callback {!r} raised for event {!r}: {}",
                    getattr(callback, "__name__", repr(callback)),
                    event_type,
                    exc,
                )

    def subscriber_count(self, event_type: str) -> int:
        """Return the number of subscribers for an event type (useful in tests)."""
        return len(self._subscribers.get(event_type, []))
