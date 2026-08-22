"""Frame show/hide helper shared by navigation.py, macros.py and profiles.py.

Lives inside scripts/ itself — part of the GUI, not the wider
VaderService/VaderConfig project — so the GUI stays self-contained and
still previews/runs standalone.

A single shared geometry cache is required here: navigation.py hides
fcm_editframe/fcp_editframe on startup, and macros.py/profiles.py show
them again later. Two separate per-file caches couldn't see each
other's state.

Also owns the SelectableList helper: single click selects, double
click opens, Delete/Backspace/Ctrl+A act on whichever list currently
has focus, drag reorders, and destructive actions go through
confirm_dialog first. fcmv_macrolist, fcpl_profilelist and
fcmevm_macroactions all share this.

open_macro_action_editor is the popup macros.py uses to add/edit a
single macro action (press/release/delay) — a self-built CTkToplevel
in the same style as confirm_dialog/confirm_unsaved_changes, not a
separate CTkMaker-exported window.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

_GEOMETRY_CACHE = {}
_STRIP_KEYS = ("width", "height")

_SHIFT_MASK = 0x0001
_CONTROL_MASK = 0x0004

# Shared gray hint color for any entry field showing placeholder/hint
# text as real (not CTkEntry-native) content — see bind_single_key_capture
# and open_macro_action_editor's delay field.
PLACEHOLDER_TEXT_COLOR = "#9ea0a2"

# ---------------------------------------------------------------------------
# Toolbar button color groups
# ---------------------------------------------------------------------------

TOOLBAR_COLORS = {
    "primary": {   # Add/Record/Save actions
        "fg":    "#7DABC3",
        "hover": "#6a91a7",
    },
    "secondary": { # Edit/Delete actions
        "fg":    "#3a3d40",
        "hover": "#4a4d50",
    },
    "cancel": {    # Cancel actions
        "fg":    "#722f35",
        "hover": "#a32e38",
    },
    "accent1": {   # Reserved for future use
        "fg":    "#e0b76c",
        "hover": "#c9a05f",
    },
    "accent2": {   # Reserved for future use
        "fg":    "#8b9dc3",
        "hover": "#7a8cb0",
    },
}

def apply_toolbar_colors(window) -> None:
    """Apply color scheme to all toolbar buttons across macros/profiles/settings."""
    groups = {
        "primary":   ["fcmvh_add", "fcmevhr_record", "fcmevh_save",
                      "fcplh_add", "fcpeh_save", "fcsvh_save"],
        "secondary": ["fcmvh_edit", "fcmvh_delete",
                      "fcmevh_add", "fcmevh_edit", "fcmevh_delete",
                      "fcplh_edit", "fcplh_delete"],
        "cancel":    ["fcmevmnn_cancel1", "fcpeenn_cancel1", "fcmevhr_stop"],
        "accent1":   [],
        "accent2":   [],
    }
    for group, names in groups.items():
        colors = TOOLBAR_COLORS[group]
        for name in names:
            widget = getattr(window, name, None)
            if widget is not None:
                widget.configure(fg_color=colors["fg"], hover_color=colors["hover"])


def _coerce(value):
    # pack_info()/grid_info()/place_info() report every value as a str.
    # CTk's DPI scaling multiplies x/y by a float, which fails on a
    # str, so numeric-looking values need converting back.
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value
    return value


def hide_frame(frame) -> None:
    manager = frame.winfo_manager()
    if not manager:
        return  # already hidden

    if manager == "pack":
        _GEOMETRY_CACHE[frame] = ("pack", frame.pack_info())
        frame.pack_forget()
    elif manager == "grid":
        _GEOMETRY_CACHE[frame] = ("grid", frame.grid_info())
        frame.grid_forget()
    elif manager == "place":
        _GEOMETRY_CACHE[frame] = ("place", frame.place_info())
        frame.place_forget()


def show_frame(frame) -> None:
    if frame.winfo_manager():
        return  # already visible

    cached = _GEOMETRY_CACHE.get(frame)
    if not cached:
        return  # never hidden through this helper — nothing to restore

    manager, info = cached
    # CTk widgets set width/height at construction — pack()/grid()/place()
    # all reject them, even though *_info() reports them back.
    info = {k: _coerce(v) for k, v in info.items() if k not in _STRIP_KEYS}

    if manager == "pack":
        frame.pack(**info)
    elif manager == "grid":
        frame.grid(**info)
    elif manager == "place":
        frame.place(**info)


def animate_show_frame(window, frame, steps: int = 10, delay_ms: int = 12) -> None:
    """Optional slide-down reveal for `frame`, in place of show_frame()'s
    instant pop. Tkinter has no per-widget alpha channel, so this grows
    the frame's height from 0 to its cached value over `steps` frames
    instead of a true opacity blend.

    Only meaningfully animatable for place()-managed frames with a
    fixed height (e.g. fcm_editframe/fcp_editframe, if reconfigured to
    use place() instead of pack()/grid()).
    """
    show_frame(frame)
    cached = _GEOMETRY_CACHE.get(frame)
    if not cached or cached[0] != "place" or "height" not in cached[1]:
        return

    target_height = _coerce(cached[1]["height"])

    def _step(i: int) -> None:
        frame.configure(height=max(1, int(target_height * i / steps)))
        if i < steps:
            window.after(delay_ms, lambda: _step(i + 1))

    _step(1)


def animate_hide_frame(window, frame, steps: int = 10, delay_ms: int = 12) -> None:
    """Reverse of animate_show_frame() — shrinks height to 0, then calls
    hide_frame(). Same place()/fixed-height requirement applies."""
    cached = _GEOMETRY_CACHE.get(frame)
    if not cached or cached[0] != "place" or "height" not in cached[1]:
        hide_frame(frame)
        return

    target_height = _coerce(cached[1]["height"])

    def _step(i: int) -> None:
        if i <= 0:
            hide_frame(frame)
            return
        frame.configure(height=max(1, int(target_height * i / steps)))
        window.after(delay_ms, lambda: _step(i - 1))

    _step(steps)


def relayout_list(list_frame, order: list, buttons: dict) -> None:
    """Grid every button in `order` into `list_frame`, one per row.

    Grid (not pack) keeps each row at a fixed height with the width
    stretching to fill — pack's fill="x" leaves rows growing to eat
    leftover vertical space in mostly-empty scrollable frames.
    """
    list_frame.grid_columnconfigure(0, weight=1)
    for i, key in enumerate(order):
        buttons[key].grid(row=i, column=0, sticky="ew", pady=2)


def resolve_button(widget, buttons: dict):
    """Walk up from `widget` to find which tracked button it belongs to.

    winfo_containing() returns whatever sub-widget is under the cursor
    (a CTkButton's internal canvas/label), not the CTkButton itself, so
    this walks the .master chain until it matches.
    """
    while widget is not None:
        for key, btn in buttons.items():
            if btn is widget:
                return key
        widget = getattr(widget, "master", None)
    return None


def highlight_selected(buttons: dict, selected_key, normal_color: str, selected_color: str) -> None:
    for key, btn in buttons.items():
        btn.configure(fg_color=selected_color if key == selected_key else normal_color)


def set_entry_value(entry, text: str) -> None:
    """Set a CTkEntry's content, restoring its placeholder_text if `text`
    is empty. delete()+insert("") doesn't bring the placeholder back on
    its own — CTkEntry only reactivates it via <FocusOut>.
    """
    entry.delete(0, "end")
    if text:
        entry.insert(0, text)
    elif hasattr(entry, "_activate_placeholder"):
        entry._activate_placeholder()


def widget_is_descendant(widget, ancestor) -> bool:
    """True if `widget` is `ancestor` or nested somewhere under it.

    Used to scope global key bindings (Delete/Backspace/Ctrl+A) to
    whichever list or field currently holds focus, so several widgets
    can share window-level bindings without stepping on each other.
    """
    while widget is not None:
        if widget is ancestor:
            return True
        widget = getattr(widget, "master", None)
    return False


def bind_list_shortcuts(window, list_frame, on_delete: Callable[[], None],
                         on_select_all: Optional[Callable[[], None]] = None) -> None:
    """Wire Delete/Backspace (and optionally Ctrl+A) so they only act
    when focus is inside `list_frame`. Bound at the window level with
    add="+" so several lists — and normal text entries elsewhere — can
    register independently.
    """
    def _delete(_event=None):
        if widget_is_descendant(window.focus_get(), list_frame):
            on_delete()

    def _select_all(_event=None):
        if on_select_all and widget_is_descendant(window.focus_get(), list_frame):
            on_select_all()
            return "break"
        return None

    window.bind_all("<Delete>", _delete, add="+")
    window.bind_all("<BackSpace>", _delete, add="+")
    if on_select_all:
        window.bind_all("<Control-a>", _select_all, add="+")


def confirm_dialog(window, title: str, message: str) -> bool:
    """Modal Yes/No prompt shared by every destructive list action.
    Blocks via wait_window, so callers can just check the return value.
    """
    result = {"confirmed": False}

    dialog = ctk.CTkToplevel(window)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.transient(window)

    ctk.CTkLabel(dialog, text=message, wraplength=300, justify="center").pack(padx=24, pady=(16, 16))

    button_row = ctk.CTkFrame(dialog, fg_color="transparent")
    button_row.pack(padx=16, pady=(0, 20))

    def _cancel():
        dialog.destroy()

    def _confirm():
        result["confirmed"] = True
        dialog.destroy()

    ctk.CTkButton(button_row, text="Cancel", width=80, fg_color="#3a3d40",
                  hover_color="#4a4d50", command=_cancel).pack(side="left", padx=6)
    ctk.CTkButton(button_row, text="Delete", width=80, fg_color="#722f35",
                  hover_color="#a32e38", command=_confirm).pack(side="left", padx=6)

    dialog.protocol("WM_DELETE_WINDOW", _cancel)
    dialog.update_idletasks()

    x = window.winfo_rootx() + (window.winfo_width() - dialog.winfo_width()) // 2
    y = window.winfo_rooty() + (window.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    dialog.grab_set()
    window.wait_window(dialog)
    return result["confirmed"]


def confirm_unsaved_changes(window, title: str, message: str) -> str:
    """Save/Discard/Cancel prompt for navigating away from a dirty
    editor. Returns "save", "discard", or "cancel".

    Closing the dialog any other way (Escape, window-close button) also
    resolves to "cancel" — the one option that can never lose data.
    """
    result = {"choice": "cancel"}

    dialog = ctk.CTkToplevel(window)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.transient(window)

    ctk.CTkLabel(dialog, text=message, wraplength=320, justify="center").pack(padx=24, pady=(16, 16))

    button_row = ctk.CTkFrame(dialog, fg_color="transparent")
    button_row.pack(padx=16, pady=(0, 20))

    def _choose(choice: str):
        result["choice"] = choice
        dialog.destroy()

    ctk.CTkButton(button_row, text="Cancel", width=80, fg_color="#3a3d40",
                  hover_color="#4a4d50", command=lambda: _choose("cancel")).pack(side="left", padx=6)
    ctk.CTkButton(button_row, text="Discard", width=80, fg_color="#722f35",
                  hover_color="#a32e38", command=lambda: _choose("discard")).pack(side="left", padx=6)
    ctk.CTkButton(button_row, text="Save", width=80, fg_color="#7dabc3",
                  hover_color="#6a91a7", command=lambda: _choose("save")).pack(side="left", padx=6)

    dialog.protocol("WM_DELETE_WINDOW", lambda: _choose("cancel"))
    dialog.bind("<Escape>", lambda e: _choose("cancel"))
    dialog.update_idletasks()

    x = window.winfo_rootx() + (window.winfo_width() - dialog.winfo_width()) // 2
    y = window.winfo_rooty() + (window.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    dialog.grab_set()
    window.wait_window(dialog)
    return result["choice"]


class SelectableList:
    """A CTkScrollableFrame full of one-per-row CTkButtons, with:

    - single click: select (supports ctrl/shift for multi-select), via `on_select`
    - double click: open (via `on_open`)
    - Delete/Backspace/toolbar Delete button: `on_delete`, after
      confirm_dialog — see `delete_selected`
    - Ctrl+A: select every row
    - drag to reorder, reported through `on_drag_end`

    `pinned` rows (e.g. the Default profile) always render first,
    can't be dragged or dragged onto, are excluded from
    delete_selected, and use `pinned_color` for their text — but stay
    otherwise selectable/openable like any other row.
    """

    def __init__(self, window, list_frame, *, make_button: Callable[[Any, str], Any],
                 on_open: Optional[Callable[[str], None]] = None,
                 on_select: Optional[Callable[[str], None]] = None,
                 on_delete: Optional[Callable[[List[str]], None]] = None,
                 on_drag_end: Optional[Callable[[List[str]], None]] = None,
                 normal_color: str = "#1f252a", selected_color: str = "#3a3d40",
                 drag_color: str = "#50597a", pinned_color: Optional[str] = None,
                 confirm_title: str = "Delete", confirm_message: Optional[Callable[[int], str]] = None):
        self.window = window
        self.list_frame = list_frame
        self._make_button = make_button
        self.on_open = on_open
        self.on_select = on_select
        self.on_delete = on_delete
        self.on_drag_end = on_drag_end
        self.normal_color = normal_color
        self.selected_color = selected_color
        self.drag_color = drag_color
        self.pinned_color = pinned_color
        self.confirm_title = confirm_title
        self.confirm_message = confirm_message or (
            lambda n: f"Delete {n} item{'s' if n != 1 else ''}? \nThis can't be undone!"
        )

        self.buttons: Dict[str, Any] = {}
        self.order: List[str] = []
        self.pinned: Set[str] = set()
        self.selected: Set[str] = set()
        self.anchor: Optional[str] = None
        self._drag_key: Optional[str] = None

        bind_list_shortcuts(window, list_frame, self.delete_selected, self.select_all)

    # --- row management ---

    def add(self, key: str, text: str, pinned: bool = False) -> Any:
        button = self._make_button(self.list_frame, text)
        button.bind("<ButtonPress-1>", lambda e, k=key: self._on_press(e, k), add="+")
        button.bind("<B1-Motion>", self._on_motion, add="+")
        button.bind("<ButtonRelease-1>", self._on_release, add="+")
        button.bind("<Double-Button-1>", lambda e, k=key: self._open(k), add="+")

        self.buttons[key] = button
        if pinned:
            self.pinned.add(key)
            self.order.insert(0, key)
        else:
            self.order.append(key)

        self.relayout()
        return button

    def remove(self, key: str) -> None:
        button = self.buttons.pop(key, None)
        if button is not None:
            button.destroy()
        if key in self.order:
            self.order.remove(key)
        self.pinned.discard(key)
        self.selected.discard(key)
        if self.anchor == key:
            self.anchor = None

    def rename(self, key: str, text: str) -> None:
        if key in self.buttons:
            self.buttons[key].configure(text=text)

    def relayout(self) -> None:
        relayout_list(self.list_frame, self.order, self.buttons)
        self._highlight()

    # --- selection ---

    def select_only(self, key: Optional[str]) -> None:
        self.selected = {key} if key else set()
        self.anchor = key
        self._highlight()

    def select_all(self):
        self.selected = set(self.order)
        self.anchor = self.order[-1] if self.order else None
        self._highlight()
        return "break"

    def clear_selection(self) -> None:
        self.selected = set()
        self.anchor = None
        self._highlight()

    def delete_selected(self) -> None:
        keys = [k for k in self.selected if k not in self.pinned]
        if not keys or self.on_delete is None:
            return
        if not confirm_dialog(self.window, self.confirm_title, self.confirm_message(len(keys))):
            return
        self.on_delete(keys)

    def _highlight(self) -> None:
        for key, btn in self.buttons.items():
            btn.configure(fg_color=self.selected_color if key in self.selected else self.normal_color)
            if self.pinned_color and key in self.pinned:
                btn.configure(text_color=self.pinned_color)

    # --- open ---

    def _open(self, key: str) -> None:
        self.select_only(key)
        if self.on_open:
            self.on_open(key)

    # --- click / drag ---

    def _on_press(self, event, key: str) -> None:
        shift = bool(event.state & _SHIFT_MASK)
        ctrl = bool(event.state & _CONTROL_MASK)

        if shift and self.anchor in self.order:
            lo, hi = sorted((self.order.index(self.anchor), self.order.index(key)))
            self.selected = set(self.order[lo:hi + 1])
        elif ctrl:
            self.selected.symmetric_difference_update({key})
            self.anchor = key
        else:
            self.selected = {key}
            self.anchor = key
            if self.on_select:
                self.on_select(key)

        self._highlight()
        self.buttons[key].focus_set()

        if key not in self.pinned:
            self._drag_key = key
            button = self.buttons[key]
            # CTkButton's text renders via a separate child Label that
            # also fires <Enter> -> hover repaint. Disabling hover here
            # stops it from overwriting drag_color mid-drag; see
            # _on_release for the matching re-enable.
            button.configure(fg_color=self.drag_color, hover=False)

    def _on_motion(self, event) -> None:
        if self._drag_key is None:
            return
        target = event.widget.winfo_containing(event.x_root, event.y_root)
        target_key = resolve_button(target, self.buttons)
        if target_key is None or target_key == self._drag_key or target_key in self.pinned:
            return
        i, j = self.order.index(self._drag_key), self.order.index(target_key)
        self.order[i], self.order[j] = self.order[j], self.order[i]
        relayout_list(self.list_frame, self.order, self.buttons)

    def _on_release(self, _event) -> None:
        if self._drag_key is not None:
            button = self.buttons.get(self._drag_key)
            if button is not None:
                button.configure(hover=True)
            if self.on_drag_end:
                self.on_drag_end(list(self.order))
            self._drag_key = None
        self._highlight()


_MODIFIER_ORDER = ("Control", "Alt", "Shift", "Super")

_KEYSYM_LABELS = {
    "Control_L": "Ctrl", "Control_R": "Ctrl",
    "Alt_L": "Alt", "Alt_R": "Alt",
    "Shift_L": "Shift", "Shift_R": "Shift",
    "Super_L": "Win", "Super_R": "Win",
    "Escape": "Esc", "Return": "Enter", "space": "Space",
    "Left": "Left", "Right": "Right", "Up": "Up", "Down": "Down",
    "Delete": "Delete", "BackSpace": "Backspace", "Tab": "Tab",
    "Prior": "PageUp", "Next": "PageDown", "Home": "Home", "End": "End",
}


def _hotkey_label(keysym: str) -> str:
    if keysym in _KEYSYM_LABELS:
        return _KEYSYM_LABELS[keysym]
    if len(keysym) == 1:
        return keysym.upper()
    return keysym


def _hotkey_sort_key(keysym: str):
    base = keysym.split("_")[0]
    if base in _MODIFIER_ORDER:
        return (_MODIFIER_ORDER.index(base), "")
    return (len(_MODIFIER_ORDER), _hotkey_label(keysym))


def bind_hotkey_capture(window, entry, on_captured=None) -> None:
    """Wire `entry` so a click starts live hotkey capture: keys fill in
    as they go down, in a fixed Ctrl+Alt+Shift+Key order, and capture
    ends once every held key comes back up. Shared by fcpeeos_entry3
    (profiles.py) and fcgafskk_entry (mapping.py).

    Captured keys are bound at the Tkinter level (KeyPress/KeyRelease
    on `entry`, swallowed with "break") rather than a global OS hook,
    so this only needs the field focused, not elevated permissions.
    The held/peak sets stop a key released and pressed again mid-combo
    from appearing twice.

    `on_captured(text)`, if given, fires once when capture ends — use
    it when the field has no separate Save button and the value needs
    to persist immediately (mapping.py). profiles.py doesn't need it,
    since fcpeh_save reads the entry directly.
    """
    state = {"active": False, "held": set(), "peak": set()}

    def _render() -> str:
        return "+".join(_hotkey_label(k) for k in sorted(state["peak"], key=_hotkey_sort_key))

    def _update_entry() -> None:
        entry.delete(0, "end")
        entry.insert(0, _render())

    def _on_press(event):
        if not state["active"]:
            return "break"  # focused without a click (e.g. pre-filled for editing) — stay read-only
        state["held"].add(event.keysym)
        state["peak"].add(event.keysym)
        _update_entry()
        return "break"

    def _on_release(event):
        if not state["active"]:
            return None
        state["held"].discard(event.keysym)
        if not state["held"] and state["peak"]:
            state["active"] = False
            if on_captured:
                text = _render()
                window.after(0, lambda: on_captured(text))
            # Release focus once captured so arrow keys/Backspace/Delete
            # can't then edit the result as ordinary text.
            window.after(0, window.focus_set)
        return "break"

    def _start(_event=None) -> None:
        state["active"] = True
        state["held"] = set()
        state["peak"] = set()
        entry.delete(0, "end")
        entry.focus_set()

    def _swallow_navigation(_event=None):
        # Tab (and Shift-Tab) trigger Tk's focus-traversal via a
        # separate binding path from generic <KeyPress>, so "break"
        # from _on_press alone doesn't stop focus jumping mid-capture.
        if state["active"]:
            return "break"
        return None

    entry.bind("<Button-1>", _start)
    entry.bind("<KeyPress>", _on_press)
    entry.bind("<KeyRelease>", _on_release)
    # ISO_Left_Tab (the X11/Linux keysym for Shift+Tab some window
    # managers send) isn't included — Tk on Windows raises TclError at
    # bind time for it. <Shift-Tab> alone already covers Windows.
    for sequence in ("<Tab>", "<Shift-Tab>"):
        try:
            entry.bind(sequence, _swallow_navigation, add="+")
        except tk.TclError:
            pass


def bind_single_key_capture(window, entry, on_captured=None):
    """Like bind_hotkey_capture, but captures exactly one physical key
    instead of a held combo, for the Macroaction editor's press/release
    fields: a macro "press"/"release" action represents a single
    physical key event, not a chord.

    Shift/Ctrl/Alt/Super may be held *before* the deciding key without
    ending the capture — that's what lets Shift+A resolve to "A", or
    Ctrl+Alt+E to "€", with the *resulting* character captured instead
    of ending on the first modifier. While modifiers are held, the
    entry renders them live in press order (not the fixed
    Ctrl/Alt/Shift/Super convention bind_hotkey_capture uses, since
    there's no saved shortcut to normalize here). A non-modifier key
    replaces that live display with the resolved character and ends
    capture.

    The character is read from event.char (what Tk/the OS/the active
    layout resolved the combination to), not derived from event.keysym
    — keysym reports e.g. "EuroSign" for Ctrl+Alt+E, not "€", and Tk
    already does the layout resolution for us via event.char.

    If every held modifier comes back up without another key ever
    being pressed, that modifier alone is captured (e.g. a standalone
    "press Shift" action); if more than one was held, the first one
    pressed is captured.

    Returns the `arm` function so a caller can start capture
    programmatically. `arm(placeholder)` clears any actual text and
    shows `placeholder` as grayed-out hint text — visible but never
    treated as a confirmed value.

    entry._is_placeholder tracks whether the currently shown text is a
    hint (True) or an actual resolved value (False). Callers must check
    getattr(entry, "_is_placeholder", False) alongside the usual
    "is it empty" check before persisting.
    """
    _MODIFIER_KEYSYMS = {
        "Shift_L", "Shift_R",
        "Control_L", "Control_R",
        "Alt_L", "Alt_R",
        "Super_L", "Super_R",
    }

    state = {
        "active": False, "held": [], "peak": [],
        "normal_color": entry.cget("text_color"),
    }
    entry._is_placeholder = False

    def _render_held() -> str:
        return "+".join(_hotkey_label(k) for k in state["peak"])

    def _update_live_display() -> None:
        entry.configure(placeholder_text="", text_color=state["normal_color"])
        entry.delete(0, "end")
        entry.insert(0, _render_held())
        entry._is_placeholder = True

    def _finalize(label: str) -> None:
        state["active"] = False
        entry.configure(placeholder_text="", text_color=state["normal_color"])
        entry.delete(0, "end")
        entry.insert(0, label)
        entry._is_placeholder = False
        if on_captured:
            window.after(0, lambda: on_captured(label))
        window.after(0, window.focus_set)

    def _on_press(event):
        if not state["active"]:
            return "break"

        keysym = event.keysym
        if keysym in _MODIFIER_KEYSYMS:
            if keysym not in state["held"]:
                state["held"].append(keysym)
            if keysym not in state["peak"]:
                state["peak"].append(keysym)
            _update_live_display()
            return "break"

        char = event.char
        if char == " ":
            label = "Space"
        elif char and char.isprintable() and len(char) == 1:
            label = char
        else:
            label = _hotkey_label(keysym)

        _finalize(label)
        return "break"

    def _on_release(event):
        if not state["active"]:
            return None
        keysym = event.keysym
        if keysym in _MODIFIER_KEYSYMS:
            if keysym in state["held"]:
                state["held"].remove(keysym)
            if not state["held"] and state["peak"]:
                _finalize(_hotkey_label(state["peak"][0]))
            return "break"
        return None

    def arm(placeholder: str = "") -> None:
        state["active"] = True
        state["held"] = []
        state["peak"] = []
        entry.configure(placeholder_text="")
        entry.delete(0, "end")
        if placeholder:
            # Inserted as real, gray-colored content rather than via
            # placeholder_text — CTkEntry clears that on focus, and
            # this is focused immediately below.
            entry.insert(0, placeholder)
            entry.configure(text_color=PLACEHOLDER_TEXT_COLOR)
            entry._is_placeholder = True
        else:
            entry.configure(text_color=state["normal_color"])
            entry._is_placeholder = False
        entry.focus_set()

    def _swallow_navigation(_event=None):
        if state["active"]:
            return "break"
        return None

    entry.bind("<Button-1>", lambda e: arm())
    entry.bind("<KeyPress>", _on_press)
    entry.bind("<KeyRelease>", _on_release)
    for sequence in ("<Tab>", "<Shift-Tab>"):
        try:
            entry.bind(sequence, _swallow_navigation, add="+")
        except tk.TclError:
            pass

    return arm


def open_macro_action_editor(window, action=None):
    """Modal popup to add or edit one macro action (press / release /
    delay). Built like confirm_dialog/confirm_unsaved_changes — a plain
    CTkToplevel constructed fresh per call and torn down via
    wait_window.

    Returns the new/edited action dict, or None if the user cancelled.
    Pass an existing action dict via `action` to pre-fill for editing;
    omit it to add a new one.

    Manual entries never get a scan_code — only actions captured
    through macros.py's keyboard-hook recording do — except when
    editing and the key is left unchanged, in which case the original
    scan_code carries over.

    Pressing Enter while a press/release/delay entry is focused is
    consumed by that entry's own key handler (capture, or delay-digit
    filtering) and never reaches the dialog-level <Return> (Save)
    binding until a later Enter press, once focus has already left the
    entry.

    Entries can show grayed-out hint text that must never be persisted
    as if the user had confirmed it — each entry's `_is_placeholder`
    attribute tracks this; _save() checks it first.
    """
    try:
        from navigation import BTN_DEFAULT_COLOR, BTN_DEFAULT_HOVER, BTN_ACTIVE_COLOR, BTN_ACTIVE_HOVER
    except ImportError:
        from .navigation import BTN_DEFAULT_COLOR, BTN_DEFAULT_HOVER, BTN_ACTIVE_COLOR, BTN_ACTIVE_HOVER

    MODE_ORDER = ("press", "release", "delay")
    MODE_LABELS = {"press": "Press", "release": "Release", "delay": "Delay"}
    MODE_PLACEHOLDERS = {"press": "Press key...", "release": "Release key...", "delay": "Delay in ms..."}
    ENTRY_TEXT_COLOR = "#dce4ee"

    if action is not None:
        initial_mode = "delay" if action["type"] == "wait" else action["type"]
        initial_value = str(action["ms"]) if initial_mode == "delay" else str(action.get("key", ""))
        initial_scan_code = action.get("scan_code") if initial_mode != "delay" else None
    else:
        initial_mode = "press"
        initial_value = ""
        initial_scan_code = None

    result = {"action": None}
    state = {"mode": initial_mode}

    dialog = ctk.CTkToplevel(window)
    dialog.title("Macro Action")
    dialog.resizable(False, False)
    dialog.transient(window)

    mode_row = ctk.CTkFrame(dialog, fg_color="transparent")
    mode_row.pack(padx=24, pady=(24, 14))

    # Width (204) matches button_row's rendered width (2 * 90 + 4 * 6)
    # so the entry lines up with the Cancel/Save buttons below it.
    entry_area = ctk.CTkFrame(dialog, width=252, height=30, fg_color="transparent")
    entry_area.pack(padx=24, pady=(0, 26))
    entry_area.pack_propagate(False)

    button_row = ctk.CTkFrame(dialog, fg_color="transparent")
    button_row.pack(pady=(0, 20))

    mode_buttons = {}
    entries = {}
    arm_fns = {}

    def _filter_delay_input(event):
        if event.keysym in ("BackSpace", "Delete", "Left", "Right", "Tab", "Return"):
            return None
        if event.char and not event.char.isdigit():
            return "break"
        if event.char and entries["delay"]._is_placeholder:
            entries["delay"].delete(0, "end")
            entries["delay"].configure(text_color=ENTRY_TEXT_COLOR)
            entries["delay"]._is_placeholder = False
        return None

    def _set_mode(mode: str) -> None:
        if mode != state["mode"]:
            for entry in entries.values():
                entry.delete(0, "end")
        state["mode"] = mode
        for name, btn in mode_buttons.items():
            active = name == mode
            btn.configure(
                fg_color=BTN_ACTIVE_COLOR if active else BTN_DEFAULT_COLOR,
                hover_color=BTN_ACTIVE_HOVER if active else BTN_DEFAULT_HOVER,
            )
        entries[mode].tkraise()
        if mode == "delay":
            delay_entry = entries["delay"]
            if not delay_entry.get():
                delay_entry.insert(0, MODE_PLACEHOLDERS["delay"])
                delay_entry.configure(text_color=PLACEHOLDER_TEXT_COLOR)
                delay_entry._is_placeholder = True
            delay_entry.focus_set()
        else:
            hint = initial_value if (mode == initial_mode and initial_value) else MODE_PLACEHOLDERS[mode]
            arm_fns[mode](hint)

    for mode in MODE_ORDER:
        btn = ctk.CTkButton(
            mode_row, text=MODE_LABELS[mode], width=80, height=40, corner_radius=6,
            border_width=1, border_color="#38454e", text_color="#f5f5f5", full_circle=True,
            fg_color=BTN_DEFAULT_COLOR, hover_color=BTN_DEFAULT_HOVER,
            command=lambda m=mode: _set_mode(m),
        )
        btn.pack(side="left", padx=3)
        mode_buttons[mode] = btn

        entry = ctk.CTkEntry(
            entry_area, height=40, corner_radius=6, border_width=2, border_color="#565b5e",
            placeholder_text=MODE_PLACEHOLDERS[mode], fg_color="#343638", text_color=ENTRY_TEXT_COLOR,
            placeholder_text_color=PLACEHOLDER_TEXT_COLOR, justify="center",
        )
        entry.place(x=0, y=0, relwidth=1, relheight=1)
        entry._is_placeholder = False
        entries[mode] = entry

        if mode == "delay":
            entry.bind("<KeyPress>", _filter_delay_input, add="+")
        else:
            arm_fns[mode] = bind_single_key_capture(dialog, entry)

    if initial_mode == "delay" and initial_value:
        entries["delay"].insert(0, initial_value)
        entries["delay"]._is_placeholder = False

    def _cancel():
        result["action"] = None
        dialog.destroy()

    def _save():
        mode = state["mode"]
        entry = entries[mode]
        if getattr(entry, "_is_placeholder", False):
            return
        value = entry.get().strip()
        if not value:
            return
        if mode == "delay":
            try:
                ms = int(value)
            except ValueError:
                messagebox.showwarning(
                    "Invalid Delay", "Delay must be a whole number of milliseconds.", parent=dialog,
                )
                return
            result["action"] = {"type": "wait", "ms": ms}
        else:
            new_action = {"type": mode, "key": value}
            if mode == initial_mode and value == initial_value and initial_scan_code is not None:
                new_action["scan_code"] = initial_scan_code
            result["action"] = new_action
        dialog.destroy()

    ctk.CTkButton(button_row, text="Cancel", width=80, fg_color="#722f35",
                  hover_color="#a32e38", command=_cancel).pack(side="left", padx=6)
    ctk.CTkButton(button_row, text="Save", width=80, fg_color="#7dabc3",
                  hover_color="#6a91a7", command=_save).pack(side="left", padx=6)

    dialog.protocol("WM_DELETE_WINDOW", _cancel)
    dialog.bind("<Escape>", lambda e: _cancel())
    dialog.bind("<Return>", lambda e: _save())
    dialog.update_idletasks()

    x = window.winfo_rootx() + (window.winfo_width() - dialog.winfo_width()) // 2
    y = window.winfo_rooty() + (window.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    _set_mode(initial_mode)

    dialog.grab_set()
    window.wait_window(dialog)
    return result["action"]


def lock_combobox_typing(combobox) -> None:
    """Turn a CTkComboBox into selection-only: typing, cursor movement,
    and character-by-character Backspace/Delete are all blocked (mouse
    clicks on the dropdown still work) — Backspace/Delete instead clear
    the field in one step. Shared by fcgi_profile, fcgafsmm_combobox,
    fcpeeos_combobox2 and fsnc_controllers.

    Note: .set("") here does not invoke the combobox's `command`
    callback — only an actual dropdown selection does.
    """
    def _on_key(event):
        if event.keysym in ("BackSpace", "Delete"):
            combobox.set("")
        return "break"

    combobox.bind("<Key>", _on_key, add="+")


def redirect_dropdown_arrow_to_action(combobox, action: Callable[[], Any]) -> None:
    """Make `combobox`'s own dropdown arrow trigger `action` instead of
    opening its (real or empty) value list, as long as `combobox` has
    no configured `values`. Stops redirecting once values are actually
    populated.

    Needed for fcpeeos_combobox2, which is a file-browse trigger, not a
    real choice list. CTkComboBox.bind() only ever forwards to the
    inner text Entry, never to the canvas the dropdown arrow is drawn
    on — the arrow is a separate hit area, wired via
    canvas.tag_bind("dropdown_arrow", ...) inside CTkComboBox's own
    __init__, before this function ever runs, so overriding an instance
    method afterward has no effect. The only way to intercept it is a
    second, independent binding on the same canvas tag (Tk fires every
    binding registered via add="+", so this doesn't disturb the
    original).

    No-op if the installed customtkinter version doesn't expose the
    expected `_canvas` attribute.
    """
    canvas = getattr(combobox, "_canvas", None)
    if canvas is None:
        return

    def _on_arrow_click(_event=None):
        if not combobox.cget("values"):
            action()

    for tag in ("dropdown_arrow", "right_parts"):
        try:
            canvas.tag_bind(tag, "<Button-1>", _on_arrow_click, add="+")
        except tk.TclError:
            pass
