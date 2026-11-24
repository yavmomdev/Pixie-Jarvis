"""Local speech-to-text with faster-whisper (runs on your GPU if available, else CPU)."""

from __future__ import annotations

import threading

import numpy as np

from ..config import CONFIG


class Transcriber:
    def __init__(self) -> None:
        cfg = (CONFIG.get("voice") or {})
        self.model_size = cfg.get("stt_model", "small")
        self.device = cfg.get("device", "auto")
        self.language = cfg.get("language") or None  # None = auto-detect
        self._model = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def _create(self, device: str):
        from faster_whisper import WhisperModel

        compute = "int8" if device == "cpu" else "default"
        return WhisperModel(self.model_size, device=device, compute_type=compute)

    def load(self) -> None:
        """Load the model (first run downloads it). Called at startup in a thread."""
        with self._lock:
            if self._model is not None:
                return
            try:
                self._model = self._create(self.device)
            except Exception:
                self.device = "cpu"  # e.g. CUDA libraries missing
                self._model = self._create("cpu")

    def _run(self, audio: np.ndarray) -> str:
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=True,  # skip silence -> fewer hallucinations
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def transcribe(self, audio: np.ndarray) -> str:
        self.load()
        try:
            return self._run(audio)
        except RuntimeError:
            if self.device == "cpu":
                raise
            # GPU failed at runtime (missing cuDNN/cuBLAS) -> fall back to CPU once
            with self._lock:
                self.device = "cpu"
                self._model = self._create("cpu")
            return self._run(audio)
