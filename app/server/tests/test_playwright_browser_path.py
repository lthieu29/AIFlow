"""Local browser fallback respects user configuration and Playwright's revision."""

from server.render.visual_layer import playwright_renderer as renderer


def test_matching_headless_revision_is_selected(tmp_path, monkeypatch):
    cache = tmp_path / "vendor" / "playwright"
    binary = cache / "chromium_headless_shell-7" / "chrome-headless-shell-win64" / "chrome-headless-shell.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(renderer, "_BROWSER_CACHE", cache)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    default = tmp_path / "normal-cache" / "chromium-7" / "chrome-win64" / "chrome.exe"
    assert renderer._chromium_launch_options(str(default)) == {
        "headless": True, "executable_path": str(binary),
    }
    other = tmp_path / "normal-cache" / "chromium-8" / "chrome-win64" / "chrome.exe"
    assert renderer._chromium_launch_options(str(other)) == {"headless": True}


def test_explicit_browser_cache_is_not_overridden(tmp_path, monkeypatch):
    cache = tmp_path / "vendor" / "playwright"
    binary = cache / "chromium-7" / "chrome-win64" / "chrome.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(renderer, "_BROWSER_CACHE", cache)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "configured"))
    assert renderer._chromium_launch_options(str(binary)) == {"headless": True}
