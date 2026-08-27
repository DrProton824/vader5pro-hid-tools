#
# gui/scripts/navigation.py
# Page switching, frame visibility, navigation state.
#

"""
NAVIGATION GUARDS
  Before switching pages, _show_page consults window._navigation_guards — callables
  registered by macros.py/profiles.py that return False to block the switch. This
  prompts to save/discard unsaved changes instead of silently dropping them.

EDITOR CLOSE
  Page switches close any open editor via _close_editors, which broadcasts through
  window._editor_close_listeners. This discards unsaved "New Macro"/"New Profile"
  sessions that wouldn't otherwise find out about the page switch.

DUAL-ACTION BUTTONS
  Buttons marked `*` in the spec (fcmvh_add, fcmevh_save, fcplh_add, fcpeh_save, etc.)
  perform both a data action and navigation, so show/hide happens in macros.py/profiles.py
  instead. This module only owns triggers where navigation is the whole story.

MAPPING MODE TOGGLE
  fcgafs_keybind and fcgafs_macros sit at identical coordinates (fixed overlapping pair),
  so the toggle uses tkraise() instead of show_frame/hide_frame.
"""

from __future__ import annotations

from ctkmaker import CTkScript

try:
    from ui_utils import hide_frame, show_frame, apply_toolbar_colors
except ImportError:
    from .ui_utils import hide_frame, show_frame, apply_toolbar_colors

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PAGES = ("fc_mapping", "fc_macros", "fc_profiles", "fc_settings", "fc_about")

NAV_BUTTONS = {
    "fc_mapping":  "fsnb_mapping",
    "fc_macros":   "fsnb_macros",
    "fc_profiles": "fsnb_profiles",
    "fc_settings": "fsnb_settings",
    "fc_about":    "fsnb_about",
}

# Navigation button colors — adjust to match your theme.
# BTN_ACTIVE_COLOR is the "selected page" tint, roughly 50% of the hover color.
BTN_DEFAULT_COLOR = "#242B30"
BTN_DEFAULT_HOVER = "#2B343A"
BTN_ACTIVE_COLOR  = "#2B343A"
BTN_ACTIVE_HOVER  = "#2B343A"

# fcgafs_keybind / fcgafs_macros sit at identical coordinates — a fixed
# overlapping pair — so the toggle uses tkraise() rather than
# show_frame/hide_frame (see fcgaf_segmentbutton below).
MAPPING_MODES = {
    "Keybind": "fcgafs_keybind",
    "Macros": "fcgafs_macros",
}

# ---------------------------------------------------------------------------
# End configuration
# ---------------------------------------------------------------------------


class Navigation(CTkScript):

    def on_start(self):
        from .ui_utils import apply_toolbar_colors
        apply_toolbar_colors(self.window)
        self._show_page("fc_mapping")
        self._close_editors()
        self.window.fcgafs_keybind.tkraise()

    # ------------------------------------------------------------------
    # Active-button highlight
    # ------------------------------------------------------------------

    def _set_active_button(self, page_name: str) -> None:
        """Dim the previously active button, highlight the new one."""
        for page, btn_name in NAV_BUTTONS.items():
            btn = getattr(self.window, btn_name)
            if page == page_name:
                btn.configure(
                    fg_color=BTN_ACTIVE_COLOR,
                    hover_color=BTN_ACTIVE_HOVER,
                )
            else:
                btn.configure(
                    fg_color=BTN_DEFAULT_COLOR,
                    hover_color=BTN_DEFAULT_HOVER,
                )

    # ------------------------------------------------------------------
    # Navigation guards
    # ------------------------------------------------------------------

    def _confirm_navigation(self) -> bool:
        for guard in getattr(self.window, "_navigation_guards", []):
            if not guard():
                return False  # some editor has unsaved changes and the user chose to stay
        return True

    def _show_page(self, page_name: str) -> None:
        if not self._confirm_navigation():
            return
        for page in PAGES:
            frame = getattr(self.window, page)
            show_frame(frame) if page == page_name else hide_frame(frame)
        self._set_active_button(page_name)
        self._close_editors()
        for callback in getattr(self.window, "_page_show_listeners", []):
            callback(page_name)

    def _close_editors(self) -> None:
        hide_frame(self.window.fcm_editframe)
        hide_frame(self.window.fcm_frameR)
        hide_frame(self.window.fcp_editframe)
        hide_frame(self.window.fcp_frameR)
        for callback in getattr(self.window, "_editor_close_listeners", []):
            callback()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def fsnb_mapping(self):
        self._show_page("fc_mapping")

    def fsnb_macros(self):
        self._show_page("fc_macros")

    def fsnb_profiles(self):
        self._show_page("fc_profiles")

    def fsnb_settings(self):
        self._show_page("fc_settings")

    def fsnb_about(self):
        self._show_page("fc_about")

    def fcgaf_segmentbutton(self, val: str = None):
        if val is None:
            val = self.window.fcgaf_segmentbutton.get()

        values = tuple(self.window.fcgaf_segmentbutton.cget("values"))
        index = values.index(val)

        getattr(self.window, tuple(MAPPING_MODES.values())[index]).tkraise()
