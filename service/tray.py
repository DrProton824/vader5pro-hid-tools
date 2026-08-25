#
# service/tray.py
# Minimal Win32 system tray icon for VaderService
#

"""
Why hand-rolled ctypes instead of pystray / infi.systray?
──────────────────────────────────────────────────────────
The rest of this project deliberately keeps its dependency list tiny
(see input_sender.py's docstring on SendInput vs pynput). Shell_NotifyIcon
is a small, extremely stable Win32 API, so wrapping it directly avoids
pulling in a whole packaging-fragile tray library for ~600 lines of code.

Menu rendering
──────────────
An earlier version used TrackPopupMenu with MF_OWNERDRAW items
(WM_MEASUREITEM / WM_DRAWITEM). That API turned out to be unreliable from
ctypes on 64-bit Windows: WM_MEASUREITEM fired and the struct layout was
correct, but Windows ignored the returned item size and fell back to a
near-zero "checkbox only" size, so the popup rendered as a tiny blank square.

Instead, the menu is now a small borderless top-level window that we paint
ourselves (WM_PAINT with GDI FillRect/DrawTextW) and position next to the
tray icon. This sidesteps owner-draw menus entirely, so there's no dependency
on how a particular Windows build chooses to (mis)handle WM_MEASUREITEM. It
also matches the app's palette exactly regardless of the user's system theme.

Palette
───────
Colors mirror the GUI (gui/scripts/ui_utils.py), so the tray menu reads as
part of the same app rather than a bare system menu. Green dot = connected,
red dot = disconnected.

Thread safety
─────────────
update_status() and update_menu_item() are thread-safe: they post messages
to the message loop rather than calling GDI functions directly. Safe to call
before run().

Usage
─────
    icon = TrayIcon(
        tooltip="Vader Remapper",
        icon_path=pathlib.Path("assets/icons/service_connected.ico"),
        disconnected_icon_path=pathlib.Path("assets/icons/service_disconnected.ico"),
        menu_items=[
            ("Open Config", open_config),
            ("Exit", quit_app),
        ],
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
import sys
import traceback
from typing import Callable, Optional

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

# ── Debug logging ─────────────────────────────────────────────────────────────
# The service is built with --noconsole, so stderr / exception tracebacks
# are normally invisible. Route them to a small log file next to the exe
# (or the repo root when running from source) so failures inside a
# WNDPROC callback - which Windows/ctypes would otherwise swallow - are
# actually visible instead of just showing up as "nothing happened".
# Kept to genuine errors only (not per-message spam).
def _log_path() -> pathlib.Path:
    try:
        if getattr(sys, "frozen", False):
            base = pathlib.Path(sys.executable).resolve().parent
        else:
            base = pathlib.Path(__file__).resolve().parents[2]
    except Exception:
        base = pathlib.Path(".")
    return base / "tray_debug.log"


def _log(message: str) -> None:
    if getattr(sys, "frozen", False):
        return
    try:
        with open(_log_path(), "a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except Exception:
        pass


# ── Win32 constants ───────────────────────────────────────────────────────────

WM_DESTROY = 0x0002
WM_NCDESTROY = 0x0082
WM_CLOSE = 0x0010
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_UPDATE_ICON = WM_APP + 2
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDOWN = 0x0201
WM_MOUSEMOVE = 0x0200
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_ACTIVATE = 0x0006
WM_KEYDOWN = 0x0100

WA_INACTIVE = 0
VK_ESCAPE = 0x1B

CS_DROPSHADOW = 0x00020000


class LOGFONTW(ctypes.Structure):
    _fields_ = [
        ("lfHeight", ctypes.c_long),
        ("lfWidth", ctypes.c_long),
        ("lfEscapement", ctypes.c_long),
        ("lfOrientation", ctypes.c_long),
        ("lfWeight", ctypes.c_long),
        ("lfItalic", ctypes.c_byte),
        ("lfUnderline", ctypes.c_byte),
        ("lfStrikeOut", ctypes.c_byte),
        ("lfCharSet", ctypes.c_byte),
        ("lfOutPrecision", ctypes.c_byte),
        ("lfClipPrecision", ctypes.c_byte),
        ("lfQuality", ctypes.c_byte),
        ("lfPitchAndFamily", ctypes.c_byte),
        ("lfFaceName", ctypes.c_wchar * 32),
    ]



# Sentinel used in the items list to render a thin separator line instead
# of a clickable row, matching the header/body split of native context menus.
MENU_SEPARATOR = object()

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

DT_LEFT = 0x00000000
DT_VCENTER = 0x00000004
DT_SINGLELINE = 0x00000020

IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080

SW_SHOWNOACTIVATE = 4

DEFAULT_GUI_FONT = 17
NULL_PEN = 8

# LRESULT/WPARAM/LPARAM are pointer-sized (64-bit) on x64 Windows.
# ctypes.c_long is always 32-bit regardless of platform, so declaring
# a callback's return type as c_long corrupts the upper 32 bits of
# every value it returns to Windows.
LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t

WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wt.HWND, ctypes.c_uint, WPARAM, LPARAM
)


def _rgb(r: int, g: int, b: int) -> int:
    """Build a COLORREF (0x00BBGGRR) from R,G,B bytes."""
    return r | (g << 8) | (b << 16)


# Palette mirrors the GUI's own color scheme (see gui/scripts/ui_utils.py
# and the literal hex values in gui/MainPage.py), so the tray menu reads
# as part of the same app rather than a bare system menu.
_COLOR_SURFACE = _rgb(0x2B, 0x2B, 0x2B)
_COLOR_SELECTED = _rgb(0x35, 0x35, 0x35)   # hover fill, no separate hover text color
_COLOR_TEXT = _rgb(0xF2, 0xF2, 0xF2)
_COLOR_TEXT_DIM = _rgb(0x78, 0x78, 0x78)   # status text + disabled items
_COLOR_BORDER = _rgb(0x3E, 0x3E, 0x3E)
_COLOR_STATUS_ON = _rgb(0x53, 0xD0, 0x10)
_COLOR_STATUS_OFF = _rgb(0x72, 0x2F, 0x35)  # same red as the app's Cancel/Stop buttons


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


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wt.HDC),
        ("fErase", wt.BOOL),
        ("rcPaint", wt.RECT),
        ("fRestore", wt.BOOL),
        ("fIncUpdate", wt.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


# ── ctypes signatures ─────────────────────────────────────────────────────────

user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC

user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.ReleaseDC.restype = ctypes.c_int

user32.FillRect.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), wt.HBRUSH]
user32.FillRect.restype = ctypes.c_int

user32.FrameRect.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), wt.HBRUSH]
user32.FrameRect.restype = ctypes.c_int

user32.DrawTextW.argtypes = [
    wt.HDC, ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(wt.RECT), wt.UINT,
]
user32.DrawTextW.restype = ctypes.c_int

user32.BeginPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wt.HDC

user32.EndPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = wt.BOOL

user32.InvalidateRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT), wt.BOOL]
user32.InvalidateRect.restype = wt.BOOL

user32.DestroyWindow.argtypes = [wt.HWND]
user32.DestroyWindow.restype = wt.BOOL

user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.ShowWindow.restype = wt.BOOL

user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

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

gdi32.SelectObject.argtypes = [wt.HDC, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p

gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = ctypes.c_void_p

gdi32.Ellipse.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.Ellipse.restype = wt.BOOL

gdi32.CreateFontIndirectW.argtypes = [ctypes.c_void_p]
gdi32.CreateFontIndirectW.restype = ctypes.c_void_p

gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p

gdi32.RoundRect.argtypes = [wt.HDC] + [ctypes.c_int] * 6
gdi32.RoundRect.restype = wt.BOOL

gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.CreatePen.restype = ctypes.c_void_p

user32.SetWindowRgn.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
user32.SetWindowRgn.restype = ctypes.c_int


def _create_font(height_px: int, weight: int, face: str = "Segoe UI") -> int:
    lf = LOGFONTW()
    lf.lfHeight = -abs(height_px)
    lf.lfWeight = weight
    lf.lfFaceName = face
    return gdi32.CreateFontIndirectW(ctypes.byref(lf)) or gdi32.GetStockObject(DEFAULT_GUI_FONT)

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

user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT


# ═══════════════════════════════════════════════════════════════════════════
#  Custom-drawn popup menu
#
#  Replaces TrackPopupMenu + MF_OWNERDRAW items, which rendered as a
#  blank/tiny square on this system regardless of what WM_MEASUREITEM
#  returned. This paints its own borderless window instead, so there's
#  nothing left for the OS to silently override.
# ═══════════════════════════════════════════════════════════════════════════

_ITEM_HEIGHT = 42
_STATUS_HEIGHT = 38
_SEPARATOR_HEIGHT = 9
_TEXT_LEFT = 54
_CONTENT_RIGHT_PAD = 11
_MIN_WIDTH = 260
_DOT_LEFT = 30
_DOT_SIZE = 11
_CORNER_RADIUS = 10
NULL_BRUSH = 5
FW_LIGHT = 300
FW_NORMAL = 400

_MENU_CLASS_NAME = "VaderRemapperMenuWndClass"
_menu_class_registered = False
# hwnd -> _MenuPopup, so one shared trampoline WNDPROC can dispatch to
# whichever popup instance actually owns that window.
_menu_instances: dict[int, "_MenuPopup"] = {}


def _menu_wndproc_trampoline(hwnd, msg, wparam, lparam):
    inst = _menu_instances.get(hwnd)
    if inst is not None:
        try:
            return inst._handle_message(msg, wparam, lparam)
        except Exception:
            _log("Exception in menu wndproc:\n" + traceback.format_exc())
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


# Keep this alive for the process lifetime - a garbage collected ctypes
# callback means Windows calls into freed memory.
_menu_trampoline_ref = WNDPROC(_menu_wndproc_trampoline)


def _ensure_menu_class_registered() -> None:
    global _menu_class_registered
    if _menu_class_registered:
        return
    hinstance = kernel32.GetModuleHandleW(None)
    wc = WNDCLASS()
    wc.style = CS_DROPSHADOW
    wc.lpfnWndProc = _menu_trampoline_ref
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = hinstance
    wc.hIcon = None
    wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))
    wc.hbrBackground = None
    wc.lpszMenuName = None
    wc.lpszClassName = _MENU_CLASS_NAME
    user32.RegisterClassW(ctypes.byref(wc))
    _menu_class_registered = True


class _MenuPopup:
    """
    A borderless top-level window that renders as a small dark dropdown
    menu and reports clicks back through per-item callbacks.

    One instance is shown at a time. It destroys itself when an item is
    clicked, Escape is pressed, or it loses activation (click elsewhere).
    """

    def __init__(
        self,
        items: list[tuple[str, Optional[Callable[[], None]], Optional[bool]]],
    ):
        # Each item is (label, callback, status_dot). status_dot is None
        # for ordinary rows/separators, or True/False to draw a small
        # coloured dot before the label (used only for the connection
        # status row) - green for True, red for False.
        self._items = items
        self._hwnd: Optional[int] = None
        self._hot_index = -1
        self._item_rects: list[tuple[int, int, int, int]] = []
        self._width = _MIN_WIDTH
        self._height = 0
        self._font_item = _create_font(17, FW_LIGHT)
        self._font_status = _create_font(15, FW_NORMAL)

    # ── Layout / show ───────────────────────────────────────────────────

    def _measure(self) -> None:
        hdc = user32.GetDC(None)
        max_text_w = 0
        for label, _cb, dot in self._items:
            if label is MENU_SEPARATOR:
                continue
            gdi32.SelectObject(hdc, self._font_status if dot is not None else self._font_item)
            size = SIZE()
            gdi32.GetTextExtentPoint32W(hdc, label, len(label), ctypes.byref(size))
            max_text_w = max(max_text_w, size.cx)
        user32.ReleaseDC(None, hdc)
        self._width = max(_MIN_WIDTH, _TEXT_LEFT + max_text_w + _CONTENT_RIGHT_PAD)

        y = 0
        self._item_rects = []
        for label, _cb, dot in self._items:
            if label is MENU_SEPARATOR:
                row_h = _SEPARATOR_HEIGHT
            elif dot is not None:
                row_h = _STATUS_HEIGHT
            else:
                row_h = _ITEM_HEIGHT

            self._item_rects.append((0, y, self._width, y + row_h))
            y += row_h
        self._height = y

    def show(self, x: int, y: int) -> None:
        _ensure_menu_class_registered()
        self._measure()

        # Anchor like a classic tray context menu (bottom-right of the
        # cursor), clamped so it never runs off the edge of the screen.
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        wx = min(max(x - self._width, 0), max(sw - self._width, 0))
        wy = min(max(y - self._height, 0), max(sh - self._height, 0))

        hinstance = kernel32.GetModuleHandleW(None)
        hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
            _MENU_CLASS_NAME, "VaderRemapperMenu",
            WS_POPUP,
            wx, wy, self._width, self._height,
            None, None, hinstance, None,
        )
        if not hwnd:
            return
            
        region = gdi32.CreateRoundRectRgn(
            0, 0, self._width + 1, self._height + 1, _CORNER_RADIUS, _CORNER_RADIUS
        )
        if region:
            user32.SetWindowRgn(hwnd, region, True)

        self._hwnd = hwnd
        _menu_instances[hwnd] = self

        user32.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL
        user32.SetForegroundWindow(hwnd)

    def _close(self) -> None:
        if self._font_item:
            gdi32.DeleteObject(self._font_item)
            self._font_item = None

        if self._font_status:
            gdi32.DeleteObject(self._font_status)
            self._font_status = None

        if self._hwnd:
            hwnd = self._hwnd
            self._hwnd = None
            _menu_instances.pop(hwnd, None)
            user32.DestroyWindow(hwnd)

    # ── Hit testing ──────────────────────────────────────────────────────

    def _index_at(self, x: int, y: int) -> int:
        for i, (l, t, r, b) in enumerate(self._item_rects):
            if l <= x < r and t <= y < b:
                if self._items[i][0] is MENU_SEPARATOR:
                    return -1
                return i
        return -1

    # ── Message handling ───────────────────────────────────────────────

    def _handle_message(self, msg, wparam, lparam) -> int:
        if msg == WM_PAINT:
            self._on_paint()
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_MOUSEMOVE:
            x = lparam & 0xFFFF
            y = (lparam >> 16) & 0xFFFF
            index = self._index_at(x, y)
            if index != self._hot_index:
                self._hot_index = index
                user32.InvalidateRect(self._hwnd, None, False)
            return 0
        if msg == WM_LBUTTONUP:
            x = lparam & 0xFFFF
            y = (lparam >> 16) & 0xFFFF
            index = self._index_at(x, y)
            callback = None
            if 0 <= index < len(self._items):
                callback = self._items[index][1]
            self._close()
            if callback is not None:
                callback()
            return 0
        if msg == WM_KEYDOWN:
            if wparam == VK_ESCAPE:
                self._close()
            return 0
        if msg == WM_ACTIVATE:
            if (wparam & 0xFFFF) == WA_INACTIVE:
                self._close()
            return 0
        if msg == WM_NCDESTROY:
            return 0
        return user32.DefWindowProcW(self._hwnd, msg, wparam, lparam)

    # ── Drawing ────────────────────────────────────────────────────────

    def _on_paint(self) -> None:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(self._hwnd, ctypes.byref(ps))

        rc = wt.RECT(0, 0, self._width, self._height)
        bg_brush = gdi32.CreateSolidBrush(_COLOR_SURFACE)
        user32.FillRect(hdc, ctypes.byref(rc), bg_brush)
        gdi32.DeleteObject(bg_brush)

        gdi32.SetBkMode(hdc, 1)  # TRANSPARENT

        for i, (label, cb, dot) in enumerate(self._items):
            l, t, r, b = self._item_rects[i]

            if label is MENU_SEPARATOR:
                mid_y = (t + b) // 2
                sep_rc = wt.RECT(l + _CONTENT_RIGHT_PAD, mid_y, r - _CONTENT_RIGHT_PAD, mid_y + 1)
                sep_brush = gdi32.CreateSolidBrush(_COLOR_BORDER)
                user32.FillRect(hdc, ctypes.byref(sep_rc), sep_brush)
                gdi32.DeleteObject(sep_brush)
                continue

            is_status_row = dot is not None
            gdi32.SelectObject(hdc, self._font_status if is_status_row else self._font_item)

            disabled = cb is None and not is_status_row
            selected = (i == self._hot_index) and cb is not None

            if selected:
                item_rc = wt.RECT(l + 7, t + 3, r - 7, b - 3)

                sel_brush = gdi32.CreateSolidBrush(_COLOR_SELECTED)
                old_brush = gdi32.SelectObject(hdc, sel_brush)

                null_pen = gdi32.GetStockObject(NULL_PEN)
                old_pen = gdi32.SelectObject(hdc, null_pen)

                gdi32.RoundRect(hdc, item_rc.left, item_rc.top, item_rc.right,item_rc.bottom, 8, 8)

                gdi32.SelectObject(hdc, old_pen)
                gdi32.SelectObject(hdc, old_brush)

                gdi32.DeleteObject(sel_brush)

            gdi32.SetTextColor(hdc, _COLOR_TEXT_DIM if (disabled or is_status_row) else _COLOR_TEXT)

            text_left = l + _TEXT_LEFT
            if is_status_row:
                dot_color = _COLOR_STATUS_ON if dot else _COLOR_STATUS_OFF
                mid_y = (t + b) // 2
                dot_top = mid_y - _DOT_SIZE // 2
                dot_left = l + _DOT_LEFT
                dot_brush = gdi32.CreateSolidBrush(dot_color)
                dot_pen = gdi32.CreatePen(0, 1, _COLOR_BORDER)  # PS_SOLID
                old_brush = gdi32.SelectObject(hdc, dot_brush)
                old_pen = gdi32.SelectObject(hdc, dot_pen)
                gdi32.Ellipse(hdc, dot_left, dot_top, dot_left + _DOT_SIZE, dot_top + _DOT_SIZE)
                gdi32.SelectObject(hdc, old_pen)
                gdi32.SelectObject(hdc, old_brush)
                gdi32.DeleteObject(dot_brush)
                gdi32.DeleteObject(dot_pen)

            text_rc = wt.RECT(text_left, t, r - _CONTENT_RIGHT_PAD, b)
            user32.DrawTextW(hdc, label, -1, ctypes.byref(text_rc), DT_SINGLELINE | DT_VCENTER | DT_LEFT)

        border_pen = gdi32.CreatePen(0, 1, _COLOR_BORDER)
        old_pen = gdi32.SelectObject(hdc, border_pen)
        old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_BRUSH))
        gdi32.RoundRect(hdc, 0, 0, self._width, self._height, _CORNER_RADIUS, _CORNER_RADIUS)
        gdi32.SelectObject(hdc, old_pen)
        gdi32.SelectObject(hdc, old_brush)
        gdi32.DeleteObject(border_pen)

        user32.EndPaint(self._hwnd, ctypes.byref(ps))


# ═══════════════════════════════════════════════════════════════════════════
#  Tray icon
# ═══════════════════════════════════════════════════════════════════════════

class TrayIcon:
    _CLASS_NAME = "VaderRemapperTrayWndClass"

    def __init__(
        self,
        tooltip: str,
        icon_path: Optional[pathlib.Path],
        disconnected_icon_path: Optional[pathlib.Path] = None,
        menu_items: Optional[list[tuple[str, Callable[[], None]]]] = None,
    ) -> None:
        self._base_tooltip = tooltip
        self._connected_icon_path = icon_path
        self._disconnected_icon_path = disconnected_icon_path
        self._menu_items = menu_items or []
        self._hwnd: Optional[int] = None
        self._nid: Optional[NOTIFYICONDATA] = None
        self._running = False
        self._status_line = "Checking connection\u2026"
        self._status_connected: Optional[bool] = None
        self._tooltip = tooltip[:127]
        self._popup: Optional[_MenuPopup] = None
        self._connected_hicon = None
        self._disconnected_hicon = None
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
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    def update_status(self, connected: bool) -> None:
        """
        Thread-safe?: reflect controller connection state in the tray
        icon and the status line at the top of the menu, which shows a
        small green/red dot (see _MenuPopup._on_paint) rather than a
        plain glyph. The tooltip itself stays static (just the app
        name) — connection state is already conveyed by the icon and
        the menu, so it doesn't need to change too.
        Safe to call before run() – the values are just cached until the
        icon actually exists.
        """
        self._status_line = "Connected" if connected else "Disconnected"
        self._status_connected = connected

        if self._hwnd:
            user32.PostMessageW(
                self._hwnd,
                WM_UPDATE_ICON,
                int(connected),
                0,
            )

    def update_menu_item(self, index: int, label: str) -> None:
        """
        Thread-safe enough for our use (single writer, called from the
        same click handler that owns the toggle): replace a menu item's
        label while keeping its callback, so the next time the menu is
        opened it reflects the new state (e.g. a checkbox-style toggle).
        """
        if 0 <= index < len(self._menu_items):
            _label, callback = self._menu_items[index]
            self._menu_items[index] = (label, callback)
            
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

    def _load_icon(self, path: Optional[pathlib.Path] = None) -> int:
        icon_path = path or self._connected_icon_path

        if icon_path == self._connected_icon_path:
            if self._connected_hicon:
                return self._connected_hicon

        if icon_path == self._disconnected_icon_path:
            if self._disconnected_hicon:
                return self._disconnected_hicon

        if icon_path and icon_path.exists():
            hicon = user32.LoadImageW(
                None, str(icon_path), IMAGE_ICON, 0, 0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )

            if hicon:
                if icon_path == self._connected_icon_path:
                    self._connected_hicon = hicon

                elif icon_path == self._disconnected_icon_path:
                    self._disconnected_hicon = hicon

                return hicon

        return user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _add_icon(self) -> None:
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        if self._status_connected is False and self._disconnected_icon_path:
            nid.hIcon = self._load_icon(self._disconnected_icon_path)
        else:
            nid.hIcon = self._load_icon(self._connected_icon_path)
        nid.szTip = self._tooltip
        self._nid = nid
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _remove_icon(self) -> None:
        if self._nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))

    def _update_icon(self, connected: bool) -> None:
        if self._nid is None:
            return

        icon_path = (
            self._connected_icon_path
            if connected
            else self._disconnected_icon_path
        )

        if icon_path and icon_path.exists():
            hicon = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 
                0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )

            if hicon:
                self._nid.hIcon = hicon
                self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
                shell32.Shell_NotifyIconW(
                    NIM_MODIFY,
                    ctypes.byref(self._nid),
                )

    # ── Menu ──────────────────────────────────────────────────────────────

    def _show_menu(self) -> None:
        # Toggle: if a menu is already open (and still actually alive),
        # a second click just closes it instead of stacking another one.
        if self._popup is not None and self._popup._hwnd is not None:
            self._popup._close()
            self._popup = None
            return

        items: list[tuple[str, Optional[Callable[[], None]], Optional[bool]]] = [
            (self._status_line, None, self._status_connected),
            (MENU_SEPARATOR, None, None),
        ] + [(label, callback, None) for label, callback in self._menu_items]

        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        popup = _MenuPopup(items)
        popup.show(pt.x, pt.y)
        self._popup = popup

    # ── WndProc ──────────────────────────────────────────────────────────

    def _wndproc(self, hwnd, msg, wparam, lparam) -> int:
        try:
            if msg == WM_UPDATE_ICON:
                connected = bool(wparam)

                self._status_line = (
                    "Connected"
                    if connected
                    else "Disconnected"
                )
                self._status_connected = connected

                self._update_icon(connected)

                return 0

            if msg == WM_TRAYICON:
                if lparam in (WM_LBUTTONUP, WM_RBUTTONUP):
                    self._show_menu()
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            
            if msg == WM_DESTROY:
                self._remove_icon()
                self._running = False
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            _log("Exception in _wndproc:\n" + traceback.format_exc())
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
