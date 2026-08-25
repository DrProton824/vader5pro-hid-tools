#
# service/mapping/mapper.py
# Mapping engine – the bridge between HID events and key injection.
#

"""
Purpose
───────
This module knows nothing about HID reports. It knows nothing about Win32
SendInput. It only translates ButtonEvent objects into either press/release
calls on an InputSender (keybind assignments) or a MacroPlayer.play() call
(macro assignments), using the current config bindings.

Keeping this layer thin and independent makes it trivially testable: you
can unit-test it with a fake InputSender/MacroPlayer and fake events
without needing a controller or Windows at all.
"""

from __future__ import annotations

from ..hid_interface.hid_protocol import ButtonEvent, ButtonPressed, ButtonReleased
from .input_sender import InputSender
from .macro_player import MacroPlayer


class ButtonMapper:
    """
    Receives button events and forwards them to either the input sender
    (keybind) or the macro player (macro), per the current bindings.

    Usage
    ─────
        sender = InputSender()
        macro_player = MacroPlayer()
        mapper = ButtonMapper(sender, macro_player)
        mapper.update_bindings(config.load_bindings())

        # Then wire into the HID reader:
        reader = HIDReaderThread(mapper.handle_event)
    """

    def __init__(self, sender: InputSender, macro_player: MacroPlayer) -> None:
        self._sender = sender
        self._macro_player = macro_player
        self._bindings: dict[str, dict] = {}

    def update_bindings(self, bindings: dict[str, dict]) -> None:
        """Push new bindings (called on startup and config reload)."""
        self._bindings = bindings
        # InputSender only needs to pre-parse the keybind subset.
        keybind_mapping = {
            button: binding.get("value", "")
            for button, binding in bindings.items()
            if binding.get("type") == "keybind"
        }
        self._sender.update_mappings(keybind_mapping)

    def handle_event(self, event: ButtonEvent) -> None:
        """
        Called on the HID reader thread for every state change.

        Must be fast – no I/O, no blocking calls in the hot path. Macro
        playback runs on its own thread (see MacroPlayer), so it never
        blocks this one.
        """
        binding = self._bindings.get(event.button)
        if binding is None:
            return

        if binding.get("type") == "macro":
            if isinstance(event, ButtonPressed):
                self._macro_player.play(binding.get("actions", []))
            return  # macros play in full on press; release is a no-op

        if isinstance(event, ButtonPressed):
            self._sender.press(event.button)
        elif isinstance(event, ButtonReleased):
            self._sender.release(event.button)
        # Unknown event subtypes are silently ignored (forward compatibility).
