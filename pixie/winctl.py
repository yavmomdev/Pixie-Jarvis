"""Windows window/focus helpers (all no-ops on other systems).

keep_in_background(launch) runs a launch and makes sure whatever it opens stays
out of your way:

  * A Windows event hook (SetWinEventHook) is told the INSTANT a new window
    appears or grabs focus - no polling - and minimizes it right then, usually
    before it has even painted, so there's no visible flash.
  * Focus goes straight back to the window you were using.
  * Only windows from the launch are touched: a window must be NEW (not open
    before the launch) AND belong either to a process started by the launch or
    to an expected program (e.g. your browser for "open in a new window").
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

IS_WINDOWS = sys.platform == "win32"
SW_SHOWMINNOACTIVE = 7

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
GA_ROOT = 2
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION, WS_POPUP = 0x00C00000, 0x80000000
WS_EX_TOOLWINDOW = 0x00000080

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
    _user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _WinEventProc = ctypes.WINFUNCTYPE(
        None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
        wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
    )
    _user32.SetWinEventHook.argtypes = [
        wintypes.UINT, wintypes.UINT, wintypes.HMODULE, _WinEventProc,
        wintypes.DWORD, wintypes.DWORD, wintypes.UINT,
    ]
    _user32.SetWinEventHook.restype = wintypes.HANDLE


# ------------------------------------------------------------------ basics
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
    """Minimize without activating anything (async: never blocks on a busy app)."""
    if IS_WINDOWS and hwnd:
        _user32.ShowWindowAsync(hwnd, SW_SHOWMINNOACTIVE)


def _is_app_window(hwnd) -> bool:
    """A real top-level app window (not a tooltip, menu or tiny helper window)."""
    if _user32.GetAncestor(hwnd, GA_ROOT) != hwnd or not _user32.IsWindowVisible(hwnd):
        return False
    if _user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
        return False
    style = _user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    big = (rect.right - rect.left) >= 120 and (rect.bottom - rect.top) >= 80
    return big and bool(style & WS_CAPTION or style & WS_POPUP)


_create_times: dict[int, float] = {}


def _process_started(pid: int) -> float:
    if pid not in _create_times:
        try:
            import psutil

            _create_times[pid] = psutil.Process(pid).create_time()
        except Exception:
            _create_times[pid] = 0.0
    return _create_times[pid]


def _exe_name(pid: int) -> str:
    try:
        import psutil

        return psutil.Process(pid).name().lower()
    except Exception:
        return ""


# ------------------------------------------------------------ event hook
@dataclass
class _Watch:
    before: set
    prev: object
    started: float
    deadline: float
    expect: set = field(default_factory=set)  # exe names, e.g. {"brave.exe"}
    minimize_after: float = 0.0
    handled: set = field(default_factory=set)


class _Hook:
    """One background thread with a Windows event hook, shared by all launches."""

    def __init__(self) -> None:
        self.watches: list[_Watch] = []
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.ok = False
        self._proc = None  # keep the ctypes callback alive
        threading.Thread(target=self._run, daemon=True, name="pixie-winhook").start()
        self.ready.wait(2)

    def _run(self) -> None:
        self._proc = _WinEventProc(self._on_event)
        flags = WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
        h1 = _user32.SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, None, self._proc, 0, 0, flags)
        h2 = _user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._proc, 0, 0, flags
        )
        self.ok = bool(h1 and h2)
        self.ready.set()
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:  # pump: hooks need it
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def add(self, w: _Watch) -> None:
        with self.lock:
            self.watches.append(w)

    def _on_event(self, _hook, event, hwnd, id_object, _id_child, _thread, _time) -> None:
        if id_object != 0 or not hwnd:  # OBJID_WINDOW only
            return
        try:
            with self.lock:
                now = time.time()
                self.watches = [w for w in self.watches if w.deadline > now]
                watches = list(self.watches)
            if not watches or not _is_app_window(hwnd):
                return
            pid = window_pid(hwnd)
            for w in watches:
                if hwnd in w.before or hwnd == w.prev:
                    continue
                new_process = _process_started(pid) >= w.started - 1.0
                if not new_process and _exe_name(pid) not in w.expect:
                    continue
                self._handle(w, hwnd, event)
                break
        except Exception:
            pass  # never let an exception escape into Windows

    def _handle(self, w: _Watch, hwnd, event) -> None:
        first = hwnd not in w.handled
        w.handled.add(hwnd)
        w.deadline = max(w.deadline, time.time() + 2)  # apps often open a 2nd window right after
        if event == EVENT_SYSTEM_FOREGROUND or foreground() == hwnd:
            set_foreground(w.prev)  # give focus back right away
        if w.minimize_after:
            if first:  # e.g. YouTube in a browser: let playback start, then minimize
                threading.Timer(w.minimize_after, minimize_quietly, args=(hwnd,)).start()
        else:
            minimize_quietly(hwnd)


_hook: _Hook | None = None
_hook_lock = threading.Lock()


def _get_hook() -> _Hook | None:
    global _hook
    if not IS_WINDOWS:
        return None
    with _hook_lock:
        if _hook is None:
            _hook = _Hook()
    return _hook if _hook.ok else None


def keep_in_background(
    launch: Callable[[], None],
    watch: float = 8.0,
    minimize_after: float = 0.0,
    expect: Iterable[str] = (),
    wait: bool = False,
) -> None:
    """Run `launch`, then keep any window it opens in the background.

    watch          - how long to watch for new windows (extended while windows keep appearing)
    minimize_after - wait this long before minimizing (lets e.g. a video start); focus still
                     comes back to you immediately
    expect         - exe names whose NEW windows count even if the process already ran
                     (e.g. your browser opening a new window)
    wait           - ignored with the event hook (kept for compatibility)
    """
    if not IS_WINDOWS:
        launch()
        return
    hook = _get_hook()
    before = visible_windows()
    prev = foreground()
    now = time.time()
    if hook:
        hook.add(_Watch(before, prev, now, now + watch, {e.lower() for e in expect}, minimize_after))
        launch()
        return
    # fallback (hook unavailable): poll the foreground window
    launch()
    threading.Thread(target=_poll, args=(before, prev, watch, minimize_after), daemon=True).start()


def _poll(before: set, prev, watch: float, minimize_after: float) -> None:
    me = os.getpid()
    handled: set = set()
    deadline = time.time() + watch
    while time.time() < deadline:
        time.sleep(0.05)
        fg = foreground()
        if not fg or fg == prev or fg in before or fg in handled or window_pid(fg) == me:
            continue
        handled.add(fg)
        set_foreground(prev)
        if minimize_after:
            threading.Timer(minimize_after, minimize_quietly, args=(fg,)).start()
        else:
            minimize_quietly(fg)
        deadline = max(deadline, time.time() + 2)
