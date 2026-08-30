#
# gui/scripts/ui_utils.py
# Frame show/hide helpers, list management, and shared UI components.
#

"""
GEOMETRY CACHE
  Single shared _GEOMETRY_CACHE preserves pack/grid/place state across show/hide calls.
  Required because navigation.py hides fcm_editframe/fcp_editframe on startup, and
  macros.py/profiles.py show them again later — separate per-file caches couldn't
  coordinate. animate_show_frame/animate_hide_frame optionally slide-reveal instead
  of instant pop (requires place() with fixed height).

SELECTABLE LIST
  SelectableList: single click selects, double click opens, Delete/Backspace/Ctrl+A
  act on focused list, drag reorders. Supports multi-select via Shift/Ctrl. Pinned
  rows (e.g. Default profile) always render first, can't be dragged/deleted, render
  in pinned_color. Destructive actions confirm via confirm_dialog first.
  fcmv_macrolist, fcpl_profilelist, fcmevm_macroactions all use SelectableList.

DIALOGS
  confirm_dialog — modal Yes/No for destructive actions.
  confirm_unsaved_changes — modal Save/Discard/Cancel for dirty editors.
  open_macro_action_editor — CTkToplevel popup to add/edit one macro action
    (press/release/delay). Captures single keys via bind_single_key_capture.
    Returns new/edited action dict or None on cancel.

HOTKEY CAPTURE
  bind_hotkey_capture — live hotkey combo capture for fcpeeos_entry3 (profiles.py)
    and fcgafskk_entry (mapping.py). Keys fill in as held, capture ends when all
    keys release. Ctrl+Alt+Shift+Key fixed order.
  bind_single_key_capture — single physical key capture for macro press/release fields.
    Modifiers can be held before the deciding key; result is the character Tk resolved,
    not the keysym. Returns arm() function for programmatic start. entry._is_placeholder
    tracks whether shown text is hint (True) or confirmed value (False).

COMBOBOX HELPERS
  lock_combobox_typing — convert CTkComboBox to selection-only (dropdown works,
    typing/arrow keys blocked, Backspace/Delete clear field).
  redirect_dropdown_arrow_to_action — make dropdown arrow trigger custom action
    instead of opening value list, used by fcpeeos_combobox2 (file browser).

TOOLBAR COLORS
  apply_toolbar_colors — apply TOOLBAR_COLORS scheme to all toolbar buttons across
    macros/profiles/settings pages. Groups: primary (Add/Record/Save), secondary
    (Edit/Delete), cancel (Cancel/Stop), accent1/accent2 (reserved).

OTHER HELPERS
  relayout_list — grid buttons into list_frame one per row (fixed height with width stretch).
  resolve_button — walk .master chain to find which tracked button a widget belongs to.
  highlight_selected — recolor buttons by selection state.
  set_entry_value — set CTkEntry content with placeholder_text restoration on empty.
  widget_is_descendant — True if widget is ancestor or nested under it (scope bindings).
  bind_list_shortcuts — wire Delete/Backspace/Ctrl+A to list_frame when focused.
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
    """Slide-down reveal by growing height from 0 to cached value. Requires place() with fixed height."""
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


def refresh_scroll_region(scrollable_frame) -> None:
    """Recompute a CTkScrollableFrame's scrollbar range against its
    current contents.

    Needed after adding/removing rows — left stale, an emptied list keeps
    the scrollbar range/thumb size from before the last item was removed,
    since customtkinter only recomputes it off a <Configure> event that a
    frame with zero remaining children doesn't reliably fire on its own.
    Safe no-op if the frame hasn't been laid out yet or customtkinter's
    internal canvas attribute isn't present (version differences).
    """
    canvas = getattr(scrollable_frame, "_parent_canvas", None)
    if canvas is None:
        return
    try:
        # If the inner frame has no children, reset unconditionally
        if not scrollable_frame.winfo_children():
            canvas.configure(scrollregion=(0, 0, 0, 0))
            scrollable_frame.update_idletasks()
            canvas.configure(scrollregion=(0, 0, 0, 0))
            return
        scrollable_frame.update_idletasks()
        bbox = canvas.bbox("all")
        canvas.configure(scrollregion=bbox if bbox else (0, 0, 0, 0))
    except tk.TclError:
        pass


def scroll_to_top(scrollable_frame) -> None:
    """Reset a CTkScrollableFrame's scroll position to the top and fix scrollbar.
    
    For empty frames, uses a temporary dummy widget to force Tk's geometry
    manager to fire Configure events and recalculate frame size. Without
    this, a frame with zero children doesn't trigger geometry updates, leaving
    the canvas window item (and thus bbox/scrollregion) stuck at stale values
    from before the last child was removed.
    """
    canvas = getattr(scrollable_frame, "_parent_canvas", None)
    scrollbar = getattr(scrollable_frame, "_scrollbar", None)
    if canvas is None:
        return
    
    try:
        scrollable_frame.update()
    except tk.TclError:
        return
    
    has_children = bool(scrollable_frame.winfo_children())
    
    try:
        if not has_children:
            # Tk won't run geometry manager for empty frame. Force it by
            # adding a minimal dummy, letting geometry settle, then removing.
            dummy = tk.Frame(scrollable_frame, height=1, width=1)
            dummy.grid(row=0, column=0)
            scrollable_frame.update_idletasks()  # geometry manager places dummy
            dummy.destroy()
            scrollable_frame.update_idletasks()  # geometry manager removes dummy, frame truly empty now
        else:
            scrollable_frame.update_idletasks()
        
        # Now bbox("all") reflects actual current state
        bbox = canvas.bbox("all")
        canvas.configure(scrollregion=bbox if bbox else (0, 0, 1, 1))
        canvas.yview_moveto(0.0)
        
        if scrollbar is not None:
            if not has_children:
                scrollbar.set(0.0, 1.0)
            else:
                scrollbar.set(*canvas.yview())
    except tk.TclError:
        pass


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

    def add_batch(self, key: str, text: str, pinned: bool = False) -> Any:
        """Same as add(), but skips relayout() — caller must call relayout() manually after batch is done."""
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

        return button  # No relayout() call here

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
        refresh_scroll_region(self.list_frame)

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
_CAPTURE_FINALIZE_DELAY_MS = 150  # idle gap after the last key event before finalizing a combo

# Windows key keysym varies by system — "Super_L"/"Super_R" on some,
# "Win_L"/"Win_R" or "Meta_L"/"Meta_R" on others. All aliases map to "Win".
_KEYSYM_LABELS = {
    "Control_L": "Ctrl", "Control_R": "Ctrl",
    "Alt_L": "Alt", "Alt_R": "Alt",
    "Shift_L": "Shift", "Shift_R": "Shift",
    "Super_L": "Win", "Super_R": "Win",
    "Win_L": "Win", "Win_R": "Win",
    "Meta_L": "Win", "Meta_R": "Win",
    "Escape": "Esc", "Return": "Enter", "space": "Space",
    "Left": "Left", "Right": "Right", "Up": "Up", "Down": "Down",
    "Delete": "Delete", "BackSpace": "Backspace", "Tab": "Tab",
    "Prior": "PageUp", "Next": "PageDown", "Home": "Home", "End": "End",
}

# Sorts the Win_L/Meta_L aliases above into the same bucket as Super
# so modifier ordering stays correct regardless of spelling used.
_MODIFIER_BASE_ALIASES = {"Win": "Super", "Meta": "Super"}


def _hotkey_label(keysym: str) -> str:
    if keysym in _KEYSYM_LABELS:
        return _KEYSYM_LABELS[keysym]
    if len(keysym) == 1:
        return keysym.upper()
    return keysym


def _hotkey_sort_key(keysym: str):
    base = keysym.split("_")[0]
    base = _MODIFIER_BASE_ALIASES.get(base, base)
    if base in _MODIFIER_ORDER:
        return (_MODIFIER_ORDER.index(base), "")
    return (len(_MODIFIER_ORDER), _hotkey_label(keysym))


def bind_hotkey_capture(window, entry, on_captured=None) -> None:
    """Live hotkey combo capture: click to start, keys fill as held, capture ends
    _CAPTURE_FINALIZE_DELAY_MS after the last key event once nothing is held.
    Fires `on_captured(text)` when done.

    Finalizing on a short idle gap (rather than the instant `held` hits zero)
    tolerates a single dropped or reordered KeyRelease — a fast press+release
    can otherwise leave `held` never fully clearing, silently freezing capture
    until the field is re-armed and tried again more slowly.

    FocusOut finalizes any in-progress capture so that keys whose release
    events are swallowed by the OS (Win key opening the shell, Alt+Tab, etc.)
    don't leave capture frozen with the field showing text that was never saved.
    """
    state = {"active": False, "held": set(), "peak": set(), "finalize_job": None}

    def _render() -> str:
        return "+".join(_hotkey_label(k) for k in sorted(state["peak"], key=_hotkey_sort_key))

    def _update_entry() -> None:
        entry.delete(0, "end")
        entry.insert(0, _render())

    def _cancel_finalize() -> None:
        if state["finalize_job"] is not None:
            window.after_cancel(state["finalize_job"])
            state["finalize_job"] = None

    def _finalize() -> None:
        state["finalize_job"] = None
        if not state["active"] or not state["peak"]:
            state["active"] = False
            return
        state["active"] = False
        # Use on_captured when the field has no separate Save button and needs
        # to persist immediately (mapping.py does this; profiles.py doesn't,
        # since fcpeh_save reads the entry directly).
        if on_captured:
            on_captured(_render())
        # Release focus once captured so arrow keys/Backspace/Delete
        # can't then edit the result as ordinary text.
        window.focus_set()

    def _schedule_finalize() -> None:
        _cancel_finalize()
        state["finalize_job"] = window.after(_CAPTURE_FINALIZE_DELAY_MS, _finalize)

    def _on_press(event):
        if not state["active"]:
            return "break"  # focused without a click (e.g. pre-filled for editing) — stay read-only
        _cancel_finalize()  # another key joined the combo — not done yet
        state["held"].add(event.keysym)
        state["peak"].add(event.keysym)
        _update_entry()
        return "break"

    def _on_release(event):
        if not state["active"]:
            return None
        state["held"].discard(event.keysym)
        if not state["held"]:
            _schedule_finalize()
        return "break"

    def _on_focus_out(_event=None) -> None:
        # FocusOut can interrupt capture before KeyRelease arrives (Win key,
        # Alt+Tab, minimize, click elsewhere, etc.). Finalize any captured keys
        # rather than leaving capture stuck.
        #
        # Use the existing 150 ms debounce instead of finalizing immediately:
        # the Win key can cause FocusOut while still held, and the delay lets the
        # shell event settle. A subsequent keypress can still cancel finalization
        # and continue the combo if focus returns.
        if state["active"] and state["peak"]:
            _schedule_finalize()
        elif state["active"] and not state["peak"]:
            # Armed (clicked) but no key was pressed before focus left —
            # just disarm cleanly without firing on_captured with empty text.
            state["active"] = False
            _cancel_finalize()

    def _start(_event=None) -> None:
        _cancel_finalize()
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
    entry.bind("<FocusOut>", _on_focus_out)  # finalizes on OS-level focus steal


try:
    import keyboard as _keyboard
except ImportError:
    _keyboard = None

# Scan codes the `keyboard` library's key_to_scan_codes() can return an
# extended-prefixed artifact for instead of the plain byte macro playback
# expects (e.g. 57435 for "left windows" instead of 91). Same source of
# truth as service/mapping/extended_keys.py's ALWAYS_EXTENDED | NAV_CLUSTER
# — checked first, before ever asking the library for these names.
_KNOWN_SCAN_CODES = {
    "left windows": 91, "right windows": 92, "application": 93,
    "home": 71, "up": 72, "pageup": 73, "left": 75, "right": 77,
    "end": 79, "down": 80, "pagedown": 81, "insert": 82, "delete": 83,
}

# Scan codes that need "extended": true on the resulting action — same set
# as service/mapping/extended_keys.py's ALWAYS_EXTENDED | NAV_CLUSTER. A key
# typed here always means the dedicated key, never the numpad substitute, so
# unlike macros.py's live recorder there's no ambiguity to check for.
_EXTENDED_SCAN_CODES = {71, 72, 73, 75, 77, 79, 80, 81, 82, 83, 91, 92, 93}


def _resolve_scan_code(label: str) -> int | None:
    """Translate a captured key label to the same hardware scan code
    `keyboard.hook()` reports during recording (macros.py's _on_key_event).
    _KNOWN_SCAN_CODES is checked first — see its comment for why. Anything
    else falls back to the `keyboard` library's own table.
    """
    name = label.lower()
    if name in _KNOWN_SCAN_CODES:
        return _KNOWN_SCAN_CODES[name]
    if _keyboard is None:
        return None
    try:
        codes = _keyboard.key_to_scan_codes(name)
        return codes[0] if codes else None
    except (ValueError, KeyError):
        return None


def bind_single_key_capture(window, entry, on_captured=None):
    """Single physical key capture for macro press/release fields.
    Returns `arm(placeholder)` function to start capture. entry._is_placeholder tracks hint vs confirmed value."""
    # Same Win_L/Win_R/Meta_L/Meta_R aliases as _KEYSYM_LABELS above.
    _MODIFIER_KEYSYMS = {
        "Shift_L", "Shift_R",
        "Control_L", "Control_R",
        "Alt_L", "Alt_R",
        "Super_L", "Super_R",
        "Win_L", "Win_R",
        "Meta_L", "Meta_R",
    }

    # Distinct left/right labels, unlike the shared _KEYSYM_LABELS table
    # (which collapses left/right for keybind chords) — a recorded macro
    # action needs the distinction to resolve the correct scan code.
    _MODIFIER_KEY_LABELS = {
        "Shift_L": "left shift", "Shift_R": "right shift",
        "Control_L": "left ctrl", "Control_R": "right ctrl",
        "Alt_L": "left alt", "Alt_R": "right alt",
        "Super_L": "left windows", "Super_R": "right windows",
        "Win_L": "left windows", "Win_R": "right windows",
        "Meta_L": "left windows", "Meta_R": "right windows",
    }

    state = {
        "active": False, "held": [], "peak": [],
        "normal_color": entry.cget("text_color"),
    }
    entry._is_placeholder = False

    # Modifiers (Shift/Ctrl/Alt/Super) may be held before the deciding key without
    # ending capture — Shift+A resolves to "A", Ctrl+Alt+E to "€". While modifiers
    # are held, the entry shows them live in press order. A non-modifier key replaces
    # that display with the resolved character (from event.char, not keysym) and ends capture.

    def _render_held() -> str:
        return "+".join(_MODIFIER_KEY_LABELS.get(k, _hotkey_label(k)) for k in state["peak"])

    def _update_live_display() -> None:
        entry.configure(placeholder_text="", text_color=state["normal_color"])
        entry.delete(0, "end")
        entry.insert(0, _render_held())
        entry._is_placeholder = True

    def _finalize(label: str, scan_code: int | None = None) -> None:
        state["active"] = False
        entry.configure(placeholder_text="", text_color=state["normal_color"])
        entry.delete(0, "end")
        entry.insert(0, label)
        entry._is_placeholder = False
        if on_captured:
            window.after(0, lambda: on_captured(label, scan_code))
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

        _finalize(label, _resolve_scan_code(label))
        return "break"

    def _on_release(event):
        if not state["active"]:
            return None
        keysym = event.keysym
        if keysym in _MODIFIER_KEYSYMS:
            if keysym in state["held"]:
                state["held"].remove(keysym)
            # If all modifiers release without another key, capture that modifier alone
            # (e.g. a standalone "press Shift" action). If multiple were held, capture the first.
            if not state["held"] and state["peak"]:
                modifier_label = _MODIFIER_KEY_LABELS.get(state["peak"][0], _hotkey_label(state["peak"][0]))
                _finalize(modifier_label, _resolve_scan_code(modifier_label))
            return "break"
        return None

    def arm(placeholder: str = "") -> None:
        state["active"] = True
        state["held"] = []
        state["peak"] = []
        entry.configure(placeholder_text="")
        entry.delete(0, "end")
        if placeholder:
            # Show placeholder as grayed-out hint text (not via placeholder_text, which CTkEntry
            # clears on focus). Callers must check getattr(entry, "_is_placeholder", False)
            # before persisting to avoid treating hints as confirmed values.
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

    return arm


def open_macro_action_editor(window, action=None):
    """Modal popup to add or edit a macro action (press/release/delay).
    Returns the action dict, or None if cancelled. Pass `action` to pre-fill for editing."""
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
        initial_extended = action.get("extended", False) if initial_mode != "delay" else False
    else:
        initial_mode = "press"
        initial_value = ""
        initial_scan_code = None
        initial_extended = False

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
        entry._scan_code = None
        entry._extended = False
        entries[mode] = entry

        if mode == "delay":
            entry.bind("<KeyPress>", _filter_delay_input, add="+")
        else:
            def _capture_macro_key(label, scan_code, _entry=entry):
                _entry._scan_code = scan_code
                _entry._extended = scan_code in _EXTENDED_SCAN_CODES

            arm_fns[mode] = bind_single_key_capture(
                dialog,
                entry,
                on_captured=_capture_macro_key,
            )

    if initial_mode == "delay" and initial_value:
        entries["delay"].insert(0, initial_value)
        entries["delay"]._is_placeholder = False

    def _cancel():
        result["action"] = None
        dialog.destroy()

    def _save():
        mode = state["mode"]
        entry = entries[mode]
        # Each entry's _is_placeholder tracks whether the shown text is a hint
        # (True) or a confirmed value (False). _save() checks it before persisting.
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

            scan_code = getattr(entry, "_scan_code", None)

            if scan_code is not None:
                new_action["scan_code"] = scan_code
                if getattr(entry, "_extended", False):
                    new_action["extended"] = True
            elif mode == initial_mode and value == initial_value and initial_scan_code is not None:
                new_action["scan_code"] = initial_scan_code
                if initial_extended:
                    new_action["extended"] = True

            result["action"] = new_action
        dialog.destroy()

    ctk.CTkButton(button_row, text="Cancel", width=80, fg_color="#722f35",
                  hover_color="#a32e38", command=_cancel).pack(side="left", padx=6)
    ctk.CTkButton(button_row, text="Save", width=80, fg_color="#7dabc3",
                  hover_color="#6a91a7", command=_save).pack(side="left", padx=6)

    dialog.protocol("WM_DELETE_WINDOW", _cancel)
    dialog.bind("<Escape>", lambda e: _cancel())

    # Pressing Enter while a press/release/delay entry is focused is consumed
    # by that entry's own key handler (capture or digit filtering) and never
    # reaches the dialog-level <Return> binding until focus leaves the entry.
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
    """Convert CTkComboBox to selection-only: typing blocked, Backspace/Delete clear the field."""
    def _on_key(event):
        if event.keysym in ("BackSpace", "Delete"):
            combobox.set("")
        return "break"

    combobox.bind("<Key>", _on_key, add="+")


def redirect_dropdown_arrow_to_action(combobox, action: Callable[[], Any]) -> None:
    """Make dropdown arrow trigger `action` instead of opening value list. Only works if `combobox` has no configured `values`."""

    # CTkComboBox.bind() only forwards to the inner text Entry, not the canvas
    # the arrow is drawn on. We need a second binding on the canvas tag itself.
    # add="+" lets multiple bindings coexist on the same tag.
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
