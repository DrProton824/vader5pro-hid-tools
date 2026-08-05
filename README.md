# Flydigi Vader 5 Pro Remapper

Lightweight, portable remapper for all vendor-specific extra buttons on the Flydigi Vader 5 Pro
that Windows applications cannot access through normal XInput mode.


## What it should do

Maps the vendor-specific buttons (M1–M4, LM/RM, C/Z, Home, Select/Start, Share/Fn) to any desired
keyboard shortcut. The standard gamepad buttons (A/B/X/Y, bumpers, triggers, sticks, D-pad) are not
the main target but may be remappable in the future.


## What it does NOT do

Replace the Flydigi SpaceStation software. The primary goal is to extend the capabilities of the
Flydigi software by allowing buttons to be mapped to full key combinations. Other functions
(LEDs, controller settings, etc.) are not the target.


## Usage

1. Extract the folder anywhere.
2. Run **VaderService.exe**. A tray icon appears in the system tray.
   Right-click for **Open Config** / **Exit**.
3. Run **VaderConfig.exe** or select **Open Config** from the system tray to change mappings.
4. Close VaderConfig when done. VaderService automatically picks up the changes.


## Portability

Everything lives in one folder. Deleting it completely removes the application.
Nothing is written to AppData, the registry, or anywhere else. A shortcut can be
added to the Startup folder to start the application automatically after each reboot.
The application is lightweight and should have only minimal performance impact.


## Optional: Start with Windows

Create a shortcut to VaderService.exe and place it in:

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
````


## Building from source

```
pip install pyinstaller hid pillow customtkinter
python build/build.py
````

## Change History

None yet.

## Requirements

* Windows 10 / 11
* Flydigi Vader 5 Pro
* Flydigi SpaceStation installed and its service running

## License

MIT
