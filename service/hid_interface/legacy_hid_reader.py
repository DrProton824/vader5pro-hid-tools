#
# service/hid_interface/legacy_hid_reader.py
# Legacy hidapi-based HID reader (deprecated).
#

"""
Status
──────
Deprecated for the Windows service path: replaced by
rawinput_reader.RawInputReaderThread.

This module is kept as a reference implementation of the hidapi approach.
It documents the direct HID read model, vendor interface selection, report
decoding, and event generation flow. Do not run both readers against the
same controller at the same time.

Why this approach was replaced
──────────────────────────────
hidapi's blocking device.read() consumes reports from the HID interface,
which can race with other readers such as Flydigi SpaceStation. In practice
this caused competing readers to miss packets or starve each other.

The exclusive read model means only one process can successfully read from
the vendor interface at a time. If the official Flydigi software is running,
this reader may receive no data, or vice versa. Raw Input (the replacement)
uses a broadcast model where every registered process receives its own copy
of reports, eliminating the contention.

Responsibilities
────────────────
1. Open the Flydigi vendor HID interface via hidapi.
2. Block on read() while waiting for reports.
3. Decode reports using BUTTON_BITS.
4. Compare reports to detect button press/release edges.
5. Emit ButtonPressed / ButtonReleased events to a callback.
6. Reconnect automatically after disconnect.

Design choices
──────────────
- Uses hid (the `hid` PyPI package wrapping hidapi.dll) for direct HID access.
  No subprocess, stdout parsing, or device discovery hacks.
- The reader runs as a daemon thread so it exits with the service process.
- Callbacks execute on the reader thread; the mapper must not perform slow
  work inside them.

Interface selection
───────────────────
The controller exposes multiple HID interfaces under the same VID/PID
(an XInput passthrough interface plus a vendor-specific interface).

Opening by VID/PID alone can select the wrong interface: the handle opens
successfully, but vendor reports arrive elsewhere and no button changes are
seen.

This implementation enumerates all matching interfaces and opens the one
whose usage page matches USAGE_PAGE (0xFFA0), equivalent to the selection
performed by tools/monitoring_buttons.py using ``--usagePage 0xFFA0``.
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

# Interface presence != controller connected (the dongle alone enumerates
# all 4 interfaces with no controller paired). The only reliable connect
# signal is real traffic on Interface 1.
DEFAULT_SEND_VENDOR_INITIALIZATION = True

# After sending vendor initialization commands, how long to watch for a real
# high-rate input stream (buttons/sticks/gyro) before concluding they did not
# activate the expected reporting mode.
# The startup burst + 30s heartbeat alone won't cross
# VENDOR_INITIALIZATION_ACTIVE_THRESHOLD reports in this window; live polling will.
VENDOR_INITIALIZATION_VERIFY_SECONDS = 2.0
VENDOR_INITIALIZATION_ACTIVE_THRESHOLD = 10

# How often to re-confirm the vendor interface is still enumerated.
# Interface disappearance is the disconnect signal, not read silence.
INTERFACE_PRESENCE_CHECK_SECONDS = 2.0


def _send_command(device: "hid.device", command: tuple[int, ...]) -> None:
    """
    Best-effort output-report write. hidapi's write() expects the report
    ID as the first byte; this device uses unnumbered reports, so that
    byte is 0x00, followed by the command padded to REPORT_LENGTH bytes.
    Never raises; a failed vendor initialization command write should not
    crash the reader.
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

        reader = HIDReaderThread(callback=on_event)
        reader.start()
        # … later …
        reader.stop()
    """

    def __init__(
        self,
        callback: EventCallback,
        on_connection_change: Optional[Callable[[bool], None]] = None,
        send_vendor_initialization: bool = DEFAULT_SEND_VENDOR_INITIALIZATION,
    ) -> None:
        super().__init__(name="HIDReader", daemon=True)
        self._callback = callback
        self._on_connection_change = on_connection_change
        self._send_vendor_initialization = send_vendor_initialization
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

            # Deliberately NOT calling _set_connected(True) here: opening
            # the dongle's HID interface succeeds even when the physical
            # controller itself is off / unpaired, so "the handle opened"
            # is not proof anything is actually connected. Only
            # _read_loop calls _set_connected(True), and only once it has
            # actually seen a report.

            try:
                self._read_loop(device)
            finally:
                self._set_connected(False)
                if self._send_vendor_initialization:
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
            if (
                info.get("interface_number") == 1
                and info.get("usage_page") == USAGE_PAGE
            ):
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
            device.set_nonblocking(True)
            return device
        except OSError:
            return None

    def _read_loop(self, device: "hid.device") -> None:
        """
        Read passively until real Interface 1 traffic confirms the
        controller is connected, then send vendor initialization commands once.
        Verify they produced a live input stream (not just heartbeat)
        and retry initialization at most once if they did not. Disconnect = interface
        disappearing, never read silence.
        """
        last_presence_check = time.monotonic()
        vendor_initialization_sent = False
        vendor_initialization_retried = False
        verify_window_start: Optional[float] = None
        verify_count = 0

        while not self._stop_event.is_set():
            try:
                report = device.read(REPORT_LENGTH, timeout_ms=100)
            except OSError:
                break  # device disconnected mid-session

            now = time.monotonic()

            if report:
                self._set_connected(True)

                if not vendor_initialization_sent:
                    if self._send_vendor_initialization:
                        for command in INIT_COMMANDS:
                            _send_command(device, command)
                        verify_window_start = now
                        verify_count = 0
                    vendor_initialization_sent = True
                elif verify_window_start is not None:
                    verify_count += 1
                    if verify_count >= VENDOR_INITIALIZATION_ACTIVE_THRESHOLD:
                        verify_window_start = None  # confirmed active

                report_bytes = bytes(report)
                try:
                    current = decode_report(report_bytes)
                except Exception:
                    continue
                if current is None:
                    continue  # status/heartbeat report, not button data
                self._emit_deltas(current)
                continue

            # No data this read.
            if (
                verify_window_start is not None
                and now - verify_window_start >= VENDOR_INITIALIZATION_VERIFY_SECONDS
            ):
                if not vendor_initialization_retried:
                    for command in INIT_COMMANDS:
                        _send_command(device, command)
                    vendor_initialization_retried = True
                    verify_window_start = now
                    verify_count = 0
                else:
                    verify_window_start = None  # give up, stop tracking

            if now - last_presence_check >= INTERFACE_PRESENCE_CHECK_SECONDS:
                last_presence_check = now
                if self._find_vendor_interface_path() is None:
                    self._set_connected(False)
                    return

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
