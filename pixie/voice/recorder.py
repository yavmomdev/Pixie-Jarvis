"""Microphone recorder. Only records while the talk key is held."""

from __future__ import annotations

import threading

import numpy as np

SAMPLE_RATE = 16000  # what Whisper expects


class Recorder:
    def __init__(self, samplerate: int = SAMPLE_RATE, device=None):
        self.samplerate = samplerate
        self.device = device
        self.level = 0.0  # 0..1 live mic loudness, read by the UI
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        self._chunks.append(indata.copy())
        rms = float(np.sqrt(np.mean(np.square(indata))))
        self.level = min(1.0, rms * 10)

    def start(self) -> None:
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return
            self._chunks = []
            self.level = 0.0
            self._stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=1,
                dtype="float32",
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop and return the recorded audio as mono float32 at 16 kHz."""
        with self._lock:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
            self.level = 0.0
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks).flatten()
            self._chunks = []
            return audio

    @property
    def recording(self) -> bool:
        return self._stream is not None
