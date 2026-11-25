"""Browser tools: open websites, play YouTube videos, search - in the background.

Pages open in a NEW window of your default browser (Brave, Chrome, Edge, Firefox...),
which is pushed to the background straight away, so your current window/game keeps focus.
Audio (YouTube) keeps playing from the minimized window.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from functools import lru_cache

from ..winctl import keep_in_background
from . import tool

IS_WINDOWS = sys.platform == "win32"

SITES = {
    "youtube": "https://www.youtube.com", "yt": "https://www.youtube.com",
    "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "drive": "https://drive.google.com", "google drive": "https://drive.google.com",
    "maps": "https://maps.google.com", "google maps": "https://maps.google.com",
    "translate": "https://translate.google.com", "google translate": "https://translate.google.com",
    "github": "https://github.com", "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    "netflix": "https://www.netflix.com", "twitch": "https://www.twitch.tv",
    "reddit": "https://www.reddit.com", "x": "https://x.com", "twitter": "https://x.com",
    "instagram": "https://www.instagram.com", "facebook": "https://www.facebook.com",
    "tiktok": "https://www.tiktok.com", "wikipedia": "https://www.wikipedia.org",
    "outlook": "https://outlook.live.com", "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.com", "emag": "https://www.emag.bg", "olx": "https://www.olx.bg",
    "spotify web": "https://open.spotify.com", "steam store": "https://store.steampowered.com",
}

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "bing": "https://www.bing.com/search?q={}",
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={}",
    "github": "https://github.com/search?q={}",
    "maps": "https://www.google.com/maps/search/{}",
    "amazon": "https://www.amazon.com/s?k={}",
    "emag": "https://www.emag.bg/search/{}",
}


@lru_cache(maxsize=1)
def default_browser() -> tuple[str, str] | None:
    """(exe path, family) of the default browser, e.g. ('C:\\...\\brave.exe', 'chromium')."""
    if not IS_WINDOWS:
        return None
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        ) as k:
            prog_id = winreg.QueryValueEx(k, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as k:
            command = winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None
    m = re.match(r'\s*"([^"]+)"|\s*(\S+)', command)
    exe = (m[1] or m[2]) if m else ""
    if not exe or not os.path.exists(exe):
        return None
    family = "firefox" if "firefox" in exe.lower() else "chromium"  # Brave/Chrome/Edge/Opera/Vivaldi
    return exe, family


def open_url(url: str, background: bool = True, media: bool = False) -> None:
    """Open a URL. background=True -> new browser window that is sent to the back."""
    browser = default_browser()

    def launch() -> None:
        if browser:
            exe, family = browser
            flag = "-new-window" if family == "firefox" else "--new-window"
            subprocess.Popen([exe, flag, url])
        elif IS_WINDOWS:
            os.startfile(url)
        else:
            import webbrowser

            webbrowser.open(url, new=1)

    if background:
        # media: let the page start playing (browsers pause never-shown pages), then minimize
        expect = [os.path.basename(browser[0])] if browser else []
        keep_in_background(launch, watch=6, minimize_after=3.0 if media else 0.0, expect=expect)
    else:
        launch()


def site_url(site: str) -> str:
    s = site.strip().lower()
    if s in SITES:
        return SITES[s]
    if re.match(r"^https?://", s):
        return site.strip()
    if re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", s):  # looks like a domain: "emag.bg", "youtube.com/feed"
        return "https://" + site.strip()
    # unknown name -> DuckDuckGo "I'm feeling lucky" jumps to the first result
    return "https://duckduckgo.com/?q=" + urllib.parse.quote("! " + site)


def youtube_first_video(query: str) -> tuple[str, str] | None:
    """(video url, title) of the top YouTube result - no API key needed."""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": "SOCS=CAI; CONSENT=YES+1",  # skip the EU cookie consent page
    })
    try:
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
        m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})".*?"title":\{"runs":\[\{"text":"(.*?)"\}', html)
        if m:
            return f"https://www.youtube.com/watch?v={m[1]}", json.loads(f'"{m[2]}"')
        m = re.search(r'"videoId":"([\w-]{11})"', html)
        if m:
            return f"https://www.youtube.com/watch?v={m[1]}", query
    except Exception:
        pass
    try:  # fallback: DuckDuckGo video search
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        for r in DDGS().videos(f"{query} youtube", max_results=5):
            if "youtube.com/watch" in r.get("content", ""):
                return r["content"], r.get("title", query)
    except Exception:
        pass
    return None


@tool(
    "open_website",
    "Open a website in the browser, in the background (e.g. 'youtube', 'gmail', 'emag.bg', 'github').",
    {
        "site": {"type": "string", "description": "Site name or address, e.g. 'youtube' or 'emag.bg'"},
        "show": {"type": "boolean", "description": "true only if the user wants to SEE it now. Default: background"},
    },
    ["site"],
)
def open_website(site: str, show: bool = False) -> str:
    url = site_url(site)
    open_url(url, background=not show)
    return f"Opened {site}{'' if show else ' in the background'} 🌐"


@tool(
    "youtube_play",
    "Play something from YouTube (music, a podcast, a video's sound). By default it plays "
    "INVISIBLY, with no browser window. Use show=true only if the user wants to WATCH the video.",
    {
        "query": {"type": "string", "description": "What to play, e.g. 'lofi hip hop' or a YouTube link"},
        "show": {"type": "boolean", "description": "true = open the video in the browser to watch it"},
    },
    ["query"],
)
def youtube_play(query: str, show: bool = False) -> str:
    if not show:
        try:
            from ..player import PLAYER, find_track

            track = find_track(query)
            PLAYER.play(track)
            return f"Playing from YouTube: {track.title} ▶️"
        except ImportError:
            pass  # yt-dlp / audio libs missing -> use the browser
        except Exception as e:  # e.g. YouTube's bot check -> fall back to a minimized browser window
            print(f"[youtube] hidden player failed, using the browser: {e}")
    found = youtube_first_video(query)
    if not found:
        return f"Couldn't find '{query}' on YouTube."
    url, title = found
    open_url(url, background=not show, media=True)
    return f"Playing on YouTube: {title} ▶️" + ("" if show else " (in a minimized browser window)")


@tool(
    "youtube_control",
    "Control YouTube audio that Pixie is playing: pause, resume, stop, volume (0-100), or what's playing.",
    {
        "action": {"type": "string", "enum": ["pause", "resume", "stop", "volume", "now_playing"]},
        "volume": {"type": "integer", "description": "0-100, only for action=volume"},
    },
    ["action"],
)
def youtube_control(action: str, volume: int | None = None) -> str:
    from ..player import PLAYER

    if not PLAYER.playing:
        return "Nothing from YouTube is playing."
    title = PLAYER.track.title if PLAYER.track else "YouTube"
    if action == "pause":
        PLAYER.pause()
        return f"Paused {title} ⏸️"
    if action == "resume":
        PLAYER.resume()
        return f"Playing {title} ▶️"
    if action == "stop":
        PLAYER.stop()
        return "Stopped YouTube ⏹️"
    if action == "volume":
        v = max(0, min(100, int(volume if volume is not None else 50)))
        PLAYER.volume = v / 100
        return f"YouTube volume {v}% 🔊"
    return f"{'Paused' if PLAYER.paused else 'Playing'}: {title}"


@tool(
    "browser_search",
    "Open search results in the browser, in the background. Use when the user wants to SEE results "
    "on a site (google, youtube, maps, amazon, emag, wikipedia, github). For a quick answer use web_search.",
    {
        "query": {"type": "string"},
        "site": {
            "type": "string",
            "enum": list(SEARCH_URLS),
            "description": "Where to search (default google)",
        },
    },
    ["query"],
)
def browser_search(query: str, site: str = "google") -> str:
    template = SEARCH_URLS.get(site, SEARCH_URLS["google"])
    open_url(template.format(urllib.parse.quote_plus(query)), background=True)
    return f"Opened {site} results for '{query}' in the background 🔎"
