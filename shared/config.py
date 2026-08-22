"""
Config file read / write.

Schema: {"active_profile": "<id>", "profiles": [...], "macros": [...], "settings": {...}}.
Each profile is {"id", "name", "mapping": {button: {"type": "keybind"|"macro", "value": "..."}}, "automation", "hotkey"}.

load()/load_settings() stay flat-shaped for VaderService.exe: they resolve the active
profile and, for load(), project only its keybind-type assignments into the old
{button: shortcut} dict — macro assignments aren't playable by the service yet.

Atomic write (write to .tmp, rename) so a crash never corrupts the file. The service
detects changes via mtime polling rather than inotify/ReadDirectoryChangesW so the
implementation stays identical on every Python runtime without extra deps.
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
        "M1": {"type": "keybind", "value": "f13"},
        "M2": {"type": "keybind", "value": "f14"},
        "M3": {"type": "keybind", "value": "f15"},
        "M4": {"type": "keybind", "value": "f16"},
        "LM": {"type": "keybind", "value": "f17"},
        "RM": {"type": "keybind", "value": "f18"},
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
    """Return the full config, migrating a legacy/incomplete file on read."""
    data = _read_raw()
    if not data:
        return json.loads(json.dumps(DEFAULT_CONFIG))
    if _migrate(data):
        save_config(data)
    return data


def save_config(data: ConfigData) -> None:
    _atomic_write(json.dumps(data, indent=2))


def load() -> Mapping:
    """
    Return the active profile's mapping as a flat {button: shortcut} dict.
    Macro-type assignments resolve to "" (unmapped) — the service can only
    play keybind shortcuts today. Never raises.
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
            mapping[button] = ""  # unmapped, or a macro — see MacroPlayer follow-up
    return mapping


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
