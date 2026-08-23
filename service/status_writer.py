"""
Writes status.json for the GUI to read (see gui/scripts/device.py).

Kept as a small, focused writer rather than folded into main.py so the
service's core startup flow stays readable. Called from the HID reader's
connection-change callback — never polled, since status.json only needs
to change when the underlying state actually does; the GUI does its own
periodic re-read (STATUS_POLL_MS in device.py).

Scope note: only the single controller RawInputReaderThread actively
streams from gets a live connected/battery state. Any other Vader 5 Pro
dongles enumerated at the same time are listed too (so the GUI's device
dropdown reflects reality when more than one is plugged in), but
remapping more than one controller at once isn't implemented — see
PROJECT.md.

Battery: no HID report byte has been decoded for it yet (see
docs/Wireless_HID_ReverseEngineering.md), so it's always written as
None today. Once decoded, wire the real value through the `battery`
parameter here instead of changing gui/scripts/device.py — it already
treats a missing/non-numeric battery as blank.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import tempfile
from typing import Optional

try:
    import hid
except ImportError:
    hid = None

from .hid_interface.constants import PRODUCT_ID, VENDOR_ID

_MI_SUFFIX = re.compile(rb"&mi_[0-9a-f]+", re.IGNORECASE)


def _status_path() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        base = pathlib.Path(sys.executable).resolve().parent
    else:
        base = pathlib.Path(__file__).resolve().parents[1]
    return base / "status.json"


def _dongle_key(info: dict) -> str:
    """
    Identify one physical dongle across the 4 HID interfaces it exposes
    under the same VID/PID. Prefers serial_number when the firmware
    reports one; otherwise strips the "&mi_NN" interface-number segment
    from the device path, which is the only part that differs between
    interfaces of the same physical device (and the only part that's
    shared between two different ones).
    """
    serial = info.get("serial_number")
    if serial:
        return str(serial)

    path = info.get("path") or b""
    if isinstance(path, str):
        path = path.encode("utf-8", errors="ignore")
    return _MI_SUFFIX.sub(b"", path.lower()).decode(errors="ignore")


def _enumerate_dongles() -> list[dict]:
    if hid is None:
        return []

    try:
        candidates = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    except Exception:
        return []

    seen: dict[str, dict] = {}
    for info in candidates:
        seen.setdefault(_dongle_key(info), info)
    return list(seen.values())


def write(connected: bool, battery: Optional[int] = None) -> None:
    """
    Write status.json. `connected`/`battery` describe the actively
    tracked controller; see module docstring for the multi-dongle and
    battery caveats. Best-effort — never raises.
    """
    dongles = _enumerate_dongles()

    controllers = [
        {
            "name": info.get("product_string") or "Flydigi Vader 5 Pro",
            "connected": connected if i == 0 else False,
            "battery": battery if i == 0 else None,
        }
        for i, info in enumerate(dongles)
    ]

    path = _status_path()

    try:
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"controllers": controllers}, fh, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        pass
