"""Make sure only one Pixie runs (two would both react to Right Alt)."""

from __future__ import annotations

import sys

_handle = None  # keep the mutex alive for the whole run


def already_running() -> bool:
    global _handle
    if sys.platform != "win32":
        return False
    import ctypes

    ERROR_ALREADY_EXISTS = 183
    _handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PixieJarvisAssistant")
    return ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS
