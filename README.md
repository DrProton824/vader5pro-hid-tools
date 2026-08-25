# Flydigi Vader 5 Pro Remapper

Lightweight, portable remapper for the vendor-specific extra buttons on the Flydigi Vader 5 Pro —
buttons that Windows applications cannot access through normal XInput mode.

## What it does

- Maps any controller button to a **keyboard shortcut** or **macro**
- Macros support press, release, and delay actions, recorded directly from your keyboard
- Multiple **profiles** with per-profile mappings, switchable from the config app
- **Autostart with Windows** toggle built into the settings page
- Runs silently in the background with a system tray icon
- Works without Flydigi SpaceStation installed or running

## What it does not do

- Replace Flydigi SpaceStation (LEDs, firmware updates, controller settings are out of scope)
- Read battery level (not yet decoded — shown as blank in the GUI)
- Remap more than one controller at a time

## Usage

1. Extract the folder anywhere.
2. Run **VaderService.exe** — a tray icon appears in the system tray.
3. Right-click the tray icon → **Open Config** to change mappings, or **Exit** to stop.
4. Close VaderConfig when done — VaderService picks up changes automatically.

## Portability

Everything lives in one folder. Nothing is written outside it except an optional
autostart registry entry if you enable that in Settings.

## Requirements

- Windows 10 / 11
- Flydigi Vader 5 Pro with USB dongle

## Building from source

pip install pyinstaller hid pillow customtkinter keyboard ctkmaker
python build/build.py

Output lands in dist/VaderMapper/.

## License

MIT
