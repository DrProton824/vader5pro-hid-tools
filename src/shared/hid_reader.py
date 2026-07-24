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

Picking the right interface
────────────────────────────
The controller enumerates as *multiple* HID interfaces under the same
VID/PID (an XInput-passthrough interface plus a vendor-specific one).
``hid.device().open(vid, pid)`` just grabs whichever interface the OS
lists first, which is usually the wrong one – the process opens
successfully, read() never times out fatally, but no button bits ever
change because the vendor reports are arriving on a *different* handle.
We therefore enumerate all interfaces for this VID/PID and open the one
whose usage page matches USAGE_PAGE (0xFFA0), exactly like
tools/monitoring_buttons.py does via ``--usagePage 0xFFA0``.
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
    USAGE_PAGE,
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
                # Controller not connected (or vendor interface not found)
                # – wait, then retry.
                self._stop_event.wait(timeout=RECONNECT_DELAY_SECONDS)
                continue
            try:
                self._read_loop(device)
            finally:
                try:
                    device.close()
                except Exception:
                    pass

    @staticmethod
    def _find_vendor_interface_path() -> Optional[bytes]:
        """
        Enumerate every HID interface for VENDOR_ID/PRODUCT_ID and return
        the ``path`` of the one on USAGE_PAGE.  Returns None if the
        controller isn't connected or the vendor interface isn't present.
        """
        try:
            candidates = hid.enumerate(VENDOR_ID, PRODUCT_ID)
        except Exception:
            return None

        for info in candidates:
            if info.get("usage_page") == USAGE_PAGE:
                return info.get("path")

        # Fall back to the first interface rather than refusing to open
        # anything, in case usage_page reporting differs across hidapi
        # backends/OS versions – better to try than to silently do nothing.
        if candidates:
            return candidates[0].get("path")
        return None

    def _open_device(self) -> Optional["hid.device"]:
        """
        Open the vendor HID interface specifically (not just "a" device
        matching VID/PID – see module docstring for why that matters).

        Returns None if the device is not present so the caller can retry.
        """
        path = self._find_vendor_interface_path()
        if path is None:
            return None
        try:
            device = hid.device()
            device.open_path(path)
            # Non-blocking mode is NOT used: blocking read() is more efficient
            # because the OS wakes us only when data arrives.
            device.set_nonblocking(False)
            return device
        except OSError:
            return None

    def _read_loop(self, device: "hid.device") -> None:
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
