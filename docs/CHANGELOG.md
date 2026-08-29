# Changelog

All notable changes to this project are documented in this file.

> **Note:** Version 1.1 marks the beginning of the project's documented release history.
> Earlier versions were not documented consistently, so changes made before 1.1 are not fully represented here.

## [Unreleased]
Changes made since the latest release that will be included in the next version.

### Added
-  Added the application version to the application title and about page for consistent version identification.
  (gui/MainPage.py)

### Changed
- Duplicate GUI launches now bring the existing window to the front instead of opening a second one. 
  (gui/MainPage.py, gui/single_instance_guard.py)
- Smart dropdown positioning for macro and profile comboboxes on mapping screen. Dropdown now opens downward by default but flips upward when insufficient screen space is available. Added scrollbar for more than >5 entries.
  (gui/scripts/mapping.py)
- Minor GUI adjustments
  (gui/MainPage.py)


### Fixed
- Fixed profile automation not reverting to the selected base profile after the linked program loses focus. 
  (service/automation/foreground_watcher.py, shared/config.py)
- Fixed the macro action list showing leftover empty scroll space after switching to a macro with fewer actions. 
  (gui/scripts/macros.py, gui/scripts/ui_utils.py)
- Fixed macro and profile dropdowns not reflecting the order defined in their corresponding list. Dropdowns now update immediately after drag-reordering.
  (gui/scripts/macros.py, gui/scripts/profiles.py)
- Fixed an issue where double-clicking or editing the currently open macro/profile could discard unsaved changes by reloading the last-saved state. 
  (gui/scripts/macros.py, gui/scripts/profiles.py)
- Fixed the Windows key, right Ctrl, right Alt, and navigation keys (arrows, Home/End, Page Up/Down, Insert/Delete) not being sent correctly by macros and not being capturable as keybinds.
(service/mapping/extended_keys.py, service/mapping/macro_player.py, gui/scripts/ui_utils.py)
  

### Removed
- 


## [1.1] - 2026-08-25
> First documented release. This version establishes the starting point for the project's documented release history.
