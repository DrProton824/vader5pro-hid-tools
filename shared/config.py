#
# shared/config.py
# Config file read/write for profiles, macros and settings.
#

"""
Schema
──────
  {
    "active_profile": "<id>",
    "profiles": [{"id", "name", "mapping": {button: {"type": "keybind"|"macro", "value": "..."}}, "automation", "hotkey"}],
    "macros":   [{"name", "actions": [...]}],
    "settings": {"vendor_initialization", "autostart", "close_to_tray"}
  }

Reading
───────
load_config() returns the full config, migrating a legacy/incomplete file on read.
load() returns only the active profile's keybind assignments as a flat {button: shortcut}
dict — macro assignments resolve to "" since they aren't directly playable by InputSender.
load_bindings() returns the full active profile assignments including resolved macro action
lists, for callers (ButtonMapper) that need both types.

Migration
─────────
_migrate() handles: backfilling profile ids, guaranteeing a Default profile always
exists, repairing a dangling active_profile pointer, and folding a pre-migration flat
{"M1": "f13", ...} config into the profile schema. Runs transparently on read;
migrated data is written back immediately.

Writing
───────
Atomic write (write to .tmp, rename) so a crash never corrupts the file.

Change detection
────────────────
ConfigWatcher uses mtime polling rather than inotify/ReadDirectoryChangesW so the
implementation stays identical on every Python runtime without extra dependencies.
The service polls once per loop iteration via ConfigWatcher.changed().
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import uuid
from typing import Any, Optional

MAPPABLE_BUTTONS: tuple[str, ...] = (
    "A", "B", "X", "Y",
    "UP", "DOWN", "LEFT", "RIGHT",
    "LB", "RB", "LT", "RT",
    "LS", "RS",
    "SELECT", "START",
    "M1", "M2", "M3", "M4",
    "LM", "RM",
    "C",  "Z",
    "HOME", "Arrow", "Circle",
)

def _find_config_path() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent / "config.json"
    else:
        return pathlib.Path(__file__).resolve().parents[1] / "config.json"


CONFIG_PATH = _find_config_path()

Mapping = dict[str, str]
Settings = dict[str, object]
ConfigData = dict[str, Any]

DEFAULT_PROFILE_ID = "default"

DEFAULT_PROFILE: ConfigData = {
    "id": DEFAULT_PROFILE_ID,
    "name": "Default",
    "mapping": {
        "C": {"type": "keybind", "value": "F15"},
        "Z": {"type": "keybind", "value": "F16"},
        "M1": {"type": "keybind", "value": "F17"},
        "M2": {"type": "keybind", "value": "F18"},
        "M3": {"type": "keybind", "value": "F19"},
        "M4": {"type": "keybind", "value": "F20"},
        "LM": {"type": "keybind", "value": "F13"},
        "RM": {"type": "keybind", "value": "F14"},
    },
    "automation": {"enabled": False, "exe": ""},
    "hotkey": "",
}

DEFAULT_SETTINGS: Settings = {
    "vendor_initialization": True,
    "autostart": False,
    "close_to_tray": True,
}

DEFAULT_CONFIG: ConfigData = {
    "active_profile": DEFAULT_PROFILE_ID,
    "profiles": [DEFAULT_PROFILE],
    "macros": [],
    "settings": DEFAULT_SETTINGS,
}


def _read_raw() -> ConfigData:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _atomic_write(text: str) -> None:
    dir_ = CONFIG_PATH.parent
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _migrate(data: ConfigData) -> bool:
    """
    Backfill profile ids, guarantee a Default profile, repair a dangling
    active_profile, and fold a pre-migration flat {"M1": "f13", ...}
    config into a fresh Default profile. Returns True if data changed.
    """
    changed = False

    if "profiles" not in data:
        legacy_mapping = {
            key: value for key, value in data.items()
            if key in MAPPABLE_BUTTONS and isinstance(value, str)
        }
        if legacy_mapping:
            profile = json.loads(json.dumps(DEFAULT_PROFILE))
            profile["mapping"] = {
                button: {"type": "keybind", "value": shortcut}
                for button, shortcut in legacy_mapping.items() if shortcut
            }
            data["profiles"] = [profile]
            for key in legacy_mapping:
                data.pop(key, None)
            changed = True

    profiles = data.setdefault("profiles", [])

    for profile in profiles:
        if "id" not in profile:
            profile["id"] = DEFAULT_PROFILE_ID if profile.get("name") == "Default" else uuid.uuid4().hex
            changed = True

    if not any(p["id"] == DEFAULT_PROFILE_ID for p in profiles):
        profiles.insert(0, json.loads(json.dumps(DEFAULT_PROFILE)))
        changed = True

    active = data.get("active_profile")
    if not any(p["id"] == active for p in profiles):
        by_name = next((p for p in profiles if p.get("name") == active), None)
        data["active_profile"] = by_name["id"] if by_name else DEFAULT_PROFILE_ID
        changed = True

    data.setdefault("macros", [])
    settings = dict(DEFAULT_SETTINGS)
    settings.update(data.get("settings", {}))
    if data.get("settings") != settings:
        changed = True
    data["settings"] = settings

    return changed


def load_config() -> ConfigData:
    data = _read_raw()
    if not data:
        data = json.loads(json.dumps(DEFAULT_CONFIG))
        save_config(data)
        return data
    if _migrate(data):
        save_config(data)
    return data


def save_config(data: ConfigData) -> None:
    _atomic_write(json.dumps(data, indent=2))


def load() -> Mapping:
    """
    Return the active profile's mapping as a flat {button: shortcut} dict.
    Macro-type assignments resolve to "" (unmapped) — kept for anything
    that only wants keybinds (e.g. InputSender.update_mappings). Services
    that also need to play macros should use load_bindings() instead.
    Never raises.
    """
    try:
        data = load_config()
    except Exception:
        return {button: "" for button in MAPPABLE_BUTTONS}

    active_id = data.get("active_profile", DEFAULT_PROFILE_ID)
    profile = next((p for p in data.get("profiles", []) if p["id"] == active_id), None)
    raw_mapping = (profile or {}).get("mapping", {})

    mapping: Mapping = {}
    for button in MAPPABLE_BUTTONS:
        assignment = raw_mapping.get(button)
        if isinstance(assignment, dict) and assignment.get("type") == "keybind":
            mapping[button] = str(assignment.get("value", ""))
        else:
            mapping[button] = ""  # unmapped, or a macro — see load_bindings()
    return mapping


Binding = dict[str, Any]


def load_bindings_for(profile_id: str) -> dict[str, Binding]:
    """
    Same as load_bindings(), but for an explicit profile id instead of the
    persisted active_profile. Used by foreground-window profile automation
    (see service/main.py) to apply a profile's bindings temporarily without
    persisting it as the user's chosen active profile, so it can be cleanly
    reverted once the linked program loses focus. Never raises.
    """
    try:
        data = load_config()
    except Exception:
        return {button: {"type": "keybind", "value": ""} for button in MAPPABLE_BUTTONS}

    profile = next((p for p in data.get("profiles", []) if p["id"] == profile_id), None)
    raw_mapping = (profile or {}).get("mapping", {})
    macros_by_name = {m.get("name"): m.get("actions", []) for m in data.get("macros", [])}

    bindings: dict[str, Binding] = {}
    for button in MAPPABLE_BUTTONS:
        assignment = raw_mapping.get(button)
        kind = assignment.get("type") if isinstance(assignment, dict) else None

        if kind == "macro":
            actions = macros_by_name.get(str(assignment.get("value", "")), [])
            bindings[button] = {"type": "macro", "actions": actions}
        elif kind == "keybind":
            bindings[button] = {"type": "keybind", "value": str(assignment.get("value", ""))}
        else:
            bindings[button] = {"type": "keybind", "value": ""}

    return bindings


def load_bindings() -> dict[str, Binding]:
    """
    Return the active profile's mapping resolved to executable bindings:

        {button: {"type": "keybind", "value": "<shortcut>"}}
        {button: {"type": "macro", "actions": [<recorded actions>]}}

    Macro names are resolved against the top-level "macros" list here, so
    callers (ButtonMapper) never need to know the config schema — a
    button with a macro assignment pointing at a since-deleted or
    since-renamed macro just resolves to an empty action list. Never
    raises.
    """
    try:
        active_id = get_active_profile()
    except Exception:
        active_id = DEFAULT_PROFILE_ID
    return load_bindings_for(active_id)


def load_settings() -> Settings:
    try:
        return dict(load_config().get("settings", DEFAULT_SETTINGS))
    except Exception:
        return dict(DEFAULT_SETTINGS)

def get_macros() -> list[ConfigData]:
    return load_config().get("macros", [])

def save_macros(macros: list[ConfigData]) -> None:
    data = load_config()
    data["macros"] = macros
    save_config(data)

def get_profiles() -> list[ConfigData]:
    return load_config().get("profiles", [])

def save_profiles(profiles: list[ConfigData]) -> None:
    data = load_config()
    data["profiles"] = profiles
    save_config(data)

def get_active_profile() -> str:
    return load_config().get("active_profile", DEFAULT_PROFILE_ID)

def set_active_profile(profile_id: str) -> None:
    data = load_config()
    data["active_profile"] = profile_id
    save_config(data)

def get_settings() -> Settings:
    return load_settings()

def save_settings(settings: Settings) -> None:
    data = load_config()
    data["settings"] = settings
    save_config(data)


def get_automation_targets() -> tuple[dict[str, str], dict[str, str]]:
    """Return (hotkeys_by_profile, exe_by_profile) for every profile with
    automation enabled -- consumed by the service's hotkey/foreground
    watchers (see service/automation/)."""
    hotkeys: dict[str, str] = {}
    exes: dict[str, str] = {}
    for profile in get_profiles():
        automation = profile.get("automation", {})
        if not automation.get("enabled"):
            continue
        hotkey = profile.get("hotkey", "")
        if hotkey:
            hotkeys[profile["id"]] = hotkey
        exe = automation.get("exe", "")
        if exe:
            exes[profile["id"]] = exe
    return hotkeys, exes


class ConfigWatcher:
    """
    Lightweight mtime-based config change detector.

    The service calls ``changed()`` once per loop iteration.
    When it returns True the caller should reload the config.
    No threads, no OS notifications, no extra dependencies.
    """

    def __init__(self) -> None:
        self._last_mtime: Optional[float] = self._mtime()

    def _mtime(self) -> Optional[float]:
        try:
            return CONFIG_PATH.stat().st_mtime
        except OSError:
            return None

    def changed(self) -> bool:
        current = self._mtime()
        if current != self._last_mtime:
            self._last_mtime = current
            return True
        return False
