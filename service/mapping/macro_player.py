#
# service/mapping/macro_player.py
# Macro playback via Win32 SendInput scancodes.
#

"""
Recording and playback
──────────────────────
Macro actions are recorded by the GUI's macros.py using the `keyboard`
library, which reports hardware scan codes rather than virtual-key
names. Replaying by scan code (KEYEVENTF_SCANCODE) sidesteps needing a
second name-to-VK table that would have to agree with keyboard's naming
exactly — each action is just replayed with the same scan code it was
captured with.

Known limitation
────────────────
The recorder does not currently store whether a key was an extended key
(arrow cluster, navigation cluster, right-side Ctrl/Alt, ...), so those
are replayed without KEYEVENTF_EXTENDEDKEY and may not register correctly.
Regular letters, digits, F-keys and left-side modifiers are unaffected.

Threading
─────────
Each play() call runs on its own daemon thread so a macro's "wait"
actions never block the HID reader thread — other buttons keep working
while a macro is mid-playback. MAX_CONCURRENT_MACROS caps how many can
run at once (e.g. rapid re-presses of the same macro button); beyond
that, further presses are dropped rather than queued.
"""

from __future__ import annotations

import ctypes
import threading
import time
from typing import Any

from .input_sender import INPUT, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP

KEYEVENTF_SCANCODE = 0x0008

MAX_CONCURRENT_MACROS = 4
MAX_MACRO_ACTIONS = 500   # guards against a corrupt/huge macro locking up a thread
MAX_WAIT_MS = 5000        # guards against a single bogus "wait" entry stalling playback

_SendInput = ctypes.windll.user32.SendInput


def _make_scancode_input(scan_code: int, key_up: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
    inp = INPUT(type=INPUT_KEYBOARD)
    inp._input.ki = KEYBDINPUT(wVk=0, wScan=scan_code, dwFlags=flags)
    return inp


class MacroPlayer:
    """
    Usage
    ─────
        player = MacroPlayer()
        player.play(binding["actions"])   # returns immediately
    """

    def __init__(self) -> None:
        self._active = 0
        self._lock = threading.Lock()

    def play(self, actions: list[dict[str, Any]]) -> None:
        if not actions:
            return
        with self._lock:
            if self._active >= MAX_CONCURRENT_MACROS:
                return
            self._active += 1
        threading.Thread(target=self._run, args=(actions,), name="MacroPlayer", daemon=True).start()

    def _run(self, actions: list[dict[str, Any]]) -> None:
        try:
            for action in actions[:MAX_MACRO_ACTIONS]:
                kind = action.get("type")

                if kind == "wait":
                    ms = action.get("ms", 0)
                    if isinstance(ms, (int, float)) and ms > 0:
                        time.sleep(min(ms, MAX_WAIT_MS) / 1000)
                    continue

                if kind not in ("press", "release"):
                    continue

                scan_code = action.get("scan_code")
                if not isinstance(scan_code, int):
                    continue

                inp = _make_scancode_input(scan_code, key_up=(kind == "release"))
                _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        finally:
            with self._lock:
                self._active -= 1
