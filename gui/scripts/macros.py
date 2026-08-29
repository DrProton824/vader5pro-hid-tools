#
# gui/scripts/macros.py
# Create/edit/delete macros and manage macro actions.
#

"""
SESSIONS
  Each fcmv_macrolist entry is a "session" — a stable key independent of the macro's
  display name. fcmvh_add creates an in-memory, unsaved session. Nothing appears in
  fcmv_macrolist (or fcgafsmm_combobox) until fcmevh_save runs. Cancel or navigating
  away discards unsaved sessions (see _discard_pending and window._editor_close_listeners).

SELECTABLE LISTS
  fcmv_macrolist and fcmevm_macroactions use ui_utils.SelectableList: single click
  selects, double click (or Edit button) opens, Delete/Backspace/Ctrl+A act on the
  focused list. Deletes confirm via ui_utils.confirm_dialog before calling back.

ACTION KEYS
  fcmevm_macroactions entries keyed by fresh UUIDs each rebuild (_action_by_key),
  since action dicts have no stable id. _reorder_draft_actions and _delete_actions
  translate keys back to the actions list on the current session.

DRAFT ACTIONS
  Editing (record, add/edit, delete, drag-reorder) operates on self._draft_actions,
  a working copy snapshotted when the session opens (_open_session). Only fcmevh_save
  commits the draft to session["actions"] and disk. Cancel or switching rows discards
  the draft, leaving the session's actual actions untouched.

RECORDING
  Appends to self._draft_actions from a background keyboard-hook thread (_on_key_event).
  UI refresh throttled (RECORD_REFRESH_THROTTLE_MS) — _flush_action_refresh only appends
  new rows (_append_new_actions) instead of rebuilding the whole list each tick.

NAVIGATION GUARD
  _navigation_guard registered on window._navigation_guards (consulted by navigation.py
  before page switches) and called from _on_list_select before switching macros. If the
  current session is dirty (_has_unsaved_changes), shows ui_utils.confirm_unsaved_changes.
  Only returns True if user picks Save or Discard — Cancel blocks navigation.

GEOMETRY CACHE
  show_frame/hide_frame from ui_utils.py share the same geometry cache as navigation.py
  (fcm_editframe hidden there, shown here).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import tkinter as tk
import customtkinter as ctk
from ctkmaker import CTkScript

try:
    from ui_utils import (
        hide_frame, show_frame, SelectableList, confirm_unsaved_changes,
        open_macro_action_editor, scroll_to_top,
    )
except ImportError:
    from .ui_utils import (
        hide_frame, show_frame, SelectableList, confirm_unsaved_changes,
        open_macro_action_editor, scroll_to_top,
    )

try:
    import keyboard
except ImportError:
    keyboard = None

try:
    from shared import config as _app_config
    _read_config = _app_config.load_config
    _write_config = _app_config.save_config
except ImportError:
    CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

    def _read_config() -> Dict[str, Any]:
        if not CONFIG_PATH.exists():
            return {}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_config(data: Dict[str, Any]) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

RECORD_REFRESH_THROTTLE_MS = 120  # coalesces bursts of key events (auto-repeat) into fewer list rebuilds

# Nav-cluster scan codes that need "extended": true recorded when they're
# the dedicated key rather than the numpad acting as navigation (Num Lock
# off) — see service/mapping/extended_keys.py's NAV_CLUSTER, which this
# must stay in sync with. Duplicated here rather than imported since gui/
# and service/ aren't assumed to share an import path.
_NAV_CLUSTER_SCAN_CODES = {71, 72, 73, 75, 77, 79, 80, 81, 82, 83}

SCAN_CODE_TO_NAME = {
    # Modifiers
    42: "shift",       # Left Shift
    54: "shift",       # Right Shift  
    29: "ctrl",        # Left or Right Ctrl — both report scan 29, indistinguishable (see extended_keys.py)
    97: "right ctrl",  # Right Ctrl (only reported distinctly on some systems)
    56: "alt",         # Left Alt
    100: "alt gr",     # Right Alt / AltGr
    91: "left windows",   # Left Windows
    92: "right windows",  # Right Windows
    93: "application",    # Application / Menu key
    
    # Common special keys that might be localized
    1: "esc",
    14: "backspace",
    15: "tab",
    28: "enter",
    57: "space",
    58: "caps lock",
    
    # Function keys (usually not localized, but good to have)
    59: "f1", 60: "f2", 61: "f3", 62: "f4",
    63: "f5", 64: "f6", 65: "f7", 66: "f8",
    67: "f9", 68: "f10", 87: "f11", 88: "f12",
}

def _normalize_key_name(event) -> str:
    if event.scan_code in SCAN_CODE_TO_NAME:
        return SCAN_CODE_TO_NAME[event.scan_code]
    return event.name.lower()

def _get_macros() -> List[Dict[str, Any]]:
    return _read_config().get("macros", [])


def _save_macro(macro: Dict[str, Any]) -> None:
    data = _read_config()
    macros = data.get("macros", [])
    for i, existing in enumerate(macros):
        if existing["name"] == macro["name"]:
            macros[i] = macro
            break
    else:
        macros.append(macro)
    data["macros"] = macros
    _write_config(data)


def _delete_macro(name: str) -> None:
    data = _read_config()
    data["macros"] = [m for m in data.get("macros", []) if m["name"] != name]
    _write_config(data)


def _set_macro_order(names: List[str]) -> None:
    macros = {m["name"]: m for m in _get_macros()}
    data = _read_config()
    data["macros"] = [macros[name] for name in names if name in macros]
    _write_config(data)


def _make_list_button(parent, text: str) -> ctk.CTkButton:
    # Mirrors the color theme of fcmvm_example. Not placed here —
    # SelectableList/relayout_list grids it once the row is added.
    return ctk.CTkButton(
        parent, text=text, height=30, width=140,
        fg_color="#262d33", hover_color="#3a3d40",
        text_color="#f5f5f5", corner_radius=6,
        anchor="w", font=ctk.CTkFont(size=17),
    )


def _make_action_button(parent, text: str) -> ctk.CTkButton:
    return ctk.CTkButton(
        parent, text=text, height=25, width=140,
        fg_color="#1f252a", hover_color="#3a3d40",
        text_color="#f5f5f5", corner_radius=6,
        anchor="w", font=ctk.CTkFont(size=13),
    )


class Macros(CTkScript):

    def on_start(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._current_session: Optional[str] = None
        self._action_by_key: Dict[str, Dict[str, Any]] = {}
        self._draft_actions: List[Dict[str, Any]] = []

        self._recording = False
        self._refresh_pending = False
        self._pressed_keys: set = set()
        self._skip_next_wait = False
        
        self.window.fcmevmnn_entry1.bind("<Return>", lambda e: self._save_and_unfocus())

        self.window.fcmvm_example.destroy()

        self._macro_list = SelectableList(
            self.window, self.window.fcmv_macrolist,
            make_button=_make_list_button,
            on_open=self._open_session,
            on_select=self._on_list_select,
            on_delete=self._delete_sessions,
            on_drag_end=self._persist_macro_order,
            confirm_title="Delete Macro",
            confirm_message=lambda n: f"Delete {n} macro{'s' if n != 1 else ''}? This can't be undone.",
        )
        self._action_list = SelectableList(
            self.window, self.window.fcmevm_macroactions,
            make_button=_make_action_button,
            on_open=self._open_action_editor,
            on_delete=self._delete_actions,
            on_drag_end=self._reorder_draft_actions,
            confirm_title="Delete Action",
            confirm_message=lambda n: f"Delete {n} action{'s' if n != 1 else ''}?",
        )

        for macro in _get_macros():
            self._sessions[macro["name"]] = self._new_session_dict(
                macro["name"], saved=True, actions=list(macro["actions"]),
            )
            self._macro_list.add(macro["name"], macro["name"])
        self._refresh_macro_combobox()

        # fcmevhr_record / fcmevhr_stop occupy the same grid cell — a
        # fixed overlapping pair, toggled with tkraise() like the
        # segment button in navigation.py.
        self.window.fcmevhr_record.tkraise()

        self.window.__dict__.setdefault("_editor_close_listeners", []).append(
            lambda: self._discard_pending()
        )
        self.window.__dict__.setdefault("_navigation_guards", []).append(self._navigation_guard)

    def on_close(self):
        # keyboard.hook() installs a system-wide low-level hook — leaving
        # it active while the process tears down is exactly the kind of
        # state a global input hook should never be left in, especially
        # alongside another low-level input hook/driver (the Flydigi
        # SpaceStation software) also watching the same input stream.
        # Closing the window mid-recording must unhook it in an orderly
        # way rather than relying on process teardown to clean it up.
        if self._recording:
            self.fcmevhr_stop()

    # --- sessions ---

    def _new_session_dict(self, display_name: str, saved: bool, actions=None) -> Dict[str, Any]:
        return {
            "saved": saved,
            "display_name": display_name,
            "actions": actions if actions is not None else [],
        }

    def _discard_pending(self, keep: Optional[str] = None) -> None:
        # Drops the current session if it was never saved (no list
        # button exists for it) — used by Cancel and by page-navigation
        # forcing the editor closed. `keep` lets _open_session reuse
        # this without touching _current_session itself.
        if self._current_session and self._current_session != keep \
                and self._current_session not in self._macro_list.buttons:
            self._sessions.pop(self._current_session, None)
        if keep is None:
            self._current_session = None

    def _show_editor(self) -> None:
        show_frame(self.window.fcm_editframe)
        show_frame(self.window.fcm_frameR)

    def _hide_editor(self) -> None:
        hide_frame(self.window.fcm_editframe)
        hide_frame(self.window.fcm_frameR)

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
        current_name = self.window.fcmevmnn_entry1.get().strip()
        return current_name != session["display_name"] or self._draft_actions != session["actions"]

    def _navigation_guard(self) -> bool:
        if not self._has_unsaved_changes():
            return True
        choice = confirm_unsaved_changes(
            self.window, "Unsaved Changes",
            "This macro has unsaved changes. \nSave changes before leaving?",
        )
        if choice == "save":
            self.fcmevh_save()
            return True
        return choice == "discard"

    def _on_list_select(self, session_key: str) -> None:
        # A plain click on a different row while the editor is open
        # closes it the same way Cancel would — opening (double click /
        # Edit) is handled elsewhere and doesn't go through here.
        if session_key == self._current_session or not self.window.fcm_editframe.winfo_manager():
            return
        if self._recording:
            self.fcmevhr_stop()  # never let recording keep writing into a session we're leaving
        if not self._navigation_guard():
            self._macro_list.select_only(self._current_session)  # user cancelled — restore the old selection
            return
        self._discard_pending()
        self._hide_editor()

    def _open_session(self, session_key: str) -> None:
        if session_key == self._current_session:
            # Already open. Double-click and the Edit button both route
            # here without going through _navigation_guard() first (see
            # _on_list_select and fcmvh_edit for the equivalent guard on
            # the other paths) -- without this, re-opening the same
            # macro silently reloads session["actions"], discarding any
            # unsaved edits in self._draft_actions/the name field.
            return
        if self._recording:
            self.fcmevhr_stop()
        self._discard_pending(keep=session_key)
        self._current_session = session_key
        session = self._sessions[session_key]
        self._macro_list.select_only(session_key)
        self.window.fcmevmnn_entry1.delete(0, "end")
        self.window.fcmevmnn_entry1.insert(0, session["display_name"])
        self._draft_actions = [dict(action) for action in session["actions"]]
        self._refresh_action_list()
        scroll_to_top(self.window.fcmevm_macroactions)
        self._show_editor()
        self.window.fcmevmnn_entry1.focus_set()

    def _refresh_macro_combobox(self) -> None:
        # Same pattern as profiles.py's fcgi_profile <-> fcpl_profilelist link.
        # Use live list order instead of self._sessions (which reflects creation order).
        names = [
            self._sessions[k]["display_name"]
            for k in self._macro_list.order
            if k in self._sessions and self._sessions[k]["saved"]
        ]
        self.window.fcgafsmm_combobox.configure(values=names)

    # --- fcmv_macrolist toolbar ---

    def fcmvh_add(self):
        if not self._navigation_guard():
            return
        session_key = uuid.uuid4().hex
        display_name = self._unique_default_name("New Macro")
        self._sessions[session_key] = self._new_session_dict(display_name, saved=False)
        self._open_session(session_key)

    def fcmvh_edit(self):
        keys = self._macro_list.selected
        if len(keys) != 1:
            return
        key = next(iter(keys))
        if key == self._current_session:
            return
        if not self._navigation_guard():
            return
        self._open_session(key)

    def fcmvh_delete(self):
        self._macro_list.delete_selected()

    def _delete_sessions(self, keys: List[str]) -> None:
        for key in keys:
            session = self._sessions.pop(key, None)
            if session and session["saved"]:
                _delete_macro(session["display_name"])
            self._macro_list.remove(key)
            if self._current_session == key:
                self._hide_editor()
                self._current_session = None
        self._macro_list.relayout()
        self._refresh_macro_combobox()

    def _persist_macro_order(self, order: List[str]) -> None:
        saved_order = [k for k in order if self._sessions[k]["saved"]]
        _set_macro_order([self._sessions[k]["display_name"] for k in saved_order])
        self._refresh_macro_combobox()

    def fcmevmnn_cancel1(self):
        if not self._navigation_guard():
            return
        self._discard_pending()
        self._hide_editor()

    def _save_and_unfocus(self) -> None:
        self.fcmevh_save()
        self.window.focus_set()

    # --- macro edit panel: actions list ---

    def _refresh_action_list(self) -> None:
        list_frame = self.window.fcmevm_macroactions
        for child in list_frame.winfo_children():
            child.destroy()

        self._action_list.buttons = {}
        self._action_list.order = []
        self._action_list.selected = set()
        self._action_list.anchor = None
        self._action_by_key = {}

        for action in self._draft_actions:
            key = uuid.uuid4().hex
            self._action_by_key[key] = action
            self._action_list.add_batch(key, self._describe_action(action))
        
        self._action_list.relayout()

    def _append_new_actions(self) -> None:
        new_actions = self._draft_actions[len(self._action_list.order):]
        if not new_actions:
            return
        
        for action in new_actions:
            key = uuid.uuid4().hex
            self._action_by_key[key] = action
            self._action_list.add_batch(key, self._describe_action(action))
        
        self._action_list.relayout()

        canvas = getattr(self.window.fcmevm_macroactions, "_parent_canvas", None)
        if canvas is not None:
            try:
                canvas.yview_moveto(1.0)
            except tk.TclError:
                pass

    @staticmethod
    def _describe_action(action: Dict[str, Any]) -> str:
        if action["type"] == "wait":
            return f"wait {action['ms']}ms"
        key_display = action.get("key", f"scan:{action.get('scan_code', '?')}")
        return f"{action['type']} {key_display}"

    def fcmevh_add(self):
        if self._current_session is None:
            return
        action = open_macro_action_editor(self.window)
        if action is not None:
            self._on_action_added(action)

    def fcmevh_edit(self):
        if len(self._action_list.selected) != 1:
            return
        self._open_action_editor(next(iter(self._action_list.selected)))

    def _open_action_editor(self, key: str) -> None:
        action = self._action_by_key.get(key)
        if action is None:
            return
        new_action = open_macro_action_editor(self.window, action=action)
        if new_action is not None:
            self._on_action_edited(key, new_action)

    def _on_action_added(self, action: Dict[str, Any]) -> None:
        anchor_key = self._action_list.anchor
        anchor_action = self._action_by_key.get(anchor_key) if anchor_key else None
        index = self._index_after(self._draft_actions, anchor_action)
        self._draft_actions.insert(index, action)
        self._refresh_action_list()

    def _on_action_edited(self, key: str, new_action: Dict[str, Any]) -> None:
        old_action = self._action_by_key.get(key)
        for i, existing in enumerate(self._draft_actions):
            if existing is old_action:
                self._draft_actions[i] = new_action
                break
        self._refresh_action_list()

    @staticmethod
    def _index_after(actions: List[Dict[str, Any]], anchor_action: Optional[Dict[str, Any]]) -> int:
        # Identity (`is`), not equality — two actions can have identical
        # content (e.g. two "wait 500ms" entries), and this has to
        # resolve to the specific row that was selected.
        if anchor_action is None:
            return len(actions)
        for i, existing in enumerate(actions):
            if existing is anchor_action:
                return i + 1
        return len(actions)

    def fcmevh_delete(self):
        self._action_list.delete_selected()

    def _delete_actions(self, keys: List[str]) -> None:
        remove_ids = {id(self._action_by_key[k]) for k in keys if k in self._action_by_key}
        self._draft_actions = [a for a in self._draft_actions if id(a) not in remove_ids]
        self._refresh_action_list()

    def _reorder_draft_actions(self, order: List[str]) -> None:
        self._draft_actions = [self._action_by_key[k] for k in order]

    def fcmevh_save(self):
        if self._current_session is None:
            return
        name = self.window.fcmevmnn_entry1.get().strip()
        if not name:
            return

        session = self._sessions[self._current_session]
        if session["saved"] and session["display_name"] != name:
            _delete_macro(session["display_name"])

        session["actions"] = list(self._draft_actions)
        _save_macro({"name": name, "actions": session["actions"]})
        session["saved"] = True
        session["display_name"] = name

        if self._current_session in self._macro_list.buttons:
            self._macro_list.rename(self._current_session, name)
        else:
            self._macro_list.add(self._current_session, name)

        self._refresh_macro_combobox()
        # Editor stays open — only fcmevmnn_cancel1 (and switching to a
        # different row) closes it, see _on_list_select.

    # --- recording ---

    def fcmevhr_record(self):
        if self._recording or self._current_session is None:
            return
        if keyboard is None:
            from tkinter import messagebox
            messagebox.showerror(
                "Recording unavailable",
                "The keyboard module failed to load, so macro recording "
                "isn't available in this build. Reinstalling or "
                "re-downloading the app should fix this.",
                parent=self.window,
            )
            return
        self._recording = True
        self._last_event_time = time.monotonic()
        self._pressed_keys = set()
        self._skip_next_wait = True  # ignore the idle time before the first keystroke
        keyboard.hook(self._on_key_event)
        self.window.fcmevhr_stop.tkraise()

    def fcmevhr_stop(self):
        if not self._recording:
            return
        if keyboard is not None:
            keyboard.unhook_all()
        self._recording = False
        self._pressed_keys = set()
        self.window.fcmevhr_record.tkraise()

    def _on_key_event(self, event) -> None:
        try:
            is_press = event.event_type == "down"
            scan_code = event.scan_code
            
            if is_press and scan_code in self._pressed_keys:
                return
            if not is_press and scan_code not in self._pressed_keys:
                return 
            
            if is_press:
                self._pressed_keys.add(scan_code)
            else:
                self._pressed_keys.discard(scan_code)
            
            now = time.monotonic()
            wait_ms = round((now - self._last_event_time) * 1000)
            self._last_event_time = now

            if wait_ms > 0 and not self._skip_next_wait:
                self._draft_actions.append({"type": "wait", "ms": wait_ms})
            self._skip_next_wait = False

            action_type = "press" if is_press else "release"

            new_action = {
                "type": action_type,
                "scan_code": scan_code,
                "key": _normalize_key_name(event)
            }
            # Dedicated nav-cluster key vs. the numpad acting as navigation
            # (Num Lock off) share a scan code — only the dedicated key
            # needs the extended flag on replay. See extended_keys.py.
            if scan_code in _NAV_CLUSTER_SCAN_CODES and not getattr(event, "is_keypad", False):
                new_action["extended"] = True

            self._draft_actions.append(new_action)

            if not self._refresh_pending:
                self._refresh_pending = True
                self.window.after(RECORD_REFRESH_THROTTLE_MS, self._flush_action_refresh)
        except Exception:
            pass

    def _flush_action_refresh(self) -> None:
        self._refresh_pending = False
        self._append_new_actions()
