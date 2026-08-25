#
# service/mapping/input_sender.py
# Keyboard and mouse button injection via Win32 SendInput.
#

"""
Why not pynput / keyboard / pyautogui?
──────────────────────────────────────
- Fewer runtime dependencies.
- Direct ctypes call = no extra layer between us and the Win32 API.
- SendInput is the correct way to inject synthetic input on Windows;
  it respects UIPI levels better than WriteFile to the keyboard driver.

Shortcut string format (same as config.json values)
────────────────────────────────────────────────────
  "f13"             → single key
  "ctrl+shift+p"    → modifier chord
  "mouse4"          → X-button 1 (browser back by convention)
  "mouse5"          → X-button 2 (browser forward)
  ""                → unmapped, do nothing

Modifier names: ctrl, shift, alt, win  (case-insensitive)
Key names: anything in VIRTUAL_KEY_MAP below, or fNN for function keys.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from typing import Sequence

# ── Win32 constants ───────────────────────────────────────────────────────────

KEYEVENTF_KEYDOWN   = 0x0000
KEYEVENTF_KEYUP     = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

INPUT_KEYBOARD = 1
INPUT_MOUSE    = 0

MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP   = 0x0100
XBUTTON1 = 0x0001   # mouse4
XBUTTON2 = 0x0002   # mouse5


# ── Virtual key map ───────────────────────────────────────────────────────────
# Extend this table as needed.  Names are lower-cased before lookup.

VIRTUAL_KEY_MAP: dict[str, int] = {
    # Modifiers
    "ctrl":    0x11,  # VK_CONTROL
    "shift":   0x10,  # VK_SHIFT
    "alt":     0x12,  # VK_MENU
    "win":     0x5B,  # VK_LWIN

    # Navigation
    "home":    0x24,
    "end":     0x23,
    "pageup":  0x21,
    "pagedown":0x22,
    "insert":  0x2D,
    "delete":  0x2E,
    "up":      0x26,
    "down":    0x28,
    "left":    0x25,
    "right":   0x27,

    # Common
    "enter":   0x0D,
    "space":   0x20,
    "tab":     0x09,
    "escape":  0x1B,
    "back":    0x08,

    # Media
    "playpause":  0xB3,
    "nexttrack":  0xB0,
    "prevtrack":  0xB1,
    "volumeup":   0xAF,
    "volumedown": 0xAE,
    "mute":       0xAD,

    # Letters a-z  (VK codes == ASCII upper-case)
    **{chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)},

    # Digits 0-9
    **{str(d): 0x30 + d for d in range(10)},

    # Function keys F1-F24
    **{f"f{n}": 0x6F + n for n in range(1, 25)},   # F1=0x70 … F24=0x87
}

MODIFIER_KEYS = frozenset({"ctrl", "shift", "alt", "win"})


# ── ctypes structures ─────────────────────────────────────────────────────────

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.wintypes.WORD),
        ("wScan",       ctypes.wintypes.WORD),
        ("dwFlags",     ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.wintypes.LONG),
        ("dy",          ctypes.wintypes.LONG),
        ("mouseData",   ctypes.wintypes.DWORD),
        ("dwFlags",     ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type",    ctypes.wintypes.DWORD),
        ("_input",  _INPUT_UNION),
    ]


_SendInput = ctypes.windll.user32.SendInput


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_key_input(vk: int, key_up: bool) -> INPUT:
    flags = KEYEVENTF_KEYUP if key_up else KEYEVENTF_KEYDOWN
    inp = INPUT(type=INPUT_KEYBOARD)
    inp._input.ki = KEYBDINPUT(wVk=vk, dwFlags=flags)
    return inp


def _make_mouse_x_input(xbutton: int, button_up: bool) -> INPUT:
    flags = MOUSEEVENTF_XUP if button_up else MOUSEEVENTF_XDOWN
    inp = INPUT(type=INPUT_MOUSE)
    inp._input.mi = MOUSEINPUT(mouseData=xbutton, dwFlags=flags)
    return inp


def _parse_shortcut(shortcut: str) -> tuple[list[int], bool]:
    """
    Parse a shortcut string into (list_of_vk_codes, is_mouse).

    Returns ([], False) for empty / unmapped shortcuts.
    Raises ValueError for unrecognised key names.
    """
    shortcut = shortcut.strip().lower()
    if not shortcut:
        return [], False

    if shortcut == "mouse4":
        return [XBUTTON1], True
    if shortcut == "mouse5":
        return [XBUTTON2], True

    parts = [p.strip() for p in shortcut.split("+")]
    vk_codes: list[int] = []
    for part in parts:
        if part not in VIRTUAL_KEY_MAP:
            raise ValueError(f"Unknown key name: {part!r}")
        vk_codes.append(VIRTUAL_KEY_MAP[part])
    return vk_codes, False


# ── Public API ────────────────────────────────────────────────────────────────

class InputSender:
    """
    Converts shortcut strings to Win32 SendInput calls.

    Caches parsed shortcuts so the hot path (button event → send) does
    no string work at all after the first press.
    """

    def __init__(self) -> None:
        # Cache:  shortcut_string -> (vk_codes, is_mouse)
        self._cache: dict[str, tuple[list[int], bool]] = {}

    def update_mappings(self, mapping: dict[str, str]) -> None:
        """Pre-parse all shortcuts in the current config."""
        self._cache.clear()
        for button, shortcut in mapping.items():
            try:
                self._cache[button] = _parse_shortcut(shortcut)
            except ValueError:
                # Bad shortcut in config – treat as unmapped rather than crash.
                self._cache[button] = ([], False)

    def press(self, button: str) -> None:
        """Send key-down events for the shortcut mapped to button."""
        self._send(button, key_up=False)

    def release(self, button: str) -> None:
        """Send key-up events for the shortcut mapped to button."""
        self._send(button, key_up=True)

    def _send(self, button: str, key_up: bool) -> None:
        parsed = self._cache.get(button)
        if parsed is None:
            return  # button not in mapping
        vk_codes, is_mouse = parsed
        if not vk_codes:
            return  # unmapped

        if is_mouse:
            xbutton = vk_codes[0]
            inputs = [_make_mouse_x_input(xbutton, button_up=key_up)]
        else:
            # Press modifiers first, release them last (reverse order on up).
            if key_up:
                vk_codes = list(reversed(vk_codes))
            inputs = [_make_key_input(vk, key_up=key_up) for vk in vk_codes]

        arr = (INPUT * len(inputs))(*inputs)
        _SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
