#
# gui/scripts/settings.py
# Application settings, startup options, user preferences.
#

"""
CONFIG SOURCE
  _read_config/_write_config prefer shared/config.py (present once merged into repo)
  and fall back to local config.json for standalone testing in CTkMaker. Either way
  reads/writes the same config.json that VaderService.exe watches.

AUTOSTART
  fcsvss_switch2 toggles autostart via Windows registry (HKEY_CURRENT_USER\Software\...).
  _service_exe_path() resolves to VaderService.exe in dist folder if frozen (PyInstaller),
  or to service/main.py via pythonw.exe if running from source. Non-Windows platforms
  are no-op (winreg unavailable).

CLOSE TO TRAY
  fcsvss_switch3 toggles whether closing the window minimizes to system tray (withdraw)
  or exits the application (destroy). Default is True (close to tray).

STATUS DISPLAY
  Both switches display "ON"/"OFF" status labels updated on toggle.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from ctkmaker import CTkScript


REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_VALUE = "VaderRemapper"


try:
    import winreg
except ImportError:
    winreg = None  # not on Windows — autostart is a no-op


try:
    from shared import config as _app_config
    _read_config = _app_config.load_config
    _write_config = _app_config.save_config
except ImportError:
    CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

    def _read_config() -> Dict[str, Any]:
        if not CONFIG_PATH.exists():
            return {}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_config(data: Dict[str, Any]) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def _get_settings() -> Dict[str, Any]:
    return _read_config().get("settings", {})


def _save_settings(settings: Dict[str, Any]) -> None:
    data = _read_config()
    data["settings"] = settings
    _write_config(data)


def _find_service_exe() -> Path | None:
    """Locate the service exe next to this one by content, not filename,
    so renaming either .exe (keeping both in the same folder) still works.
    Falls back to VaderService.exe as a tie-breaker if more than one other
    .exe is present."""
    self_path = Path(sys.executable).resolve()
    folder = self_path.parent
    candidates = [p for p in folder.glob("*.exe") if p.resolve() != self_path]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    for p in candidates:
        if p.name.lower() == "vaderservice.exe":
            return p
    return candidates[0]


def _service_exe_path() -> str:
    if getattr(sys, "frozen", False):
        # Both onefile exes land flat in the same dist folder - sys.executable
        # is this exe's own real path (unlike __file__, which points inside
        # PyInstaller's temp extraction dir for a frozen build).
        service_exe = _find_service_exe() or (Path(sys.executable).resolve().parent / "VaderService.exe")
        return f'"{service_exe}"'
    # Running from source: no built exe exists yet, so autostart launches
    # the service module directly instead.
    repo_root = Path(__file__).resolve().parents[2]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{interpreter}" "{repo_root / "service" / "main.py"}"'


def _enable_autostart() -> None:
    if winreg is None:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, REGISTRY_VALUE, 0, winreg.REG_SZ, _service_exe_path())


def _status_text(is_on: bool) -> str:
    return "ON" if is_on else "OFF"


def _disable_autostart() -> None:
    if winreg is None:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, REGISTRY_VALUE)
        except FileNotFoundError:
            pass  # already absent


class Settings(CTkScript):

    def on_start(self):
        settings = _get_settings()

        autostart_on = settings.get("autostart", False)
        self.window.fcsvss_switch2.select() if autostart_on else self.window.fcsvss_switch2.deselect()
        self.window.fcsvss_label2.configure(text=_status_text(autostart_on))

        close_to_tray_on = settings.get("close_to_tray", True)
        self.window.fcsvss_switch3.select() if close_to_tray_on else self.window.fcsvss_switch3.deselect()
        self.window.fcsvss_label3.configure(text=_status_text(close_to_tray_on))

        self.window.protocol("WM_DELETE_WINDOW", self._handle_close)

    def fcsvss_switch2(self):
        enabled = bool(self.window.fcsvss_switch2.get())
        _enable_autostart() if enabled else _disable_autostart()
        self.window.fcsvss_label2.configure(text=_status_text(enabled))

        settings = _get_settings()
        settings["autostart"] = enabled
        _save_settings(settings)

    def fcsvss_switch3(self):
        enabled = bool(self.window.fcsvss_switch3.get())
        self.window.fcsvss_label3.configure(text=_status_text(enabled))

        settings = _get_settings()
        settings["close_to_tray"] = enabled
        _save_settings(settings)

    def _handle_close(self):
        if _get_settings().get("close_to_tray", False):
            self.window.withdraw()
        else:
            self.window.destroy()
