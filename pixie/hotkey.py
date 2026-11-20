"""Global push-to-talk: HOLD Right Alt to talk, DOUBLE-TAP it to type.

- Holding the key for a moment starts listening, and releasing it sends.
- If you press another key while holding it (e.g. AltGr+Q to type '@'), the
  recording is cancelled, so normal typing never triggers Pixie.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

RIGHT_ALT_NAMES = {"alt_r", "right_alt", "ralt", "alt_gr", "altgr"}


class PushToTalk:
    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_cancel: Callable[[], None],
        on_double_tap: Callable[[], None] | None = None,
        key: str = "alt_r",
        hold_delay: float = 0.15,
        double_tap_window: float = 0.35,
    ):
        self.on_start, self.on_stop, self.on_cancel = on_start, on_stop, on_cancel
        self.on_double_tap = on_double_tap
        self.key_name = key.lower()
        self.hold_delay = hold_delay
        self.double_tap_window = double_tap_window

        self.talk_keys: set = set()
        self.neutral_keys: set = set()  # keys that don't count as "another key"

        self._lock = threading.Lock()
        self._down = False
        self._other = False
        self._active = False
        self._timer: threading.Timer | None = None
        self._last_tap = 0.0
        self._listener = None

    # ---- setup -------------------------------------------------------------
    def start(self) -> None:
        from pynput import keyboard

        K = keyboard.Key
        if self.key_name in RIGHT_ALT_NAMES:
            # Right Alt is reported as alt_r or alt_gr depending on keyboard layout
            self.talk_keys = {K.alt_r, K.alt_gr}
        else:
            k = getattr(K, self.key_name, None) or keyboard.KeyCode.from_char(self.key_name)
            self.talk_keys = {k}
        # Windows sends a fake Left Ctrl together with AltGr -> ignore Ctrl
        self.neutral_keys = {K.ctrl, K.ctrl_l, K.ctrl_r}

        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()

    # ---- key logic (works with any hashable keys, so it is testable) ------
    def _press(self, key) -> None:
        with self._lock:
            if key in self.talk_keys:
                if self._down:  # key auto-repeat while holding
                    return
                self._down, self._other = True, False
                self._timer = threading.Timer(self.hold_delay, self._begin)
                self._timer.daemon = True
                self._timer.start()
                return
            if key in self.neutral_keys or not self._down:
                return
            # another key pressed during the hold -> it's a shortcut, not talking
            self._other = True
            if self._timer:
                self._timer.cancel()
            was_active, self._active = self._active, False
        if was_active:
            self.on_cancel()

    def _begin(self) -> None:
        with self._lock:
            if not self._down or self._other:
                return
            self._active = True
        self.on_start()

    def _release(self, key) -> None:
        if key not in self.talk_keys:
            return
        with self._lock:
            if not self._down:
                return
            self._down = False
            if self._timer:
                self._timer.cancel()
            was_active, self._active = self._active, False
            tapped = not was_active and not self._other
            double = False
            if tapped:
                now = time.monotonic()
                double = now - self._last_tap < self.double_tap_window
                self._last_tap = 0.0 if double else now
        if was_active:
            self.on_stop()
        elif double and self.on_double_tap:
            self.on_double_tap()
