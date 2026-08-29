#
# gui/scripts/profiles.py
# Create/edit/delete/save/load/activate profiles.
#

"""
SESSIONS
  Keyed by stable "id" (UUID assigned once at creation, never reused), not display name.
  Rename only touches "name" — anything holding the id (fcgi_profile, mapping.py's
  per-profile assignments) keeps working. fcplh_add creates in-memory, unsaved session.
  Nothing appears in fcpl_profilelist (or fcgi_profile) until fcpeh_save runs. Cancel
  or navigating away discards unsaved sessions (see _discard_pending and
  window._editor_close_listeners).

SELECTABLE LIST
  fcpl_profilelist driven by ui_utils.SelectableList: single click selects, double click
  (or Edit button) opens, Delete/Backspace/Ctrl+A act on list. Every delete confirmed
  via ui_utils.confirm_dialog. DEFAULT_PROFILE_ID always exists, can't be deleted or
  renamed. It's the fallback when active profile is deleted, so mapping.py always has
  a valid profile to read from. Registered as "pinned": always first, excluded from
  drag-reorder and delete_selected, rendered in DEFAULT_TEXT_COLOR.

AUTOMATION
  fcpeeos_combobox2 opens native file browser (tkinter.filedialog) not a dropdown,
  since "Start with Program" is a filesystem path. Displays only executable filename
  for readability, full path persisted in session["automation"]["exe"] and tracked in
  self._current_exe_path while open. Combobox locked to selection-only via
  ui_utils.lock_combobox_typing. Dropdown arrow redirected to browser via
  ui_utils.redirect_dropdown_arrow_to_action.

HOTKEY CAPTURE
  fcpeeos_entry3 "click to record a hotkey" shared with fcgafskk_entry (mapping.py)
  via ui_utils.bind_hotkey_capture.

NAVIGATION GUARD
  _navigation_guard registered on window._navigation_guards (consulted by navigation.py
  before page switches) and called from _on_list_select before switching profiles. If
  current session is dirty (_has_unsaved_changes — name, automation, or hotkey differ
  from disk), shows ui_utils.confirm_unsaved_changes. Only returns True if user picks
  Save or Discard — Cancel blocks navigation, caller restores prior selection.

PROFILE DROPDOWN
  fcgi_profile locked to selection-only, populated by _refresh_mapping_combobox from
  saved sessions. Explicit command binding in on_start (same fix as mapping.py's
  fcgafsmm_combobox) ensures selecting a profile persists active_profile to disk.
  DEFAULT_TEXT_COLOR distinguishes Default profile in dropdown.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from tkinter import filedialog
from typing import Any, Dict, List, Optional

import customtkinter as ctk
from ctkmaker import CTkScript

try:
    from ui_utils import (
        hide_frame, show_frame, bind_hotkey_capture, SelectableList, lock_combobox_typing,
        confirm_unsaved_changes, set_entry_value, redirect_dropdown_arrow_to_action,
    )
except ImportError:
    from .ui_utils import (
        hide_frame, show_frame, bind_hotkey_capture, SelectableList, lock_combobox_typing,
        confirm_unsaved_changes, set_entry_value, redirect_dropdown_arrow_to_action,
    )


DEFAULT_PROFILE_ID = "default"
DEFAULT_TEXT_COLOR = "#7DABC3"  # distinguishes the non-removable Default profile in the list
EXE_FILETYPES = [("Programs", "*.exe *.lnk"), ("All files", "*.*")]
EXE_PLACEHOLDER = "No program selected"  # shown in fcpeeos_combobox2 in place of CTkComboBox's missing placeholder_text support

def _automation_status_text(is_on: bool) -> str:
    return "ON" if is_on else "OFF (default)"

def _default_profile() -> Dict[str, Any]:
    return {
        "id": DEFAULT_PROFILE_ID,
        "name": "Default",
        "mapping": {},
        "automation": {"enabled": False, "exe": ""},
        "hotkey": "",
    }


def _migrate(data: Dict[str, Any]) -> bool:
    """Backfill ids on pre-existing config.json files, guarantee a
    Default profile exists, and make sure active_profile points at a
    valid id. Returns True if `data` was changed (caller persists it)."""
    changed = False
    profiles = data.setdefault("profiles", [])

    for profile in profiles:
        if "id" not in profile:
            profile["id"] = DEFAULT_PROFILE_ID if profile.get("name") == "Default" else uuid.uuid4().hex
            changed = True

    if not any(p["id"] == DEFAULT_PROFILE_ID for p in profiles):
        profiles.insert(0, _default_profile())
        changed = True

    active = data.get("active_profile")
    if not any(p["id"] == active for p in profiles):
        # Unset, or a pre-migration file where active_profile held a
        # display name rather than an id — resolve it either way.
        by_name = next((p for p in profiles if p.get("name") == active), None)
        data["active_profile"] = by_name["id"] if by_name else DEFAULT_PROFILE_ID
        changed = True

    return changed

try:
    from shared import config as _app_config
    _read_config = _app_config.load_config
    _write_config = _app_config.save_config
except ImportError:
    CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

    def _read_config() -> Dict[str, Any]:
        if not CONFIG_PATH.exists():
            data: Dict[str, Any] = {}
        else:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

        if _migrate(data):
            _write_config(data)
        return data

    def _write_config(data: Dict[str, Any]) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def _get_profiles() -> List[Dict[str, Any]]:
    return _read_config().get("profiles", [])


def _save_profile(profile: Dict[str, Any]) -> None:
    data = _read_config()
    profiles = data.get("profiles", [])
    for i, existing in enumerate(profiles):
        if existing["id"] == profile["id"]:
            # Keep whatever's on disk for mapping — this file doesn't
            # edit it, and never overwrite mapping.py's latest save
            # with this script's possibly-stale in-memory copy.
            profile["mapping"] = dict(existing.get("mapping", {}))
            profiles[i] = profile
            break
    else:
        profiles.append(profile)
    data["profiles"] = profiles
    _write_config(data)


def _delete_profile(profile_id: str) -> None:
    if profile_id == DEFAULT_PROFILE_ID:
        return
    data = _read_config()
    data["profiles"] = [p for p in data.get("profiles", []) if p["id"] != profile_id]
    if data.get("active_profile") == profile_id:
        data["active_profile"] = DEFAULT_PROFILE_ID
    _write_config(data)


def _set_profile_order(ids: List[str]) -> None:
    profiles = {p["id"]: p for p in _get_profiles()}
    data = _read_config()
    data["profiles"] = [profiles[i] for i in ids if i in profiles]
    _write_config(data)


def _get_active_profile() -> str:
    return _read_config().get("active_profile", DEFAULT_PROFILE_ID)


def _set_active_profile(profile_id: str) -> None:
    data = _read_config()
    data["active_profile"] = profile_id
    _write_config(data)


def _color_dropdown_entry(combobox, label: str, color: str) -> None:
    """Recolor `label`'s row in `combobox`'s open dropdown to `color`,
    matching fcpl_profilelist's pinned-row styling. CTkComboBox has no
    public per-item color option, so this reaches into its internal
    button dict; defensive no-op if that structure isn't found, so an
    internal rename upstream degrades to "no special color" rather than
    crashing.
    """
    dropdown = getattr(combobox, "_dropdown_menu", None)
    buttons = getattr(dropdown, "_buttons_dict", None) if dropdown is not None else None
    button = buttons.get(label) if buttons else None
    if button is not None:
        try:
            button.configure(text_color=color)
        except Exception:
            pass


def _make_list_button(parent, text: str) -> ctk.CTkButton:
    return ctk.CTkButton(
        parent, text=text, height=30, width=140,
        fg_color="#26282a", hover_color="#3a3d40",
        text_color="#ffffff", corner_radius=6,
        anchor="w", font=ctk.CTkFont(size=17),
    )


class Profiles(CTkScript):

    def on_start(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._current_session: Optional[str] = None
        self._profile_id_by_name: Dict[str, str] = {}
        self._current_exe_path: str = ""

        bind_hotkey_capture(self.window, self.window.fcpeeos_entry3)
        self.window.fcpeenn_entry1.bind("<Return>", lambda e: self._save_and_unfocus())

        lock_combobox_typing(self.window.fcgi_profile)
        lock_combobox_typing(self.window.fcpeeos_combobox2)
        self.window.fcpeeos_combobox2.bind("<Button-1>", lambda e: self._open_exe_browser(), add="+")
        # fcpeeos_combobox2 never has real values — the <Button-1>
        # binding above only catches the text area, so the dropdown
        # arrow needs a separate redirect to the same browse action.
        redirect_dropdown_arrow_to_action(self.window.fcpeeos_combobox2, self._open_exe_browser)

        self.window.fcplp_example.destroy()

        self._profile_list = SelectableList(
            self.window, self.window.fcpl_profilelist,
            make_button=_make_list_button,
            on_open=self._open_session,
            on_select=self._on_list_select,
            on_delete=self._delete_profiles,
            on_drag_end=self._persist_profile_order,
            pinned_color=DEFAULT_TEXT_COLOR,
            confirm_title="Delete Profile",
            confirm_message=lambda n: f"Delete {n} profile{'s' if n != 1 else ''}? This can't be undone.",
        )

        for profile in _get_profiles():
            self._add_saved_session(
                session_id=profile["id"],
                display_name=profile["name"],
                mapping=dict(profile["mapping"]),
                automation=dict(profile["automation"]),
                hotkey=profile["hotkey"],
            )

        self._refresh_mapping_combobox()
        # Explicit code-level wiring, same fix as fcgafsmm_combobox in
        # mapping.py — without it, selecting a profile can update the
        # dropdown text without persisting active_profile to disk.
        self.window.fcgi_profile.configure(command=self.fcgi_profile)

        self.window.__dict__.setdefault("_editor_close_listeners", []).append(
            lambda: self._discard_pending()
        )
        self.window.__dict__.setdefault("_navigation_guards", []).append(self._navigation_guard)

    # --- sessions ---

    def _new_session_dict(self, display_name: str, saved: bool, mapping=None,
                           automation=None, hotkey: str = "") -> Dict[str, Any]:
        return {
            "saved": saved,
            "display_name": display_name,
            "mapping": mapping if mapping is not None else {},
            "automation": automation if automation is not None else {"enabled": False, "exe": ""},
            "hotkey": hotkey,
        }

    def _add_saved_session(self, session_id: str, display_name: str,
                            mapping: Dict[str, str], automation: Dict[str, Any], hotkey: str) -> None:
        self._sessions[session_id] = self._new_session_dict(
            display_name, saved=True, mapping=mapping, automation=automation, hotkey=hotkey,
        )
        self._profile_list.add(session_id, display_name, pinned=(session_id == DEFAULT_PROFILE_ID))

    def _discard_pending(self, keep: Optional[str] = None) -> None:
        if self._current_session and self._current_session != keep \
                and self._current_session not in self._profile_list.buttons:
            self._sessions.pop(self._current_session, None)
        if keep is None:
            self._current_session = None

    def _show_editor(self) -> None:
        show_frame(self.window.fcp_editframe)
        show_frame(self.window.fcp_frameR)

    def _hide_editor(self) -> None:
        hide_frame(self.window.fcp_editframe)
        hide_frame(self.window.fcp_frameR)

    def _unique_default_name(self, base: str) -> str:
        taken = {s["display_name"] for s in self._sessions.values() if s["saved"]}
        if base not in taken:
            return base
        i = 2
        while f"{base} ({i})" in taken:
            i += 1
        return f"{base} ({i})"

    def _has_unsaved_changes(self) -> bool:
        if self._current_session is None:
            return False
        session = self._sessions[self._current_session]

        if self._current_session == DEFAULT_PROFILE_ID:
            name_changed = False  # name entry is disabled/locked for Default
        else:
            name_changed = self.window.fcpeenn_entry1.get().strip() != session["display_name"]

        automation_changed = (
            bool(self.window.fcpeeos_switch1.get()) != session["automation"]["enabled"]
            or self._current_exe_path != session["automation"]["exe"]
        )
        hotkey_changed = self.window.fcpeeos_entry3.get() != session["hotkey"]

        return name_changed or automation_changed or hotkey_changed

    def _navigation_guard(self) -> bool:
        if not self._has_unsaved_changes():
            return True
        choice = confirm_unsaved_changes(
            self.window, "Unsaved Changes",
            "This profile has unsaved changes. \nSave changes before leaving?",
        )
        if choice == "save":
            self.fcpeh_save()
            return True
        return choice == "discard"

    def _on_list_select(self, session_id: str) -> None:
        if session_id == self._current_session or not self.window.fcp_editframe.winfo_manager():
            return
        if not self._navigation_guard():
            self._profile_list.select_only(self._current_session)  # user cancelled — restore the old selection
            return
        self._discard_pending()
        self._hide_editor()

    def _open_session(self, session_id: str) -> None:
        if session_id == self._current_session:
            # Already open. Double-click and the Edit button both route
            # here without going through _navigation_guard() first (see
            # _on_list_select and fcplh_edit for the equivalent guard on
            # the other paths) -- without this, re-opening the same
            # profile silently reloads its saved name/automation/hotkey,
            # discarding any unsaved edits in the fields below.
            return
        self._discard_pending(keep=session_id)
        self._current_session = session_id
        session = self._sessions[session_id]
        self._profile_list.select_only(session_id)

        is_default = session_id == DEFAULT_PROFILE_ID
        self.window.fcpeenn_entry1.configure(state="normal")
        self.window.fcpeenn_entry1.delete(0, "end")
        self.window.fcpeenn_entry1.insert(0, session["display_name"])
        # The Default profile always has to exist as a fallback, so its
        # name can't be changed out from under fcgi_profile/mapping.py.
        self.window.fcpeenn_entry1.configure(state="disabled" if is_default else "normal")

        automation_enabled = session["automation"]["enabled"]
        if automation_enabled:
            self.window.fcpeeos_switch1.select()
        else:
            self.window.fcpeeos_switch1.deselect()
        self.window.fcpeeos_label1.configure(text=_automation_status_text(automation_enabled))

        self._current_exe_path = session["automation"]["exe"]
        self.window.fcpeeos_combobox2.set(Path(self._current_exe_path).name if self._current_exe_path else EXE_PLACEHOLDER)
        set_entry_value(self.window.fcpeeos_entry3, session["hotkey"])

        self._show_editor()
        if not is_default:
            self.window.fcpeenn_entry1.focus_set()

    def _refresh_mapping_combobox(self) -> None:
        # Use the live list order (already correct after drag/add/delete)
        # rather than re-reading disk, which may lag or require a separate read.
        saved = [
            (sid, self._sessions[sid]["display_name"])
            for sid in self._profile_list.order
            if sid in self._sessions and self._sessions[sid]["saved"]
        ]

        self._profile_id_by_name = {name: sid for sid, name in saved}
        self.window.fcgi_profile.configure(values=[name for _, name in saved])
        _color_dropdown_entry(
            self.window.fcgi_profile,
            self._sessions.get(DEFAULT_PROFILE_ID, {}).get("display_name", "Default"),
            DEFAULT_TEXT_COLOR,
        )

        active_id = _get_active_profile()
        active_name = self._sessions.get(active_id, {}).get("display_name", "Default")
        self.window.fcgi_profile.set(active_name)

    # --- fcpl_profilelist toolbar ---

    def fcplh_add(self):
        if not self._navigation_guard():
            return
        session_id = uuid.uuid4().hex
        display_name = self._unique_default_name("New Profile")
        self._sessions[session_id] = self._new_session_dict(display_name, saved=False)
        self._open_session(session_id)

    def fcplh_edit(self):
        keys = self._profile_list.selected
        if len(keys) != 1:
            return
        key = next(iter(keys))
        if key == self._current_session:
            return
        if not self._navigation_guard():
            return
        self._open_session(key)

    def fcplh_delete(self):
        self._profile_list.delete_selected()  # Default is pinned, so it's never included

    def _delete_profiles(self, keys: List[str]) -> None:
        was_active = _get_active_profile()
        for key in keys:
            session = self._sessions.pop(key, None)
            if session and session["saved"]:
                _delete_profile(key)
            self._profile_list.remove(key)
            if self._current_session == key:
                self._hide_editor()
                self._current_session = None
        self._refresh_mapping_combobox()
        if _get_active_profile() != was_active:
            # The deleted profile was active — config.py already fell
            # back to Default, but mapping.py still needs to hear about it.
            for callback in getattr(self.window, "_profile_change_listeners", []):
                callback()

    def _persist_profile_order(self, order: List[str]) -> None:
        saved_order = [k for k in order if self._sessions[k]["saved"]]
        _set_profile_order(saved_order)
        self._refresh_mapping_combobox()

    # --- profile edit panel ---

    def fcpeeos_switch1(self):
        enabled = bool(self.window.fcpeeos_switch1.get())
        self.window.fcpeeos_label1.configure(text=_automation_status_text(enabled))

    def fcpeeos_combobox2(self, val: str):
        pass  # browsing is driven by _open_exe_browser via the <Button-1> binding in on_start

    def _open_exe_browser(self) -> str:
        path = filedialog.askopenfilename(title="Select a program", filetypes=EXE_FILETYPES)
        if path:
            self._current_exe_path = path
            self.window.fcpeeos_combobox2.set(Path(path).name)
        return "break"  # don't let the click also open the (now-unused) dropdown list

    def fcpeeos_entry3(self, val: str):
        pass  # capture is driven by ui_utils.bind_hotkey_capture, not this event

    def fcpeenn_cancel1(self):
        if not self._navigation_guard():
            return
        self._discard_pending()
        self._hide_editor()

    def _save_and_unfocus(self) -> None:
        # No-op for the Default profile, same as fcpeh_save — its name
        # entry is disabled so it can't receive Enter in the first place.
        self.fcpeh_save()
        self.window.focus_set()

    def fcpeh_save(self):
        if self._current_session is None:
            return

        session = self._sessions[self._current_session]
        if self._current_session == DEFAULT_PROFILE_ID:
            name = "Default"  # locked, regardless of the (disabled) entry
        else:
            name = self.window.fcpeenn_entry1.get().strip()
            if not name:
                return

        session["display_name"] = name
        session["automation"] = {
            "enabled": bool(self.window.fcpeeos_switch1.get()),
            "exe": self._current_exe_path,
        }
        session["hotkey"] = self.window.fcpeeos_entry3.get()

        _save_profile({
            "id": self._current_session,
            "name": name,
            "mapping": session["mapping"],
            "automation": session["automation"],
            "hotkey": session["hotkey"],
        })
        session["saved"] = True

        if self._current_session in self._profile_list.buttons:
            self._profile_list.rename(self._current_session, name)
        else:
            self._profile_list.add(self._current_session, name)

        self._refresh_mapping_combobox()
        # Editor stays open — only fcpeenn_cancel1 (and switching to a
        # different row) closes it, see _on_list_select.

    # --- profile <-> mapping page link ---

    def fcgi_profile(self, val: str):
        profile_id = self._profile_id_by_name.get(val)
        if profile_id is None:
            return
        _set_active_profile(profile_id)
        for callback in getattr(self.window, "_profile_change_listeners", []):
            callback()
