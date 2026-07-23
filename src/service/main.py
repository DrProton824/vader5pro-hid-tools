"""
VaderService – background remapper process.

Startup sequence
────────────────
1. Load config.
2. Build mapper + input sender.
3. Start HID reader thread.
4. Enter a lightweight main loop that:
   a. Checks for config file changes every ~500 ms.
   b. Reloads config if changed.
   c. Sleeps the rest of the time.

There is intentionally:
  - No GUI
  - No console window (pythonw / noconsole flag in PyInstaller)
  - No logging to disk (adds I/O for negligible benefit in v1)
  - No tray icon in v1 (can be added without touching any other module)
"""

from __future__ import annotations

import sys
import time
import pathlib


def _bootstrap_path() -> pathlib.Path:
    """
    Return the root directory whether we are:
      - Running from source:  vader-remapper/src/service/main.py
      - Running as a PyInstaller onefile exe:  VaderMapper/VaderService.exe

    In the bundled case sys._MEIPASS is the temp folder where PyInstaller
    extracts files, and the exe itself sits next to config.json.
    """
    if getattr(sys, "frozen", False):
        # Bundled exe: root = directory containing the exe
        return pathlib.Path(sys.executable).resolve().parent
    else:
        # Source: root = three levels up from this file
        return pathlib.Path(__file__).resolve().parents[2]


_ROOT = _bootstrap_path()
sys.path.insert(0, str(_ROOT))

from src.shared import config as cfg
from src.shared.config import ConfigWatcher
from src.shared.hid_reader import HIDReaderThread
from src.shared.input_sender import InputSender
from src.shared.mapper import ButtonMapper

# How often the main loop wakes to check for config changes.
# 500 ms is imperceptible to users but costs essentially nothing.
CONFIG_POLL_INTERVAL = 0.5


def main() -> None:
    # ── Bootstrap ─────────────────────────────────────────────────────────────
    mapping = cfg.load()

    sender = InputSender()
    mapper = ButtonMapper(sender)
    mapper.update_mapping(mapping)

    reader = HIDReaderThread(callback=mapper.handle_event)
    reader.start()

    watcher = ConfigWatcher()

    # ── Main loop ─────────────────────────────────────────────────────────────
    # This thread does almost nothing.  All real work happens in the HID reader
    # thread which is blocked on device.read() between reports.
    try:
        while True:
            time.sleep(CONFIG_POLL_INTERVAL)

            if watcher.changed():
                new_mapping = cfg.load()
                mapper.update_mapping(new_mapping)

    except KeyboardInterrupt:
        pass
    finally:
        reader.stop()
        reader.join(timeout=2.0)


if __name__ == "__main__":
    main()