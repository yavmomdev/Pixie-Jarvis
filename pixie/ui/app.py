"""Pixie desktop app: tray icon + center popup + hold-Right-Alt voice commands.

Flow:
  hold Right Alt  -> popup "Listening", mic records
  release         -> Whisper transcribes (local) -> brain picks tools -> popup shows reply
  tools run in the background -> popup shows "Done" when each one finishes
  double-tap Right Alt -> type a command instead
"""

from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QPointF, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .. import notify
from ..brain import Brain
from ..config import CONFIG
from ..hotkey import RIGHT_ALT_NAMES, PushToTalk
from ..tasks import BackgroundLoop
from .. import app_index
from ..tools import load_all
from ..voice.recorder import SAMPLE_RATE, Recorder
from ..voice.stt import Transcriber
from .overlay import Overlay

MIN_SECONDS = 0.35  # ignore accidental tiny holds


def _orb_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QRadialGradient(QPointF(24, 22), 40)
    g.setColorAt(0, QColor(255, 255, 255))
    g.setColorAt(0.3, QColor("#38bdf8"))
    g.setColorAt(1, QColor("#a855f7"))
    p.setBrush(g)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.end()
    return QIcon(pm)


class Controller(QObject):
    # signals let worker threads safely update the UI (Qt main thread)
    hold_start = Signal()
    hold_stop = Signal()
    hold_cancel = Signal()
    double_tap = Signal()
    heard = Signal(str)
    reply = Signal(str)
    result = Signal(str)
    error = Signal(str)
    nothing = Signal()

    def __init__(self) -> None:
        super().__init__()
        load_all()
        app_index.warm_up()  # scan installed apps in the background
        self.name = CONFIG.get("assistant_name", "Pixie")
        ui_cfg = (CONFIG.get("ui") or {})
        key = str(ui_cfg.get("hotkey", "alt_r"))
        key_label = "Right Alt" if key.lower() in RIGHT_ALT_NAMES else key

        self.recorder = Recorder(device=(CONFIG.get("voice") or {}).get("mic"))
        self.stt = Transcriber()
        self.brain = Brain()
        self.tasks = BackgroundLoop(self.name)
        self.worker = ThreadPoolExecutor(max_workers=1)  # one command at a time

        self.overlay = Overlay(
            level_source=lambda: self.recorder.level,
            name=self.name,
            hotkey_label=key_label,
            position=ui_cfg.get("position", "center"),
        )
        self.overlay.submitted.connect(self.on_typed)

        self.hold_start.connect(self.on_hold_start)
        self.hold_stop.connect(self.on_hold_stop)
        self.hold_cancel.connect(self.on_hold_cancel)
        self.double_tap.connect(self.overlay.show_typing)
        self.heard.connect(self.overlay.show_thinking)
        self.reply.connect(self.overlay.show_reply)
        self.result.connect(self.overlay.show_result)
        self.error.connect(self.overlay.show_error)
        self.nothing.connect(self.on_nothing)

        notify.add_listener(lambda _title, msg: self.result.emit(msg))

        self.ptt = PushToTalk(
            on_start=self.hold_start.emit,
            on_stop=self.hold_stop.emit,
            on_cancel=self.hold_cancel.emit,
            on_double_tap=self.double_tap.emit,
            key=key,
            hold_delay=float(ui_cfg.get("hold_delay", 0.15)),
        )
        self.ptt.start()
        # load Whisper in the background so the first command is fast
        threading.Thread(target=self._warm_up, daemon=True).start()

    def _warm_up(self) -> None:
        import time

        start = time.time()
        try:
            self.stt.load()
            print(f"🎙️  Speech model ready ({self.stt.model_size} on {self.stt.device}).")
            if time.time() - start > 8:  # it was downloading -> let the user know voice works now
                self.result.emit("Voice is ready 🎙️ Hold Right Alt to talk.")
        except Exception as e:
            self.error.emit(f"Couldn't load the speech model: {e}")

    # ---- voice --------------------------------------------------------------
    @Slot()
    def on_hold_start(self) -> None:
        try:
            self.recorder.start()
        except Exception as e:
            self.overlay.show_error(f"Microphone problem: {e}")
            return
        self.overlay.show_listening()

    @Slot()
    def on_hold_cancel(self) -> None:
        self.recorder.stop()
        if self.overlay.state == "listening":
            self.overlay.cancel()

    @Slot()
    def on_hold_stop(self) -> None:
        if not self.recorder.recording:
            return
        audio = self.recorder.stop()
        if audio.size < SAMPLE_RATE * MIN_SECONDS:
            self.overlay.cancel()
            return
        if self.stt.ready:
            self.overlay.show_transcribing()
        else:
            self.overlay.show_transcribing(
                f"Downloading the speech model ({self.stt.model_size}), first time only. "
                "Your command will run when it's done. Tip: double-tap Right Alt to type meanwhile."
            )

        def job() -> None:
            try:
                text = self.stt.transcribe(audio)
            except Exception as e:
                self.error.emit(f"Speech-to-text failed: {e}")
                return
            if not text:
                self.nothing.emit()
                return
            self.heard.emit(text)
            self.worker.submit(self._handle, text)

        # transcribe in its own thread, so typed commands never wait for Whisper
        threading.Thread(target=job, daemon=True, name="pixie-stt").start()

    @Slot()
    def on_nothing(self) -> None:
        self.overlay.show_reply("I didn't catch that. Hold Right Alt and try again.")

    # ---- text ---------------------------------------------------------------
    @Slot(str)
    def on_typed(self, text: str) -> None:
        self.worker.submit(self._handle, text)

    # ---- brain --------------------------------------------------------------
    def _handle(self, text: str) -> None:
        """Runs in the worker thread."""
        print(f"you> {text}")
        try:
            decision = self.brain.decide(text)
        except Exception as e:
            self.error.emit(f"I can't reach Ollama. Is it running? ({e})")
            return
        for tool_name, args in decision.calls:
            self.tasks.submit(tool_name, args)
        print(f"{self.name}> {decision.reply}")
        self.reply.emit(decision.reply or "…")


def run() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # lives in the tray
    app.setApplicationName("Pixie")

    ctl = Controller()

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(_orb_icon(), app)
        tray.setToolTip(f"{ctl.name}: hold Right Alt to talk, double-tap to type")
        menu = QMenu()
        act_type = QAction("Type a command", menu, triggered=ctl.overlay.show_typing)
        act_quit = QAction(f"Quit {ctl.name}", menu, triggered=app.quit)
        menu.addAction(act_type)
        menu.addSeparator()
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: ctl.overlay.show_typing()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        tray.show()
        app._tray = tray  # keep a reference

    print(f"🧚 {ctl.name} is running in the tray. Hold Right Alt to talk, double-tap to type.")
    ctl.overlay.show_reply("Hi! Hold Right Alt to talk to me, or double-tap it to type.")
    sys.exit(app.exec())
