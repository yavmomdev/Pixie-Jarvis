"""Spotify control through the Spotify Web API - no window ever comes to the front.

Needs Spotify Premium (the API only allows playback control for Premium accounts)
and a free developer app from https://developer.spotify.com/dashboard.
"""

from __future__ import annotations

import random
import time
from functools import lru_cache

from ..config import CONFIG, ROOT
from . import tool
from ..app_index import INDEX
from .apps import launch_app, launch_background

SCOPES = "user-library-read user-read-playback-state user-modify-playback-state"


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


def _device_id(timeout: float = 20) -> str:
    """Return an active Spotify device; start Spotify minimized if none is running."""
    sp = _sp()
    devices = sp.devices().get("devices", [])
    if not devices:
        app = INDEX.find("spotify", use_llm=False)
        launch_app(app) if app else launch_background("spotify:")
        deadline = time.time() + timeout
        while time.time() < deadline and not devices:
            time.sleep(1.5)
            devices = sp.devices().get("devices", [])
    if not devices:
        raise RuntimeError("Spotify didn't start in time - try again in a moment.")
    active = next((d for d in devices if d.get("is_active")), None)
    computer = next((d for d in devices if d.get("type") == "Computer"), None)
    return (active or computer or devices[0])["id"]


@tool(
    "play_liked_songs",
    "Play the user's Spotify Liked Songs in the background.",
    {"shuffle": {"type": "boolean", "description": "Shuffle the songs (default true)"}},
)
def play_liked_songs(shuffle: bool = True) -> str:
    sp = _sp()
    limit = int(CONFIG["spotify"].get("liked_songs_limit", 100))
    uris: list[str] = []
    page = sp.current_user_saved_tracks(limit=50)
    while page and len(uris) < limit:
        uris += [item["track"]["uri"] for item in page["items"] if item.get("track")]
        page = sp.next(page) if page.get("next") else None
    if not uris:
        return "Your Liked Songs list is empty."
    if shuffle:
        random.shuffle(uris)
    sp.start_playback(device_id=_device_id(), uris=uris[:limit])
    return f"Playing your Liked Songs{' on shuffle' if shuffle else ''} 🎵"


@tool(
    "spotify_play",
    "Search Spotify and play a song, artist, album or playlist.",
    {
        "query": {"type": "string", "description": "What to play, e.g. 'Blinding Lights' or 'Eminem'"},
        "kind": {
            "type": "string",
            "enum": ["track", "artist", "album", "playlist"],
            "description": "What kind of thing it is (default track)",
        },
    },
    ["query"],
)
def spotify_play(query: str, kind: str = "track") -> str:
    sp = _sp()
    items = sp.search(q=query, type=kind, limit=1)[f"{kind}s"]["items"]
    if not items:
        return f"Couldn't find '{query}' on Spotify."
    item = items[0]
    device = _device_id()
    if kind == "track":
        sp.start_playback(device_id=device, uris=[item["uri"]])
    else:
        sp.start_playback(device_id=device, context_uri=item["uri"])
    return f"Playing {item['name']} 🎵"


@tool(
    "spotify_control",
    "Control Spotify playback: pause, resume, next, previous, or set volume.",
    {
        "action": {"type": "string", "enum": ["pause", "resume", "next", "previous", "volume"]},
        "volume": {"type": "integer", "description": "0-100, only for action=volume"},
    },
    ["action"],
)
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
        sp.volume(max(0, min(100, int(volume if volume is not None else 50))))
    return f"Spotify: {action} ✔"
