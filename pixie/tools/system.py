"""Windows controls: volume, media keys, brightness, dark mode, power, screenshots, status.

Everything here works in the background - nothing opens or takes focus.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import tool

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000

VK = {"volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
      "next": 0xB0, "previous": 0xB1, "stop": 0xB2, "play_pause": 0xB3}


def _press(vk: int, times: int = 1) -> None:
    import ctypes

    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP


def _run(cmd: list[str]) -> None:
    subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0)


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise RuntimeError("this only works on Windows")


# ------------------------------------------------------------------ volume
def _endpoint_volume():
    """System master volume via pycaw (supports old and new pycaw APIs)."""
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    comtypes.CoInitialize()  # tools run in worker threads
    speakers = AudioUtilities.GetSpeakers()
    vol = getattr(speakers, "EndpointVolume", None)
    if vol is None:  # older pycaw
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL

        iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(iface, POINTER(IAudioEndpointVolume))
    return vol


@tool(
    "set_volume",
    "Change the PC's system volume: set a level, turn it up/down, mute or unmute.",
    {
        "action": {"type": "string", "enum": ["set", "up", "down", "mute", "unmute"]},
        "level": {"type": "integer", "description": "0-100 for action=set; step size for up/down (default 10)"},
    },
    ["action"],
)
def set_volume(action: str, level: int | None = None) -> str:
    _require_windows()
    try:
        vol = _endpoint_volume()
        now = round(vol.GetMasterVolumeLevelScalar() * 100)
        if action in ("mute", "unmute"):
            vol.SetMute(1 if action == "mute" else 0, None)
            return "Muted 🔇" if action == "mute" else f"Unmuted 🔊 ({now}%)"
        step = int(level or 10)
        new = {"set": int(level if level is not None else now), "up": now + step, "down": now - step}[action]
        new = max(0, min(100, new))
        vol.SetMute(0, None)
        vol.SetMasterVolumeLevelScalar(new / 100, None)
        return f"Volume {new}% 🔊"
    except ImportError:
        # fallback without pycaw: volume keys (each press = 2%)
        if action in ("mute", "unmute"):
            _press(VK["volume_mute"])
            return "Toggled mute 🔇"
        if action == "set":
            _press(VK["volume_down"], 50)
            _press(VK["volume_up"], max(0, min(100, int(level or 50))) // 2)
            return f"Volume {level}% 🔊"
        _press(VK[f"volume_{action}"], max(1, int(level or 10) // 2))
        return f"Volume {action} 🔊"


@tool(
    "media_control",
    "Control whatever is playing on the PC (Spotify, YouTube, any player) with the media keys.",
    {"action": {"type": "string", "enum": ["play_pause", "next", "previous", "stop"]}},
    ["action"],
)
def media_control(action: str) -> str:
    _require_windows()
    _press(VK.get(action, VK["play_pause"]))
    return {"play_pause": "Play/pause ⏯️", "next": "Next ⏭️", "previous": "Previous ⏮️", "stop": "Stopped ⏹️"}.get(
        action, "Done"
    )


# -------------------------------------------------------------- brightness
@tool(
    "set_brightness",
    "Change the screen brightness (laptop screen): set a level or turn it up/down.",
    {
        "action": {"type": "string", "enum": ["set", "up", "down"]},
        "level": {"type": "integer", "description": "0-100 for action=set; step for up/down (default 20)"},
    },
    ["action"],
)
def set_brightness(action: str, level: int | None = None) -> str:
    import screen_brightness_control as sbc

    now = sbc.get_brightness(display=0)[0]
    step = int(level or 20)
    new = {"set": int(level if level is not None else now), "up": now + step, "down": now - step}.get(action, now)
    new = max(0, min(100, new))
    sbc.set_brightness(new, display=0)
    return f"Brightness {new}% ☀️"


# --------------------------------------------------------------- dark mode
@tool(
    "set_dark_mode",
    "Switch Windows between dark mode and light mode.",
    {"mode": {"type": "string", "enum": ["dark", "light", "toggle"]}},
    ["mode"],
)
def set_dark_mode(mode: str) -> str:
    _require_windows()
    import ctypes
    import winreg

    path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
        if mode == "toggle":
            light_now = winreg.QueryValueEx(k, "AppsUseLightTheme")[0]
            mode = "dark" if light_now else "light"
        value = 0 if mode == "dark" else 1
        winreg.SetValueEx(k, "AppsUseLightTheme", 0, winreg.REG_DWORD, value)
        winreg.SetValueEx(k, "SystemUsesLightTheme", 0, winreg.REG_DWORD, value)
    # tell open apps that the theme changed
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 2, 1000, None)
    return "Dark mode on 🌙" if mode == "dark" else "Light mode on ☀️"


# ------------------------------------------------------------------- power
@tool(
    "power",
    "Lock, sleep, shut down or restart the PC. Shutdown/restart wait 60 seconds and can be "
    "cancelled with action=cancel.",
    {"action": {"type": "string", "enum": ["lock", "sleep", "shutdown", "restart", "cancel"]}},
    ["action"],
)
def power(action: str) -> str:
    _require_windows()
    import ctypes

    if action == "lock":
        ctypes.windll.user32.LockWorkStation()
        return "PC locked 🔒"
    if action == "sleep":
        _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return "Going to sleep 😴"
    if action == "shutdown":
        _run(["shutdown", "/s", "/t", "60"])
        return "Shutting down in 60 seconds. Say 'cancel shutdown' to stop it ⏻"
    if action == "restart":
        _run(["shutdown", "/r", "/t", "60"])
        return "Restarting in 60 seconds. Say 'cancel shutdown' to stop it 🔄"
    _run(["shutdown", "/a"])
    return "Cancelled the shutdown/restart ✋"


# -------------------------------------------------------------- screenshot
@tool("screenshot", "Take a screenshot of the whole screen and save it to Pictures\\Screenshots.")
def screenshot() -> str:
    from PIL import ImageGrab

    folder = Path.home() / "Pictures" / "Screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"pixie-{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
    ImageGrab.grab(all_screens=True).save(path)
    return f"Screenshot saved to {path} 📸"


# ------------------------------------------------------------------ status
@tool("system_status", "Report battery, CPU, RAM and disk usage of the PC.")
def system_status() -> str:
    import psutil

    parts = []
    bat = psutil.sensors_battery()
    if bat:
        plug = "charging" if bat.power_plugged else "on battery"
        parts.append(f"🔋 {bat.percent:.0f}% ({plug})")
    parts.append(f"CPU {psutil.cpu_percent(interval=0.5):.0f}%")
    mem = psutil.virtual_memory()
    parts.append(f"RAM {mem.percent:.0f}% of {mem.total / 2**30:.0f} GB")
    disk = psutil.disk_usage(str(Path.home().anchor or "/"))
    parts.append(f"Disk {disk.free / 2**30:.0f} GB free")
    return " · ".join(parts)
