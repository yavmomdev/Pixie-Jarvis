"""The Pixie popup: a floating panel in the middle of the screen.

States:
  listening    - glowing orb reacts to your voice, live mic bars
  transcribing - turning speech into text
  thinking     - shows what you said while the LLM decides
  reply/result - Pixie's answer / a finished background task, then fades away
  typing       - text box (double-tap Right Alt)

The popup never steals focus, except in typing mode (it needs the keyboard there).
"""

from __future__ import annotations

import math
from collections import deque
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QCursor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from . import win

WIDTH = 640  # panel width
MIN_H = 116  # panel min height
MAX_H = 380
PAD = 26  # transparent margin around the panel for the glow
RADIUS = 30
ORB = 60
BARS = 26

PALETTE = {
    "listening": ("#38bdf8", "#6366f1"),  # cyan -> indigo
    "transcribing": ("#818cf8", "#a855f7"),
    "thinking": ("#a855f7", "#ec4899"),  # purple -> pink
    "reply": ("#c084fc", "#6366f1"),
    "result": ("#34d399", "#38bdf8"),  # green -> cyan
    "typing": ("#38bdf8", "#a855f7"),
    "error": ("#f87171", "#f43f5e"),
    "hidden": ("#c084fc", "#6366f1"),
}
BUSY = {"listening", "transcribing", "thinking", "typing"}


def _font(size: float, weight=QFont.Weight.Normal, spacing: float = 0) -> QFont:
    f = QFont("Segoe UI Variable Display")
    f.setFamilies(["Segoe UI Variable Display", "Segoe UI", "Inter", "Helvetica Neue", "Arial"])
    f.setPointSizeF(size)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


class Overlay(QWidget):
    submitted = Signal(str)  # text typed in typing mode

    def __init__(
        self,
        level_source: Callable[[], float] = lambda: 0.0,
        name: str = "Pixie",
        hotkey_label: str = "Right Alt",
        position: str = "center",
    ):
        super().__init__(None)
        self.name = name
        self.hotkey_label = hotkey_label
        self.position = position
        self._level_source = level_source
        self.state = "hidden"
        self._phase = 0.0
        self._level = 0.0
        self._levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self._queue: list[str] = []
        self._prev_window = None
        self._anim: QParallelAnimationGroup | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # no taskbar button
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)  # don't steal focus
        self.setFixedWidth(WIDTH + 2 * PAD)

        # --- widgets ---
        self.title = QLabel()
        self.title.setFont(_font(8.5, QFont.Weight.DemiBold, 1.6))
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setFont(_font(12.5))
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.input = QLineEdit()
        self.input.setFont(_font(13))
        self.input.setPlaceholderText("Type a command…   (Enter to send, Esc to close)")
        self.input.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,0.06); color: #f4f4f8;"
            " border: 1px solid rgba(255,255,255,0.10); border-radius: 12px; padding: 8px 12px; }"
            "QLineEdit:focus { border: 1px solid rgba(56,189,248,0.55); }"
        )
        self.input.returnPressed.connect(self._submit)
        self.input.hide()

        col = QVBoxLayout()
        col.setSpacing(5)
        col.addStretch(1)
        col.addWidget(self.title)
        col.addWidget(self.text)
        col.addWidget(self.input)
        col.addStretch(1)

        row = QHBoxLayout(self)
        self._left = PAD + 26 + ORB + 22
        self._right = PAD + 28
        row.setContentsMargins(self._left, PAD + 16, self._right, PAD + 16)
        row.addLayout(col)

        # --- timers ---
        self._frame = QTimer(self, interval=16, timeout=self._tick)  # ~60 fps
        self._hide_timer = QTimer(self, singleShot=True, timeout=self.fade_out)

        self._set("", "", "hidden")

    # =================================================================== API
    def show_listening(self) -> None:
        self._set("LISTENING", f"Speak now · release {self.hotkey_label} to send", "listening", dim=True)
        self._pop_in()

    def show_transcribing(self, note: str = "One sec…") -> None:
        self._set("TRANSCRIBING", note, "transcribing", dim=True)
        self._pop_in()

    def show_thinking(self, said: str) -> None:
        self._set("THINKING", f"“{said}”", "thinking", dim=True)
        self._pop_in()

    def show_reply(self, text: str) -> None:
        self._set(self.name.upper(), text, "reply")
        self._pop_in()
        self._auto_hide(text)

    def show_result(self, text: str) -> None:
        """A background task finished. Waits if you're in the middle of talking."""
        if self.state in BUSY:
            self._queue.append(text)
            return
        if self.state == "result" and self.isVisible() and self.text.text():
            # several tasks finished together -> stack them (max 4 lines)
            lines = (self.text.text().split("\n") + [text])[-4:]
            text = "\n".join(lines)
        self._set("DONE", text, "result")
        self._pop_in()
        self._auto_hide(text)

    def show_error(self, text: str) -> None:
        self._set("SOMETHING WENT WRONG", text, "error")
        self._pop_in()
        self._hide_timer.start(6000)

    def show_typing(self) -> None:
        self._prev_window = win.foreground()
        self._set("ASK " + self.name.upper(), "", "typing")
        self.input.clear()
        self._pop_in(focus=True)

    def cancel(self) -> None:
        self.fade_out()

    # ============================================================ internals
    def _set(self, title: str, text: str, state: str, dim: bool = False) -> None:
        self.state = state
        c1, _ = PALETTE.get(state, PALETTE["reply"])
        self.title.setText(title)
        self.title.setStyleSheet(f"color: {c1};")
        self.text.setText(text)
        self.text.setStyleSheet(f"color: {'#9a9ab0' if dim else '#f4f4f8'};")
        self.text.setVisible(bool(text))
        self.input.setVisible(state == "typing")
        self._fit()

    def _fit(self) -> None:
        inner_w = self.width() - self._left - self._right
        h = self.title.sizeHint().height()
        if self.text.isVisibleTo(self) and self.text.text():
            text_h = self.text.heightForWidth(inner_w)
            self.text.setMinimumHeight(text_h)  # make the layout give it all the lines
            h += 5 + text_h
        if self.input.isVisibleTo(self):
            h += 5 + self.input.sizeHint().height()
        panel = max(MIN_H, min(MAX_H, h + 40))
        self.setFixedHeight(panel + 2 * PAD)
        if self.layout():
            self.layout().activate()
        if self.isVisible():
            self.move(self._target_pos())

    def _target_pos(self) -> QPoint:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x = g.center().x() - self.width() // 2
        if self.position == "top":
            y = g.top() + int(g.height() * 0.16)
        elif self.position == "bottom":
            y = g.bottom() - int(g.height() * 0.12) - self.height()
        else:  # center
            y = g.center().y() - self.height() // 2
        return QPoint(x, y)

    def _pop_in(self, focus: bool = False) -> None:
        self._hide_timer.stop()
        if self._anim:
            self._anim.stop()
        target = self._target_pos()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.move(target + QPoint(0, 16))
            self.show()
            self._frame.start()
            fade = QPropertyAnimation(self, b"windowOpacity", self)
            fade.setDuration(170)
            fade.setEndValue(1.0)
            slide = QPropertyAnimation(self, b"pos", self)
            slide.setDuration(260)
            slide.setEndValue(target)
            slide.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim = QParallelAnimationGroup(self)
            self._anim.addAnimation(fade)
            self._anim.addAnimation(slide)
            self._anim.start()
        else:
            self.setWindowOpacity(1.0)
            self.move(target)
        if focus:
            self.raise_()
            self.activateWindow()
            win.set_foreground(int(self.winId()))
            self.input.setFocus()

    def _auto_hide(self, text: str) -> None:
        self._hide_timer.start(max(3200, min(12000, 2200 + 45 * len(text))))

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        self._hide_timer.stop()
        if self._anim:
            self._anim.stop()
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(160)
        fade.setEndValue(0.0)
        self._anim = QParallelAnimationGroup(self)
        self._anim.addAnimation(fade)
        self._anim.finished.connect(self._after_hide)
        self._anim.start()

    def _after_hide(self) -> None:
        was_typing = self.state == "typing"
        self.hide()
        self._frame.stop()
        self.state = "hidden"
        if was_typing:
            win.set_foreground(self._prev_window)
        if self._queue:
            self.show_result(self._queue.pop(0))

    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        win.set_foreground(self._prev_window)  # give focus back to your app/game
        self.show_thinking(text)
        self.submitted.emit(text)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.fade_out()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e) -> None:
        if self.state not in BUSY:  # click to dismiss
            self.fade_out()

    # ============================================================ painting
    def _tick(self) -> None:
        self._phase += 0.016
        target = self._level_source() if self.state == "listening" else 0.0
        self._level += (target - self._level) * 0.35
        self._levels.append(self._level)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(PAD, PAD, -PAD, -PAD)
        c1, c2 = (QColor(c) for c in PALETTE.get(self.state, PALETTE["reply"]))

        # soft outer glow
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(PAD, 0, -2):
            g = QColor(c1)
            g.setAlpha(int(12 * (1 - i / PAD) ** 1.6))
            p.setBrush(g)
            p.drawRoundedRect(r.adjusted(-i, -i, i, i), RADIUS + i, RADIUS + i)

        # glass panel
        bg = QLinearGradient(r.topLeft(), r.bottomLeft())
        bg.setColorAt(0, QColor(24, 24, 34, 242))
        bg.setColorAt(1, QColor(12, 12, 18, 242))
        p.setBrush(bg)
        border = QLinearGradient(r.topLeft(), r.bottomRight())
        b1, b2 = QColor(c1), QColor(c2)
        b1.setAlpha(150)
        b2.setAlpha(40)
        border.setColorAt(0, b1)
        border.setColorAt(1, b2)
        p.setPen(QPen(border, 1.2))
        p.drawRoundedRect(r, RADIUS, RADIUS)

        self._paint_orb(p, QPointF(r.left() + 26 + ORB / 2, r.center().y()), c1, c2)
        if self.state == "listening":
            self._paint_bars(p, r, c1, c2)
        p.end()

    def _paint_orb(self, p: QPainter, c: QPointF, c1: QColor, c2: QColor) -> None:
        t = self._phase
        if self.state == "listening":
            s = 0.78 + 0.42 * min(1.0, self._level * 1.4)
        elif self.state in ("thinking", "transcribing"):
            s = 0.86 + 0.06 * math.sin(t * 5)
        else:
            s = 0.9 + 0.03 * math.sin(t * 2)
        rad = ORB / 2 * s

        # halo
        halo = QRadialGradient(c, rad * 1.9)
        h1 = QColor(c1)
        h1.setAlpha(110)
        h2 = QColor(c2)
        h2.setAlpha(0)
        halo.setColorAt(0.45, h1)
        halo.setColorAt(1, h2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, rad * 1.9, rad * 1.9)

        # core, with a slowly moving highlight so it feels alive
        hl = QPointF(c.x() - rad * 0.35 + math.sin(t * 1.3) * rad * 0.12,
                     c.y() - rad * 0.4 + math.cos(t * 1.1) * rad * 0.1)
        core = QRadialGradient(hl, rad * 1.5)
        core.setColorAt(0.0, QColor(255, 255, 255, 235))
        core.setColorAt(0.28, c1)
        core.setColorAt(1.0, c2)
        p.setBrush(core)
        p.drawEllipse(c, rad, rad)

        # spinning ring while working
        if self.state in ("thinking", "transcribing"):
            ring = QConicalGradient(c, -t * 300)
            r1 = QColor(c1)
            r1.setAlpha(255)
            r0 = QColor(c1)
            r0.setAlpha(0)
            ring.setColorAt(0.0, r1)
            ring.setColorAt(0.55, r0)
            ring.setColorAt(1.0, r0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ring, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawEllipse(c, ORB / 2 + 9, ORB / 2 + 9)

    def _paint_bars(self, p: QPainter, r: QRectF, c1: QColor, c2: QColor) -> None:
        bw, gap = 3.0, 3.0
        x = r.right() - 28 - BARS * (bw + gap)
        cy = r.center().y()
        grad = QLinearGradient(QPointF(x, 0), QPointF(r.right() - 28, 0))
        grad.setColorAt(0, c2)
        grad.setColorAt(1, c1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        for i, lvl in enumerate(self._levels):
            idle = 1.5 + 1.2 * math.sin(self._phase * 4 + i * 0.6)
            h = 4 + idle + min(1.0, lvl * 1.4) * 34
            p.drawRoundedRect(QRectF(x + i * (bw + gap), cy - h / 2, bw, h), 1.5, 1.5)
