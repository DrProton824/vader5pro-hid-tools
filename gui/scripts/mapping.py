#
# gui/scripts/mapping.py
# Button selection and per-profile key/macro assignment.
#

"""
BUTTON SELECTION
  Hit-testing handled by ControllerCanvas using polygon data from hit_zones.json.
  Exception: fcgi_HOME has no SVG hit zone and remains a CTkButton layered over
  the canvas (like fcgi_profile).
  
  Selecting a button loads its assignment for the active profile, switches the
  keybind/macro segment to the assigned type, and highlights the button. A button
  holds either a keybind or a macro, never both.

ASSIGNMENTS
  Stored per profile (keyed by profile id) as {"type": "keybind"|"macro", "value": "..."}.
  Extends the flat DEFAULT_MAPPING shape in config.py. shared/config.py's load_bindings()
  resolves both types for the service (see service/mapping/mapper.py and macro_player.py).

INDICATORS
  Each assigned button gets a visual indicator via _controller.set_indicator().
  Refreshed on save, profile switch, and startup.

MACROS
  fcgafsmm_combobox populated from macros.py via _refresh_macro_combobox. This module
  only reads/writes the selected assignment. Renaming or deleting an already-assigned
  macro does not update that assignment automatically.

PROFILE CHANGES
  profiles.py notifies window._profile_change_listeners when the active profile changes.
  This module registers a listener to refresh fields, selection, and indicators.

CLEARING
  Delete/Backspace clears the selected button's assignment unless focus is inside
  fcgafskk_entry or fcgafsmm_combobox.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ctkmaker import CTkScript

try:
    from ui_utils import bind_hotkey_capture, widget_is_descendant, lock_combobox_typing
except ImportError:
    from .ui_utils import bind_hotkey_capture, widget_is_descendant, lock_combobox_typing

try:
    from navigation import MAPPING_MODES
except ImportError:
    from .navigation import MAPPING_MODES

try:
    from controller_canvas import ControllerCanvas, HIGHLIGHT_COLORS, HIGHLIGHT_HOVER_COLORS
except ImportError:
    from .controller_canvas import ControllerCanvas, HIGHLIGHT_COLORS, HIGHLIGHT_HOVER_COLORS

SCRIPTS_DIR = Path(__file__).resolve().parent

# Frozen (PyInstaller onefile): __file__ resolves inside the temp
# extraction dir, not the real dist folder — assets live next to the
# exe instead (sys.executable), in the same flat assets/ folder
# service/main.py's tray icons and status.json already use.
# From source: assets live under gui/assets/ (one level above scripts/).
if getattr(sys, "frozen", False):
    ASSETS_DIR = Path(sys.executable).resolve().parent / "assets"
else:
    ASSETS_DIR = SCRIPTS_DIR.parent / "assets"

# Runtime/exported projects keep these in assets/.
# CTkMaker development exports still have them in scripts/. > fallback logic
if (ASSETS_DIR / "controller.png").exists() and (ASSETS_DIR / "hit_zones.json").exists():
    CONTROLLER_PNG = ASSETS_DIR / "controller.png"
    HIT_ZONES_JSON = ASSETS_DIR / "hit_zones.json"
else:
    CONTROLLER_PNG = SCRIPTS_DIR / "controller.png"
    HIT_ZONES_JSON = SCRIPTS_DIR / "hit_zones.json"

DEFAULT_PROFILE_ID = "default"

# fcgi_controller's design-time placement from the .ctkproj: fcg_image is
# 1030 wide, and the Image widget sits at x=30 y=0 with width=970 within
# it. fcg_image has "stretch": "fill", so its runtime width can differ
# from 1030 — _on_frame_resize rescales x and width by
# current_width / DESIGN_FRAME_WIDTH to track it.
DESIGN_FRAME_WIDTH = 1030
IMAGE_X, IMAGE_Y = 30, 0
IMAGE_DESIGN_WIDTH = 970


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


def _get_macro_names() -> List[str]:
    return [m["name"] for m in _read_config().get("macros", [])]


class Mapping(CTkScript):

    def on_start(self):
        self._selected_button: Optional[str] = None
        self._controller: Optional[ControllerCanvas] = None

        if CONTROLLER_PNG.exists() and HIT_ZONES_JSON.exists():
            self._controller = ControllerCanvas(
                self.window.fcg_image, CONTROLLER_PNG, HIT_ZONES_JSON,
                on_click=self._select_button, on_background_click=self._deselect_button,
                display_width=IMAGE_DESIGN_WIDTH,
            )
            self._controller.canvas.place(x=IMAGE_X, y=IMAGE_Y)
            self._controller.set_highlight_kind(self._mode_to_kind(self.window.fcgaf_segmentbutton.get()))
            self.window.fcg_image.bind("<Configure>", self._on_frame_resize, add="+")
            # tkinter.Canvas overrides .lower() for canvas item stacking
            # (tag_lower), not widget stacking, so it can't be used here.
            # Lifting the two widgets above the artwork achieves the same.
            self.window.fcgi_profile.lift()
            self._setup_home_button()
        else:
            print(
                f"Mapping: controller.png/hit_zones.json not found in assets/ "
                f"or scripts/ — controller image and hit zones won't be shown."
            )

        bind_hotkey_capture(self.window, self.window.fcgafskk_entry, on_captured=self._on_keybind_captured)
        self.window.fcgafsmm_combobox.configure(values=_get_macro_names())
        self.window.fcgafsmm_combobox.configure(command=self.fcgafsmm_combobox)
        lock_combobox_typing(self.window.fcgafsmm_combobox)
        # Wired explicitly — the .ctkproj only auto-wires commands that
        # existed at export time, and fcgaf_segmentbutton is new.
        self.window.fcgaf_segmentbutton.configure(command=self.fcgaf_segmentbutton)
        self._apply_segment_color(self.window.fcgaf_segmentbutton.get())

        self.window.bind_all("<Delete>", self._clear_assignment, add="+")
        self.window.bind_all("<BackSpace>", self._clear_assignment, add="+")

        self.window.__dict__.setdefault("_profile_change_listeners", []).append(
            self._on_active_profile_changed
        )
        self.window.__dict__.setdefault("_page_show_listeners", []).append(self._on_page_shown)

        self._prune_invalid_macro_assignments()
        self._refresh_assignment_dots()

    # --- button selection ---

    def _setup_home_button(self) -> None:
        """fcgi_HOME has no polygon in hit_zones.json. If a future asset
        adds one under "HOME"/"Home", the canvas hit-test polygon takes
        over and this widget is hidden. Until then it falls back to this
        real widget, stripped of button chrome so it blends into the
        controller artwork, keeping only the "HOME" text.
        """
        button = getattr(self.window, "fcgi_HOME", None)
        if button is None:
            return
        if self._controller and "HOME" in self._controller.button_names():
            button.place_forget()
            return
        button.configure(fg_color="transparent", hover=False, border_width=0)
        button.lift()

    def _on_frame_resize(self, event) -> None:
        if not self._controller or event.width <= 1:
            return  # width of 0/1 shows up during initial layout
        scale = event.width / DESIGN_FRAME_WIDTH
        self._controller.resize(max(1, round(IMAGE_DESIGN_WIDTH * scale)))
        self._controller.canvas.place(x=round(IMAGE_X * scale), y=round(IMAGE_Y * scale))

    def _select_button(self, name: str) -> None:
        self._selected_button = name
        self.window.fcgafsms_selection.configure(text=name)
        self.window.fcgafsks_selection.configure(text=name)
        if self._controller:
            self._controller.select(name)
        self._load_assignment()

    def _deselect_button(self) -> None:
        self._selected_button = None
        if self._controller:
            self._controller.clear_selection()

    def _on_active_profile_changed(self) -> None:
        # Deselect rather than reload the same button under the new
        # profile, so fcgafskk_entry/fcgafsmm_combobox can never show a
        # stale value from the previous profile.
        self._deselect_button()
        self.window.fcgafskk_entry.delete(0, "end")
        self.window.fcgafsmm_combobox.set("")
        self._refresh_assignment_dots()

    def _on_page_shown(self, page_name: str) -> None:
        if page_name == "fc_mapping":
            self._prune_invalid_macro_assignments()

    def _prune_invalid_macro_assignments(self) -> None:
        """Drop macro assignments (in every profile) whose macro no longer
        exists — e.g. deleted from the Macros tab after being assigned here."""
        valid_names = set(_get_macro_names())
        data = _read_config()
        changed = False
        for profile in data.get("profiles", []):
            mapping = profile.get("mapping", {})
            for button in list(mapping.keys()):
                assignment = mapping[button]
                if assignment.get("type") == "macro" and assignment.get("value") not in valid_names:
                    del mapping[button]
                    changed = True
        if not changed:
            return
        _write_config(data)
        self._refresh_assignment_dots()
        if self._selected_button is not None:
            self._load_assignment()

    def _active_profile(self) -> Optional[Dict[str, Any]]:
        data = _read_config()
        active_id = data.get("active_profile", DEFAULT_PROFILE_ID)
        return next((p for p in data.get("profiles", []) if p["id"] == active_id), None)

    def _load_assignment(self) -> None:
        self.window.fcgafskk_entry.delete(0, "end")
        self.window.fcgafsmm_combobox.set("")

        profile = self._active_profile()
        assignment = (profile or {}).get("mapping", {}).get(self._selected_button)
        if not assignment:
            return

        if assignment.get("type") == "keybind":
            self.window.fcgafskk_entry.insert(0, assignment.get("value", ""))
            self._set_mapping_mode("Keybind")
        elif assignment.get("type") == "macro":
            self.window.fcgafsmm_combobox.set(assignment.get("value", ""))
            self._set_mapping_mode("Macros")

    def _mode_to_kind(self, mode: str) -> str:
        return "macro" if mode == "Macros" else "keybind"

    def _apply_segment_color(self, mode: str) -> None:
        # fcgaf_segmentbutton's colors come from the .ctkproj as fixed
        # values, including an unrelated unselected_hover_color. Reusing
        # HIGHLIGHT_COLORS/HIGHLIGHT_HOVER_COLORS keeps the selected
        # segment's background/hover in sync with the controller outline
        # and assignment dots.
        #
        # unselected_hover_color deliberately gets the OPPOSITE kind's
        # hover shade: with exactly two segments, "the unselected one"
        # always means "the other kind." This assumption breaks down if
        # a third mode is ever added here.
        kind = self._mode_to_kind(mode)
        other_kind = "keybind" if kind == "macro" else "macro"
        color = HIGHLIGHT_COLORS.get(kind, HIGHLIGHT_COLORS["keybind"])
        hover = HIGHLIGHT_HOVER_COLORS.get(kind, HIGHLIGHT_HOVER_COLORS["keybind"])
        other_hover = HIGHLIGHT_HOVER_COLORS.get(other_kind, HIGHLIGHT_HOVER_COLORS["macro"])
        self.window.fcgaf_segmentbutton.configure(
            selected_color=color,
            selected_hover_color=hover,
            unselected_hover_color=other_hover,
        )

    def _set_mapping_mode(self, mode: str) -> None:
        self.window.fcgaf_segmentbutton.set(mode)
        getattr(self.window, MAPPING_MODES[mode]).tkraise()
        if self._controller:
            self._controller.set_highlight_kind(self._mode_to_kind(mode))
        self._apply_segment_color(mode)

    def _save_assignment(self, kind: str, value: str) -> None:
        if self._selected_button is None or not value:
            return
        data = _read_config()
        active_id = data.get("active_profile", DEFAULT_PROFILE_ID)
        for profile in data.get("profiles", []):
            if profile["id"] == active_id:
                profile.setdefault("mapping", {})[self._selected_button] = {
                    "type": kind, "value": value,
                }
                break
        _write_config(data)
        self._refresh_assignment_dots()

    def _clear_assignment(self, _event=None) -> None:
        if self._selected_button is None or not self.window.fc_mapping.winfo_manager():
            return  # nothing selected, or the mapping page isn't visible
        focus = self.window.focus_get()
        if widget_is_descendant(focus, self.window.fcgafskk_entry) \
                or widget_is_descendant(focus, self.window.fcgafsmm_combobox):
            return  # user is editing the field itself, not clearing the assignment

        data = _read_config()
        active_id = data.get("active_profile", DEFAULT_PROFILE_ID)
        for profile in data.get("profiles", []):
            if profile["id"] == active_id:
                profile.get("mapping", {}).pop(self._selected_button, None)
                break
        _write_config(data)

        self.window.fcgafskk_entry.delete(0, "end")
        self.window.fcgafsmm_combobox.set("")
        self._refresh_assignment_dots()

    def _refresh_assignment_dots(self) -> None:
        if not self._controller:
            return
        mapping = (self._active_profile() or {}).get("mapping", {})
        for button in self._controller.button_names():
            assignment = mapping.get(button)
            self._controller.set_indicator(button, assignment.get("type") if assignment else None)

    # --- fcgi_HOME (no shape in the SVG, so it's a real widget, not a canvas hitbox) ---

    def fcgi_HOME(self): self._select_button("HOME")

    # --- other widget events ---

    def _on_keybind_captured(self, text: str) -> None:
        self._save_assignment("keybind", text)

    def fcgafskk_entry(self, val: str) -> None:
        pass  # capture is driven by ui_utils.bind_hotkey_capture, not this event

    def fcgafsmm_combobox(self, val: str) -> None:
        self._save_assignment("macro", val)

    def fcgaf_segmentbutton(self, val: str) -> None:
        # Programmatic .set() calls from _set_mapping_mode don't trigger
        # this event, so that path updates the canvas/segment color itself.
        getattr(self.window, MAPPING_MODES[val]).tkraise()
        if self._controller:
            self._controller.set_highlight_kind(self._mode_to_kind(val))
        self._apply_segment_color(val)
