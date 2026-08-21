"""
Mapping engine – the bridge between HID events and key injection.

This module knows nothing about HID reports.
It knows nothing about Win32 SendInput.
It only translates ButtonEvent objects into press / release calls on an
InputSender, using the current config mapping.

Keeping this layer thin and independent makes it trivially testable:
you can unit-test it with a fake InputSender and fake events without
needing a controller or Windows at all.
"""

from __future__ import annotations

from ..hid.hid_protocol import ButtonEvent, ButtonPressed, ButtonReleased
from .input_sender import InputSender


class ButtonMapper:
    """
    Receives button events and forwards them to the input sender.

    Usage
    ─────
        sender = InputSender()
        mapper = ButtonMapper(sender)
        mapper.update_mapping(config.load())

        # Then wire into the HID reader:
        reader = HIDReaderThread(mapper.handle_event)
    """

    def __init__(self, sender: InputSender) -> None:
        self._sender = sender

    def update_mapping(self, mapping: dict[str, str]) -> None:
        """Push a new mapping to the sender (called on startup and config reload)."""
        self._sender.update_mappings(mapping)

    def handle_event(self, event: ButtonEvent) -> None:
        """
        Called on the HID reader thread for every state change.

        Must be fast – no I/O, no locks, no allocations in the hot path.
        """
        if isinstance(event, ButtonPressed):
            self._sender.press(event.button)
        elif isinstance(event, ButtonReleased):
            self._sender.release(event.button)
        # Unknown event subtypes are silently ignored (forward compatibility).
