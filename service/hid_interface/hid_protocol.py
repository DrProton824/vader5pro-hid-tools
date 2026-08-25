#
# service/hid_interface/hid_protocol.py
# Vader 5 Pro HID report decoding.
#

"""
Purpose
───────
Pure decode logic shared by every reader implementation (current and legacy):
turns a raw HID report into a set of currently-pressed button names, and
defines the press/release event types passed to the mapper. No device I/O
lives here.
"""

from __future__ import annotations

from typing import Callable, Optional

from .constants import BUTTON_BITS, REPORT_MAGIC, REPORT_TYPE_INPUT


class ButtonEvent:
    """Base class – gives isinstance checks a clean anchor."""
    __slots__ = ("button",)

    def __init__(self, button: str) -> None:
        self.button = button

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.button!r})"


class ButtonPressed(ButtonEvent):
    __slots__ = ()


class ButtonReleased(ButtonEvent):
    __slots__ = ()


# Callback signature: (event: ButtonEvent) -> None
EventCallback = Callable[[ButtonEvent], None]


def decode_report(report: bytes) -> Optional[frozenset[str]]:
    """
    Return the set of button names currently pressed, or None if this
    report isn't a live input report (the vendor interface multiplexes
    heartbeat/LED-config reports over the same byte offsets).
    """
    if (
        len(report) < 3
        or report[0] != REPORT_MAGIC[0]
        or report[1] != REPORT_MAGIC[1]
        or report[2] != REPORT_TYPE_INPUT
    ):
        return None

    pressed: set[str] = set()
    for byte_index, bit_map in BUTTON_BITS.items():
        if byte_index >= len(report):
            continue
        byte_value = report[byte_index]
        for mask, name in bit_map.items():
            if byte_value & mask:
                pressed.add(name)
    return frozenset(pressed)
