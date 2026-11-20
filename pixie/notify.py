"""Windows toast notifications, with a console fallback everywhere else."""

from __future__ import annotations

from .config import CONFIG


def notify(title: str, message: str) -> None:
    print(f"\n🔔 {title}: {message}")
    if not CONFIG.get("notifications", True):
        return
    try:
        from win11toast import notify as toast  # non-blocking

        toast(title, message[:250])
    except Exception:
        pass  # not on Windows / package missing -> console only
