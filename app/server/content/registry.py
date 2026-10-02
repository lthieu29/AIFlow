"""ContentAdapter registry — auto-discover and manage adapter classes.

Usage
-----
Register an adapter explicitly::

    from server.content.registry import REGISTRY, register_adapter

    @register_adapter
    class MyAdapter:
        adapter_type = "my_adapter"
        async def adapt(self, input): ...
        def validate_input(self, input): ...

Or let the registry auto-discover adapters in a package::

    REGISTRY.auto_discover("server.content.adapters")

Then retrieve an adapter instance::

    adapter = REGISTRY.get("my_adapter")
    scene_list = await adapter.adapt(input)

Convention
----------
Each adapter module inside ``server/content/adapters/<name>/adapter.py``
must expose a module-level ``ADAPTER`` attribute that is an *instance* of
the adapter class.  ``auto_discover`` will pick it up automatically.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
from typing import TYPE_CHECKING, Type

from server.content.base import AdapterError, ContentAdapter

if TYPE_CHECKING:
    pass  # avoid circular imports at runtime

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Registry that maps adapter type strings to adapter instances.

    This is a plain class (not a singleton by itself); the module-level
    :data:`REGISTRY` constant is the shared singleton used by the rest of
    the application.
    """

    def __init__(self) -> None:
        self._instances: dict[str, ContentAdapter] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, adapter_cls: Type) -> Type:
        """Register an adapter class and store a single instance.

        The class must have an ``adapter_type`` class attribute.

        Args:
            adapter_cls: The adapter class to register.

        Returns:
            The same class (so this method can be used as a decorator).

        Raises:
            :class:`~server.content.base.AdapterError`: If ``adapter_type``
                is missing or already registered.
        """
        adapter_type: str | None = getattr(adapter_cls, "adapter_type", None)
        if not adapter_type:
            raise AdapterError(
                "ADAPTER_MISSING_TYPE",
                f"Adapter class {adapter_cls.__name__!r} must define 'adapter_type'",
            )
        if adapter_type in self._instances:
            logger.warning(
                "Adapter %r already registered; overwriting with %s",
                adapter_type,
                adapter_cls.__name__,
            )
        instance = adapter_cls()
        self._instances[adapter_type] = instance
        logger.debug("Registered adapter %r (%s)", adapter_type, adapter_cls.__name__)
        return adapter_cls

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def get(self, adapter_type: str) -> ContentAdapter:
        """Return the adapter instance for *adapter_type*.

        Args:
            adapter_type: The ``adapter_type`` string (e.g. ``"script_direct"``).

        Returns:
            The registered :class:`~server.content.base.ContentAdapter` instance.

        Raises:
            :class:`~server.content.base.AdapterError`: If no adapter with
                that type is registered.
        """
        if adapter_type not in self._instances:
            available = ", ".join(sorted(self._instances)) or "(none)"
            raise AdapterError(
                "ADAPTER_NOT_FOUND",
                f"No adapter registered for type {adapter_type!r}. "
                f"Available: {available}",
            )
        return self._instances[adapter_type]

    # ── Listing ───────────────────────────────────────────────────────────────

    def list_types(self) -> list[str]:
        """Return a sorted list of all registered adapter type strings."""
        return sorted(self._instances.keys())

    # ── Auto-discovery ────────────────────────────────────────────────────────

    def auto_discover(self, package: str) -> None:
        """Auto-discover adapters in *package* and register them.

        For each sub-package found under *package*, this method attempts to
        import ``<sub_package>.adapter`` and looks for:

        1. A module-level ``ADAPTER`` attribute (an instance) — registered
           directly.
        2. A module-level ``ADAPTER_CLASS`` attribute (a class) — instantiated
           and registered.

        Any import errors are logged as warnings and skipped so that a broken
        adapter does not prevent the rest from loading.

        Args:
            package: Dotted package name, e.g. ``"server.content.adapters"``.
        """
        try:
            pkg = importlib.import_module(package)
        except ImportError as exc:
            logger.warning("auto_discover: cannot import package %r: %s", package, exc)
            return

        pkg_path = getattr(pkg, "__path__", None)
        if pkg_path is None:
            logger.warning("auto_discover: %r is not a package", package)
            return

        for module_info in pkgutil.iter_modules(pkg_path):
            if not module_info.ispkg:
                continue  # only look at sub-packages (adapter directories)

            adapter_module_name = f"{package}.{module_info.name}.adapter"
            try:
                module = importlib.import_module(adapter_module_name)
            except ImportError as exc:
                logger.debug(
                    "auto_discover: skipping %r — cannot import: %s",
                    adapter_module_name,
                    exc,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "auto_discover: error importing %r: %s",
                    adapter_module_name,
                    exc,
                )
                continue

            # Convention 1: module exposes an ADAPTER instance
            if hasattr(module, "ADAPTER"):
                instance = module.ADAPTER
                adapter_type = getattr(instance, "adapter_type", None)
                if adapter_type:
                    self._instances[adapter_type] = instance
                    logger.debug(
                        "auto_discover: registered %r from %s (ADAPTER instance)",
                        adapter_type,
                        adapter_module_name,
                    )
                else:
                    logger.warning(
                        "auto_discover: ADAPTER in %r has no adapter_type",
                        adapter_module_name,
                    )
                continue

            # Convention 2: module exposes an ADAPTER_CLASS class
            if hasattr(module, "ADAPTER_CLASS"):
                cls = module.ADAPTER_CLASS
                try:
                    self.register(cls)
                except AdapterError as exc:
                    logger.warning(
                        "auto_discover: failed to register ADAPTER_CLASS from %r: %s",
                        adapter_module_name,
                        exc,
                    )
                continue

            logger.debug(
                "auto_discover: %r has neither ADAPTER nor ADAPTER_CLASS — skipped",
                adapter_module_name,
            )


# ─── Module-level singleton ───────────────────────────────────────────────────

#: Shared registry instance used by the rest of the application.
REGISTRY: AdapterRegistry = AdapterRegistry()


# ─── Decorator ───────────────────────────────────────────────────────────────


def register_adapter(cls: Type) -> Type:
    """Class decorator that registers *cls* with the shared :data:`REGISTRY`.

    Example::

        @register_adapter
        class ScriptDirectAdapter:
            adapter_type = "script_direct"
            ...

    Args:
        cls: The adapter class to register.

    Returns:
        The same class (unchanged).
    """
    REGISTRY.register(cls)
    return cls
