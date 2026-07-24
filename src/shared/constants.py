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
REPORT_LENGTH = 64

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
        0x40: "Select",
        0x20: "B",
        0x10: "A",
        0x08: "DPad Left",
        0x04: "DPad Down",
        0x02: "DPad Right",
        0x01: "DPad Up",
    },
    12: {
        0x80: "STICK-R",
        0x40: "STICK-L",
        0x20: "RT",
        0x10: "LT",
        0x08: "RB",
        0x04: "LB",
        0x02: "Start",
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
        0x08: "Home",
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

# Buttons the GUI exposes for remapping (the "extra" vendor-only buttons).
# Standard XInput buttons (A/B/X/Y, bumpers, triggers, sticks, dpad) are
# intentionally excluded from v1 – they already work via XInput/DirectInput.
MAPPABLE_BUTTONS: tuple[str, ...] = (
    "M1", "M2", "M3", "M4",
    "LM", "RM",
    "C",  "Z",
    "Home", "Arrow", "Circle",
)

# ── Reconnect behaviour ───────────────────────────────────────────────────────
# How many seconds to wait before trying to reopen the HID device after
# a disconnect.  Short enough to feel instant, long enough not to spin.
RECONNECT_DELAY_SECONDS = 2.0
