"""Open, close and list apps/games on this PC - launched in the background where possible."""

from __future__ import annotations

import os
import subprocess
import sys

from ..app_index import INDEX, App, normalize
from ..winctl import keep_in_background
from . import tool

IS_WINDOWS = sys.platform == "win32"
SW_SHOWMINNOACTIVE = 7  # minimized, does NOT take focus
CREATE_NO_WINDOW = 0x08000000


def launch_background(target: str, kind: str = "shortcut") -> None:
    """Start something minimized and without stealing focus (when Windows allows it)."""
    if not IS_WINDOWS:
        subprocess.Popen(target, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if kind == "store":
        # Start-menu AppID (works for Microsoft Store apps and normal apps alike)
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target}"])
    elif target.lower().endswith(".exe") and os.path.exists(target):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = SW_SHOWMINNOACTIVE
        subprocess.Popen([target], startupinfo=si, creationflags=subprocess.DETACHED_PROCESS)
    elif os.path.exists(target):  # .lnk / .url shortcut
        subprocess.Popen(f'start "" /min "{target}"', shell=True, creationflags=CREATE_NO_WINDOW)
    elif "://" in target or target.endswith(":"):  # steam://, com.epicgames..., spotify:
        os.startfile(target)
    else:  # a command from config.yaml, e.g. "C:\...\Update.exe --processStart Discord.exe"
        subprocess.Popen(f'start "" /min {target}', shell=True, creationflags=CREATE_NO_WINDOW)


def resolve_app(name: str) -> str | None:
    """Kept for other tools (Spotify): returns a launch target or None."""
    app = INDEX.find(name, use_llm=False)
    return app.target if app else None


def launch_app(app: App, show: bool | None = None) -> None:
    """Launch an indexed app. Apps stay in the background; games are shown (you want to play)."""
    if show is None:
        show = app.kind in ("steam", "epic")
    if show:
        launch_background(app.target, app.kind)
    else:
        keep_in_background(lambda: launch_background(app.target, app.kind))


@tool(
    "open_app",
    "Open ONE installed application or game on this PC in the background "
    "(e.g. Spotify, Discord, Steam, Valorant, Chrome, VS Code). Call it once per app.",
    {
        "name": {"type": "string", "description": "App or game name as the user said it, e.g. 'discord'"},
        "show": {
            "type": "boolean",
            "description": "true only if the user explicitly wants to SEE/switch to it. Default: background",
        },
    },
    ["name"],
)
def open_app(name: str, show: bool | None = None) -> str:
    app = INDEX.find(name)
    if not app:
        return f"I couldn't find '{name}' on this PC. You can add it under 'apps' in config.yaml."
    launch_app(app, show)
    shown = show if show is not None else app.kind in ("steam", "epic")
    return f"Opened {app.name}." if shown else f"Opened {app.name} in the background."


@tool(
    "close_app",
    "Close a running application or game.",
    {"name": {"type": "string", "description": "App or game name, e.g. 'chrome'"}},
    ["name"],
)
def close_app(name: str) -> str:
    import psutil

    wanted = {normalize(name)}
    app = INDEX.find(name, use_llm=False)
    if app:
        wanted.add(app.key)
        if app.target.lower().endswith(".exe"):
            wanted.add(normalize(os.path.splitext(os.path.basename(app.target))[0]))
    wanted.discard("")

    closed = set()
    for proc in psutil.process_iter(["name"]):
        pname = normalize(os.path.splitext(proc.info["name"] or "")[0])
        if pname and any(w in pname or pname in w for w in wanted if len(w) >= 3):
            try:
                proc.terminate()
                closed.add(proc.info["name"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    shown = app.name if app else name
    return f"Closed {shown}." if closed else f"{shown} doesn't seem to be running."


@tool(
    "list_apps",
    "List installed apps or games on this PC, optionally filtered (e.g. 'games', 'steam', 'adobe').",
    {"filter": {"type": "string", "description": "Optional word to filter by, or 'games'"}},
)
def list_apps(filter: str = "") -> str:
    apps = INDEX.all()
    f = filter.lower().strip()
    if f in ("game", "games"):
        apps = [a for a in apps if a.kind in ("steam", "epic")]
    elif f:
        apps = [a for a in apps if f in a.name.lower() or f == a.kind]
    if not apps:
        return f"No apps found{f' for {filter}' if f else ''}."
    names = sorted({a.name for a in apps}, key=str.lower)
    more = f" (+{len(names) - 40} more)" if len(names) > 40 else ""
    return f"{len(names)} found: " + ", ".join(names[:40]) + more
