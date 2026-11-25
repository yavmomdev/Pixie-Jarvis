"""Open, close and list apps/games on this PC - launched in the background where possible."""

from __future__ import annotations

import os
import subprocess
import sys

from ..app_index import INDEX, App, normalize
from ..winctl import keep_in_background
from . import Info, tool

IS_WINDOWS = sys.platform == "win32"
SW_SHOWMINNOACTIVE = 7  # minimized, does NOT take focus
CREATE_NO_WINDOW = 0x08000000


def launch_background(target: str, kind: str = "shortcut", minimized: bool = True) -> None:
    """Start something, minimized and without stealing focus where the app allows it."""
    if not IS_WINDOWS:
        subprocess.Popen(target, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    show = SW_SHOWMINNOACTIVE if minimized else 1  # 1 = SW_SHOWNORMAL
    if kind == "store":
        # Start-menu AppID (works for Microsoft Store apps and normal apps alike)
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target}"])
    elif target.lower().endswith(".exe") and os.path.exists(target):
        _start_exe([target], show)
    elif os.path.exists(target) and target.lower().endswith(".lnk"):
        _start_shell(target, show)
    elif os.path.exists(target) or "://" in target or target.endswith(":"):
        os.startfile(target)  # .url shortcuts and URIs: steam://, com.epicgames..., spotify:
    else:  # a command from config.yaml, e.g. "C:\...\Update.exe --processStart Discord.exe"
        min_flag = "/min " if minimized else ""
        subprocess.Popen(f'start "" {min_flag}{target}', shell=True, creationflags=CREATE_NO_WINDOW)


def _start_exe(cmd: list[str], show: int = SW_SHOWMINNOACTIVE) -> None:
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = show
    subprocess.Popen(cmd, startupinfo=si, creationflags=subprocess.DETACHED_PROCESS)


def _start_shell(path: str, show: int) -> None:
    """Open a file/shortcut through the Windows shell with a show-window hint (no console)."""
    import ctypes

    ctypes.windll.shell32.ShellExecuteW(None, "open", path, None, None, show)


# --------------------------------------------------- apps that can start hidden
def _first(*paths: str) -> str | None:
    return next((p for p in paths if p and os.path.exists(p)), None)


def hidden_command(app: App) -> tuple[list[str], str] | None:
    """(command, exe name) to start an app straight into the tray - no window at all.

    Uses each app's own 'start minimized' switch (the same one its autostart uses).
    """
    if not IS_WINDOWS:
        return None
    k = app.key
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    if "spotify" in k:
        exe = _first(os.path.join(roaming, "Spotify", "Spotify.exe"),
                     os.path.join(local, "Microsoft", "WindowsApps", "Spotify.exe"))  # Store version
        return ([exe, "--minimized"], "spotify.exe") if exe else None
    variants = {"discord": "Discord", "discordptb": "DiscordPTB", "discordcanary": "DiscordCanary"}
    if k in variants:
        v = variants[k]
        upd = _first(os.path.join(local, v, "Update.exe"))
        if upd:
            return [upd, "--processStart", f"{v}.exe", "--process-start-args", "--start-minimized"], f"{v}.exe".lower()
    if k == "steam":
        from ..app_index import _steam_root

        root = _steam_root()
        exe = _first(str(root / "steam.exe")) if root else None
        return ([exe, "-silent"], "steam.exe") if exe else None
    if "epicgameslauncher" in k:
        base = os.path.join(pf86, "Epic Games", "Launcher", "Portal", "Binaries")
        exe = _first(os.path.join(base, "Win64", "EpicGamesLauncher.exe"),
                     os.path.join(base, "Win32", "EpicGamesLauncher.exe"))
        return ([exe, "-silent"], "epicgameslauncher.exe") if exe else None
    if "telegram" in k:
        exe = _first(os.path.join(roaming, "Telegram Desktop", "Telegram.exe"))
        return ([exe, "-startintray"], "telegram.exe") if exe else None
    return None


def is_running(exe_name: str) -> bool:
    import psutil

    exe_name = exe_name.lower()
    return any((p.info["name"] or "").lower() == exe_name for p in psutil.process_iter(["name"]))


def resolve_app(name: str) -> str | None:
    """Kept for other tools: returns a launch target or None."""
    app = INDEX.find(name, use_llm=False)
    return app.target if app else None


def launch_app(app: App, show: bool | None = None) -> str:
    """Launch an indexed app. Apps stay in the background; games are shown (you want to play).

    Returns "started", "hidden" (started straight into the tray) or "running" (already open).
    """
    if show is None:
        show = app.kind in ("steam", "epic")
    if show:
        launch_background(app.target, app.kind, minimized=False)
        return "started"
    hidden = hidden_command(app)
    if hidden:
        cmd, exe = hidden
        if is_running(exe):
            return "running"  # don't poke it - that could bring its window to the front
        keep_in_background(lambda: _start_exe(cmd), expect=[exe])  # safety net, usually no window
        return "hidden"
    expect = [os.path.basename(app.target)] if app.target.lower().endswith(".exe") else []
    keep_in_background(lambda: launch_background(app.target, app.kind), expect=expect)
    return "started"


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
    how = launch_app(app, show)
    shown = show if show is not None else app.kind in ("steam", "epic")
    if how == "running":
        return f"{app.name} is already running in the background."
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
    return Info(f"{len(names)} found: " + ", ".join(names[:40]) + more)
