"""
HID reader thread.

Responsibilities
────────────────
1. Open the Flydigi vendor HID interface via hidapi.
2. Block on read() – zero CPU while waiting for a report.
3. Decode the report using BUTTON_BITS.
4. Compare with the previous report to detect press / release edges.
5. Emit ButtonPressed / ButtonReleased events to a callback.
6. Reconnect automatically after disconnect.

Design choices
──────────────
- Uses hid (the `hid` PyPI package wrapping hidapi.dll) for direct HID access.
  No subprocess, no stdout parsing, no regex.
- The reader runs in a daemon thread so it dies automatically when the
  main process exits without needing an explicit shutdown signal in the
  happy path.
- Callbacks are called on the reader thread.  The mapper must not do
  anything slow inside them.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import hid  # pip install hid  (wraps hidapi.dll / libhidapi)

from .constants import (
    BUTTON_BITS,
    PRODUCT_ID,
    RECONNECT_DELAY_SECONDS,
    REPORT_LENGTH,
    VENDOR_ID,
)

# ── Event types ───────────────────────────────────────────────────────────────

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


# Callback signature:  (event: ButtonEvent) -> None
EventCallback = Callable[[ButtonEvent], None]


# ── Decoder ───────────────────────────────────────────────────────────────────

def decode_report(report: bytes) -> frozenset[str]:
    """
    Return the set of button names that are currently pressed according
    to one 64-byte HID report.

    Pure function – no state, easy to unit-test.
    """
    pressed: set[str] = set()
    for byte_index, bit_map in BUTTON_BITS.items():
        if byte_index >= len(report):
            continue
        byte_value = report[byte_index]
        for mask, name in bit_map.items():
            if byte_value & mask:
                pressed.add(name)
    return frozenset(pressed)


# ── Reader thread ─────────────────────────────────────────────────────────────

class HIDReaderThread(threading.Thread):
    """
    Background thread that reads HID reports and emits button events.

    Usage
    ─────
        def on_event(event):
            print(event)

        reader = HIDReaderThread(on_event)
        reader.start()
        # … later …
        reader.stop()
    """

    def __init__(self, callback: EventCallback) -> None:
        super().__init__(name="HIDReader", daemon=True)
        self._callback = callback
        self._stop_event = threading.Event()
        self._previous: frozenset[str] = frozenset()

    # ── Public API ────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the thread to exit.  Returns immediately."""
        self._stop_event.set()

    # ── Internal ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        while not self._stop_event.is_set():
            device = self._open_device()
            if device is None:
                # Controller not connected – wait, then retry.
                self._stop_event.wait(timeout=RECONNECT_DELAY_SECONDS)
                continue
            try:
                self._read_loop(device)
            finally:
                try:
                    device.close()
                except Exception:
                    pass

    def _open_device(self) -> Optional[hid.device]:
        """
        Try to open the vendor HID interface.

        Returns None if the device is not present so the caller can retry.
        """
        try:
            device = hid.device()
            device.open(VENDOR_ID, PRODUCT_ID)
            # Non-blocking mode is NOT used: blocking read() is more efficient
            # because the OS wakes us only when data arrives.
            device.set_nonblocking(False)
            return device
        except OSError:
            return None

    def _read_loop(self, device: hid.device) -> None:
        """
        Block on read() forever, emit events on state changes.
        Exits when the device disconnects or stop() is called.
        """
        while not self._stop_event.is_set():
            try:
                # read() blocks until a report arrives or the device disconnects.
                # Timeout of 100 ms lets us check _stop_event periodically.
                report = device.read(REPORT_LENGTH, timeout_ms=100)
            except OSError:
                # Device disconnected mid-session.
                break

            if not report:
                # Timeout with no data – loop back to check stop event.
                continue

            report_bytes = bytes(report)
            current = decode_report(report_bytes)
            self._emit_deltas(current)
            self._previous = current

    def _emit_deltas(self, current: frozenset[str]) -> None:
        """
        Compare current pressed set with previous and fire events for changes.

        Only buttons that actually changed state generate callbacks, so the
        mapper is never called unnecessarily.
        """
        for button in current - self._previous:
            self._callback(ButtonPressed(button))
        for button in self._previous - current:
            self._callback(ButtonReleased(button))