"""Small Windows helpers for focus handling (no-ops on other systems)."""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]


def foreground():
    """The window that currently has focus (to give focus back later)."""
    return _user32.GetForegroundWindow() if IS_WINDOWS else None


def set_foreground(hwnd) -> None:
    """Reliably focus a window, even from a background app."""
    if not IS_WINDOWS or not hwnd:
        return
    fg = _user32.GetForegroundWindow()
    fg_thread = _user32.GetWindowThreadProcessId(fg, None)
    me = _kernel32.GetCurrentThreadId()
    attached = fg_thread and fg_thread != me and _user32.AttachThreadInput(fg_thread, me, True)
    _user32.SetForegroundWindow(hwnd)
    _user32.BringWindowToTop(hwnd)
    if attached:
        _user32.AttachThreadInput(fg_thread, me, False)
