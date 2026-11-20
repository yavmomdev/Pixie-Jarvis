"""Open and close apps/games - in the background (minimized, without stealing focus)."""

from __future__ import annotations

import difflib
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from ..config import CONFIG
from . import tool

IS_WINDOWS = sys.platform == "win32"
SW_SHOWMINNOACTIVE = 7  # minimized, does NOT take focus


@lru_cache(maxsize=1)
def _start_menu_shortcuts() -> dict[str, str]:
    """Map 'app name' -> shortcut path, from the Windows Start Menu (+ Desktop)."""
    dirs = [
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path.home() / "Desktop",
    ]
    found: dict[str, str] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.suffix.lower() in (".lnk", ".url"):
                found.setdefault(p.stem.lower(), str(p))
    return found


def resolve_app(name: str) -> str | None:
    """Find what to launch: config.yaml 'apps' first, then Start Menu shortcuts."""
    key = name.lower().strip()
    apps = {k.lower(): v for k, v in CONFIG.get("apps", {}).items()}
    if key in apps:
        return apps[key]
    shortcuts = _start_menu_shortcuts()
    if key in shortcuts:
        return shortcuts[key]
    # fuzzy: "valorant" -> "VALORANT", "vs code" -> "Visual Studio Code"
    contains = [k for k in shortcuts if key in k]
    if contains:
        return shortcuts[min(contains, key=len)]
    close = difflib.get_close_matches(key, list(apps) + list(shortcuts), n=1, cutoff=0.6)
    if close:
        return apps.get(close[0]) or shortcuts[close[0]]
    return None


def launch_background(target: str) -> None:
    """Launch an exe / shortcut / URI (spotify:, steam://...) minimized and unfocused."""
    if not IS_WINDOWS:
        subprocess.Popen(target, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if target.lower().endswith(".exe") and os.path.exists(target):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = SW_SHOWMINNOACTIVE
        subprocess.Popen([target], startupinfo=si, creationflags=subprocess.DETACHED_PROCESS)
    else:
        # shortcuts and URIs: let Windows resolve them, start minimized
        subprocess.Popen(f'start "" /min "{target}"', shell=True)


@tool(
    "open_app",
    "Open an application or game on the PC in the background (e.g. Discord, Steam, Valorant, Chrome).",
    {"name": {"type": "string", "description": "App or game name, e.g. 'discord'"}},
    ["name"],
)
def open_app(name: str) -> str:
    target = resolve_app(name)
    if not target:
        return f"I couldn't find an app called '{name}'. Add it under 'apps' in config.yaml."
    launch_background(target)
    return f"Opened {name} in the background."


@tool(
    "close_app",
    "Close a running application or game.",
    {"name": {"type": "string", "description": "App or game name, e.g. 'chrome'"}},
    ["name"],
)
def close_app(name: str) -> str:
    import psutil

    key = name.lower().replace(" ", "")
    closed = 0
    for proc in psutil.process_iter(["name"]):
        pname = (proc.info["name"] or "").lower()
        if key in pname.replace(" ", ""):
            try:
                proc.terminate()
                closed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    return f"Closed {name}." if closed else f"{name} doesn't seem to be running."
