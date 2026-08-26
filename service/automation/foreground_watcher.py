#
# service/automation/foreground_watcher.py
# Foreground-window based profile automation.
#

"""
Switches profile the moment the assigned program becomes the active
window, using SetWinEventHook(EVENT_SYSTEM_FOREGROUND, ...) instead of
polling the process list. Windows calls back into this thread only when
the foreground window actually changes, so there is no fixed-interval
work at all -- cheaper than a poll loop and reacts immediately, and it
matches automation's actual intent better than "is it merely running":
the profile should be active while the assigned program is the one
being used, not while it's sitting unfocused in the background.

WINEVENT_OUTOFCONTEXT delivers the callback on this thread's own
message queue, so -- same as hotkey_watcher.HotkeyWatcherThread -- it
needs its own dedicated hidden window and GetMessageW loop, and must
not share one with tray.py or the raw input reader.

on_unmatch fires whenever the foreground window changes to something
that isn't one of the watched programs, so callers can revert a
profile that automation applied while that program was focused (see
service/main.py's _revert_foreground_automation). It's a plain
per-event signal, not per-target -- main.py decides whether a revert
is actually needed.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import pathlib
import threading
from typing import Callable, Dict, Optional

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 260

WM_CLOSE = 0x0010
WM_APP = 0x8000
WM_RELOAD = WM_APP + 1

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, ctypes.c_uint, WPARAM, LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None, wt.HANDLE, wt.DWORD, wt.HWND, ctypes.c_long, ctypes.c_long, wt.DWORD, wt.DWORD,
)

user32.SetWinEventHook.argtypes = [
    wt.DWORD, wt.DWORD, wt.HMODULE, WINEVENTPROC, wt.DWORD, wt.DWORD, wt.DWORD,
]
user32.SetWinEventHook.restype = wt.HANDLE
user32.UnhookWinEvent.argtypes = [wt.HANDLE]
user32.UnhookWinEvent.restype = wt.BOOL
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
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
user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
kernel32.GetModuleHandleW.restype = wt.HINSTANCE

kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
    ]


def _basename_of_foreground(hwnd: int) -> Optional[str]:
    """Best-effort: resolve the foreground hwnd to its owning process's
    executable basename. Returns None for anything that can't be
    resolved (elevated/protected processes, the hwnd already gone, ...)
    rather than raising -- a missed match is harmless, a crash isn't."""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(MAX_PATH)
        size = wt.DWORD(MAX_PATH)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return pathlib.Path(buf.value).name.lower()
    finally:
        kernel32.CloseHandle(handle)


class ForegroundWatcherThread(threading.Thread):
    """Calls `on_match(profile_id)` whenever the foreground window
    belongs to a watched program. Call reload() after a config change to
    update what's being watched."""

    _CLASS_NAME = "VaderRemapperForegroundWndClass"

    def __init__(
        self,
        on_match: Callable[[str], None],
        on_unmatch: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(name="ForegroundWatcher", daemon=True)
        self._on_match = on_match
        self._on_unmatch = on_unmatch
        self._hwnd: Optional[int] = None
        self._hook: Optional[int] = None
        self._wndproc_ref = WNDPROC(self._wndproc)
        self._eventproc_ref = WINEVENTPROC(self._on_foreground_event)
        self._lock = threading.Lock()
        self._targets: Dict[str, str] = {}   # basename (lower) -> profile_id
        self._pending: Dict[str, str] = {}

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
            0, self._CLASS_NAME, "VaderRemapperForeground", 0, 0, 0, 0, 0, None, None, hinstance, None,
        )
        if not self._hwnd:
            return

        self._hook = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
            None, self._eventproc_ref, 0, 0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )
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

    def reload(self, exe_by_profile: Dict[str, str]) -> None:
        """exe_by_profile: {profile_id: exe_path}, already filtered to
        automation-enabled profiles with a non-empty exe."""
        with self._lock:
            self._pending = {
                pathlib.Path(exe).name.lower(): profile_id
                for profile_id, exe in exe_by_profile.items() if exe
            }
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_RELOAD, 0, 0)

    def _apply_pending(self) -> None:
        with self._lock:
            self._targets = dict(self._pending)

    def _on_foreground_event(self, hook, event, hwnd, id_object, id_child, thread_id, event_time) -> None:
        if not hwnd:
            return
        try:
            basename = _basename_of_foreground(hwnd)
        except Exception:
            return
        if basename is None:
            return

        with self._lock:
            profile_id = self._targets.get(basename)
        if profile_id:
            try:
                self._on_match(profile_id)
            except Exception:
                pass
        elif self._on_unmatch is not None:
            try:
                self._on_unmatch()
            except Exception:
                pass

    def _wndproc(self, hwnd, msg, wparam, lparam) -> int:
        if msg == WM_RELOAD:
            self._apply_pending()
            return 0
        if msg == WM_CLOSE:
            if self._hook:
                user32.UnhookWinEvent(self._hook)
                self._hook = None
            user32.DestroyWindow(hwnd)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
