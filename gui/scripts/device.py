#
# gui/scripts/device.py
# Controller detection, connection state, battery and status info.
#

"""
STATUS SOURCE
  Reads service-written status.json (not config.json), keeping service → GUI status
  separate from GUI → service configuration. This script only reads, never writes.

STATUS FILE STRUCTURE
  {
    "controllers": [
      {"name": "Flydigi Vader 4 Pro", "connected": true, "battery": 82}
    ]
  }
  
  Supports multiple devices though the service typically tracks zero or one.
  Missing or invalid status.json falls back to "Disconnected" without errors.

UI BEHAVIOR
  Polls STATUS_PATH every STATUS_POLL_MS after on_start(). Manual refresh via
  fsncs_refresh. Controller dropdown is selection-only (locked via
  ui_utils.lock_combobox_typing) and auto-selects the first available controller
  when the current selection becomes unavailable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from ctkmaker import CTkScript

try:
    from ui_utils import lock_combobox_typing
except ImportError:
    from .ui_utils import lock_combobox_typing

if getattr(sys, "frozen", False):
    # sys.executable is the real exe location; __file__ inside a frozen
    # onefile build resolves into PyInstaller's temp extraction dir, not
    # the dist folder both status.json and the exe actually live in.
    STATUS_PATH = Path(sys.executable).resolve().parent / "status.json"
else:
    STATUS_PATH = Path(__file__).resolve().parent.parent.parent / "status.json"
STATUS_POLL_MS = 2000

# Same colors the rest of the app uses for this state — the polygon
# hit-zone outline color for "assigned" (blue) and the Cancel/Stop
# button color for a stopped/negative state (red).
CONNECTED_COLOR = "#7DABC3"
DISCONNECTED_COLOR = "#722F35"


def _read_status() -> Dict[str, Any]:
    if not STATUS_PATH.exists():
        return {"controllers": []}
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"controllers": []}  # mid-write on the service side, or a stale/corrupt file


class Device(CTkScript):

    def on_start(self):
        self._controllers: List[Dict[str, Any]] = []
        self._selected_name: str = ""

        lock_combobox_typing(self.window.fsnc_controllers)
        self.window.fsnc_controllers.configure(command=self.fsnc_controllers)

        self.window.fsncs_status.configure(text="Disconnected", text_color=DISCONNECTED_COLOR)
        self.window.fsncs_battery.configure(text="")

        self._refresh()
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        self.window.after(STATUS_POLL_MS, self._poll)

    def _poll(self) -> None:
        self._refresh()
        self._schedule_poll()

    def fsncs_refresh(self):
        self._refresh()

    def _refresh(self) -> None:
        status = _read_status()
        self._controllers = status.get("controllers", [])

        names = [c.get("name", "Unknown") for c in self._controllers]
        self.window.fsnc_controllers.configure(values=names)

        if self._selected_name not in names:
            self._selected_name = names[0] if names else ""
            self.window.fsnc_controllers.set(self._selected_name)

        self._update_status_fields()

    def _update_status_fields(self) -> None:
        controller = next((c for c in self._controllers if c.get("name") == self._selected_name), None)
        if controller is None:
            self.window.fsncs_status.configure(text="Disconnected", text_color=DISCONNECTED_COLOR)
            self.window.fsncs_battery.configure(text="")
            return

        connected = bool(controller.get("connected", False))
        self.window.fsncs_status.configure(
            text="Connected" if connected else "Disconnected",
            text_color=CONNECTED_COLOR if connected else DISCONNECTED_COLOR,
        )

        battery = controller.get("battery")
        self.window.fsncs_battery.configure(text=f"{battery}%" if isinstance(battery, (int, float)) else "")

    def fsnc_controllers(self, val: str):
        self._selected_name = val
        self._update_status_fields()
