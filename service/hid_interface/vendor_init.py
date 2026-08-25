#
# service/hid_interface/vendor_init.py
# Vendor HID initialization and stop commands.
#

"""
Purpose
───────
Write-only helpers that open the Vader 5 Pro's vendor (0xFFA0) interface
just long enough to send one command, then close it immediately. Used by
rawinput_reader.py to send the recovered vendor initialization sequence
that puts the vendor interface into reporting mode, and the matching
stop sequence on shutdown.

Why write-only
──────────────
Never reads from the device, so it can't race Raw Input (or Flydigi
SpaceStation) for incoming reports the way a blocking hidapi read would.
"""

from __future__ import annotations
from typing import Optional

import hid  # pip install hid

from .constants import (
    INIT_COMMANDS,
    PRODUCT_ID,
    REPORT_LENGTH,
    STOP_COMMAND,
    USAGE_PAGE,
    VENDOR_ID,
)


# after
def find_vendor_interface_path() -> Optional[bytes]:
    """Locate the vendor (usage page 0xFFA0) HID interface path, if present."""
    try:
        candidates = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    except Exception as exc:
        print(f"[vendor_init] hid.enumerate() raised: {exc!r}")
        return None
    print(f"[vendor_init] {len(candidates)} candidate(s): "
          f"{[(c.get('interface_number'), hex(c.get('usage_page', 0))) for c in candidates]}")
    for info in candidates:
        if info.get("interface_number") == 1 and info.get("usage_page") == USAGE_PAGE:
            return info.get("path")
    if candidates:
        return candidates[0].get("path")
    return None


def send_command(path: bytes, command: tuple[int, ...]) -> None:
    """Open, send one output report, close. Best-effort -- never raises."""
    try:
        device = hid.device()
        device.open_path(path)
        try:
            payload = bytes(command) + bytes(REPORT_LENGTH - len(command))
            device.write(bytes([0x00]) + payload)
        finally:
            device.close()
    except Exception:
        pass


def send_init_sequence(path: bytes) -> None:
    """Send the full recovered vendor initialization sequence."""
    for command in INIT_COMMANDS:
        send_command(path, command)


def send_stop_sequence(path: bytes) -> None:
    """Send the matching stop command (call on shutdown/disconnect)."""
    send_command(path, STOP_COMMAND)
