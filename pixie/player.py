"""Invisible audio player for YouTube - no browser, no window, nothing on screen.

yt-dlp finds the audio stream (it uses Deno, installed via pip, for YouTube's
JavaScript challenge), PyAV decodes it while it downloads, and sounddevice plays
it. Pause / resume / stop / volume are instant because it all runs inside Pixie.
"""

from __future__ import annotations

import io
import os
import sys
import threading
import time
from dataclasses import dataclass

RATE = 48000


def _add_venv_scripts_to_path() -> None:
    """Deno is installed into the venv's Scripts folder; make sure yt-dlp can find it."""
    scripts = os.path.join(sys.prefix, "Scripts" if sys.platform == "win32" else "bin")
    if os.path.isdir(scripts) and scripts not in os.environ.get("PATH", ""):
        os.environ["PATH"] = scripts + os.pathsep + os.environ.get("PATH", "")


@dataclass
class Track:
    title: str
    url: str  # direct audio stream URL
    headers: dict
    page: str  # youtube.com/watch?v=... (to open in the browser if wanted)
    duration: float = 0.0


def find_track(query: str) -> Track:
    """Search YouTube (or take a URL) and return the best audio stream."""
    _add_venv_scripts_to_path()
    from yt_dlp import YoutubeDL

    opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "default_search": "ytsearch1",
        "extract_flat": False,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
    if "entries" in info:
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise LookupError(f"nothing found for '{query}'")
        info = entries[0]
    return Track(
        title=info.get("title") or query,
        url=info["url"],
        headers=dict(info.get("http_headers") or {}),
        page=info.get("webpage_url") or "",
        duration=float(info.get("duration") or 0),
    )


class _HttpStream(io.RawIOBase):
    """Non-seekable file object over yt-dlp's HTTP response (proxies, headers, retries handled)."""

    def __init__(self, response) -> None:
        self.r = response

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def readinto(self, b) -> int:
        data = self.r.read(len(b))
        b[: len(data)] = data
        return len(data)

    def close(self) -> None:
        try:
            self.r.close()
        finally:
            super().close()


class Player:
    def __init__(self) -> None:
        self.track: Track | None = None
        self.volume = 1.0
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ control
    @property
    def playing(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def play(self, track: Track, timeout: float = 20) -> None:
        """Start playing; returns once sound is coming out (or raises the error)."""
        self.stop()
        started, failed = threading.Event(), []
        with self._lock:
            self._stop = threading.Event()
            self._paused.clear()
            self.track = track
            self._thread = threading.Thread(
                target=self._run, args=(track, self._stop, started, failed), daemon=True, name="pixie-player"
            )
            self._thread.start()
        deadline = time.time() + timeout
        while time.time() < deadline and not started.is_set() and not failed:
            time.sleep(0.05)
        if failed:
            raise failed[0]
        if not started.is_set():
            self.stop()
            raise TimeoutError("YouTube took too long to start playing")

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def toggle(self) -> None:
        self.resume() if self.paused else self.pause()

    def stop(self) -> None:
        self._stop.set()
        self._paused.clear()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2)
        self._thread = None

    # ------------------------------------------------------------- worker
    def _run(self, track: Track, stop: threading.Event, started: threading.Event, failed: list) -> None:
        container = None
        try:
            import av
            import numpy as np
            import sounddevice as sd
            from yt_dlp import YoutubeDL
            from yt_dlp.networking import Request

            with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                response = ydl.urlopen(Request(track.url, headers=track.headers))
            container = av.open(io.BufferedReader(_HttpStream(response), 1 << 16), mode="r")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="flt", layout="stereo", rate=RATE)
            with sd.OutputStream(samplerate=RATE, channels=2, dtype="float32", latency="high") as out:
                for frame in container.decode(stream):
                    while self._paused.is_set() and not stop.is_set():
                        time.sleep(0.05)
                    if stop.is_set():
                        break
                    for f in resampler.resample(frame):
                        data = f.to_ndarray().reshape(-1, 2)
                        if self.volume != 1.0:
                            data = data * np.float32(self.volume)
                        out.write(data)
                        started.set()
        except Exception as e:  # noqa: BLE001 - reported to the caller
            if not started.is_set():
                failed.append(e)
        finally:
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass
            if self.track is track and not stop.is_set():
                self.track = None  # finished on its own


PLAYER = Player()
