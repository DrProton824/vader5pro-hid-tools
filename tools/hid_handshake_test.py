"""
hid_handshake_test.py — Vader 5 Pro vendor HID handshake experiment.

Tests the vendor HID interface of the FLYDIGI Vader 5 Pro wireless dongle
(VID 0x37D7, PID 0x2401, Usage Page 0xFFA0) to determine whether the
recovered init handshake is required before normal controller input reports
are available.

Runs a baseline capture, sends the init sequence, captures again, and
compares received report types. Experimental reverse-engineering tool only;
does not modify the main HID reader implementation.

Usage:
    pip install hid
    python hid_handshake_test.py
"""

from __future__ import annotations

import sys
import time

import hid  # pip install hid  (wraps hidapi.dll / libhidapi)

# ── Device identity (same as src/shared/constants.py) ─────────────────────────
VENDOR_ID = 0x37D7
PRODUCT_ID = 0x2401
USAGE_PAGE = 0xFFA0
REPORT_LENGTH = 32  # confirmed 32-byte unnumbered reports, see prior notes

# ── Handshake, recovered from ControlLab's Vader5Protocol.swift ───────────────
# Format: 0x5A 0xA5 <cmd> <params...> <checksum>
INIT_COMMANDS: list[tuple[int, ...]] = [
    (0x5A, 0xA5, 0x01, 0x02, 0x03),
    (0x5A, 0xA5, 0xA1, 0x02, 0xA3),
    (0x5A, 0xA5, 0x02, 0x02, 0x04),
    (0x5A, 0xA5, 0x04, 0x02, 0x06),
    (0x5A, 0xA5, 0x11, 0x07, 0xFF, 0x01, 0xFF, 0xFF, 0xFF, 0x15),
]
STOP_COMMAND: tuple[int, ...] = (0x5A, 0xA5, 0x11, 0x07, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0x14)

# ── Button decode (subset of src/shared/constants.py, for phase B feedback) ───
BUTTON_BITS: dict[int, dict[int, str]] = {
    11: {0x80: "X", 0x40: "Select", 0x20: "B", 0x10: "A",
         0x08: "DPad Left", 0x04: "DPad Down", 0x02: "DPad Right", 0x01: "DPad Up"},
    12: {0x80: "STICK-R", 0x40: "STICK-L", 0x20: "RT", 0x10: "LT",
         0x08: "RB", 0x04: "LB", 0x02: "Start", 0x01: "Y"},
    13: {0x80: "RM", 0x40: "LM", 0x20: "M4", 0x10: "M3",
         0x08: "M2", 0x04: "M1", 0x02: "Z", 0x01: "C"},
    14: {0x08: "Home", 0x02: "Arrow", 0x01: "Circle/Fn"},
}

PHASE_A_SECONDS = 3.0
PHASE_B_SECONDS = 15.0


def find_vendor_interface_path() -> bytes | None:
    candidates = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    for info in candidates:
        if info.get("usage_page") == USAGE_PAGE:
            return info.get("path")
    if candidates:
        print("  (no interface reported usage_page == 0xFFA0; "
              "falling back to the first candidate)")
        return candidates[0].get("path")
    return None


def decode_buttons(report: bytes) -> set[str]:
    pressed: set[str] = set()
    for byte_index, bit_map in BUTTON_BITS.items():
        if byte_index >= len(report):
            continue
        value = report[byte_index]
        for mask, name in bit_map.items():
            if value & mask:
                pressed.add(name)
    return pressed


def send_command(device: "hid.device", command: tuple[int, ...]) -> bool:
    """Pad to REPORT_LENGTH and write with a leading 0x00 report-ID byte."""
    payload = bytes(command) + bytes(REPORT_LENGTH - len(command))
    try:
        written = device.write(bytes([0x00]) + payload)
        ok = written > 0
    except OSError as exc:
        print(f"    write raised OSError: {exc}")
        return False
    print(f"    wrote {' '.join(f'{b:02X}' for b in command)} "
          f"-> device.write() returned {written} ({'ok' if ok else 'FAILED'})")
    return ok


def read_reports(device: "hid.device", seconds: float, label: str, decode: bool) -> dict:
    """Read for `seconds`, tally report-type bytes, optionally decode buttons."""
    stats: dict[str, int] = {}
    seen_ef = False
    previous_pressed: set[str] = set()
    deadline = time.monotonic() + seconds
    print(f"\n--- {label}: reading for {seconds:.0f}s ---")

    while time.monotonic() < deadline:
        try:
            report = device.read(REPORT_LENGTH, timeout_ms=200)
        except OSError as exc:
            print(f"    read raised OSError: {exc}")
            break
        if not report:
            continue

        report = bytes(report)
        if len(report) >= 3 and report[0] == 0x5A and report[1] == 0xA5:
            type_byte = report[2]
            key = f"5A A5 {type_byte:02X}"
        else:
            key = f"other (starts {' '.join(f'{b:02X}' for b in report[:3])})"
        stats[key] = stats.get(key, 0) + 1

        if len(report) >= 3 and report[0] == 0x5A and report[1] == 0xA5 and report[2] == 0xEF:
            seen_ef = True
            if decode:
                pressed = decode_buttons(report)
                newly_pressed = pressed - previous_pressed
                released = previous_pressed - pressed
                for name in newly_pressed:
                    print(f"    PRESS   {name}")
                for name in released:
                    print(f"    RELEASE {name}")
                previous_pressed = pressed

    print(f"--- {label} summary ---")
    for key, count in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f"    {key}: {count} reports")
    if not stats:
        print("    (no reports received at all)")
    return {"report_types": stats, "saw_input_reports": seen_ef}


def main() -> int:
    print("Vader 5 Pro vendor handshake test")
    print("==================================\n")

    path = find_vendor_interface_path()
    if path is None:
        print("Could not find the vendor (0xFFA0) interface. "
              "Is the controller plugged into the 2.4GHz dongle?")
        return 1

    device = hid.device()
    device.open_path(path)
    device.set_nonblocking(False)
    print("Opened vendor interface.\n")

    try:
        phase_a = read_reports(device, PHASE_A_SECONDS, "PHASE A (no handshake sent)",
                                decode=False)

        print("\nSending init handshake...")
        results = [send_command(device, cmd) for cmd in INIT_COMMANDS]
        time.sleep(0.1)
        if not all(results):
            print("  WARNING: at least one handshake write failed "
                  "(see 'FAILED' lines above). Results below may not reflect "
                  "a fully-sent handshake.")

        print("\nNow press a few buttons (M1, LM, Home, ...) during phase B "
              "to confirm real decoding, not just report traffic.")
        phase_b = read_reports(device, PHASE_B_SECONDS,
                                "PHASE B (after handshake)", decode=True)

        print("\nSending stop command...")
        send_command(device, STOP_COMMAND)

    finally:
        device.close()

    # ── Verdict ────────────────────────────────────────────────────────────────
    print("\n==================================")
    print("VERDICT")
    print("==================================")
    a_saw_input = phase_a["saw_input_reports"]
    b_saw_input = phase_b["saw_input_reports"]

    if a_saw_input and b_saw_input:
        print("Input (0xEF) reports arrived in BOTH phases.")
        print("-> The handshake does not appear to be required on this "
              "system/driver. Our current 'just open and read' approach is "
              "sufficient; no change recommended to hid_reader.py.")
    elif not a_saw_input and b_saw_input:
        print("Input (0xEF) reports arrived ONLY AFTER the handshake.")
        print("-> The handshake looks necessary here. Recommend setting "
              "SEND_VENDOR_HANDSHAKE = True in hid_reader.py, and re-running "
              "this test after a cold unplug/replug and after sleep/resume "
              "to check consistency before making it the default.")
    elif a_saw_input and not b_saw_input:
        print("Input (0xEF) reports arrived BEFORE the handshake but NOT after.")
        print("-> Unexpected: the handshake may have disrupted the stream "
              "(possibly one of the init commands is wrong, or the stop-like "
              "trailing command shouldn't be in the init sequence). Do NOT "
              "enable SEND_VENDOR_HANDSHAKE based on this result without "
              "investigating further.")
    else:
        print("No input (0xEF) reports arrived in either phase.")
        print("-> Something else is wrong (wrong interface opened, "
              "controller asleep, wrong VID/PID/usage page, or another app "
              "already has the interface open). This result doesn't tell us "
              "anything about the handshake either way.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
