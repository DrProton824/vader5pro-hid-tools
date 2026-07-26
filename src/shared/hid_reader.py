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
    DEBOUNCE_SECONDS,
    INIT_COMMANDS,
    PRODUCT_ID,
    RECONNECT_DELAY_SECONDS,
    REPORT_LENGTH,
    REPORT_MAGIC,
    REPORT_TYPE_INPUT,
    STOP_COMMAND,
    USAGE_PAGE,
    VENDOR_ID,
)

# Off by default: sends third-party-recovered vendor handshake commands
# before/after reading. Our current decode already works without this on
# Windows/hidapi. Flip to True only to experiment with reliability around
# cold-plug / resume-from-sleep; verify with tools/monitoring_buttons.py
# first if reports stop arriving after enabling it.
DEFAULT_SEND_VENDOR_HANDSHAKE = True


def _send_command(device: "hid.device", command: tuple[int, ...]) -> None:
    """
    Best-effort output-report write. hidapi's write() expects the report
    ID as the first byte; this device uses unnumbered reports, so that
    byte is 0x00, followed by the command padded to REPORT_LENGTH bytes.
    Never raises – a failed handshake write should not crash the reader.
    """
    try:
        payload = bytes(command) + bytes(REPORT_LENGTH - len(command))
        device.write(bytes([0x00]) + payload)
    except OSError:
        pass

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


def decode_report(report: bytes) -> Optional[frozenset[str]]:
    """
    Return the set of button names currently pressed, or None if this
    report isn't a live input report at all.

    The vendor interface reuses BUTTON_BITS' byte offsets for unrelated
    data in other report kinds (firmware/heartbeat status, LED-config
    responses, ...), distinguished by the byte at index 2. Skipping the
    check would occasionally decode a non-input report as a burst of
    phantom presses/releases.

    Pure function – no state, easy to unit-test.
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

    def __init__(
        self,
        callback: EventCallback,
        on_connection_change: Optional[Callable[[bool], None]] = None,
        send_handshake: bool = DEFAULT_SEND_VENDOR_HANDSHAKE,
    ) -> None:
        super().__init__(name="HIDReader", daemon=True)
        self._callback = callback
        self._on_connection_change = on_connection_change
        self._send_handshake = send_handshake
        self._stop_event = threading.Event()

        # Raw state from the previous HID report.
        self._previous: frozenset[str] = frozenset()

        # Debounced state that has actually been reported.
        self._debounced: set[str] = set()

        # Last accepted transition time for each button.
        self._last_change: dict[str, float] = {}

        self._connected = False

    # ── Public API ────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the thread to exit.  Returns immediately."""
        self._stop_event.set()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _set_connected(self, connected: bool) -> None:
        """Notify when the controller connection state changes."""
        if connected == self._connected:
            return

        self._connected = connected

        if self._on_connection_change:
            try:
                self._on_connection_change(connected)
            except Exception:
                pass

    def run(self) -> None:
        while not self._stop_event.is_set():
            device = self._open_device()
            if device is None:
                # Controller not connected (or vendor interface not found)
                # – wait, then retry.
                self._set_connected(False)
                self._stop_event.wait(timeout=RECONNECT_DELAY_SECONDS)
                continue

            self._set_connected(True)

            try:
                self._read_loop(device)
            finally:
                self._set_connected(False)
                if self._send_handshake:
                    _send_command(device, STOP_COMMAND)
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
            if self._send_handshake:
                for command in INIT_COMMANDS:
                    _send_command(device, command)
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
            try:
                current = decode_report(report_bytes)
            except Exception:
                # A malformed/unexpected report should never be able to
                # kill the whole reader thread silently — that's exactly
                # what happened before (see the fix for the missing
                # REPORT_MAGIC / REPORT_TYPE_INPUT import): one NameError
                # on the first report read after opening the device left
                # the thread dead and the tray permanently "disconnected".
                continue
            if current is None:
                continue  # heartbeat/status/LED-response report, not button data
            self._emit_deltas(current)

    def _emit_deltas(self, current: frozenset[str]) -> None:
        """
        Compare current pressed set with previous and fire events for changes.

        Only buttons that actually changed state generate callbacks, so the
        mapper is never called unnecessarily.
        """
        now = time.monotonic()
        changed = current.symmetric_difference(self._previous)

        for button in changed:
            last = self._last_change.get(button, 0.0)
            if now - last < DEBOUNCE_SECONDS:
                continue  # Ignore rapid state flips (contact bounce).

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
