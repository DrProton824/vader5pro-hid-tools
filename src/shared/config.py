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

# ── Defaults ──────────────────────────────────────────────────────────────────
# Shipped in the repo so a first run works without opening the GUI.
DEFAULT_MAPPING: Mapping = {
    "M1":     "f13",
    "M2":     "f14",
    "M3":     "f15",
    "M4":     "f16",
    "LM":     "mouse4",
    "RM":     "mouse5",
    "C":      "home",
    "Z":      "end",
    "Home":   "",       # empty string = unmapped
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


def save(mapping: Mapping) -> None:
    """
    Write mapping to disk atomically.

    Uses a temp file in the same directory so the rename is on the same
    filesystem (avoids cross-device link errors on some Windows setups).
    """
    # Validate before touching disk
    for button in mapping:
        if button not in MAPPABLE_BUTTONS:
            raise ValueError(f"Unknown button: {button!r}")

    data = {btn: mapping.get(btn, "") for btn in MAPPABLE_BUTTONS}
    text = json.dumps(data, indent=2)

    # Atomic write
    dir_ = CONFIG_PATH.parent
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_path, CONFIG_PATH)  # atomic on Windows (same volume)
    except Exception:
        # Clean up temp file if rename failed
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
