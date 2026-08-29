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

Extended keys (Windows, right-side Ctrl/Alt, navigation cluster)
──────────────────────────────────────────────────────────────────
Those don't replay correctly via raw scan code alone (see
extended_keys.py for why). SCAN_CODE_TO_VK maps the affected scan codes
to the correct Virtual-Key code and is sent via VK + KEYEVENTF_EXTENDEDKEY
instead. Every other key still replays by scan code exactly as before —
that's what keeps this layout-independent.

Threading
─────────
Each play() call runs on its own daemon thread so a macro's "wait"
actions never block the HID reader thread — other buttons keep working
while a macro is mid-playback. MAX_CONCURRENT_MACROS caps how many can
run at once (e.g. rapid re-presses of different macro buttons); beyond
that, further presses are dropped rather than queued.

On top of that, the *same* macro (identified by the identity of its
`actions` list, which is the same object each time a given macro button
is pressed since it's looked up from the in-memory config rather than
re-parsed per press) is never played more than once concurrently — a
repress while it's still running is dropped. This avoids two copies of
the same macro racing each other and stomping on shared keys (e.g. both
holding/releasing "shift" out of sync with one another).

Stuck-key safety net
─────────────────────
If playback stops mid-sequence (exception, a future cancel path, ...)
while a key is still logically "held," that key is force-released in
`finally` — otherwise it can end up physically stuck down system-wide
until the user happens to tap that exact key themselves.
"""

from __future__ import annotations

import ctypes
import threading
import time
from typing import Any, Optional

from .input_sender import INPUT, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, KEYEVENTF_EXTENDEDKEY
from .extended_keys import SCAN_CODE_TO_VK

KEYEVENTF_SCANCODE = 0x0008

MAX_CONCURRENT_MACROS = 2
MAX_MACRO_ACTIONS = 500   # guards against a corrupt/huge macro locking up a thread
MAX_WAIT_MS = 5000        # guards against a single bogus "wait" entry stalling playback

_SendInput = ctypes.windll.user32.SendInput


def _make_scancode_input(scan_code: int, key_up: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
    inp = INPUT(type=INPUT_KEYBOARD)
    inp._input.ki = KEYBDINPUT(wVk=0, wScan=scan_code, dwFlags=flags)
    return inp


def _make_vk_input(vk: int, key_up: bool) -> INPUT:
    # Every VK this is called with (see SCAN_CODE_TO_VK) is an extended
    # key on real hardware. Windows doesn't infer that from the VK code
    # alone — without KEYEVENTF_EXTENDEDKEY the E0 prefix bit is dropped,
    # so right Ctrl/Alt can be indistinguishable from their left-side
    # counterparts and the nav cluster can be read as numpad keys.
    flags = KEYEVENTF_EXTENDEDKEY | (KEYEVENTF_KEYUP if key_up else 0)
    inp = INPUT(type=INPUT_KEYBOARD)
    inp._input.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags)
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
        self._active_macros: set[int] = set()
        self._lock = threading.Lock()

    def play(self, actions: list[dict[str, Any]]) -> None:
        if not actions:
            return
        macro_id = id(actions)
        with self._lock:
            if self._active >= MAX_CONCURRENT_MACROS:
                return
            if macro_id in self._active_macros:
                return
            self._active += 1
            self._active_macros.add(macro_id)
        threading.Thread(target=self._run, args=(actions, macro_id), name="MacroPlayer", daemon=True).start()

    def _run(self, actions: list[dict[str, Any]], macro_id: int) -> None:
        held: list[tuple[Optional[int], Optional[int]]] = []  # keys currently held: [(vk, scan_code), ...]
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

                key_up = (kind == "release")
                vk = SCAN_CODE_TO_VK.get(scan_code)

                if vk is not None:
                    inp = _make_vk_input(vk, key_up=key_up)
                    token = (vk, None)
                else:
                    inp = _make_scancode_input(scan_code, key_up=key_up)
                    token = (None, scan_code)

                _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

                if key_up:
                    if token in held:
                        held.remove(token)
                else:
                    held.append(token)
        finally:
            for vk, scan_code in held:
                try:
                    if vk is not None:
                        inp = _make_vk_input(vk, key_up=True)
                    else:
                        inp = _make_scancode_input(scan_code, key_up=True)
                    _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
                except Exception:
                    pass

            with self._lock:
                self._active -= 1
                self._active_macros.discard(macro_id)
