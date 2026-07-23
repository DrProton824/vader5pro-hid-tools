# Flydigi Vader 5 Pro Remapper

A lightweight, portable remapper for the extra buttons on the Vader 5 Pro
that Windows applications cannot see through XInput.

## What it does

Maps the vendor-only buttons (M1–M4, LM/RM, C/Z, Home, Arrow, Circle)
to any keyboard shortcut you choose.  The standard gamepad buttons
(A/B/X/Y, bumpers, triggers, sticks, d-pad) are left untouched.

## What it does NOT do

Replace Flydigi Space Station.  It solves exactly one problem and nothing else.

## Usage

1. Extract the folder anywhere.
2. Run **VaderService.exe** in the background.
3. Run **VaderConfig.exe** to change mappings.
4. Close VaderConfig when done – VaderService picks up changes automatically.

## Portable

Everything lives in one folder.  Deleting it completely removes the application.
Nothing is written to AppData, the registry, or anywhere else.

## Optional: Start with Windows

Create a shortcut to VaderService.exe and place it in:

    %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

## Building from source

    pip install pyinstaller hid
    python build/build.py

## Requirements

- Windows 10 / 11
- Flydigi Vader 5 Pro

## License

MIT