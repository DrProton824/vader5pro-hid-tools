"""
All hardware constants in one place.

Keeping these separate from logic means that if Flydigi ships a firmware
update that moves a bit, there is exactly one file to change.
"""

# ── HID device identity ───────────────────────────────────────────────────────
# Confirmed via hidapitester / Windows Device Manager captures
# (see tools/monitoring_buttons.py, which is what these values were
# reverse-engineered against).
#
# IMPORTANT: the Vader 5 Pro exposes *several* HID interfaces under the
# same VID/PID (an XInput-passthrough one and a vendor-specific one).
# Only the vendor-specific interface, identified by USAGE_PAGE below,
# ever reports the M1-M4 / LM / RM / C / Z / Home / Arrow / Circle bits.
# Opening "the device" without filtering by usage page will silently
# attach to the wrong interface and just never see button events.
VENDOR_ID  = 0x37D7   # Flydigi Vader 5 Pro
PRODUCT_ID = 0x2401   # Vader 5 Pro
USAGE_PAGE = 0xFFA0   # Vendor-defined usage page (NOT the XInput interface)
USAGE      = 0x0001

# HID report length observed from hidapitester captures
REPORT_LENGTH = 32

# ── Report framing ────────────────────────────────────────────────────────────
# The vendor interface multiplexes several report kinds over the same
# 32-byte reads and the same byte offsets used by BUTTON_BITS below
# (live input, firmware/heartbeat status, LED-config responses, ...).
# Byte 2 is the discriminator; only REPORT_TYPE_INPUT reports actually
# carry button/stick data at those offsets. Confirmed against third-party
# clean-room reverse engineering (ControlLab's Vader5ProtocolTests.swift).
REPORT_MAGIC: tuple[int, int] = (0x5A, 0xA5)
REPORT_TYPE_INPUT = 0xEF

# ── Vendor initialization commands (experimental) ─────────────────────────────
# Recovered from independent clean-room reverse-engineering of the same
# vendor interface (ControlLab's Vader5Protocol.swift / Vader5Bridge.swift).
# Format: 0x5A 0xA5 <cmd> <params...> <checksum>, checksum = 8-bit additive
# sum of every byte from <cmd> through the last param.
# init[4]'s 0x01 vs STOP_COMMAND's 0x00 (same position) look like an
# enable/disable flag for the extended (0xEF) report stream.
# NOTE: our Windows hidapi backend already decodes buttons correctly
# without sending anything, so this is untested here — treat as an
# opt-in experiment (see vendor_init.py and RawInputReaderThread's
# send_vendor_initialization flag), not a fix.
INIT_COMMANDS: tuple[tuple[int, ...], ...] = (
    (0x5A, 0xA5, 0x01, 0x02, 0x03),
    (0x5A, 0xA5, 0xA1, 0x02, 0xA3),
    (0x5A, 0xA5, 0x02, 0x02, 0x04),
    (0x5A, 0xA5, 0x04, 0x02, 0x06),
    (0x5A, 0xA5, 0x11, 0x07, 0xFF, 0x01, 0xFF, 0xFF, 0xFF, 0x15),
)
STOP_COMMAND: tuple[int, ...] = (0x5A, 0xA5, 0x11, 0x07, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0x14)

# ── Button bit layout ─────────────────────────────────────────────────────────
# Each entry maps  byte_index -> { bitmask -> button_name }
# Byte indices are zero-based offsets inside the 64-byte HID report.
#
# These were reverse-engineered by holding one physical button at a time
# and recording which bit changed.  The names match the labels printed on
# the controller so users can recognise them immediately.
BUTTON_BITS: dict[int, dict[int, str]] = {
    11: {
        0x80: "X",
        0x40: "SELECT",
        0x20: "B",
        0x10: "A",
        0x08: "LEFT",
        0x04: "DOWN",
        0x02: "RIGHT",
        0x01: "UP",
    },
    12: {
        0x80: "RS",
        0x40: "LS",
        0x20: "RT",
        0x10: "LT",
        0x08: "RB",
        0x04: "LB",
        0x02: "START",
        0x01: "Y",
    },
    13: {
        0x80: "RM",
        0x40: "LM",
        0x20: "M4",
        0x10: "M3",
        0x08: "M2",
        0x04: "M1",
        0x02: "Z",
        0x01: "C",
    },
    14: {
        0x08: "HOME",
        0x02: "Arrow",
        0x01: "Circle",
    },
}

# Flat set of every button name – used for validation elsewhere
ALL_BUTTONS: frozenset[str] = frozenset(
    name
    for byte_map in BUTTON_BITS.values()
    for name in byte_map.values()
)

# Buttons the GUI exposes for remapping.
#
# v1.2 change: previously this excluded standard XInput buttons (A/B/X/Y,
# bumpers, triggers, sticks, dpad) because they already work via
# XInput/DirectInput. The new controller artwork makes every physical
# button clickable, so this now covers everything in ALL_BUTTONS.
#
# IMPORTANT: mapping a standard XInput button (A, B, LT, RB, DPad Up, ...)
# means the physical press will now ALSO fire through XInput as normal –
# this remapper does not (and cannot, from a second HID interface) suppress
# the XInput report. Only map these if double input is what you want.
MAPPABLE_BUTTONS: tuple[str, ...] = (
    # Face buttons
    "A", "B", "X", "Y",
    # D-Pad
    "UP", "DOWN", "LEFT", "RIGHT",
    # Shoulder
    "LB", "RB", "LT", "RT",
    # Sticks (click)
    "LS", "RS",
    # Select / Start
    "SELECT", "START",
    # Macro / extra buttons (original v1 set)
    "M1", "M2", "M3", "M4",
    "LM", "RM",
    "C",  "Z",
    "HOME", "Arrow", "Circle",
)

# How long (seconds) a button's raw HID bit must hold its new state
# before it's treated as a real press/release rather than contact
# bounce or a single noisy report. Comfortably above USB polling
# jitter, comfortably below the fastest deliberate human tap.
DEBOUNCE_SECONDS = 0.025

# ── Reconnect behaviour ───────────────────────────────────────────────────────
# How many seconds to wait before trying to reopen the HID device after
# a disconnect.  Short enough to feel instant, long enough not to spin.
RECONNECT_DELAY_SECONDS = 2.0
