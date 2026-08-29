#
# service/mapping/extended_keys.py
# Scan-code -> Virtual-Key lookup for keys that don't replay correctly
# via raw KEYEVENTF_SCANCODE alone.
#

"""
Purpose
──────────────────────
Macro actions are recorded with the scan codes the `keyboard` library
reports (see gui/scripts/macros.py). For ordinary character keys,
`keyboard`'s numbering matches real PS/2 Set-1 codes closely enough that
feeding them straight back into SendInput(KEYEVENTF_SCANCODE) reproduces
the original keystroke correctly on any layout — which is the whole
reason this project uses scan codes for macros in the first place.

Two families of keys break that assumption:

1. Genuine *extended* keys (Windows, the arrow/navigation cluster) whose
   real hardware code needs the E0 prefix / KEYEVENTF_EXTENDEDKEY to be
   interpreted correctly.
2. Keys where `keyboard` uses its own internal numbering that doesn't
   match any real PS/2 code at all — confirmed for right Ctrl / right
   Alt: both physical Ctrl keys share one real code, both Alt keys share
   another, distinguished only by the E0 prefix bit, never by a
   different number. `keyboard`'s numbers for these (whatever they are)
   are just internal disambiguation IDs.

Rather than hardcode either family's numbers — fragile, since that
depends on `keyboard` internals that could differ across versions — this
module asks `keyboard` itself, at import time, what scan code it uses
for each key name we care about, and maps *that* number to the correct
Virtual-Key code. If `keyboard` isn't installed, or a key can't be
resolved on this system, it's simply skipped and playback for it falls
back to the ordinary scan-code path unchanged.

Because this is keyed by scan code (not by the "key" name string), it
transparently covers BOTH ways a macro action can be created — the
hook-based recorder in macros.py and the manual "Macro Action" editor in
ui_utils.py — without those two files needing to agree on spelling.
"""

from __future__ import annotations

try:
    import keyboard as _keyboard
except ImportError:
    _keyboard = None

# `keyboard`-library key name -> Virtual-Key code. Names must be ones
# `keyboard.key_to_scan_codes()` understands.
_NAME_TO_VK: dict[str, int] = {
    "left windows": 0x5B,
    "right windows": 0x5C,
    "right ctrl": 0xA3,
    "right alt": 0xA5,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23,
    "page up": 0x21, "page down": 0x22,
    "insert": 0x2D, "delete": 0x2E,
}


# Hardcoded, empirically confirmed scan codes — used as the primary
# source of truth instead of dynamic `keyboard.key_to_scan_codes()`
# lookups, because that lookup has been observed to silently fail for
# the Windows key specifically on at least one real machine (the same
# machine where `event.name` also came back None for a live Left
# Windows keypress via `keyboard.hook()` — the two failures share the
# same underlying resolution path inside the `keyboard` library, most
# likely related to Windows shell-level interception of that key).
# Relying on the dynamic lookup for these would silently do nothing,
# with no error, exactly as observed.
#
# 91/92 (Windows) are also independently documented as the real
# E0-prefixed PS/2 Set-1 hardware codes for these keys. 97/100 (right
# Ctrl/right Alt) match what this project's own recorder has empirically
# reported for years (see gui/scripts/macros.py's SCAN_CODE_TO_NAME).
_CONFIRMED_SCAN_CODE_TO_VK: dict[int, int] = {
    91: 0x5B,   # Left Windows  -> VK_LWIN
    92: 0x5C,   # Right Windows -> VK_RWIN
    97: 0xA3,   # Right Ctrl    -> VK_RCONTROL
    100: 0xA5,  # Right Alt     -> VK_RMENU
}


def _build_scan_code_to_vk() -> dict[int, int]:
    # Dynamic lookup fills in anything NOT already confirmed above (the
    # navigation cluster, currently) — best-effort, and simply absent
    # if it fails, rather than being relied on for keys we already have
    # hard numbers for.
    table: dict[int, int] = dict(_CONFIRMED_SCAN_CODE_TO_VK)
    if _keyboard is None:
        return table
    for name, vk in _NAME_TO_VK.items():
        try:
            codes = _keyboard.key_to_scan_codes(name)
        except (ValueError, KeyError):
            continue
        for code in codes:
            table.setdefault(code, vk)
    return table


# Built once — a given `keyboard` install's scan-code numbering for a
# key name doesn't change at runtime.
SCAN_CODE_TO_VK: dict[int, int] = _build_scan_code_to_vk()