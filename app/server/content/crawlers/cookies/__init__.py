"""Cookie management for platform downloaders.

Provides CookieManager for reading/storing cookies from Chrome (browser-cookie3),
manual Netscape files, or the browser extension.

Usage:
    from server.content.crawlers.cookies.manager import CookieManager

    manager = CookieManager()
    cookie_file = manager.get_cookie_file("bilibili")
    # Pass cookie_file to yt-dlp via --cookies flag
"""

from server.content.crawlers.cookies.manager import (
    CookieManager,
    CookieEntry,
    CookieSource,
    format_cookie_string,
    PLATFORM_DOMAINS,
)

__all__ = [
    "CookieManager",
    "CookieEntry",
    "CookieSource",
    "format_cookie_string",
    "PLATFORM_DOMAINS",
]
