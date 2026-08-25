#
# service/hid_interface/rawinput_reader.py
# Raw Input based HID reader thread.
#

"""
Why Windows Raw Input instead of hidapi?
─────────────────────────────────────────
hidapi's blocking device.read() consumes reports from the HID interface,
which can race with other readers such as Flydigi SpaceStation. In
practice this caused competing readers to miss packets or starve each
other.

Windows Raw Input (RegisterRawInputDevices / WM_INPUT) is a broadcast
model: every registered process receives its own copy of reports. This
avoids read contention, requires no polling loop, and the thread sleeps
at zero CPU usage while waiting in the normal Win32 message loop.

Raw Input is read-only, so vendor initialization and shutdown commands
still use a short-lived hidapi write-only open/write/close. These rare
writes do not compete with report delivery like a blocking read does.

Connection model
────────────────
- The vendor HID interface (VID/PID, usage page 0xFFA0, usage 1) exists
  while the USB dongle is connected, even if the controller is off.
  WM_INPUT_DEVICE_CHANGE therefore tracks the dongle, not controller
  power state.
- The controller is considered connected only after actual traffic is
  received. Initial traffic is typically status/heartbeat reports,
  followed by periodic heartbeats.
- After first traffic following a disconnect, vendor initialization is
  delayed by VENDOR_INIT_DELAY_SECONDS using a non-blocking Win32 timer.
  Sending immediately was unreliable (validated in tools/hid_handshake.py).
- If the dongle interface disappears, the connection state is cleared
  and initialization is armed again for the next real controller traffic.
"""


from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import pathlib
import sys
import threading
import time
import traceback
from typing import Callable, Optional
from datetime import datetime

from .constants import DEBOUNCE_SECONDS, PRODUCT_ID, USAGE_PAGE, VENDOR_ID
from .hid_protocol import ButtonEvent, ButtonPressed, ButtonReleased, decode_report
from .vendor_init import (
    find_vendor_interface_path,
    send_init_sequence,
    send_stop_sequence,
)

EventCallback = Callable[[ButtonEvent], None]

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


# ── Debug logging ────────────────────────────────────────────────────────────
# Default behaviour:
#   - Running from python: print to console only
#   - Frozen exe: no console, no file logging

DEBUG_FILE_LOGGING = False
_CONSOLE_RAW_LINE_ACTIVE = False
_CONSOLE_RAW_LINE_LENGTH = 0

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
    global _CONSOLE_RAW_LINE_ACTIVE, _CONSOLE_RAW_LINE_LENGTH

    line = f"{datetime.now():%H:%M:%S} {message}"

    # Source run: visible console debugging
    if not getattr(sys, "frozen", False):
        # Raw input uses \r to stay on one live line.
        # Break that line before printing normal messages.
        if _CONSOLE_RAW_LINE_ACTIVE:
            print()
            _CONSOLE_RAW_LINE_ACTIVE = False
            _CONSOLE_RAW_LINE_LENGTH = 0

        print(line)

    # Disabled by default. Only enable manually for troubleshooting.
    if DEBUG_FILE_LOGGING:
        try:
            with open(_log_path(), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass
          

# ── Win32 constants ───────────────────────────────────────────────────────────

WM_INPUT = 0x00FF
WM_INPUT_DEVICE_CHANGE = 0x00FE
WM_TIMER = 0x0113
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002

GIDC_ARRIVAL = 1
GIDC_REMOVAL = 2

RIDEV_INPUTSINK = 0x00000100
RIDEV_DEVNOTIFY = 0x00002000

# In some situations, the vendor interface (0xFFA0, 0x0001)
# stays silent until its initialization sequence runs. 
# Watching (0x01, 0x05) breaks this startup deadlock.
# Button reports are still decoded only from (0xFFA0, 0x0001)
# (0x01, 0x05) is used solely for connection detection.
GENERIC_GAMEPAD_USAGE_PAGE = 0x01
GENERIC_GAMEPAD_USAGE = 0x05

RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007

# How long to wait after first seeing real controller traffic before
# sending the vendor initialization sequence. Sending immediately on the first
# report was unreliable in testing; kept mid-range of the validated
# 5-10s window.
VENDOR_INIT_DELAY_SECONDS = 5
_VENDOR_INIT_TIMER_ID = 1

_TARGET_VID_TAG = f"VID_{VENDOR_ID:04X}"
_TARGET_PID_TAG = f"PID_{PRODUCT_ID:04X}"

# LRESULT/WPARAM/LPARAM are pointer-sized on x64 Windows -- see the
# identical note in tray.py. Getting this wrong corrupts the upper 32
# bits of every value passed to/from Windows.
LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, ctypes.c_uint, WPARAM, LPARAM)


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wt.USHORT),
        ("usUsage", wt.USHORT),
        ("dwFlags", wt.DWORD),
        ("hwndTarget", wt.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wt.DWORD),
        ("dwSize", wt.DWORD),
        ("hDevice", wt.HANDLE),
        ("wParam", WPARAM),
    ]


class RAWHID(ctypes.Structure):
    _fields_ = [
        ("dwSizeHid", wt.DWORD),
        ("dwCount", wt.DWORD),
    ]


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


user32.RegisterRawInputDevices.argtypes = [
    ctypes.POINTER(RAWINPUTDEVICE), ctypes.c_uint, ctypes.c_uint,
]
user32.RegisterRawInputDevices.restype = wt.BOOL

user32.GetRawInputData.argtypes = [
    wt.HANDLE, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.c_uint,
]
user32.GetRawInputData.restype = ctypes.c_uint

user32.GetRawInputDeviceInfoW.argtypes = [
    wt.HANDLE, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint),
]
user32.GetRawInputDeviceInfoW.restype = ctypes.c_uint

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

user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wt.BOOL

class RawInputReaderThread(threading.Thread):
    """
    Drop-in replacement for HIDReaderThread with the same public API
    (constructor, start(), stop(), join()) but backed by Windows Raw
    Input instead of a blocking hidapi read loop.

    Runs its own hidden window and Win32 message loop on this thread --
    it must not share a window/message loop with anything else (e.g.
    tray.py's TrayIcon), so each gets its own.
    """

    _CLASS_NAME = "VaderRemapperRawInputWndClass"

    def __init__(
        self,
        callback: EventCallback,
        on_connection_change: Optional[Callable[[bool], None]] = None,
        send_vendor_initialization: bool = True,
    ) -> None:
        super().__init__(name="RawInputReader", daemon=True)
        self._callback = callback
        self._on_connection_change = on_connection_change
        self._vendor_init_enabled = send_vendor_initialization
        self._hwnd: Optional[int] = None
        self._wndproc_ref = WNDPROC(self._wndproc)
        self._connected = False
        self._vendor_init_armed = False  # timer currently pending

        # Debounce state -- identical logic to HIDReaderThread._emit_deltas.
        self._previous: frozenset[str] = frozenset()
        self._debounced: set[str] = set()
        self._last_change: dict[str, float] = {}

        # Per-hDevice VID/PID verification cache -- avoids a string
        # lookup on every single WM_INPUT once the controller is
        # streaming at high rate.
        self._verified_devices: set[int] = set()
        self._rejected_devices: set[int] = set()
        self._present_devices: set[int] = set()

        # Per-hDevice running counters and timestamps for (0xFFA0) and (0x01/0x05)
        self._raw_input_data: dict[int, tuple[int, datetime]] = {}
        self._device_labels: dict[int, str] = {}

    # ── Public API (matches HIDReaderThread) ─────────────────────────────────

    def stop(self) -> None:
        """Thread-safe: request the message loop to exit."""
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    # ── Thread body ───────────────────────────────────────────────────────────

    def run(self) -> None:
        if not self._create_window():
            _log("RawInputReader: failed to create hidden window")
            return

        if not self._register_raw_input():
            _log("RawInputReader: RegisterRawInputDevices failed")
            user32.DestroyWindow(self._hwnd)
            return

        msg = wt.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    # ── Window / registration setup ──────────────────────────────────────────

    def _create_window(self) -> bool:
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
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            # ERROR_CLASS_ALREADY_EXISTS is okay
            if ctypes.get_last_error() != 1410:
                return False

        self._hwnd = user32.CreateWindowExW(
            0, self._CLASS_NAME, "VaderRemapperRawInput",
            0, 0, 0, 0, 0, None, None, hinstance, None,
        )
        return bool(self._hwnd)

    def _register_raw_input(self) -> bool:
        devices = (RAWINPUTDEVICE * 2)(
            RAWINPUTDEVICE(
                usUsagePage=USAGE_PAGE,
                usUsage=0x0001,
                dwFlags=RIDEV_INPUTSINK | RIDEV_DEVNOTIFY,
                hwndTarget=self._hwnd,
            ),
            RAWINPUTDEVICE(
                usUsagePage=GENERIC_GAMEPAD_USAGE_PAGE,
                usUsage=GENERIC_GAMEPAD_USAGE,
                dwFlags=RIDEV_INPUTSINK | RIDEV_DEVNOTIFY,
                hwndTarget=self._hwnd,
            ),
        )
        return bool(
            user32.RegisterRawInputDevices(devices, 2, ctypes.sizeof(RAWINPUTDEVICE))
        )

    # ── Connection bookkeeping ───────────────────────────────────────────────

    def _set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        self._connected = connected
        if self._on_connection_change:
            try:
                self._on_connection_change(connected)
            except Exception:
                pass

    def _arm_vendor_init_timer(self) -> None:
        if self._vendor_init_armed or not self._vendor_init_enabled:
            return
        self._vendor_init_armed = True
        user32.SetTimer(self._hwnd, _VENDOR_INIT_TIMER_ID, int(VENDOR_INIT_DELAY_SECONDS * 1000), None)
        _log(f"Vendor initialization scheduled in {VENDOR_INIT_DELAY_SECONDS}s")

    def _disarm_vendor_init_timer(self, cancelled: bool = False) -> None:
        if not self._vendor_init_armed:
            return
        self._vendor_init_armed = False
        user32.KillTimer(self._hwnd, _VENDOR_INIT_TIMER_ID)

        if cancelled:
            _log("Vendor initialization cancelled")

    def _send_vendor_initialization(self) -> None:
        path = find_vendor_interface_path()
        if path is None:
            _log("Vendor initialization interface not found")
            return
        send_init_sequence(path)
        _log("Vendor initialization sequence sent")

    def _send_vendor_stop(self) -> None:
        if not self._vendor_init_enabled:
            return
        path = find_vendor_interface_path()
        if path is None:
            _log("Vendor initialization interface not found")
            return
        send_stop_sequence(path)
        _log("Vendor stop sequence sent")

    # ── Device identity check (cached per hDevice) ───────────────────────────

    def _is_target_device(self, hdevice) -> bool:
        key = int(hdevice) if hdevice else 0
        if key in self._verified_devices:
            return True
        if key in self._rejected_devices:
            return False

        size = ctypes.c_uint(0)
        user32.GetRawInputDeviceInfoW(hdevice, RIDI_DEVICENAME, None, ctypes.byref(size))
        ok = False
        if size.value:
            buf = ctypes.create_unicode_buffer(size.value)
            result = user32.GetRawInputDeviceInfoW(
                hdevice, RIDI_DEVICENAME, buf, ctypes.byref(size)
            )
            if result != 0xFFFFFFFF:
                name = buf.value.upper()
                ok = _TARGET_VID_TAG in name and _TARGET_PID_TAG in name

        (self._verified_devices if ok else self._rejected_devices).add(key)
        return ok

    def _get_device_label(self, hdevice) -> str:
        """Get a short label from the device path, e.g. 'VID_0C12&PID_1E10&MI_03'."""
        size = ctypes.c_uint(0)
        user32.GetRawInputDeviceInfoW(hdevice, RIDI_DEVICENAME, None, ctypes.byref(size))
        if size.value:
            buf = ctypes.create_unicode_buffer(size.value)
            if user32.GetRawInputDeviceInfoW(hdevice, RIDI_DEVICENAME, buf, ctypes.byref(size)) != 0xFFFFFFFF:
                parts = buf.value.split("#")
                if len(parts) > 1:
                    return parts[1]
        return str(int(hdevice) if hdevice else 0)

    # ── WM_INPUT handling ─────────────────────────────────────────────────────
    def _log_raw_input(self, hdevice) -> None:
        if getattr(sys, "frozen", False):
            return

        global _CONSOLE_RAW_LINE_ACTIVE, _CONSOLE_RAW_LINE_LENGTH

        key = int(hdevice) if hdevice else 0
        now = datetime.now()

        if key not in self._device_labels:
            self._device_labels[key] = self._get_device_label(hdevice)

        old_count, _ = self._raw_input_data.get(key, (0, now))
        self._raw_input_data[key] = (old_count + 1, now)

        text = " | ".join(
            f"{timestamp:%H:%M:%S} Raw input from {self._device_labels.get(device, str(device))} x{count}"
            for device, (count, timestamp) in sorted(self._raw_input_data.items())
        )

        try:
            max_width = min(os.get_terminal_size().columns - 1, len(text))
        except OSError:
            max_width = len(text)

        truncated = text[:max_width]
        padding = " " * max(0, _CONSOLE_RAW_LINE_LENGTH - max_width)

        print(
            f"\r{truncated}{padding}",
            end="",
            flush=True,
        )

        _CONSOLE_RAW_LINE_LENGTH = max_width
        _CONSOLE_RAW_LINE_ACTIVE = True


    def _end_raw_input_line(self) -> None:
        global _CONSOLE_RAW_LINE_ACTIVE, _CONSOLE_RAW_LINE_LENGTH

        if not _CONSOLE_RAW_LINE_ACTIVE:
            return

        if not getattr(sys, "frozen", False):
            print()

        if DEBUG_FILE_LOGGING:
            for device, (count, timestamp) in self._raw_input_data.items():
                _log(f"Raw input from {device} x{count}")

        _CONSOLE_RAW_LINE_ACTIVE = False
        _CONSOLE_RAW_LINE_LENGTH = 0
        self._raw_input_data.clear()
        self._device_labels.clear()
  
    def _handle_input(self, lparam) -> None:
        size = ctypes.c_uint(0)
        user32.GetRawInputData(
            lparam, RID_INPUT, None, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)
        )
        if not size.value:
            return

        buf = ctypes.create_string_buffer(size.value)
        copied = user32.GetRawInputData(
            lparam, RID_INPUT, buf, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)
        )
        if copied != size.value:
            return

        raw = buf.raw
        header = RAWINPUTHEADER.from_buffer_copy(raw)
        self._log_raw_input(header.hDevice)

        if not self._is_target_device(header.hDevice):
            return

        header_size = ctypes.sizeof(RAWINPUTHEADER)
        hid_data = raw[header_size:]
        if len(hid_data) < ctypes.sizeof(RAWHID):
            return
        hid_header = RAWHID.from_buffer_copy(hid_data)
        offset = ctypes.sizeof(RAWHID)
        # Drop GetRawInputData's report-ID byte (0x00 unnumbered reports) to
        # match hidapi's Windows-stripped framing used by decode_report()/BUTTON_BITS.
        report = hid_data[offset + 1:offset + hid_header.dwSizeHid]

        # Traffic from the vendor interface indicates the controller is
        # connected. Interface presence alone is insufficient because the
        # dongle enumerates even while the controller is powered off.
        if not self._connected:
            self._set_connected(True)
            _log("Controller detected")
            self._arm_vendor_init_timer()

        try:
            current = decode_report(bytes(report))
        except Exception:
            return
        if current is None:
            return
        self._emit_deltas(current)

    def _emit_deltas(self, current: frozenset[str]) -> None:
        # Identical logic to HIDReaderThread._emit_deltas.
        now = time.monotonic()
        changed = current.symmetric_difference(self._previous)

        for button in changed:
            last = self._last_change.get(button, 0.0)
            if now - last < DEBOUNCE_SECONDS:
                continue

            self._last_change[button] = now

            is_pressed = button in current
            was_pressed = button in self._debounced

            if is_pressed and not was_pressed:
                self._debounced.add(button)
                self._callback(ButtonPressed(button))
            elif not is_pressed and was_pressed:
                self._debounced.discard(button)
                self._callback(ButtonReleased(button))

        self._previous = current

    # ── WM_INPUT_DEVICE_CHANGE handling ──────────────────────────────────────

    def _handle_device_change(self, wparam, lparam) -> None:
        key = int(lparam) if lparam else 0

        if wparam == GIDC_ARRIVAL:
            if self._is_target_device(lparam):
                was_empty = not self._present_devices
                self._present_devices.add(key)
                if was_empty:
                    _log("Dongle detected")
            return

        if wparam == GIDC_REMOVAL:
            if key not in self._present_devices:
                return
            self._present_devices.discard(key)
            # Re-arm so the next real traffic (after reconnect) waits out
            # the vendor initialization delay again, same as a fresh connect.
            self._verified_devices.discard(key)
            self._rejected_devices.discard(key)
            if not self._present_devices:
                self._end_raw_input_line()
                self._set_connected(False)
                _log("Dongle removed")
                self._disarm_vendor_init_timer(cancelled=True)
                self._previous = frozenset()
                self._debounced.clear()
                self._raw_input_data.clear()
                self._device_labels.clear()

    # ── WndProc ──────────────────────────────────────────────────────────────

    def _wndproc(self, hwnd, msg, wparam, lparam) -> int:
        try:
            if msg == WM_INPUT:
                self._handle_input(lparam)
                return 0
            if msg == WM_INPUT_DEVICE_CHANGE:
                self._handle_device_change(wparam, lparam)
                return 0
            if msg == WM_TIMER:
                if wparam == _VENDOR_INIT_TIMER_ID:
                    self._disarm_vendor_init_timer()
                    self._send_vendor_initialization()
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                self._end_raw_input_line()
                self._disarm_vendor_init_timer()
                self._send_vendor_stop()
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            _log("Exception in RawInputReader wndproc:\n" + traceback.format_exc())
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
