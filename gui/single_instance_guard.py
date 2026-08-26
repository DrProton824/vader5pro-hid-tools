#
# gui/single_instance_guard.py
# Single-instance guard for the config GUI, with bring-to-front on repeat launch.
#

"""
Mirrors service/single_instance.py's named-mutex approach (see that module's
docstring for why a mutex over a lock file), under its own mutex name so the
GUI and the service guard independently.

Unlike the service - which just shows a message box and exits when already
running - a second GUI launch should feel like clicking the taskbar icon:
locate the existing window by its title and bring it to the foreground
instead of doing nothing or showing an error.

Argtypes/restype are declared explicitly on every user32 call below - same
reasoning as tray.py's LRESULT/WPARAM/LPARAM comment: HWND is pointer-sized
(8 bytes on x64), and ctypes silently truncates it to a 32-bit int for any
call left without a declared argtype.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from typing import Optional

from service import single_instance

MUTEX_NAME = "VaderRemapperConfig"

# Matched as a prefix, not exact equality, so the version suffix appended
# to the window title (see MainPage.py's APP_TITLE) doesn't break the lookup.
WINDOW_TITLE_MARKER = "Vader5Mapper"

SW_RESTORE = 9

LPARAM = ctypes.c_ssize_t
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, LPARAM)

try:
    user32 = ctypes.windll.user32
    user32.EnumWindows.argtypes = [WNDENUMPROC, LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsIconic.argtypes = [wt.HWND]
    user32.IsIconic.restype = wt.BOOL
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wt.BOOL
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.SetForegroundWindow.restype = wt.BOOL
except AttributeError:
    user32 = None  # not on Windows


def _find_existing_window() -> Optional[int]:
    if user32 is None:
        return None

    found = {"hwnd": None}

    def _enum_proc(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value.strip().startswith(WINDOW_TITLE_MARKER):
            found["hwnd"] = hwnd
            return False
        return True

    user32.EnumWindows(WNDENUMPROC(_enum_proc), 0)
    return found["hwnd"]


def _bring_to_front(hwnd: int) -> None:
    if user32 is None:
        return
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)


def ensure_single_instance() -> bool:
    """
    Returns True if this process should continue starting up.

    Returns False if another instance is already running - the existing
    window has been brought to the foreground (best-effort) and the
    caller should exit immediately without creating a second window.
    """
    if single_instance.acquire(MUTEX_NAME):
        return True

    hwnd = _find_existing_window()
    if hwnd is not None:
        try:
            _bring_to_front(hwnd)
        except Exception:
            pass
    return False
