"""Index of everything you can open on this PC.

Sources (all merged into one searchable list):
  1. config.yaml "apps"          - your own nicknames
  2. Start Menu + Desktop shortcuts (.lnk / .url)
  3. Get-StartApps               - every Start menu app, incl. Microsoft Store apps
  4. Steam library               - installed Steam games
  5. Epic Games launcher         - installed Epic games

Finding an app: exact name -> close/fuzzy match -> the local LLM picks from the
best candidates (so "open the music app" or "dc" still work).
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import CONFIG

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000
REFRESH_SECONDS = 300

JUNK = re.compile(
    r"\b(uninstall|uninstaller|readme|read me|help|documentation|manual|website|"
    r"release notes|license|support|changelog|what's new)\b",
    re.I,
)


@dataclass(frozen=True)
class App:
    name: str  # display name, e.g. "Spotify"
    target: str  # path, URI or AppID
    kind: str  # config | shortcut | store | steam | epic

    @property
    def key(self) -> str:
        return normalize(self.name)


# common nicknames -> real names (the LLM handles anything not listed here)
ALIASES = {
    "vscode": "visual studio code", "code": "visual studio code", "vs": "visual studio",
    "gta": "grand theft auto", "cs": "counter-strike", "csgo": "counter-strike",
    "lol": "league of legends", "mc": "minecraft", "dc": "discord", "ps": "photoshop",
    "edge": "microsoft edge", "word": "microsoft word", "excel": "microsoft excel",
    "powerpoint": "microsoft powerpoint", "ppt": "microsoft powerpoint", "teams": "microsoft teams",
    "explorer": "file explorer", "files": "file explorer", "settings": "settings",
    "terminal": "terminal", "cmd": "command prompt", "notes": "notepad", "wa": "whatsapp",
}
ROMAN = {"1": "i", "2": "ii", "3": "iii", "4": "iv", "5": "v", "6": "vi", "7": "vii", "8": "viii", "9": "ix", "10": "x"}


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9а-я]+", "", s.lower())


# --------------------------------------------------------------- collectors
def _from_config() -> list[App]:
    apps = CONFIG.get("apps") or {}
    return [App(str(k), str(v), "config") for k, v in apps.items() if v]


def _from_shortcuts() -> list[App]:
    dirs = [
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path.home() / "Desktop",
        Path.home() / "OneDrive/Desktop",
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
    ]
    found = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.suffix.lower() in (".lnk", ".url") and not JUNK.search(p.stem):
                found.append(App(p.stem, str(p), "shortcut"))
    return found


def _from_start_apps() -> list[App]:
    """All Start menu apps incl. Microsoft Store ones (Spotify/WhatsApp from the Store...)."""
    if not IS_WINDOWS:
        return []
    cmd = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW,
        ).stdout.decode("utf-8", "ignore")
        data = json.loads(out or "[]")
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        App(d["Name"], d["AppID"], "store")
        for d in data
        if d.get("Name") and d.get("AppID") and not JUNK.search(d["Name"])
    ]


def _steam_root() -> Path | None:
    if IS_WINDOWS:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                return Path(winreg.QueryValueEx(k, "SteamPath")[0])
        except OSError:
            pass
    for p in (Path(r"C:\Program Files (x86)\Steam"), Path.home() / ".steam/steam"):
        if p.exists():
            return p
    return None


def _from_steam() -> list[App]:
    root = _steam_root()
    if not root:
        return []
    libraries = {root}
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for path in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
            libraries.add(Path(path.replace("\\\\", "\\")))
    games = []
    for lib in libraries:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            text = acf.read_text(encoding="utf-8", errors="ignore")
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            if appid and name and not re.search(r"redistributable|steamworks|proton|runtime", name[1], re.I):
                games.append(App(name[1], f"steam://rungameid/{appid[1]}", "steam"))
    return games


def _from_epic() -> list[App]:
    folder = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Epic/EpicGamesLauncher/Data/Manifests"
    games = []
    for item in folder.glob("*.item") if folder.is_dir() else []:
        try:
            d = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
            games.append(App(
                d["DisplayName"],
                f"com.epicgames.launcher://apps/{d['AppName']}?action=launch&silent=true",
                "epic",
            ))
        except Exception:
            continue
    return games


# -------------------------------------------------------------------- index
class AppIndex:
    def __init__(self) -> None:
        self.apps: list[App] = []
        self.built_at = 0.0
        self._lock = threading.Lock()

    def build(self) -> list[App]:
        apps: list[App] = []
        for collect in (_from_config, _from_shortcuts, _from_start_apps, _from_steam, _from_epic):
            try:
                apps += collect()
            except Exception:
                pass
        # de-duplicate by name; earlier sources win (config > shortcut > store ...)
        seen, unique = set(), []
        for a in apps:
            if a.key and a.key not in seen:
                seen.add(a.key)
                unique.append(a)
        with self._lock:
            self.apps, self.built_at = unique, time.time()
        return unique

    def all(self) -> list[App]:
        if not self.apps or time.time() - self.built_at > REFRESH_SECONDS:
            self.build()
        return self.apps

    # ---------------------------------------------------------- matching
    def _score(self, query: str, app: App) -> float:
        q, k = normalize(query), app.key
        if not q:
            return 0.0
        # "gta 5" -> "grand theft auto v", "vs code" -> "visual studio code"
        num = re.search(r"(\d+)$", q)
        base = q[: num.start()] if num else q
        if base in ALIASES:
            q = normalize(ALIASES[base]) + (ROMAN.get(num[1], num[1]) if num else "")
        if q == k:
            return 1.0
        if k.startswith(q) or q.startswith(k):
            return 0.92 - 0.002 * abs(len(k) - len(q))
        words = [normalize(w) for w in re.split(r"[\s\-_:.]+", app.name) if w]
        if q in words:
            return 0.88
        initials = "".join(w if w.isdigit() or w in ROMAN.values() else w[0] for w in words if w)
        q_roman = re.sub(r"\d+", lambda m: ROMAN.get(m[0], m[0]), q)
        if len(q) >= 2 and initials in (q, q_roman):  # "vsc" -> Visual Studio Code, "gta" -> Grand Theft Auto
            return 0.85
        if q in k:
            return 0.8 - 0.002 * (len(k) - len(q))
        ratio = difflib.SequenceMatcher(None, q, k).ratio()
        if ratio >= 0.8 and len(q) >= 4:  # typos: "discrod", "spotfy"
            return 0.78 + (ratio - 0.8) * 0.5
        return ratio * 0.75

    def candidates(self, query: str, n: int = 25) -> list[tuple[float, App]]:
        scored = sorted(((self._score(query, a), a) for a in self.all()), key=lambda x: -x[0])
        return scored[:n]

    def find(self, query: str, use_llm: bool = True) -> App | None:
        best = self.candidates(query)
        if not best:
            return None
        if best[0][0] >= 0.78:
            return best[0][1]
        # not sure? refresh once (maybe it was just installed), then ask the LLM
        if time.time() - self.built_at > 30:
            self.build()
            best = self.candidates(query)
            if best and best[0][0] >= 0.78:
                return best[0][1]
        return self._llm_pick(query, [a for _, a in best]) if use_llm else None

    def _llm_pick(self, query: str, options: list[App]) -> App | None:
        from . import llm

        names = "\n".join(f"- {a.name}" for a in options)
        try:
            answer = llm.complete(
                f'The user wants to open: "{query}".\nInstalled apps and games:\n{names}\n\n'
                "Reply with the exact name of the ONE app from the list they mean, "
                "or NONE if it isn't in the list. Reply with the name only.",
                system="You match app requests to installed apps. Be strict: no guessing unrelated apps.",
            )
        except Exception:
            return None
        answer = answer.strip().strip('"').strip("-").strip()
        if answer.upper().startswith("NONE"):
            return None
        for a in options:
            if normalize(a.name) == normalize(answer):
                return a
        return None


INDEX = AppIndex()


def warm_up() -> None:
    """Build the index in the background at startup so the first command is instant."""
    threading.Thread(target=INDEX.build, daemon=True, name="pixie-app-index").start()
