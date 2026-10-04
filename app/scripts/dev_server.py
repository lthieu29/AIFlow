"""Uvicorn launcher with reliable reload for redirected Windows consoles."""

import ctypes
import os
import sys
from contextlib import contextmanager
from ctypes import wintypes

from uvicorn.main import main as uvicorn_main


class _ConsoleFlushStream:
    def __init__(self, stream, kernel, console):
        self._stream = stream
        self._kernel = kernel
        self._console = console

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def write(self, text):
        return self._stream.write(text)

    def flush(self):
        self._stream.flush()
        written = wintypes.DWORD()
        self._kernel.WriteConsoleW(self._console, " ", 1, ctypes.byref(written), None)


@contextmanager
def redirected_reload_console(enabled):
    """Preserve Uvicorn's console-write wakeup when stdout points to a file/pipe."""
    if not enabled or os.name != "nt" or sys.stdout.isatty():
        yield
        return

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.WriteConsoleW.argtypes = [
        wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    console = kernel.CreateFileW("CONOUT$", 0x40000000, 3, None, 3, 0, None)
    if console == ctypes.c_void_p(-1).value:
        raise RuntimeError("Windows reload requires a console; launch with -WindowStyle Hidden, not CREATE_NO_WINDOW.")

    original = sys.stdout
    sys.stdout = _ConsoleFlushStream(original, kernel, console)
    try:
        yield
    finally:
        sys.stdout = original
        kernel.CloseHandle(console)


def main(args=None):
    args = list(sys.argv[1:] if args is None else args)
    if not args or args[0].startswith("-"):
        args.insert(0, "server.main:app")
    for option, default in (("--port", "8101"), ("--timeout-graceful-shutdown", "10")):
        if not any(arg == option or arg.startswith(option + "=") for arg in args):
            args.extend([option, default])
    with redirected_reload_console("--reload" in args):
        uvicorn_main(args=args)


if __name__ == "__main__":
    main()
