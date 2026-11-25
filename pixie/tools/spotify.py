"""Spotify control through the Spotify Web API - no window ever comes to the front.

Needs Spotify Premium (the API only allows playback control for Premium accounts)
and a free developer app from https://developer.spotify.com/dashboard.
"""

from __future__ import annotations

import functools
import random
import re
import time
from functools import lru_cache

from ..app_index import INDEX, normalize
from ..config import CONFIG, ROOT
from ..winctl import keep_in_background
from . import tool
from .apps import launch_app, launch_background

SCOPES = (
    "user-library-read user-library-modify user-read-playback-state "
    "user-modify-playback-state user-read-currently-playing playlist-read-private"
)


@lru_cache(maxsize=1)
def _sp():
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    cfg = CONFIG["spotify"]
    if not cfg.get("client_id"):
        raise RuntimeError("Spotify isn't set up - add client_id/client_secret to config.yaml.")
    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=cfg["client_id"],
            client_secret=cfg["client_secret"],
            redirect_uri=cfg["redirect_uri"],
            scope=SCOPES,
            cache_path=str(ROOT / ".spotify_cache"),
        )
    )


def _friendly(fn):
    """Turn Spotify API errors into messages that say what to do."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            reason = str(getattr(e, "reason", "") or "")
            status = getattr(e, "http_status", 0)
            text = str(e).lower()
            if reason == "PREMIUM_REQUIRED" or (status == 403 and "premium" in text):
                raise RuntimeError("Spotify only lets apps control playback with Spotify Premium.") from None
            if reason == "NO_ACTIVE_DEVICE" or "no active device" in text:
                raise RuntimeError("Spotify isn't ready yet. Try again in a few seconds.") from None
            if status == 401:
                raise RuntimeError("Spotify login expired. Say the command again to log in.") from None
            if status == 429:
                raise RuntimeError("Spotify says too many requests. Wait a minute and try again.") from None
            raise

    return wrapper


_liked_cache: tuple[float, list[str]] = (0.0, [])


def _liked_uris(limit: int) -> list[str]:
    """Your Liked Songs, cached for 10 minutes (saves 2+ requests per 'play my liked songs')."""
    global _liked_cache
    if time.time() - _liked_cache[0] < 600 and len(_liked_cache[1]) >= min(limit, 1):
        return list(_liked_cache[1])
    sp = _sp()
    uris: list[str] = []
    page = sp.current_user_saved_tracks(limit=50)
    while page and len(uris) < limit:
        uris += [item["track"]["uri"] for item in page["items"] if item.get("track")]
        page = sp.next(page) if page.get("next") else None
    _liked_cache = (time.time(), uris)
    return list(uris)


def _stop_youtube() -> None:
    from ..player import PLAYER

    if PLAYER.playing:
        PLAYER.stop()


def _device_id(timeout: float = 25) -> str:
    """Return an active Spotify device; start Spotify in the background if none is running."""
    _stop_youtube()  # only one thing plays at a time
    sp = _sp()
    devices = sp.devices().get("devices", [])
    if not devices:
        app = INDEX.find("spotify", use_llm=False)
        if app:
            launch_app(app, show=False)
        else:
            keep_in_background(lambda: launch_background("spotify:"))
        deadline = time.time() + timeout
        while time.time() < deadline and not devices:
            time.sleep(1.5)
            devices = sp.devices().get("devices", [])
    if not devices:
        raise RuntimeError("Spotify didn't start in time - try again in a moment.")
    active = next((d for d in devices if d.get("is_active")), None)
    computer = next((d for d in devices if d.get("type") == "Computer"), None)
    return (active or computer or devices[0])["id"]


def _best(items: list[dict], wanted: str, artist: str = "") -> dict | None:
    """Pick the result whose name (and artist) match best; Spotify's order breaks ties."""
    if not items:
        return None
    w, a = normalize(wanted), normalize(artist)

    def score(it: dict) -> float:
        name = normalize(it.get("name", ""))
        s = 2.0 if name == w else 1.0 if w and (w in name or name in w) else 0.0
        artists = " ".join(x.get("name", "") for x in it.get("artists", []))
        if a and a in normalize(artists):
            s += 1.5
        return s

    return max(enumerate(items), key=lambda p: (score(p[1]), -p[0]))[1]


def _split_by(query: str) -> tuple[str, str]:
    """'numb by linkin park' -> ('numb', 'linkin park')."""
    m = re.match(r"(.+?)\s+(?:by|from|от|на)\s+(.+)", query.strip(), re.I)
    return (m[1], m[2]) if m else (query.strip(), "")


def _find(query: str, kind: str) -> dict | None:
    sp = _sp()
    title, artist = _split_by(query)
    if kind == "playlist":
        # your own / followed playlists first ("play my gym playlist")
        mine = sp.current_user_playlists(limit=50)["items"]
        q = normalize(re.sub(r"\b(my|playlist)\b", "", query, flags=re.I))
        own = [p for p in mine if p and q and q in normalize(p["name"])]
        if own:
            return own[0]
    q = f"track:{title} artist:{artist}" if kind == "track" and artist else (
        f"album:{title} artist:{artist}" if kind == "album" and artist else query
    )
    items = sp.search(q=q, type=kind, limit=10)[f"{kind}s"]["items"]
    if not items and q != query:
        items = sp.search(q=query, type=kind, limit=10)[f"{kind}s"]["items"]
    items = [i for i in items if i]
    return _best(items, title if artist else query, artist)


def _who(item: dict) -> str:
    artists = ", ".join(a["name"] for a in item.get("artists", [])[:2])
    owner = (item.get("owner") or {}).get("display_name")
    return f" by {artists}" if artists else (f" ({owner})" if owner else "")


@tool(
    "play_liked_songs",
    "Play the user's Spotify Liked Songs in the background.",
    {"shuffle": {"type": "boolean", "description": "Shuffle the songs (default true)"}},
)
@_friendly
def play_liked_songs(shuffle: bool = True) -> str:
    sp = _sp()
    limit = int(CONFIG["spotify"].get("liked_songs_limit", 100))
    uris = _liked_uris(limit)
    if not uris:
        return "Your Liked Songs list is empty."
    if shuffle:
        random.shuffle(uris)
    sp.start_playback(device_id=_device_id(), uris=uris[:limit])
    return f"Playing your Liked Songs{' on shuffle' if shuffle else ''} 🎵"


@tool(
    "spotify_play",
    "Search Spotify and play something: a song, an album, an artist, or a playlist (incl. the user's own). "
    "Examples: 'numb by linkin park' (track), 'meteora' (album), 'eminem' (artist), 'my gym playlist' (playlist).",
    {
        "query": {"type": "string", "description": "What to play, e.g. 'Blinding Lights by The Weeknd'"},
        "kind": {
            "type": "string",
            "enum": ["track", "album", "artist", "playlist"],
            "description": "track = a song (default), album, artist, or playlist",
        },
    },
    ["query"],
)
@_friendly
def spotify_play(query: str, kind: str = "track") -> str:
    kind = kind if kind in ("track", "album", "artist", "playlist") else "track"
    item = _find(query, kind)
    if not item:
        return f"Couldn't find '{query}' on Spotify."
    sp, device = _sp(), _device_id()
    if kind == "track":
        sp.start_playback(device_id=device, uris=[item["uri"]])
    else:
        sp.start_playback(device_id=device, context_uri=item["uri"])
    label = {"track": "", "album": "the album ", "artist": "", "playlist": "the playlist "}[kind]
    return f"Playing {label}{item['name']}{_who(item)} 🎵"


@tool(
    "spotify_queue",
    "Add a song to the Spotify queue (plays after the current one).",
    {"query": {"type": "string", "description": "The song, e.g. 'Numb by Linkin Park'"}},
    ["query"],
)
@_friendly
def spotify_queue(query: str) -> str:
    item = _find(query, "track")
    if not item:
        return f"Couldn't find '{query}' on Spotify."
    _sp().add_to_queue(item["uri"], device_id=_device_id())
    return f"Added {item['name']}{_who(item)} to the queue ➕"


@tool("spotify_now_playing", "Tell what song is playing on Spotify right now.")
@_friendly
def spotify_now_playing() -> str:
    cur = _sp().current_playback()
    if not cur or not cur.get("item"):
        return "Nothing is playing on Spotify."
    item = cur["item"]
    state = "Playing" if cur.get("is_playing") else "Paused"
    return f"{state}: {item['name']}{_who(item)}"


@tool(
    "spotify_control",
    "Control Spotify: pause, resume, next, previous, volume, shuffle on/off, repeat on/off, "
    "or like (save the current song to Liked Songs).",
    {
        "action": {
            "type": "string",
            "enum": ["pause", "resume", "next", "previous", "volume", "shuffle_on", "shuffle_off",
                     "repeat_on", "repeat_off", "like"],
        },
        "volume": {"type": "integer", "description": "0-100, only for action=volume"},
    },
    ["action"],
)
@_friendly
def spotify_control(action: str, volume: int | None = None) -> str:
    sp = _sp()
    if action == "pause":
        sp.pause_playback()
    elif action == "resume":
        sp.start_playback(device_id=_device_id())
    elif action == "next":
        sp.next_track()
    elif action == "previous":
        sp.previous_track()
    elif action == "volume":
        v = max(0, min(100, int(volume if volume is not None else 50)))
        sp.volume(v)
        return f"Spotify volume {v}% 🔊"
    elif action in ("shuffle_on", "shuffle_off"):
        sp.shuffle(action == "shuffle_on")
    elif action in ("repeat_on", "repeat_off"):
        sp.repeat("context" if action == "repeat_on" else "off")
    elif action == "like":
        cur = sp.current_playback()
        if not cur or not cur.get("item"):
            return "Nothing is playing to like."
        # PUT /me/library (Spotify removed PUT /me/tracks in Feb 2026)
        sp._put("me/library", uris=cur["item"]["uri"])
        return f"Added {cur['item']['name']} to your Liked Songs 💚"
    return f"Spotify: {action.replace('_', ' ')} ✔"
