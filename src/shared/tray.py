"""
Minimal Win32 system tray icon – no extra runtime dependencies.

Why hand-rolled ctypes instead of pystray / infi.systray?
─────────────────────────────────────────────────────────
The rest of this project deliberately keeps its dependency list tiny
(see input_sender.py's docstring on SendInput vs pynput).  Shell_NotifyIcon
is a small, extremely stable Win32 API, so wrapping it directly avoids
pulling in a whole packaging-fragile tray library for ~150 lines of code.

Usage
─────
    icon = TrayIcon(
        tooltip="Vader Remapper – running",
        icon_path=pathlib.Path("assets/icons/service.ico"),
        menu_items=[("Open Config", open_config), ("Exit", quit_app)],
    )
    icon.run()      # blocks, pumping the Win32 message loop
    # from another thread:
    icon.stop()     # ends run()
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import pathlib
from typing import Callable, Optional

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

# ── Win32 constants ───────────────────────────────────────────────────────────

WM_DESTROY = 0x0002
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205

NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x0000
TPM_RIGHTALIGN = 0x0008
TPM_BOTTOMALIGN = 0x0020
TPM_RETURNCMD = 0x0100

IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM
)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", ctypes.c_wchar * 128),
    ]


class TrayIcon:
    _CLASS_NAME = "VaderRemapperTrayWndClass"

    def __init__(
        self,
        tooltip: str,
        icon_path: Optional[pathlib.Path],
        menu_items: list[tuple[str, Callable[[], None]]],
    ) -> None:
        self._tooltip = tooltip[:127]
        self._icon_path = icon_path
        self._menu_items = menu_items
        self._hwnd: Optional[int] = None
        self._nid: Optional[NOTIFYICONDATA] = None
        self._running = False
        # Keep a reference to the WNDPROC closure alive for the object's
        # lifetime – ctypes does not do this for you, and a garbage
        # collected callback means Windows calls into freed memory.
        self._wndproc_ref = WNDPROC(self._wndproc)

    # ── Public API ────────────────────────────────────────────────────────

    def run(self) -> None:
        """Create the hidden window + tray icon and pump messages. Blocks."""
        self._create_window()
        self._add_icon()
        self._running = True

        msg = wt.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def stop(self) -> None:
        """Thread-safe: request the message loop to exit."""
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)

    # ── Window / icon setup ──────────────────────────────────────────────

    def _create_window(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)

        wc = WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinstance
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = self._CLASS_NAME

        # Ignore failure if the class is already registered (e.g. a
        # previous instance in the same process during testing).
        user32.RegisterClassW(ctypes.byref(wc))

        self._hwnd = user32.CreateWindowExW(
            0, self._CLASS_NAME, "VaderRemapperTray",
            0, 0, 0, 0, 0, None, None, hinstance, None,
        )

    def _load_icon(self) -> int:
        if self._icon_path and self._icon_path.exists():
            hicon = user32.LoadImageW(
                None, str(self._icon_path), IMAGE_ICON, 0, 0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if hicon:
                return hicon
        return user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _add_icon(self) -> None:
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self._load_icon()
        nid.szTip = self._tooltip
        self._nid = nid  # keep alive – Shell_NotifyIcon keeps a copy but
        # we also need it again for NIM_DELETE on shutdown.
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _remove_icon(self) -> None:
        if self._nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))

    # ── Menu ──────────────────────────────────────────────────────────────

    def _show_menu(self) -> None:
        hmenu = user32.CreatePopupMenu()
        for i, (label, _callback) in enumerate(self._menu_items):
            user32.AppendMenuW(hmenu, MF_STRING, 1000 + i, label)

        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        # Required so the menu closes if the user clicks away from it.
        user32.SetForegroundWindow(self._hwnd)
        cmd = user32.TrackPopupMenu(
            hmenu,
            TPM_RIGHTALIGN | TPM_BOTTOMALIGN | TPM_RETURNCMD,
            pt.x, pt.y, 0, self._hwnd, None,
        )
        user32.PostMessageW(self._hwnd, 0, 0, 0)  # nudge to let menu close cleanly
        user32.DestroyMenu(hmenu)

        if cmd >= 1000:
            index = cmd - 1000
            if 0 <= index < len(self._menu_items):
                self._menu_items[index][1]()

    # ── WndProc ──────────────────────────────────────────────────────────

    def _wndproc(self, hwnd, msg, wparam, lparam) -> int:
        if msg == WM_TRAYICON:
            if lparam in (WM_LBUTTONUP, WM_RBUTTONUP):
                self._show_menu()
            return 0
        if msg == WM_DESTROY:
            self._remove_icon()
            self._running = False
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
