"""
VaderService – background remapper process.

Startup sequence
────────────────
1. Grab the single-instance mutex – exit immediately (with a message box)
   if another copy is already running.
2. Load config.
3. Build mapper + input sender.
4. Start the HID reader thread.
5. Start a background thread that checks for config file changes every
   ~500 ms and reloads on change.
6. Create a tray icon and pump its message loop on the main thread until
   the user picks "Exit".

There is intentionally:
  - No console window (pythonw / noconsole flag in PyInstaller)
  - No logging to disk (adds I/O for negligible benefit in v1)

v1.1 adds a tray icon and a single-instance guard – both were previously
listed as "not in v1" but are needed for this to feel like a real
background service instead of an untraceable, unstoppable process.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
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
from src.shared import single_instance
from src.shared.config import ConfigWatcher
from src.shared.rawinput_reader import RawInputReaderThread
from src.shared.input_sender import InputSender
from src.shared.mapper import ButtonMapper
from src.shared.tray import TrayIcon

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
    mapping = cfg.load()
    settings = cfg.load_settings()

    sender = InputSender()
    mapper = ButtonMapper(sender)
    mapper.update_mapping(mapping)

    icon_holder: dict[str, TrayIcon] = {}

    def _on_connection_change(connected: bool) -> None:
        icon = icon_holder.get("icon")
        if icon is not None:
            icon.update_status(connected)

    # Vendor initialization/stop sequence – required on profiles that have no
    # macro/extra button currently assigned in the Flydigi software
    # (confirmed via tools/test_handshake.py: the vendor 0xFFA0
    # interface stays completely silent without it). Sent unconditionally
    # at startup and stopped at shutdown; no longer toggleable from the
    # tray to keep the context menu simple. The underlying setting still
    # lives in config.json (see src/shared/config.py) so a future GUI
    # settings screen can flip it – that just requires restarting the
    # service to take effect for now.
    send_vendor_init = bool(settings.get("vendor_handshake", True))

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
                mapper.update_mapping(cfg.load())

    watcher_thread = threading.Thread(
        target=_watch_config,
        name="ConfigWatcher",
        daemon=True,
    )
    watcher_thread.start()

    # ── Tray icon ─────────────────────────────────────────────────────────────

    def _open_config() -> None:
        config_exe = _ROOT / "VaderConfig.exe"
        try:
            if config_exe.exists():
                subprocess.Popen([str(config_exe)], cwd=str(_ROOT))
            else:
                # Running from source – fall back to launching the module.
                subprocess.Popen(
                    [sys.executable, "-m", "src.config_gui.main"],
                    cwd=str(_ROOT),
                )
        except Exception:
            pass

    def _quit() -> None:
        stop_event.set()
        reader.stop()
        icon_holder["icon"].stop()

    icon = TrayIcon(
        tooltip="Vader Remapper",
        icon_path=_ROOT / "assets" / "icons" / "service.ico",
        menu_items=[
            ("Open Config", _open_config),
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
        reader.join(timeout=2.0)


if __name__ == "__main__":
    main()
