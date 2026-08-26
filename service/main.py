#
# service/main.py
# VaderService – background remapper process.
#

"""
Startup sequence
────────────────
1. Grab the single-instance mutex – exit immediately (with a message box)
   if another copy is already running.
2. Load config.
3. Build mapper + input sender.
4. Start the HID reader thread.
5. Start the profile automation watchers (hotkey + foreground window).
6. Start a background thread that checks for config file changes every
   ~500 ms and reloads on change.
7. Create a tray icon and pump its message loop on the main thread until
   the user picks "Exit".

There is intentionally:
  - No console window (pythonw / noconsole flag in PyInstaller)
  - No logging to disk (adds I/O for negligible benefit in v1)

v1.1 adds a tray icon and a single-instance guard – both were previously
listed as "not in v1" but are needed for this to feel like a real
background service instead of an untraceable, unstoppable process.

Profile automation
───────────────────
Each profile can optionally carry a hotkey and/or a "start with program"
executable (see shared/config.py's get_automation_targets()). Two
dedicated threads under service/automation/ watch for those triggers
and flip active_profile even while the GUI is closed:

  - HotkeyWatcherThread: registers a Win32 RegisterHotKey per profile,
    event-driven, no polling.
  - ForegroundWatcherThread: hooks EVENT_SYSTEM_FOREGROUND, switches
    profile when the assigned program becomes the active window.

Both are reloaded whenever ConfigWatcher sees config.json change, same
as the button mapper's bindings.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import time
import pathlib

# Tell Windows this process handles DPI scaling itself.
# Must happen before creating any Win32 windows.
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(
        ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    )
except Exception:
    pass

def _bootstrap_path() -> pathlib.Path:
    """
    Return the root directory whether we are:
      - Running from source:  vader-remapper/service/main.py
      - Running as a PyInstaller onefile exe:  VaderMapper/VaderService.exe

    In the bundled case sys._MEIPASS is the temp folder where PyInstaller
    extracts files, and the exe itself sits next to config.json.
    """
    if getattr(sys, "frozen", False):
        # Bundled exe: root = directory containing the exe
        return pathlib.Path(sys.executable).resolve().parent
    else:
        # Source: root = two levels up from this file
        return pathlib.Path(__file__).resolve().parents[1]


_ROOT = _bootstrap_path()
sys.path.insert(0, str(_ROOT))

# From source, icons live under service/assets/icons/. In a frozen build
# they're flattened to assets/icons/ next to the exe (see build/build.py).
_ICON_DIR = (_ROOT / "assets" / "icons") if getattr(sys, "frozen", False) else (_ROOT / "service" / "assets" / "icons")

from shared import config as cfg
from service import single_instance
from service import status_writer
from shared.config import ConfigWatcher
from service.hid_interface.rawinput_reader import RawInputReaderThread
from service.mapping.input_sender import InputSender
from service.mapping.macro_player import MacroPlayer
from service.mapping.mapper import ButtonMapper
from service.automation.hotkey_watcher import HotkeyWatcherThread
from service.automation.foreground_watcher import ForegroundWatcherThread
from service.tray import TrayIcon

# How often the config-watcher thread wakes to check for changes.
# 500 ms is imperceptible to users but costs essentially nothing.
CONFIG_POLL_INTERVAL = 0.5

MUTEX_NAME = "VaderRemapperService"


def _already_running_dialog() -> None:
    """Show a small native message box – there's no console to print to."""
    MB_OK = 0x00000000
    MB_ICONINFORMATION = 0x00000040
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            "Vader Remapper is already running.\n\n"
            "Look for its icon in the system tray (you may need to click "
            "the little \u2303 arrow to show hidden icons).",
            "Vader Remapper",
            MB_OK | MB_ICONINFORMATION,
        )
    except Exception:
        pass


def main() -> None:
    # ── Single instance guard ────────────────────────────────────────────────
    if not single_instance.acquire(MUTEX_NAME):
        _already_running_dialog()
        return

    # ── Bootstrap ─────────────────────────────────────────────────────────────
    settings = cfg.load_settings()

    sender = InputSender()
    macro_player = MacroPlayer()
    mapper = ButtonMapper(sender, macro_player)

    status_writer.write(connected=False)  # dongle enumeration visible in the GUI immediately, even before pairing

    icon_holder: dict[str, TrayIcon] = {}

    def _on_connection_change(connected: bool) -> None:
        icon = icon_holder.get("icon")
        if icon is not None:
            icon.update_status(connected)
        # Battery isn't decoded yet (see status_writer.write's docstring) —
        # always None here until a report byte is identified for it.
        status_writer.write(connected=connected, battery=None)

    # ── Profile automation (hotkey + "start with program") ───────────────────
    #
    # profile_state["base"] is the user's manually chosen profile -- set
    # from the GUI's profile dropdown or a hotkey switch, and persisted to
    # config.json as "active_profile". profile_state["auto"] is a profile
    # temporarily applied by foreground-window automation; it is never
    # persisted, so it reverts cleanly to the base profile once the linked
    # program loses focus instead of staying stuck active.

    profile_state = {"base": cfg.get_active_profile(), "auto": None}

    def _apply_profile(profile_id: str) -> None:
        mapper.update_bindings(cfg.load_bindings_for(profile_id))

    def _switch_profile(profile_id: str) -> None:
        """Hotkey-triggered switch -- a deliberate user choice, so it
        becomes the new base profile and clears any automation override,
        same as picking a profile in the GUI."""
        profile_state["base"] = profile_id
        profile_state["auto"] = None
        if cfg.get_active_profile() != profile_id:
            cfg.set_active_profile(profile_id)
        _apply_profile(profile_id)

    def _apply_foreground_automation(profile_id: str) -> None:
        """The linked program just became foreground -- apply its profile
        without persisting it, so losing focus can revert cleanly."""
        if profile_id == profile_state["auto"]:
            return
        profile_state["auto"] = profile_id
        _apply_profile(profile_id)

    def _revert_foreground_automation() -> None:
        """No automated program is foreground anymore -- restore the base profile."""
        if profile_state["auto"] is None:
            return
        profile_state["auto"] = None
        _apply_profile(profile_state["base"])

    _apply_profile(profile_state["base"])

    hotkeys_by_profile, exe_by_profile = cfg.get_automation_targets()

    hotkey_watcher = HotkeyWatcherThread(on_trigger=_switch_profile)
    hotkey_watcher.reload(hotkeys_by_profile)
    hotkey_watcher.start()

    foreground_watcher = ForegroundWatcherThread(
        on_match=_apply_foreground_automation,
        on_unmatch=_revert_foreground_automation,
    )
    foreground_watcher.reload(exe_by_profile)
    foreground_watcher.start()

    # Vendor init/stop sequence required for profiles without assigned
    # Flydigi macros/buttons. Sent at service start/stop; controlled via
    # config.json for future GUI support.
    send_vendor_init = bool(settings.get("vendor_initialization", True))

    reader = RawInputReaderThread(
        callback=mapper.handle_event,
        on_connection_change=_on_connection_change,
        send_vendor_initialization=send_vendor_init,
    )
   
    reader.start()

    stop_event = threading.Event()

    def _watch_config() -> None:
        watcher = ConfigWatcher()
        while not stop_event.is_set():
            time.sleep(CONFIG_POLL_INTERVAL)
            if watcher.changed():
                new_base = cfg.get_active_profile()
                if new_base != profile_state["base"]:
                    # active_profile changed on disk (e.g. the GUI's profile
                    # dropdown) -- treat it like a hotkey switch: it becomes
                    # the new base and clears any automation override.
                    profile_state["base"] = new_base
                    profile_state["auto"] = None
                    _apply_profile(new_base)
                else:
                    # Just a binding/macro edit -- re-apply whichever
                    # profile is currently live (the automation override
                    # if one is active, otherwise the base) so the change
                    # shows up immediately.
                    _apply_profile(profile_state["auto"] or profile_state["base"])
                hotkeys_by_profile, exe_by_profile = cfg.get_automation_targets()
                hotkey_watcher.reload(hotkeys_by_profile)
                foreground_watcher.reload(exe_by_profile)

    watcher_thread = threading.Thread(
        target=_watch_config,
        name="ConfigWatcher",
        daemon=True,
    )
    watcher_thread.start()

    # ── Tray icon ─────────────────────────────────────────────────────────────

    def _find_config_exe() -> pathlib.Path | None:
        """Locate the GUI exe next to this one without relying on a fixed
        filename, so renaming either .exe (as long as both stay in the same
        folder) doesn't break "Open Config" / "About". Picks the only other
        .exe in the folder; if there's more than one candidate, prefers one
        still named VaderConfig.exe (unrenamed) as a tie-breaker."""
        self_path = pathlib.Path(sys.executable).resolve()
        candidates = [p for p in _ROOT.glob("*.exe") if p.resolve() != self_path]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        for p in candidates:
            if p.name.lower() == "vaderconfig.exe":
                return p
        return candidates[0]

    def _launch_gui(*extra_args: str) -> None:
        config_exe = _find_config_exe()
        try:
            if config_exe is not None:
                subprocess.Popen([str(config_exe), *extra_args], cwd=str(_ROOT))
            else:
                # Running from source, or no companion .exe found - fall
                # back to launching the module directly. MainPage.py lives
                # under gui/, so both the script path and the cwd it runs
                # from need to point there, not at _ROOT.
                gui_main = _ROOT / "gui" / "MainPage.py"
                subprocess.Popen(
                    [sys.executable, str(gui_main), *extra_args],
                    cwd=str(gui_main.parent),
                )
        except Exception:
            pass

    def _open_config() -> None:
        _launch_gui()

    def _open_about() -> None:
        # If the GUI is already running, this just brings the existing
        # window to the foreground (see gui/single_instance_guard.py) --
        # it won't jump that already-running instance to the About page,
        # only a freshly started one.
        _launch_gui("--about")

    def _quit() -> None:
        stop_event.set()
        reader.stop()
        hotkey_watcher.stop()
        foreground_watcher.stop()
        icon_holder["icon"].stop()

    icon = TrayIcon(
        tooltip="Vader5Mapper",
        icon_path=_ICON_DIR / "service_connected.ico",
        disconnected_icon_path=_ICON_DIR / "service_disconnected.ico",
        menu_items=[
            ("Open Config", _open_config),
            ("About", _open_about),
            ("Exit", _quit),
        ],
    )
    icon_holder["icon"] = icon
    icon.update_status(False)  # will flip to True as soon as the reader connects

    try:
        icon.run()  # blocks until "Exit" is chosen
    finally:
        stop_event.set()
        reader.stop()
        hotkey_watcher.stop()
        foreground_watcher.stop()
        reader.join(timeout=2.0)


if __name__ == "__main__":
    main()
