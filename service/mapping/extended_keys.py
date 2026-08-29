#
# service/mapping/extended_keys.py
# Scan codes that need Windows' "extended key" flag on injection.
#

"""
Why this exists
────────────────
A handful of keys are only distinguishable from an unrelated key by the
E0 "extended" prefix a real keyboard sends alongside the scan code:

- Left/Right Windows and the Application (Menu) key have scan codes of
  their own, never shared with anything else, and are *always* extended.
- The navigation cluster (arrows, Home/End, Page Up/Down, Insert/Delete)
  shares its scan codes with the numpad digit keys. The dedicated
  cluster key is extended; the same scan code from the numpad (acting
  as navigation when Num Lock is off) is not. macros.py records that
  distinction at capture time via the `keyboard` library's `is_keypad`
  flag — see NAV_CLUSTER's use in macros.py and macro_player.py.

These are the standard PC hardware "Scan Code Set 1" values, so they
hold regardless of keyboard layout or Windows display language — this
was verified directly against the `keyboard` library's own internal
scan-code tables (_winkeyboard.py: official_virtual_keys, keypad_keys),
not by guessing from what one machine happened to report.

Deliberately not covered: right Ctrl / right Alt (AltGr)
──────────────────────────────────────────────────────────
These share their scan code's low byte with their left-side
counterpart (Ctrl: 29, Alt: 56) with no reliable, layout-independent
way to tell them apart. The `keyboard` library itself only manages it
by asking Windows for a *localized* key name (e.g. English "right
ctrl" vs. German "strg-rechts") — not something we can safely pattern-
match across every Windows display language. Right Ctrl and right Alt
are captured and replayed as their left-side scan code, same as every
key not covered by this file.
"""

ALWAYS_EXTENDED = frozenset({
    91,  # Left Windows
    92,  # Right Windows
    93,  # Application / Menu
})

NAV_CLUSTER = frozenset({
    71,  # Home
    72,  # Up
    73,  # Page Up
    75,  # Left
    77,  # Right
    79,  # End
    80,  # Down
    81,  # Page Down
    82,  # Insert
    83,  # Delete
})
