"""video_remaster adapter package.

Wraps :class:`~server.content.crawlers.remaster.VideoRemaster` and
:class:`~server.content.crawlers.manager.DownloadManager` into a
:class:`~server.content.base.ContentAdapter` that can be auto-discovered
by :class:`~server.content.registry.AdapterRegistry`.

Auto-discovery convention:
    ``ADAPTER``       — module-level instance (used by AdapterRegistry)
    ``ADAPTER_CLASS`` — module-level class reference
"""
