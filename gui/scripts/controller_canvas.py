#
# gui/scripts/controller_canvas.py
# Polygon-accurate controller hit zones driven by controller.png and hit_zones.json.
#

"""
ARCHITECTURE
  Uses tkinter.Canvas with polygon shapes from hit_zones.json as invisible hit-test
  items, so click detection matches the actual button outlines instead of rectangles.
  Both the controller image and polygons are scaled together to the requested width.

NAME TRANSLATION
  hit_zones.json labels differ from mapping.py button names (e.g. "DPad Up" -> "UP",
  "STICK-L" -> "LS"). HITZONE_TO_BUTTON_NAME normalizes them at load time.

STACKING ORDER (bottom to top)
  1. controller image
  2. overlay tint       — semi-transparent fill for assigned buttons
  3. highlight border   — outline drawn on the selected button
  4. hit-test polygons  — invisible, must stay on top to receive clicks
  
  Items 2 and 3 are created in _render() before the polygon loop, so they naturally
  sit below the polygons. Never tag_raise them — Tk hit-tests by stacking order, so
  raising either would block clicks meant for the polygons.

SELECTION HIGHLIGHT
  Canvas polygon outlines are not anti-aliased. The highlight is rendered with
  PIL.ImageDraw at HIGHLIGHT_SUPERSAMPLE resolution, cropped to the button's bounding
  box, and downsampled with LANCZOS for smooth edges. A single canvas image item is
  repositioned via coords() and shown/hidden per selection.

INDICATOR STYLES
  set_indicator() delegates to INDICATOR_STYLE. Swap INDICATOR_STYLE_CHOICE
  ("dot" | "overlay") in the configuration section. DotIndicatorStyle draws a small
  corner dot. OverlayIndicatorStyle draws a translucent fill via pre_render() so its
  canvas item stays below the polygons.

REGENERATION
  Regenerate controller.png and hit_zones.json with render_controller_assets.py
  after changing the SVG source.
"""

from __future__ import annotations

import json
import pathlib
import tkinter as tk
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageTk

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Button name translation: hit_zones.json labels -> mapping.py canonical names.
# Entries whose label already matches the canonical name are not listed.
HITZONE_TO_BUTTON_NAME: Dict[str, str] = {
    "DPad Up":    "UP",
    "DPad Down":  "DOWN",
    "DPad Left":  "LEFT",
    "DPad Right": "RIGHT",
    "STICK-L":    "LS",
    "STICK-R":    "RS",
    "Select":     "SELECT",
    "Start":      "START",
    "Home":       "HOME",
}

# Selection highlight — the outline drawn around the active button. Color
# reflects the active fcgaf_segmentbutton value (keybind vs macro).
HIGHLIGHT_WIDTH       = 6           # outline thickness in pixels
HIGHLIGHT_SUPERSAMPLE = 4           # render multiplier before LANCZOS downsample (anti-aliasing)
HIGHLIGHT_COLORS: Dict[str, str] = {
    "keybind": "#7DABC3",
    "macro":   "#C3B87D",
}
HIGHLIGHT_HOVER_COLORS: Dict[str, str] = {
    "keybind": "#7DABC3",
    "macro":   "#C3B87D",
}

# Dot indicator — small filled circle in the button's top-right corner.
DOT_RADIUS = 5
DOT_COLORS: Dict[str, str] = {
    "keybind": "#7DABC3",
    "macro":   "#C3B87D",
}

# Overlay indicator — semi-transparent fill over the button's polygon shape.
# Fourth value is alpha: 0 = fully transparent, 255 = fully opaque.
OVERLAY_COLORS: Dict[str, Tuple[int, int, int, int]] = {
    "keybind": (125, 171, 195, 100),
    "macro": (195, 184, 125, 100),
}

# Active indicator style — switch between "dot" and "overlay".
INDICATOR_STYLE_CHOICE = "overlay"  # "dot" | "overlay"

# Fallback canvas background color if no ancestor has a readable fg_color.
FALLBACK_BG_COLOR = "#191D20"

# Debug — flip True to draw polygon outlines for hit zone calibration.
DEBUG_SHOW_HITBOXES  = False
DEBUG_OUTLINE_COLOR  = "#ff3366"

# ---------------------------------------------------------------------------
# End configuration
# ---------------------------------------------------------------------------


def _resolve_bg_color(widget) -> str:
    """Returns the nearest non-transparent fg_color from the widget's
    parent chain, resolved for the current CTk appearance mode."""
    try:
        import customtkinter as ctk
        mode_index = 1 if ctk.get_appearance_mode() == "Dark" else 0
    except ImportError:
        mode_index = 0

    node = widget
    while node is not None:
        try:
            color = node.cget("fg_color")
        except tk.TclError:
            color = None
        if color and color != "transparent":
            return color[mode_index] if isinstance(color, (list, tuple)) else color
        node = getattr(node, "master", None)
    return FALLBACK_BG_COLOR


# ---------------------------------------------------------------------------
# Indicator styles
# ---------------------------------------------------------------------------

class IndicatorStyle:
    """Base class for assignment indicator renderers.

    Styles that need their canvas item below the hit-test polygons must
    use the pre_render path: ControllerCanvas calls pre_render() for
    each button before the polygon loop in _render(), so the item
    already sits underneath the polygons when draw() later updates it
    in-place. Styles safe to sit above the polygons (e.g.
    DotIndicatorStyle) can skip pre_render and create items in draw().
    """

    def needs_pre_render(self) -> bool:
        return False

    def pre_render(self, canvas: tk.Canvas) -> int:
        """Create and return one hidden canvas item id, called once per
        button before the polygon loop. Only called when
        needs_pre_render() is True."""
        raise NotImplementedError

    def draw(
        self,
        canvas: tk.Canvas,
        kind: str,
        bbox: Tuple[float, float, float, float],
        polygons: List[List[float]],
        pre_render_item: Optional[int] = None,
    ) -> List[int]:
        """Show the indicator for `kind` ("keybind" or "macro"). Returns
        all canvas item ids created or updated, so hide() can clean
        them up."""
        raise NotImplementedError

    def hide(self, canvas: tk.Canvas, item_ids: List[int], pre_render_item: Optional[int]) -> None:
        """Hide the indicator. Hides pre_render_item in-place (preserving
        its stacking position) and deletes any extra items draw() created."""
        if pre_render_item is not None:
            canvas.itemconfig(pre_render_item, state="hidden")
        for item in item_ids:
            if item != pre_render_item:
                canvas.delete(item)


class DotIndicatorStyle(IndicatorStyle):
    """Small filled circle in the button's top-right corner. Creates its
    item in draw(), landing above the polygons — safe since it only
    covers a few pixels in one corner."""

    def __init__(self, radius: int = DOT_RADIUS, colors: Dict[str, str] = None):
        self.radius = radius
        self.colors = colors or DOT_COLORS

    def draw(self, canvas, kind, bbox, polygons, pre_render_item=None):
        x0, y0, x1, _y1 = bbox
        cx, cy = x1 - self.radius - 2, y0 + self.radius + 2
        color = self.colors.get(kind, self.colors["keybind"])
        return [canvas.create_oval(
            cx - self.radius, cy - self.radius,
            cx + self.radius, cy + self.radius,
            fill=color, outline="",
        )]


class OverlayIndicatorStyle(IndicatorStyle):
    """Semi-transparent fill over the button's polygon shape, rendered
    with PIL for true alpha (tk.Canvas stipple is a dither pattern, not
    real alpha).

    Uses the pre_render path so its canvas item sits below the hit-test
    polygons. draw() updates the existing item in-place via itemconfig +
    coords, preserving its stacking position."""

    def __init__(self, colors: Dict[str, Tuple[int, int, int, int]] = None):
        self.colors = colors or OVERLAY_COLORS
        self._cache: Dict[Tuple, ImageTk.PhotoImage] = {}

    def needs_pre_render(self) -> bool:
        return True

    def pre_render(self, canvas: tk.Canvas) -> int:
        return canvas.create_image(0, 0, anchor="nw", state="hidden")

    def draw(self, canvas, kind, bbox, polygons, pre_render_item=None):
        if not polygons or pre_render_item is None:
            return []

        xs = [c for poly in polygons for c in poly[0::2]]
        ys = [c for poly in polygons for c in poly[1::2]]
        x0, y0 = min(xs), min(ys)
        w  = max(1, round(max(xs) - x0))
        h  = max(1, round(max(ys) - y0))

        cache_key = (kind, tuple(tuple(p) for p in polygons))
        image = self._cache.get(cache_key)
        if image is None:
            local_polys = [
                [c - (x0 if i % 2 == 0 else y0) for i, c in enumerate(poly)]
                for poly in polygons
            ]
            overlay  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw_ctx = ImageDraw.Draw(overlay)
            color    = self.colors.get(kind, self.colors["keybind"])
            for poly in local_polys:
                points = [(poly[i], poly[i + 1]) for i in range(0, len(poly), 2)]
                draw_ctx.polygon(points, fill=color)
            image = ImageTk.PhotoImage(overlay)
            self._cache[cache_key] = image  # must hold a reference — Tk drops it otherwise

        canvas.coords(pre_render_item, x0, y0)
        canvas.itemconfig(pre_render_item, image=image, state="normal")
        return [pre_render_item]


_INDICATOR_STYLES: Dict[str, IndicatorStyle] = {
    "dot":     DotIndicatorStyle(),
    "overlay": OverlayIndicatorStyle(),
}
INDICATOR_STYLE: IndicatorStyle = _INDICATOR_STYLES[INDICATOR_STYLE_CHOICE]


# ---------------------------------------------------------------------------
# ControllerCanvas
# ---------------------------------------------------------------------------

class ControllerCanvas:
    """Displays controller.png with polygon-accurate clickable hit zones.

    on_click receives the canonical button name when a button is clicked.
    on_background_click fires when the canvas background is clicked.
    resize() redraws at a new width (call from a <Configure> handler).
    select()/clear_selection() show/hide the selection highlight.
    set_indicator() shows/hides the assignment indicator for a button.
    """

    def __init__(
        self,
        parent,
        image_path: pathlib.Path,
        hitzones_path: pathlib.Path,
        on_click: Optional[Callable[[str], None]] = None,
        on_background_click: Optional[Callable[[], None]] = None,
        display_width: Optional[int] = None,
    ) -> None:
        self._on_click            = on_click
        self._on_background_click = on_background_click
        self._image_path          = pathlib.Path(image_path)
        self._raw_zones           = json.loads(pathlib.Path(hitzones_path).read_text(encoding="utf-8"))
        self._selected: Optional[str] = None
        self._selected_kind: str = "keybind"
        self._bg_color            = _resolve_bg_color(parent)

        self.canvas = tk.Canvas(parent, highlightthickness=0, bd=0, bg=self._bg_color)
        # Bound to every click; fires even when a button polygon also
        # fires. gettags("current") is empty only when the click hit
        # bare background.
        self.canvas.bind("<Button-1>", self._handle_background_click)

        self.display_width: int = 0
        self._render(display_width)

    def _render(self, display_width: Optional[int]) -> None:
        self.canvas.delete("all")

        image    = Image.open(self._image_path).convert("RGBA")
        native_w, native_h = image.size
        scale    = 1.0 if display_width is None else display_width / native_w
        out_w    = round(native_w * scale)
        out_h    = round(native_h * scale)
        if scale != 1.0:
            image = image.resize((out_w, out_h), Image.LANCZOS)

        self.display_width = out_w
        self._scale        = scale
        self._out_w        = out_w
        self._out_h        = out_h
        self.canvas.configure(width=out_w, height=out_h)

        self._polygon_ids: Dict[str, List[int]]                        = {}
        self._polygons:    Dict[str, List[List[float]]]                 = {}
        self._dot_ids:     Dict[str, List[int]]                        = {}
        self._bbox:        Dict[str, Tuple[float, float, float, float]] = {}

        # --- Stacking order (items created first sit lowest) ---
        # 1. controller image
        self._tk_image = ImageTk.PhotoImage(image)
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_image)

        # 2. overlay tint (OverlayIndicatorStyle pre_render, one item per button)
        self._indicator_pre_render_items: Dict[str, Optional[int]] = {}
        if INDICATOR_STYLE.needs_pre_render():
            for raw_name in self._raw_zones:
                button = HITZONE_TO_BUTTON_NAME.get(raw_name, raw_name)
                self._indicator_pre_render_items[button] = INDICATOR_STYLE.pre_render(self.canvas)

        # 3. highlight border (small per-button image, shown/hidden and
        # repositioned per selection — see _build_highlight_image)
        self._highlight_images: Dict[Tuple[str, str], Tuple[ImageTk.PhotoImage, float, float]] = {}
        self._highlight_item: Optional[int] = self.canvas.create_image(
            0, 0, anchor="nw", state="hidden"
        )

        # 4. hit-test polygons (invisible, must remain topmost to receive clicks)
        for raw_name, entry in self._raw_zones.items():
            button = HITZONE_TO_BUTTON_NAME.get(raw_name, raw_name)
            self._polygon_ids[button] = []

            for poly in entry.get("polygons", []):
                scaled = [coord * scale for coord in poly]
                self._polygons.setdefault(button, []).append(scaled)
                item = self.canvas.create_polygon(
                    *scaled,
                    fill="",
                    outline=DEBUG_OUTLINE_COLOR if DEBUG_SHOW_HITBOXES else "",
                    width=HIGHLIGHT_WIDTH if DEBUG_SHOW_HITBOXES else 0,
                    tags=(button,),
                )
                self._polygon_ids[button].append(item)

            if entry.get("bbox"):
                bx0, by0, bx1, by1 = entry["bbox"]
                self._bbox[button] = (bx0 * scale, by0 * scale, bx1 * scale, by1 * scale)

            self.canvas.tag_bind(button, "<Button-1>", lambda e, b=button: self._handle_click(b))
            self.canvas.tag_bind(button, "<Enter>", lambda e: self.canvas.configure(cursor="hand2"))
            self.canvas.tag_bind(button, "<Leave>", lambda e: self.canvas.configure(cursor=""))

        if self._selected is not None:
            self.select(self._selected)

    def resize(self, display_width: int) -> None:
        """Redraws at a new width. Safe to call from a <Configure> handler
        when throttled to real width changes (see mapping.py _on_frame_resize)."""
        if display_width == self.display_width:
            return
        self._render(display_width)

    # --- events ---

    def _handle_click(self, button: str) -> None:
        if self._on_click:
            self._on_click(button)

    def _handle_background_click(self, event) -> None:
        if not self.canvas.gettags("current") and self._on_background_click:
            self._on_background_click()

    def button_names(self) -> List[str]:
        return list(self._polygon_ids.keys())

    # --- selection highlight ---

    def _build_highlight_image(self, button: str, kind: str) -> Tuple[ImageTk.PhotoImage, float, float]:
        """Renders the button outline at HIGHLIGHT_SUPERSAMPLE resolution
        then downsamples with LANCZOS for a smooth anti-aliased edge.
        Cropped to the button's own bounding box (plus stroke padding)
        rather than the full canvas, since rendering a full-canvas RGBA
        image per button is the main cost behind selection lag. Returns
        (image, x0, y0) so select() can position it with canvas.coords
        instead of anchoring at (0, 0)."""
        polygons = self._polygons.get(button, [])
        if not polygons:
            return ImageTk.PhotoImage(Image.new("RGBA", (1, 1), (0, 0, 0, 0))), 0, 0

        pad = HIGHLIGHT_WIDTH  # keep the stroke from clipping at the crop edge
        xs  = [c for poly in polygons for c in poly[0::2]]
        ys  = [c for poly in polygons for c in poly[1::2]]
        x0, y0 = min(xs) - pad, min(ys) - pad
        x1, y1 = max(xs) + pad, max(ys) + pad
        w = max(1, round(x1 - x0))
        h = max(1, round(y1 - y0))

        color      = HIGHLIGHT_COLORS.get(kind, HIGHLIGHT_COLORS["keybind"])
        line_width = HIGHLIGHT_WIDTH * HIGHLIGHT_SUPERSAMPLE

        highlight = Image.new("RGBA", (w * HIGHLIGHT_SUPERSAMPLE, h * HIGHLIGHT_SUPERSAMPLE), (0, 0, 0, 0))
        draw      = ImageDraw.Draw(highlight)
        for poly in polygons:
            points = [
                ((poly[i] - x0) * HIGHLIGHT_SUPERSAMPLE, (poly[i + 1] - y0) * HIGHLIGHT_SUPERSAMPLE)
                for i in range(0, len(poly), 2)
            ]
            if points[0] != points[-1]:
                points.append(points[0])  # close the loop so the last vertex also gets a joint
            # draw.polygon(outline=..., width=...) leaves gaps at concave
            # vertices since each edge is stroked independently; a closed
            # polyline with joint="curve" stamps a round join at every
            # vertex instead.
            draw.line(points, fill=color, width=line_width, joint="curve")

        highlight = highlight.resize((w, h), Image.LANCZOS)
        return ImageTk.PhotoImage(highlight), x0, y0

    def select(self, button: Optional[str], kind: Optional[str] = None) -> None:
        self._selected = button
        if kind is not None:
            self._selected_kind = kind
        if button is None:
            self.canvas.itemconfig(self._highlight_item, state="hidden")
            return
        cache_key = (button, self._selected_kind)
        cached = self._highlight_images.get(cache_key)
        if cached is None:
            cached = self._build_highlight_image(button, self._selected_kind)
            self._highlight_images[cache_key] = cached
        image, x0, y0 = cached
        # itemconfig/coords only — never tag_raise, since that would
        # swallow clicks on whatever the highlight now covers.
        self.canvas.coords(self._highlight_item, x0, y0)
        self.canvas.itemconfig(self._highlight_item, image=image, state="normal")

    def clear_selection(self) -> None:
        self.select(None)

    def set_highlight_kind(self, kind: str) -> None:
        """Updates the selection highlight color in place (e.g. when the
        Keybind/Macro segmented control changes) without changing which
        button is selected."""
        if kind == self._selected_kind:
            return
        self._selected_kind = kind
        if self._selected is not None:
            self.select(self._selected, kind)

    # --- assignment indicator ---

    def set_indicator(self, button: str, kind: Optional[str]) -> None:
        """Show (kind="keybind"/"macro") or hide (kind=None) the assignment
        indicator for `button`. Delegates rendering to INDICATOR_STYLE."""
        pre_item = self._indicator_pre_render_items.get(button)
        existing = self._dot_ids.get(button)
        if existing:
            INDICATOR_STYLE.hide(self.canvas, existing, pre_item)
            del self._dot_ids[button]

        if kind is None or button not in self._bbox:
            if kind is None and pre_item is not None:
                self.canvas.itemconfig(pre_item, state="hidden")
            return

        self._dot_ids[button] = INDICATOR_STYLE.draw(
            self.canvas, kind, self._bbox[button], self._polygons.get(button, []),
            pre_render_item=pre_item,
        )


# ---------------------------------------------------------------------------
# Calibration harness — run this file directly to verify hitboxes against
# the artwork. Click a button to highlight it; press D to toggle outlines.
# ---------------------------------------------------------------------------

def _run_calibration_harness() -> None:
    global DEBUG_SHOW_HITBOXES

    here       = pathlib.Path(__file__).resolve().parent
    image_path = here / "controller.png"
    zones_path = here / "hit_zones.json"
    if not image_path.exists() or not zones_path.exists():
        print(f"Expected {image_path.name} and {zones_path.name} next to this script.")
        return

    root   = tk.Tk()
    root.title("Controller hit zone calibration")
    status = tk.Label(root, text="Click a button. Press D to toggle hitbox outlines.")
    status.pack(side="top", pady=4)

    def _on_click(button: str) -> None:
        status.configure(text=f"Clicked: {button}")
        controller.select(button)
        print("clicked:", button)

    controller = ControllerCanvas(root, image_path, zones_path, on_click=_on_click)
    controller.canvas.pack(padx=10, pady=10)

    def _toggle_debug(_event=None) -> None:
        global DEBUG_SHOW_HITBOXES
        DEBUG_SHOW_HITBOXES = not DEBUG_SHOW_HITBOXES
        controller.canvas.destroy()
        _rebuild()

    def _rebuild() -> None:
        nonlocal controller
        controller = ControllerCanvas(root, image_path, zones_path, on_click=_on_click)
        controller.canvas.pack(padx=10, pady=10)

    root.bind("<KeyPress-d>", _toggle_debug)
    root.bind("<KeyPress-D>", _toggle_debug)
    root.mainloop()


if __name__ == "__main__":
    _run_calibration_harness()
