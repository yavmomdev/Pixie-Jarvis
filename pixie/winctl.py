"""Windows window/focus helpers (all no-ops on other systems).

The key piece is keep_in_background(): run a launch, then watch for ~N seconds.
Any NEW window that grabs the foreground is minimized (without activating
anything else) and focus goes straight back to what you were doing.
Windows that already existed are never touched.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable

IS_WINDOWS = sys.platform == "win32"
SW_SHOWMINNOACTIVE = 7

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def foreground():
    """The window that currently has focus."""
    return _user32.GetForegroundWindow() if IS_WINDOWS else None


def window_pid(hwnd) -> int:
    if not IS_WINDOWS or not hwnd:
        return 0
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def visible_windows() -> set:
    """All visible top-level windows that have a title."""
    if not IS_WINDOWS:
        return set()
    found = set()

    def cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd) and _user32.GetWindowTextLengthW(hwnd) > 0:
            found.add(hwnd)
        return True

    _user32.EnumWindows(_EnumProc(cb), 0)
    return found


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


def minimize_quietly(hwnd) -> None:
    """Minimize without activating any other window."""
    if IS_WINDOWS and hwnd:
        _user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)


def keep_in_background(
    launch: Callable[[], None], watch: float = 8.0, minimize_after: float = 0.0, wait: bool = False
) -> None:
    """Run `launch`, then push any window it opens to the background.

    watch          - how long to keep watching (apps like Discord open several windows)
    minimize_after - wait this long before minimizing a new window (lets e.g. a video
                     start playing); focus is still given back to you immediately
    wait           - block until watching is done (default: watch in a background thread)
    """
    if not IS_WINDOWS:
        launch()
        return
    me = os.getpid()
    before = visible_windows()
    prev = foreground()
    launch()
    if wait:
        _watch(before, prev, me, watch, minimize_after)
    else:
        threading.Thread(
            target=_watch, args=(before, prev, me, watch, minimize_after), daemon=True
        ).start()


def _watch(before: set, prev, me: int, watch: float, minimize_after: float) -> None:
    handled: set = set()
    deadline = time.time() + watch
    while time.time() < deadline:
        time.sleep(0.1)
        fg = foreground()
        if not fg or fg == prev or fg in before or fg in handled or window_pid(fg) == me:
            continue
        handled.add(fg)
        set_foreground(prev)  # give focus back right away
        if minimize_after:
            threading.Timer(minimize_after, minimize_quietly, args=(fg,)).start()
        else:
            minimize_quietly(fg)
        deadline = max(deadline, time.time() + 2)  # some apps open a 2nd window right after
