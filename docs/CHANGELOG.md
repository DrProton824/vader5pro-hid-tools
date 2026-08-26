# Changelog

All notable changes to this project are documented in this file.

> **Note:** Version 1.1 marks the beginning of the project's documented release history.
> Earlier versions were not documented consistently, so changes made before 1.1 are not fully represented here.

## [Unreleased]
Changes made since the latest release that will be included in the next version.

### Added
-  Added the application version to the application title and About page for consistent version identification.
  (vader5pro-hid-tools/gui/MainPage.py)

### Changed
- Duplicate GUI launches by bringing the existing window to the foreground instead of opening a second instance. 
  (vader5pro-hid-tools/gui/MainPage.py & vader5pro-hid-tools/gui/single_instance_guard.py)

### Fixed
- Fixed foreground-window profile automation not reverting to the base profile after the linked program loses focus. 
  (service/automation/foreground_watcher.py & shared/config.py)
- Fixed the macro action list showing leftover empty scroll space after switching to a macro with fewer (or zero) actions. 
  (gui/scripts/macros.py & vader5pro-hid-tools/gui/scripts/ui_utils.py)
- Fixed an issue where double-clicking or editing the currently open macro/profile could discard unsaved changes by reloading the last-saved state. 
  (gui/scripts/macros.py & vader5pro-hid-tools/gui/scripts/profiles.py)

### Removed
- 


## [1.1] - 2026-08-25
> First documented release. This version establishes the starting point for the project's documented release history.
