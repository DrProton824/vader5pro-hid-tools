#
# service/status_writer.py
# Write status.json for the GUI to read.
#

"""
Purpose
───────
Writes status.json (read by gui/scripts/device.py) with the actively tracked
controller's connection state and battery level. Kept as a small, focused writer
rather than folded into main.py so the service's core startup flow stays readable.

Called from the HID reader's connection-change callback — never polled, since
status.json only needs to change when the underlying state actually does. The GUI
does its own periodic re-read (STATUS_POLL_MS in device.py).

Multi-dongle handling
─────────────────────
Only the single controller RawInputReaderThread actively streams from gets a live
connected/battery state. Any other Vader 5 Pro dongles enumerated at the same time
are listed too (so the GUI's device dropdown reflects reality), but remapping more
than one controller at once isn't implemented — see PROJECT.md.

Dongle identification
─────────────────────
Different HID interfaces of the same physical dongle report inconsistent serial
numbers (vendor interfaces report "Flydigi Vader 5 Pro", XInput-compatible reports
"FLYDIGI_VADER_5_PRO"). We key off a normalized (lowercased, alphanumeric-only)
version to merge them. This isn't a truly unique per-unit ID (it's the model name),
so two real Vader 5 Pro dongles would collapse into one dropdown entry — acceptable
since multi-controller remapping isn't implemented anyway.

Battery decoding
────────────────
No HID report byte has been decoded for battery yet (see
docs/Wireless_HID_ReverseEngineering.md), so it's always written as None today.
Once decoded, wire the real value through the `battery` parameter here instead of
changing gui/scripts/device.py — it already treats missing/non-numeric battery as blank.
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


def _status_path() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        base = pathlib.Path(sys.executable).resolve().parent
    else:
        base = pathlib.Path(__file__).resolve().parents[1]
    return base / "status.json"


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize_serial(serial) -> str:
    return _NON_ALNUM.sub("", (serial or "").lower())


def _dongle_key(info: dict) -> str:
    """
    Identify one physical dongle across the (up to) 4 HID interfaces it
    exposes under the same VID/PID.

    This used to be done by parsing the Windows device path, on the
    assumption that sibling interfaces of one physical dongle share
    some common segment of it. Real hid.enumerate() output from the
    hardware this was reported against showed that's not true here —
    each interface gets a *completely* distinct instance-id hash in
    its path (e.g. "9&3b1490e5&0&0000" vs "a&1ddbf4b0&0&0000" vs
    "9&173d5323&0&0000"), so no amount of path-slicing was ever going
    to merge them.

    What that same diagnostic showed IS shared: serial_number. All 4
    interfaces report one, just inconsistently formatted — the vendor
    interfaces report "Flydigi Vader 5 Pro" while the XInput-compatible
    interface Windows synthesizes reports "FLYDIGI_VADER_5_PRO". Same
    string, different case/punctuation, so key off a normalized
    (lowercased, alphanumeric-only) version of it instead.

    Caveat: this "serial" isn't actually unique per physical unit (it's
    the model name, not an ID), so two real Vader 5 Pro dongles plugged
    in at once would collapse into a single dropdown entry rather than
    two. Given remapping more than one controller at once isn't
    implemented anyway (see PROJECT.md), that's an acceptable trade for
    fixing the one-dongle-shows-as-four bug this replaces.
    """
    serial = _normalize_serial(info.get("serial_number"))
    if serial:
        return serial

    # No serial reported at all on this interface (seen on some other
    # hardware/driver combos) - fall back to the raw path. Won't merge
    # correctly with siblings, but degrades gracefully instead of
    # crashing or silently dropping the entry.
    path = info.get("path") or b""
    if isinstance(path, str):
        path = path.encode("utf-8", errors="ignore")
    return path.lower().decode(errors="ignore")


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
