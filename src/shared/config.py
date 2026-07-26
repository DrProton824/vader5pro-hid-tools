"""
Config file read / write.

Deliberately simple:
  - One JSON file next to the executables.
  - No schema versioning in v1 (add it when the schema actually changes).
  - Atomic write (write to .tmp, rename) so a crash never corrupts the file.
  - Thread-safe for the single writer (VaderConfig) / single reader (VaderService).

The service detects changes via mtime polling rather than inotify/ReadDirectoryChangesW
so the implementation stays identical on every Python runtime without extra deps.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
from typing import Optional

from .constants import MAPPABLE_BUTTONS

# ── Location ──────────────────────────────────────────────────────────────────
def _find_config_path() -> pathlib.Path:
    """
    Locate config.json next to the exe (bundled) or at repo root (source).
    """
    if getattr(sys, "frozen", False):
        # Bundled exe: config.json sits in the same folder as the exe
        return pathlib.Path(sys.executable).resolve().parent / "config.json"
    else:
        # Source: config.json is at the repo root, two levels above shared/
        return pathlib.Path(__file__).resolve().parents[2] / "config.json"


CONFIG_PATH = _find_config_path()

# ── Types ─────────────────────────────────────────────────────────────────────
# A mapping is just  { button_name: shortcut_string }
# e.g. { "M1": "f13", "M2": "ctrl+shift+p" }
Mapping = dict[str, str]
Settings = dict[str, object]

# Reserved top-level key for app settings unrelated to button mapping.
# Button names are always plain strings from MAPPABLE_BUTTONS, so this
# can never collide with a real button key.
SETTINGS_KEY = "_settings"

DEFAULT_SETTINGS: Settings = {
    # Sends the recovered vendor init/stop handshake before/after reading
    # the HID interface. Confirmed necessary on Vader 5 Pro profiles that
    # have no macro/extra button currently assigned in the Flydigi
    # software — without it the vendor (0xFFA0) interface stays silent.
    "vendor_handshake": True,
}

# ── Defaults ──────────────────────────────────────────────────────────────────
# Shipped in the repo so a first run works without opening the GUI.
DEFAULT_MAPPING: Mapping = {
    # Standard XInput buttons – unmapped by default (see the warning in
    # constants.py about double input before assigning these).
    "A": "", "B": "", "X": "", "Y": "",
    "DPad Up": "", "DPad Down": "", "DPad Left": "", "DPad Right": "",
    "LB": "", "RB": "", "LT": "", "RT": "",
    "STICK-L": "", "STICK-R": "",
    "Select": "", "Start": "",

    # Original v1 extras – keep their existing defaults.
    "M1":     "f13",
    "M2":     "f14",
    "M3":     "f15",
    "M4":     "f16",
    "LM":     "f17",
    "RM":     "f18",
    "C":      "",
    "Z":      "",
    "Home":   "",
    "Arrow":  "",
    "Circle": "",
}


def load() -> Mapping:
    """
    Return the current mapping from disk.

    Returns the default mapping if the file is missing or corrupt.
    Never raises – the service must keep running even with a bad config.
    """
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
        raw: dict = json.loads(text)
    except FileNotFoundError:
        return dict(DEFAULT_MAPPING)
    except (json.JSONDecodeError, OSError):
        # Corrupt or locked file – return defaults rather than crashing.
        return dict(DEFAULT_MAPPING)

    # Keep only keys we recognise; ignore unknown keys from future versions.
    mapping: Mapping = {}
    for button in MAPPABLE_BUTTONS:
        mapping[button] = str(raw.get(button, ""))
    return mapping


def _read_raw() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _atomic_write(text: str) -> None:
    """Write text to CONFIG_PATH atomically (temp file + rename)."""
    dir_ = CONFIG_PATH.parent
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_path, CONFIG_PATH)  # atomic on Windows (same volume)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save(mapping: Mapping) -> None:
    """
    Write mapping to disk atomically.

    Preserves any existing ``_settings`` block – this used to rewrite the
    file with only button keys, which silently dropped settings on every
    autosave triggered from the config GUI.
    """
    for button in mapping:
        if button not in MAPPABLE_BUTTONS:
            raise ValueError(f"Unknown button: {button!r}")

    existing_raw = _read_raw()
    data = {btn: mapping.get(btn, "") for btn in MAPPABLE_BUTTONS}
    if SETTINGS_KEY in existing_raw:
        data[SETTINGS_KEY] = existing_raw[SETTINGS_KEY]

    _atomic_write(json.dumps(data, indent=2))


def load_settings() -> Settings:
    """Return current settings, falling back to defaults for missing keys."""
    raw = _read_raw()
    stored = raw.get(SETTINGS_KEY, {})
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(stored, dict):
        settings.update(stored)
    return settings


def save_settings(settings: Settings) -> None:
    """Write settings atomically, preserving the current button mapping."""
    existing_raw = _read_raw()
    data = {
        btn: existing_raw.get(btn, DEFAULT_MAPPING.get(btn, ""))
        for btn in MAPPABLE_BUTTONS
    }
    merged = dict(DEFAULT_SETTINGS)
    merged.update(existing_raw.get(SETTINGS_KEY, {}))
    merged.update(settings)
    data[SETTINGS_KEY] = merged

    _atomic_write(json.dumps(data, indent=2))


class ConfigWatcher:
    """
    Lightweight mtime-based config change detector.

    The service calls ``changed()`` once per loop iteration.
    When it returns True the caller should reload the config.
    No threads, no OS notifications, no extra dependencies.
    """

    def __init__(self) -> None:
        self._last_mtime: Optional[float] = self._mtime()

    def _mtime(self) -> Optional[float]:
        try:
            return CONFIG_PATH.stat().st_mtime
        except OSError:
            return None

    def changed(self) -> bool:
        """Return True once when the file has been modified since last check."""
        current = self._mtime()
        if current != self._last_mtime:
            self._last_mtime = current
            return True
        return False
