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
    under the same VID/PID, by stripping the "&mi_NN" interface-number
    segment from the device path — the only part of the path that
    differs between interfaces of the same physical device (and the
    only part shared between two different ones).

    serial_number is deliberately NOT used here: some interfaces of the
    same physical dongle report it and others don't (a real hidapi/
    Windows quirk on this device), which produced two dropdown entries
    for one dongle — "Flydigi Vader 5 Pro" and "Controller (Flydigi
    Vader 5 Pro)" — instead of merging them.
    """
    path = info.get("path") or b""
    if isinstance(path, str):
        path = path.encode("utf-8", errors="ignore")
    return _MI_SUFFIX.sub(b"", path.lower()).decode(errors="ignore")


def _pick_display_info(members: list[dict]) -> dict:
    """
    Different interfaces of the same dongle can report different
    product_string values — Windows auto-generates "Controller (<name>)"
    for the XInput-style interface, while the vendor interface reports
    the plain name. Prefer whichever candidate's name has no parens.
    """
    for info in members:
        name = info.get("product_string") or ""
        if name and "(" not in name:
            return info
    return members[0]


def _enumerate_dongles() -> list[dict]:
    if hid is None:
        return []

    try:
        candidates = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    except Exception:
        return []

    groups: dict[str, list[dict]] = {}
    for info in candidates:
        groups.setdefault(_dongle_key(info), []).append(info)

    return [_pick_display_info(members) for members in groups.values()]


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
