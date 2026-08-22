"""Page switching, frame visibility, navigation state.

Buttons marked `*` in the spec (fcmvh_add, fcmevh_save, fcplh_add,
fcpeh_save, fcmevmnn_cancel1, fcpeenn_cancel1) also perform a data
action, so their show/hide happens in macros.py / profiles.py instead
— a widget event can only bind to one method. This module only owns
triggers where navigation is the whole story.

Switching pages also closes any open editor, same as Cancel — but a
page switch never goes through fcmevmnn_cancel1/fcpeenn_cancel1, so
macros.py/profiles.py wouldn't otherwise find out and would leave a
never-saved "New Macro"/"New Profile" session dangling in memory.
_close_editors broadcasts through window._editor_close_listeners so
they can discard it the same way Cancel does.

Before any of that happens, _show_page consults
window._navigation_guards — callables macros.py/profiles.py register
that return False to block the switch. That's what makes switching
pages (or picking a different row within a list) prompt to save/discard
unsaved changes instead of silently dropping them: the guard shows
that prompt and only returns True once the user picked Save or
Discard, or the editor wasn't dirty to begin with.
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
        # CTkMaker's exporter sometimes emits this call without the new
        # value — fall back to reading it straight off the widget.
        if val is None:
            val = self.window.fcgaf_segmentbutton.get()
        getattr(self.window, MAPPING_MODES[val]).tkraise()
