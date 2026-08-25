#
# gui/scripts/storage.py
# CRUD helpers over config.json for profiles, macros and settings.
#

"""CRUD helpers over config.json for profiles, macros and settings.

Not a CTkScript — a plain module imported by macros.py, profiles.py
and settings.py so those stay focused on widget/UI logic instead of
JSON bookkeeping.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from shared import config


# --- macros ---

def list_macros() -> List[Dict[str, Any]]:
    return config.get_macros()


def save_macro(macro: Dict[str, Any]) -> None:
    macros = config.get_macros()
    for i, existing in enumerate(macros):
        if existing["name"] == macro["name"]:
            macros[i] = macro
            break
    else:
        macros.append(macro)
    config.save_macros(macros)


def delete_macro(name: str) -> None:
    config.save_macros([m for m in config.get_macros() if m["name"] != name])


# --- profiles ---

def list_profiles() -> List[Dict[str, Any]]:
    return config.get_profiles()


def get_profile(name: str) -> Optional[Dict[str, Any]]:
    return next((p for p in config.get_profiles() if p["name"] == name), None)


def save_profile(profile: Dict[str, Any]) -> None:
    profiles = config.get_profiles()
    for i, existing in enumerate(profiles):
        if existing["name"] == profile["name"]:
            profiles[i] = profile
            break
    else:
        profiles.append(profile)
    config.save_profiles(profiles)


def delete_profile(name: str) -> None:
    profiles = [p for p in config.get_profiles() if p["name"] != name]
    config.save_profiles(profiles)
    if config.get_active_profile() == name and profiles:
        config.set_active_profile(profiles[0]["name"])


# --- settings ---

def get_settings() -> Dict[str, Any]:
    return config.get_settings()


def save_settings(settings: Dict[str, Any]) -> None:
    config.save_settings(settings)
