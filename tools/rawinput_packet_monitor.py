# ============================================================
# HID Raw Input listener
#
# Device:
#   Flydigi Vader HID interface
#
# Captures Windows Raw Input reports from:
#   Usage Page : 0xFFA0
#   Usage      : 0x0001
#
# ============================================================

import ctypes
import ctypes.wintypes as wintypes
import win32gui
import time
from datetime import datetime


# ============================================================
# CONFIGURATION
# ============================================================

DEVICE_NAME = "Flydigi Vader HID"

TARGET_DEVICES = [
    ("VID_37D7", "PID_2401"),  # Vader 5 Pro Receiver
]

RIDI_DEVICENAME = 0x20000007

# Interface 0
# Standard HID Gamepad collection (xbox 360)
# USAGE_PAGE = 0x01
# USAGE = 0x05

# Interface 1
# Flydigi proprietary vendor HID command channel
USAGE_PAGE = 0xFFA0
USAGE = 0x0001

# Interface 2
# Secondary HID collection
# USAGE_PAGE = 0x01
# USAGE = 0x02

# Filter Packages as bytes([...]), deactivated by default
FILTER_ENABLE = False
FILTERED_PACKETS = []

SHOW_TIMESTAMP = True
SHOW_LENGTH = False

PAUSE_AFTER_EXIT = True

# ============================================================
# WINDOWS CONSTANTS
# ============================================================

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003

RIDEV_INPUTSINK = 0x00000100
RIDEV_DEVNOTIFY = 0x00002000

user32 = ctypes.windll.user32

# ============================================================
# STRUCTURES
# ============================================================

class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]

class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]

class RAWHID(ctypes.Structure):
    _fields_ = [
        ("dwSizeHid", wintypes.DWORD),
        ("dwCount", wintypes.DWORD),
    ]

# ============================================================
# DEVICE IDENTIFICATION
# ============================================================

def is_flydigi_device(hDevice):

    size = wintypes.UINT(0)

    user32.GetRawInputDeviceInfoW(
        hDevice,
        RIDI_DEVICENAME,
        None,
        ctypes.byref(size)
    )

    if size.value == 0:
        return False

    buffer = ctypes.create_unicode_buffer(size.value)

    result = user32.GetRawInputDeviceInfoW(
        hDevice,
        RIDI_DEVICENAME,
        buffer,
        ctypes.byref(size)
    )

    if result == -1:
        return False

    path = buffer.value.upper()

    for vid, pid in TARGET_DEVICES:
        if vid in path and pid in path:
            return True

    return False

# ============================================================
# RAW INPUT REGISTRATION
# ============================================================

def register_raw_input(hwnd):

    rid = RAWINPUTDEVICE(
        USAGE_PAGE,
        USAGE,
        RIDEV_INPUTSINK | RIDEV_DEVNOTIFY,
        hwnd
    )

    result = user32.RegisterRawInputDevices(
        ctypes.byref(rid),
        1,
        ctypes.sizeof(rid)
    )

    if not result:
        raise RuntimeError("RegisterRawInputDevices failed")

# ============================================================
# EXTRACT HID REPORT
# ============================================================

def get_hid_report(lparam):

    size = wintypes.UINT(0)

    user32.GetRawInputData(
        lparam,
        RID_INPUT,
        None,
        ctypes.byref(size),
        ctypes.sizeof(RAWINPUTHEADER)
    )

    buffer = ctypes.create_string_buffer(size.value)

    user32.GetRawInputData(
        lparam,
        RID_INPUT,
        buffer,
        ctypes.byref(size),
        ctypes.sizeof(RAWINPUTHEADER)
    )

    raw = buffer.raw
    header = RAWINPUTHEADER.from_buffer_copy(raw)

    header_size = ctypes.sizeof(RAWINPUTHEADER)

    hid_data = raw[header_size:]

    if len(hid_data) < ctypes.sizeof(RAWHID):
        return None

    hid_header = RAWHID.from_buffer_copy(hid_data)

    offset = ctypes.sizeof(RAWHID)

    return header, hid_data[offset:offset + hid_header.dwSizeHid]

# ============================================================
# FILTERING
# ============================================================

def should_filter(data):

    if not FILTER_ENABLE:
        return False

    for packet in FILTERED_PACKETS:
        if data == packet:
            return True

    return False

# ============================================================
# DISPLAY
# ============================================================

def print_packet(data):

    if should_filter(data):
        return

    output = []

    if SHOW_TIMESTAMP:
        output.append(
            "[" + datetime.now().strftime("%H:%M:%S.%f")[:-3] + "]"
        )

    if SHOW_LENGTH:
        output.append(f"LEN={len(data)}")

    output.append(" ".join(f"{b:02X}" for b in data))

    print(" ".join(output))

# ============================================================
# WINDOW PROCEDURE
# ============================================================

def wndproc(hwnd, msg, wparam, lparam):

    try:
        if msg == WM_INPUT:

            result = get_hid_report(lparam)

            if result:

                header, report = result

                if is_flydigi_device(header.hDevice):
                    print_packet(report)

    except Exception as e:
        print("RAW INPUT ERROR:", e)

    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

# ============================================================
# MAIN
# ============================================================

def main():

    wc = win32gui.WNDCLASS()
    wc.lpfnWndProc = wndproc
    wc.lpszClassName = "RawHIDMonitor"

    atom = win32gui.RegisterClass(wc)

    hwnd = win32gui.CreateWindow(
        atom, "Raw HID Monitor",
        0, 0, 0, 0, 0, 0, 0, 0,
        None
    )

    register_raw_input(hwnd)

    print()
    print("=" * 45)
    print(" RAW INPUT HID MONITOR")
    print("=" * 45)
    print(f"Device target : {DEVICE_NAME}")
    print(f"Usage Page    : 0x{USAGE_PAGE:04X}")
    print(f"Usage         : 0x{USAGE:04X}")
    print(f"Packet filter : {'enabled' if FILTER_ENABLE else 'disabled'}")
    print("=" * 45)
    print()
    print("Waiting for HID reports...")
    print("CTRL+C stops capture.")
    print()

    try:
        while True:
            win32gui.PumpWaitingMessages()
            time.sleep(0.01)

    except KeyboardInterrupt:
        print()
        print("Stopping capture.")

    if PAUSE_AFTER_EXIT:
        input("Press ENTER to close...")


if __name__ == "__main__":
    main()
