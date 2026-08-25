#
# service/automation/hotkey_watcher.py
# Global hotkey listener for profile automation.
#

"""
Uses the Win32 RegisterHotKey API instead of a low-level keyboard hook
(the approach macros.py's `keyboard` module uses for GUI-side macro
recording). RegisterHotKey only asks Windows to notify this thread when
a specific modifier+key combo fires -- it never sees other keystrokes,
so it carries none of the "watches every keypress" surface a global
hook does. That keeps it both cheap (a handful of WM_HOTKEY messages a
day, not a callback per key) and unlikely to trip antivirus/EDR
heuristics that watch for keylogger-style hooks.

Runs its own hidden window and message loop on a dedicated thread, same
pattern as rawinput_reader.RawInputReaderThread -- it must not share a
loop with tray.py or the raw input reader.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from typing import Callable, Dict, Optional, Tuple

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_HOTKEY = 0x0312
WM_CLOSE = 0x0010
WM_APP = 0x8000
WM_RELOAD = WM_APP + 1

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

MODIFIER_VALUES = {"Ctrl": MOD_CONTROL, "Alt": MOD_ALT, "Shift": MOD_SHIFT, "Win": MOD_WIN}

# Maps the exact label strings gui/scripts/ui_utils.py's
# bind_hotkey_capture produces (see _KEYSYM_LABELS / _hotkey_label) to
# virtual-key codes. Keep in sync if that label table changes.
VK_MAP: Dict[str, int] = {
    "Esc": 0x1B, "Enter": 0x0D, "Space": 0x20,
    "Left": 0x25, "Right": 0x27, "Up": 0x26, "Down": 0x28,
    "Delete": 0x2E, "Backspace": 0x08, "Tab": 0x09,
    "PageUp": 0x21, "PageDown": 0x22, "Home": 0x24, "End": 0x23,
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    **{f"F{n}": 0x6F + n for n in range(1, 25)},
}

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, ctypes.c_uint, WPARAM, LPARAM)

user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wt.BOOL
user32.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.DestroyWindow.argtypes = [wt.HWND]
user32.DestroyWindow.restype = wt.BOOL
user32.CreateWindowExW.argtypes = [
    wt.DWORD, ctypes.c_wchar_p, ctypes.c_wchar_p, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p,
]
user32.CreateWindowExW.restype = wt.HWND
user32.RegisterClassW.restype = wt.ATOM
kernel32.GetModuleHandleW.restype = wt.HINSTANCE
user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
    ]


def parse_hotkey(text: str) -> Optional[Tuple[int, int]]:
    """Parse a ui_utils-captured hotkey string ("Ctrl+Alt+P") into
    (modifiers, vk). Returns None for anything RegisterHotKey can't
    take -- e.g. a bare modifier alone, or an unrecognised key label."""
    parts = [p for p in text.split("+") if p]
    if not parts:
        return None
    modifiers = 0
    vk = None
    for part in parts:
        if part in MODIFIER_VALUES:
            modifiers |= MODIFIER_VALUES[part]
        elif vk is None:
            vk = VK_MAP.get(part)
    if vk is None:
        return None
    return modifiers | MOD_NOREPEAT, vk


class HotkeyWatcherThread(threading.Thread):
    """Watches for WM_HOTKEY and calls `on_trigger(profile_id)` when a
    registered profile hotkey fires. Call reload() after a config change
    (hotkey added/removed/renamed) to re-register."""

    _CLASS_NAME = "VaderRemapperHotkeyWndClass"

    def __init__(self, on_trigger: Callable[[str], None]) -> None:
        super().__init__(name="HotkeyWatcher", daemon=True)
        self._on_trigger = on_trigger
        self._hwnd: Optional[int] = None
        self._wndproc_ref = WNDPROC(self._wndproc)
        self._hotkeys: Dict[int, str] = {}   # hotkey id -> profile_id
        self._pending: Dict[str, str] = {}   # profile_id -> hotkey text

    def run(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        wc = WNDCLASS()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinstance
        wc.lpszClassName = self._CLASS_NAME
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom and ctypes.get_last_error() != 1410:  # ERROR_CLASS_ALREADY_EXISTS
            return

        self._hwnd = user32.CreateWindowExW(
            0, self._CLASS_NAME, "VaderRemapperHotkeys", 0, 0, 0, 0, 0, None, None, hinstance, None,
        )
        if not self._hwnd:
            return
        self._apply_pending()

        msg = wt.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    def reload(self, hotkeys_by_profile: Dict[str, str]) -> None:
        """hotkeys_by_profile: {profile_id: hotkey_text}, already
        filtered to automation-enabled profiles with a non-empty hotkey."""
        self._pending = dict(hotkeys_by_profile)
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_RELOAD, 0, 0)

    def _apply_pending(self) -> None:
        for hotkey_id in list(self._hotkeys):
            user32.UnregisterHotKey(self._hwnd, hotkey_id)
        self._hotkeys = {}

        hotkey_id = 1
        for profile_id, text in self._pending.items():
            parsed = parse_hotkey(text)
            if parsed is None:
                continue
            modifiers, vk = parsed
            # Fails silently if the combo is already claimed globally by
            # another app -- there's no good recovery besides "don't crash".
            if user32.RegisterHotKey(self._hwnd, hotkey_id, modifiers, vk):
                self._hotkeys[hotkey_id] = profile_id
            hotkey_id += 1

    def _wndproc(self, hwnd, msg, wparam, lparam) -> int:
        if msg == WM_HOTKEY:
            profile_id = self._hotkeys.get(wparam)
            if profile_id:
                try:
                    self._on_trigger(profile_id)
                except Exception:
                    pass
            return 0
        if msg == WM_RELOAD:
            self._apply_pending()
            return 0
        if msg == WM_CLOSE:
            for hotkey_id in list(self._hotkeys):
                user32.UnregisterHotKey(self._hwnd, hotkey_id)
            user32.DestroyWindow(hwnd)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
