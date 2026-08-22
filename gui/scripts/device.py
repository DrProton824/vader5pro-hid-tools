"""Controller detection, connection state, battery and status info.

Reads service-written status.json instead of config.json, keeping
service → GUI status separate from GUI → service configuration. This
script only reads the file; it never writes it.

Expected STATUS_PATH shape:

    {
      "controllers": [
        {"name": "Flydigi Vader 4 Pro", "connected": true, "battery": 82}
      ]
    }

"controllers" supports multiple devices, though the current service
normally tracks zero or one. A missing or invalid status.json falls
back to "Disconnected"/blank without raising errors.

fsncs_refresh triggers a manual refresh; on_start also polls every
STATUS_POLL_MS. fsnc_controllers is selection-only via
ui_utils.lock_combobox_typing and auto-selects the first available
controller when the current selection is unavailable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ctkmaker import CTkScript

try:
    from ui_utils import lock_combobox_typing
except ImportError:
    from .ui_utils import lock_combobox_typing

STATUS_PATH = Path(__file__).resolve().parent.parent.parent / "status.json"
STATUS_POLL_MS = 2000


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

        self.window.fsncs_status.configure(text="Disconnected")
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
            self.window.fsncs_status.configure(text="Disconnected")
            self.window.fsncs_battery.configure(text="")
            return

        connected = bool(controller.get("connected", False))
        self.window.fsncs_status.configure(text="Connected" if connected else "Disconnected")

        battery = controller.get("battery")
        self.window.fsncs_battery.configure(text=f"{battery}%" if isinstance(battery, (int, float)) else "")

    def fsnc_controllers(self, val: str):
        self._selected_name = val
        self._update_status_fields()
