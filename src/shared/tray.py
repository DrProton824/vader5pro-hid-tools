"""
Minimal Win32 system tray icon – no extra runtime dependencies.

Why hand-rolled ctypes instead of pystray / infi.systray?
─────────────────────────────────────────────────────────
The rest of this project deliberately keeps its dependency list tiny
(see input_sender.py's docstring on SendInput vs pynput). Shell_NotifyIcon
is a small, extremely stable Win32 API, so wrapping it directly avoids
pulling in a whole packaging-fragile tray library for a couple hundred
lines of code.

Menu rendering
──────────────
The popup menu is owner-drawn (WM_MEASUREITEM / WM_DRAWITEM) instead of
using plain MF_STRING items. A manually created TrackPopupMenu does not
automatically pick up Windows' dark-mode menu theming the way Explorer's
menus do (that requires undocumented uxtheme APIs), so on a dark-themed
desktop the default-themed popup can render with illegible/mismatched
colors. Owning the drawing guarantees the menu is legible regardless of
the user's system theme, and lets it match the rest of the app's palette.

Usage
─────
    icon = TrayIcon(
        tooltip="Vader Remapper",
        icon_path=pathlib.Path("assets/icons/service.ico"),
        menu_items=[("Open Config", open_config), ("Exit", quit_app)],
    )
    icon.update_status(False)   # optional initial state
    icon.run()      # blocks, pumping the Win32 message loop
    # from another thread:
    icon.update_status(True)    # reflect HID connect/disconnect
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
gdi32 = ctypes.windll.gdi32

# ── Win32 constants ───────────────────────────────────────────────────────────

WM_DESTROY = 0x0002
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_MEASUREITEM = 0x002C
WM_DRAWITEM = 0x002B

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x00000000
MF_GRAYED = 0x00000001
MF_DISABLED = 0x00000002
MF_OWNERDRAW = 0x00000100
TPM_RIGHTALIGN = 0x0008
TPM_BOTTOMALIGN = 0x0020
TPM_RETURNCMD = 0x0100

ODT_MENU = 0x00000004
ODS_SELECTED = 0x0001

DT_LEFT = 0x00000000
DT_VCENTER = 0x00000004
DT_SINGLELINE = 0x00000020

IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM
)


def _rgb(r: int, g: int, b: int) -> int:
    """Build a COLORREF (0x00BBGGRR) from R,G,B bytes."""
    return r | (g << 8) | (b << 16)


# Palette mirrors src/config_gui/main.py's C dict, so the tray menu
# reads as part of the same app rather than a bare system menu.
_COLOR_SURFACE = _rgb(0x1A, 0x25, 0x35)
_COLOR_SELECTED = _rgb(0x2A, 0x5A, 0x8A)
_COLOR_TEXT = _rgb(0xC8, 0xD8, 0xE8)
_COLOR_TEXT_SELECTED = _rgb(0xE8, 0xF0, 0xF8)
_COLOR_TEXT_DIM = _rgb(0x5A, 0x7A, 0x9A)


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


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class MEASUREITEMSTRUCT(ctypes.Structure):
    _fields_ = [
        ("CtlType", wt.UINT),
        ("CtlID", wt.UINT),
        ("itemID", wt.UINT),
        ("itemWidth", wt.UINT),
        ("itemHeight", wt.UINT),
        ("itemData", ctypes.c_size_t),
    ]


class DRAWITEMSTRUCT(ctypes.Structure):
    _fields_ = [
        ("CtlType", wt.UINT),
        ("CtlID", wt.UINT),
        ("itemID", wt.UINT),
        ("itemAction", wt.UINT),
        ("itemState", wt.UINT),
        ("hwndItem", wt.HWND),
        ("hDC", wt.HDC),
        ("rcItem", wt.RECT),
        ("itemData", ctypes.c_size_t),
    ]


# AppendMenuW's 4th param is LPCWSTR normally, but for MF_OWNERDRAW items
# it's treated as an opaque application value (ends up in itemData of the
# MEASUREITEMSTRUCT/DRAWITEMSTRUCT). Declare it as a void pointer so we
# can safely pass an integer index instead of a string.
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, ctypes.c_void_p]
user32.AppendMenuW.restype = wt.BOOL

user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC

user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.ReleaseDC.restype = ctypes.c_int

user32.FillRect.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), wt.HBRUSH]
user32.FillRect.restype = ctypes.c_int

user32.DrawTextW.argtypes = [
    wt.HDC, ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(wt.RECT), wt.UINT,
]
user32.DrawTextW.restype = ctypes.c_int

gdi32.GetTextExtentPoint32W.argtypes = [
    wt.HDC, ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(SIZE),
]
gdi32.GetTextExtentPoint32W.restype = wt.BOOL

gdi32.SetBkMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int

gdi32.SetTextColor.argtypes = [wt.HDC, wt.DWORD]
gdi32.SetTextColor.restype = wt.DWORD

gdi32.CreateSolidBrush.argtypes = [wt.DWORD]
gdi32.CreateSolidBrush.restype = wt.HBRUSH

gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = wt.BOOL

user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = wt.HMENU

user32.TrackPopupMenu.argtypes = [
    wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, ctypes.POINTER(wt.RECT),
]
user32.TrackPopupMenu.restype = ctypes.c_int

user32.CreateWindowExW.argtypes = [
    wt.DWORD, ctypes.c_wchar_p, ctypes.c_wchar_p, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p,
]
user32.CreateWindowExW.restype = wt.HWND
user32.RegisterClassW.restype = wt.ATOM
kernel32.GetModuleHandleW.restype = wt.HINSTANCE
user32.LoadImageW.restype = wt.HANDLE
user32.LoadIconW.restype = wt.HICON

class TrayIcon:
    _CLASS_NAME = "VaderRemapperTrayWndClass"

    def __init__(
        self,
        tooltip: str,
        icon_path: Optional[pathlib.Path],
        menu_items: list[tuple[str, Callable[[], None]]],
    ) -> None:
        self._base_tooltip = tooltip
        self._icon_path = icon_path
        self._menu_items = menu_items
        self._hwnd: Optional[int] = None
        self._nid: Optional[NOTIFYICONDATA] = None
        self._running = False
        self._status_line = "Checking connection\u2026"
        self._tooltip = tooltip[:127]
        # Items currently shown in an open popup, used by the
        # measure/draw handlers to look up label + enabled state by index.
        self._current_items: list[tuple[str, Optional[Callable[[], None]]]] = []
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

    def update_status(self, connected: bool) -> None:
        """
        Thread-safe: reflect controller connection state in the tray
        tooltip and the (non-clickable) status line at the top of the menu.
        Safe to call before run() – the values are just cached until the
        icon actually exists.
        """
        self._status_line = (
            "\u25CF Controller connected" if connected else "\u25CB Controller not connected"
        )
        state = "Connected" if connected else "Disconnected"
        self._tooltip = f"{self._base_tooltip} \u2013 {state}"[:127]
        self._update_tooltip()

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
        self._nid = nid
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _remove_icon(self) -> None:
        if self._nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))

    def _update_tooltip(self) -> None:
        if self._nid is None or self._hwnd is None:
            return
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_TIP
        nid.szTip = self._tooltip
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    # ── Menu ──────────────────────────────────────────────────────────────

    def _show_menu(self) -> None:
        items: list[tuple[str, Optional[Callable[[], None]]]] = [
            (self._status_line, None)
        ] + self._menu_items
        self._current_items = items

        hmenu = user32.CreatePopupMenu()
        for i, (_label, callback) in enumerate(items):
            flags = MF_STRING | MF_OWNERDRAW
            if callback is None:
                flags |= MF_DISABLED | MF_GRAYED
            user32.AppendMenuW(hmenu, flags, 1000 + i, ctypes.c_void_p(i))

        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))

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
            if 0 <= index < len(items) and items[index][1] is not None:
                items[index][1]()

    # ── Owner-draw handlers ──────────────────────────────────────────────

    def _measure_text(self, text: str) -> tuple[int, int]:
        hdc = user32.GetDC(None)
        size = SIZE()
        gdi32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))
        user32.ReleaseDC(None, hdc)
        return size.cx + 36, max(size.cy + 12, 24)

    def _on_measure_item(self, lparam: int) -> None:
        mis = ctypes.cast(lparam, ctypes.POINTER(MEASUREITEMSTRUCT)).contents
        if mis.CtlType != ODT_MENU:
            return
        index = mis.itemData
        if 0 <= index < len(self._current_items):
            label = self._current_items[index][0]
        else:
            label = ""
        width, height = self._measure_text(label)
        mis.itemWidth = width
        mis.itemHeight = height

    def _on_draw_item(self, lparam: int) -> None:
        dis = ctypes.cast(lparam, ctypes.POINTER(DRAWITEMSTRUCT)).contents
        if dis.CtlType != ODT_MENU:
            return

        index = dis.itemData
        if 0 <= index < len(self._current_items):
            label, callback = self._current_items[index]
        else:
            label, callback = "", None
        disabled = callback is None
        selected = bool(dis.itemState & ODS_SELECTED) and not disabled

        bg_color = _COLOR_SELECTED if selected else _COLOR_SURFACE
        brush = gdi32.CreateSolidBrush(bg_color)
        user32.FillRect(dis.hDC, ctypes.byref(dis.rcItem), brush)
        gdi32.DeleteObject(brush)

        gdi32.SetBkMode(dis.hDC, 1)  # TRANSPARENT
        if disabled:
            text_color = _COLOR_TEXT_DIM
        elif selected:
            text_color = _COLOR_TEXT_SELECTED
        else:
            text_color = _COLOR_TEXT
        gdi32.SetTextColor(dis.hDC, text_color)

        rect = wt.RECT(
            dis.rcItem.left + 14, dis.rcItem.top,
            dis.rcItem.right - 8, dis.rcItem.bottom,
        )
        user32.DrawTextW(
            dis.hDC, label, -1, ctypes.byref(rect),
            DT_SINGLELINE | DT_VCENTER | DT_LEFT,
        )

    # ── WndProc ──────────────────────────────────────────────────────────

    def _wndproc(self, hwnd, msg, wparam, lparam) -> int:
        if msg == WM_TRAYICON:
            if lparam in (WM_LBUTTONUP, WM_RBUTTONUP):
                self._show_menu()
            return 0
        if msg == WM_MEASUREITEM:
            self._on_measure_item(lparam)
            return 1
        if msg == WM_DRAWITEM:
            self._on_draw_item(lparam)
            return 1
        if msg == WM_DESTROY:
            self._remove_icon()
            self._running = False
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
