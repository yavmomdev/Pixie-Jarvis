"""Notifications for finished background tasks.

When the popup UI is running it registers a listener and shows results itself;
otherwise Windows toast notifications are used (console fallback elsewhere).
"""

from __future__ import annotations

from typing import Callable

from .config import CONFIG

_listeners: list[Callable[[str, str, bool, bool, bool], None]] = []


def add_listener(fn: Callable[[str, str, bool, bool, bool], None]) -> None:
    """fn(title, message, copyable, is_error, is_info)"""
    _listeners.append(fn)


def notify(title: str, message: str, copyable: bool = False, error: bool = False, info: bool = False) -> None:
    print(f"\n🔔 {title}: {message}")
    if _listeners:
        for fn in _listeners:
            try:
                fn(title, message, copyable, error, info)
            except Exception:
                pass
        return
    if not CONFIG.get("notifications", True):
        return
    try:
        from win11toast import notify as toast  # non-blocking

        toast(title, message[:250])
    except Exception:
        pass  # not on Windows / package missing -> console only
