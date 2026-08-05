"""
VaderConfig – click-on-controller configuration GUI.

Interaction model
─────────────────
  1. Controller image is displayed (SVG rendered to PNG, or fallback canvas).
  2. Mappable buttons have invisible hit-zones drawn over them.
  3. User clicks a button zone → it highlights, a capture bar appears below.
  4. User presses a key combination → shortcut is recorded.
  5. The zone label updates to show the assigned shortcut.
  6. User clicks Save (or it auto-saves after each assignment – see AUTOSAVE).
  7. VaderService picks up the change within ~500 ms.

Dependencies
────────────
  Required:  tkinter (stdlib)
  Optional:  cairosvg, Pillow  (for SVG rendering; falls back gracefully)

Window chrome
─────────────
Tk's native title bar looks unmistakably like a Tk app.  Instead of
hiding it with overrideredirect() (which, on Windows, also drops the
taskbar entry and breaks Alt‑Tab), we strip just the caption/border
styles from the underlying HWND via ctypes and draw our own title bar
(icon, title, minimize, close) as a normal Tk frame.  Minimize/close
still work exactly like a native window; only the paint style changes.

Layout (900 × 760 window)
──────────────────────────
  ┌──────────────────────────────────────────┐
  │  ⬤ Vader Remapper                 – ×    │  ← custom title bar
  ├──────────────────────────────────────────┤
  │                                          │
  │   [ canvas: controller + hit zones ]     │
  │                                          │
  ├──────────────────────────────────────────┤
  │  ● M1   [  Ctrl+Shift+P  ]  ← active    │
  │  Capture bar: "Click a button above,     │
  │  then press your shortcut."              │
  ├──────────────────────────────────────────┤
  │  [ Save ]           status: Saved ✓      │
  └──────────────────────────────────────────┘
"""

from __future__ import annotations

import ctypes
import io
import json
import pathlib
import sys
import tkinter as tk
from tkinter import messagebox
from typing import Optional

# ── Path bootstrap ────────────────────────────────────────────────────────────
def _bootstrap_path() -> pathlib.Path:
    """
    Return the root directory whether running from source or as a
    PyInstaller bundled exe.
    """
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    else:
        return pathlib.Path(__file__).resolve().parents[2]


_ROOT = _bootstrap_path()
sys.path.insert(0, str(_ROOT))

from src.shared import config as cfg
from src.shared import single_instance
from src.shared.constants import MAPPABLE_BUTTONS
from src.shared.version import VERSION

# ── Optional SVG rendering ────────────────────────────────────────────────────
try:
    import cairosvg          # type: ignore
    from PIL import Image, ImageTk  # type: ignore
    _CAIROSVG_OK = True
except ImportError:
    _CAIROSVG_OK = False

_SVG_PATH = _ROOT / "assets" / "controller.svg"
_PNG_PATH = _ROOT / "assets" / "controller.png"
_HIT_ZONES_JSON_PATH = _ROOT / "assets" / "hit_zones.json"
_ICON_PATH = _ROOT / "assets" / "icons" / "config.ico"


def _load_svg_derived_zones() -> dict[str, dict]:
    """
    Read the pre-derived button hit zones (see
    tools/render_controller_assets.py). Each entry is
    {"bbox": [minx, miny, maxx, maxy], "polygons": [[x,y,...], ...]} -
    one or more polygons approximating the actual button outline,
    not just its bounding box.
    """
    try:
        raw = json.loads(_HIT_ZONES_JSON_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {}

    zones: dict[str, dict] = {}
    for button, entry in raw.items():
        if isinstance(entry, dict) and "polygons" in entry:
            zones[button] = entry
    return zones

MUTEX_NAME = "VaderRemapperConfig"

# ── Auto-save preference ──────────────────────────────────────────────────────
# If True, config is written immediately after each key assignment.
# If False, user must click Save.
AUTOSAVE = True

# ── Colour palette ────────────────────────────────────────────────────────────
C = {
    "bg":           "#0d1117",
    "surface":      "#1a2535",
    "surface2":     "#111820",
    "border":       "#2a3a50",
    "accent":       "#3d7ab5",
    "accent_hover": "#5a9ad5",
    "accent_press": "#2a5a8a",
    "text":         "#c8d8e8",
    "text_dim":     "#5a7a9a",
    "text_bright":  "#e8f0f8",
    "mapped":       "#8ab0d0",
    "unmapped":     "#3a5070",
    "highlight":    "#1a4a70",
    "green":        "#3a8a5a",
    "red":          "#8a3a3a",
    "titlebar":     "#0a0f16",
}

# ── Hit-zone definitions ──────────────────────────────────────────────────────
# Each entry:  button_name -> (shape, geometry, label_offset)
#
# shape:    "rect"   → (x, y, w, h)
#           "circle" → (cx, cy, r)
#           "poly"   → flat list of (x,y) pairs
#
# The coordinates match the SVG viewBox (860 × 580).
# They are scaled when the canvas is created.
#
# label_offset: (dx, dy) from shape centre for the shortcut label.

SVG_W, SVG_H = 1315, 913   # new controller.svg viewBox dimensions

HIT_ZONES: dict[str, dict] = {
    # ── Face buttons ─────────────────────────────────────────────────
    "Y": {"shape": "circle", "coords": (923, 320, 32), "label_xy": (923, 320)},
    "X": {"shape": "circle", "coords": (860, 383, 32), "label_xy": (860, 383)},
    "B": {"shape": "circle", "coords": (985, 383, 32), "label_xy": (985, 383)},
    "A": {"shape": "circle", "coords": (923, 445, 32), "label_xy": (923, 445)},

    # ── Z / C ────────────────────────────────────────────────────────
    "Z": {"shape": "circle", "coords": (1015, 487, 32), "label_xy": (1015, 487)},
    "C": {"shape": "circle", "coords": (952, 548, 32), "label_xy": (952, 548)},

    # ── D-Pad (four independent zones) ──────────────────────────────
    "DPad Up":    {"shape": "circle", "coords": (527, 448, 26), "label_xy": (527, 415)},
    "DPad Down":  {"shape": "circle", "coords": (527, 563, 26), "label_xy": (527, 596)},
    "DPad Left":  {"shape": "circle", "coords": (469, 505, 26), "label_xy": (436, 505)},
    "DPad Right": {"shape": "circle", "coords": (589, 505, 26), "label_xy": (622, 505)},

    # ── Sticks (click) ──────────────────────────────────────────────
    "STICK-L": {"shape": "circle", "coords": (391, 370, 29), "label_xy": (391, 370)},
    "STICK-R": {"shape": "circle", "coords": (789, 509, 29), "label_xy": (789, 509)},

    # ── Select / Start ───────────────────────────────────────────────
    "Select": {"shape": "circle", "coords": (535, 297, 30), "label_xy": (535, 258)},
    "Start":  {"shape": "circle", "coords": (778, 297, 30), "label_xy": (778, 258)},

    # ── Shoulder buttons ─────────────────────────────────────────────
    # NOTE: coordinates follow the *printed* text in the SVG. The source
    # file's internal inkscape:label on these paths is mirrored/swapped
    # vs. the printed text (looks like a left/right mirror-copy that
    # wasn't relabeled) — do not trust path labels if you re-derive this.
    "RM": {"shape": "rect", "coords": (185, 35, 150, 70), "label_xy": (260, 70)},
    "RB": {"shape": "rect", "coords": (105, 120, 165, 65), "label_xy": (187, 152)},
    "RT": {"shape": "rect", "coords": (95, 14, 100, 65),  "label_xy": (145, 46)},
    "LM": {"shape": "rect", "coords": (995, 35, 150, 70), "label_xy": (1070, 70)},
    "LB": {"shape": "rect", "coords": (1030, 120, 170, 65), "label_xy": (1115, 152)},
    "LT": {"shape": "rect", "coords": (1120, 14, 100, 65),  "label_xy": (1170, 46)},

    # ── Macro buttons ────────────────────────────────────────────────
    "M1": {"shape": "rect", "coords": (715, 668, 130, 75), "label_xy": (780, 706)},
    "M2": {"shape": "rect", "coords": (435, 668, 140, 80), "label_xy": (505, 708)},
    "M3": {"shape": "rect", "coords": (700, 800, 180, 80), "label_xy": (790, 838)},
    "M4": {"shape": "rect", "coords": (400, 800, 200, 80), "label_xy": (500, 838)},

    # ── Home / Arrow / Circle ────────────────────────────────────────
    # These three don't have distinct shapes in the new artwork (only an
    # "FN" toggle near the logo). Placeholder zones on that toggle so the
    # app keeps working — reposition once the artwork has real shapes.
    "Home":   {"shape": "circle", "coords": (612, 684, 22), "label_xy": (612, 655)},
    "Arrow":  {"shape": "circle", "coords": (664, 684, 22), "label_xy": (664, 655)},
    "Circle": {"shape": "circle", "coords": (612, 684, 22), "label_xy": (612, 715)},
}

def _resolve_hit_zones() -> dict[str, dict]:
    """
    Prefer the polygon outlines read straight from controller.svg's own
    labelled shapes (assets/hit_zones.json); fall back to the manual
    HIT_ZONES table only for buttons the artwork doesn't unambiguously
    provide yet (currently: Home, Arrow, Circle).

    A resolved "poly" zone's "coords" is a list of flat point-lists -
    one per polygon part, since some buttons (e.g. Start/Select) are
    drawn as more than one path - so the canvas can draw/hit-test the
    actual button silhouette instead of a bounding box.
    """
    derived = _load_svg_derived_zones()
    resolved: dict[str, dict] = {}
    for button, manual in HIT_ZONES.items():
        entry = derived.get(button)
        if entry and entry.get("polygons"):
            min_x, min_y, max_x, max_y = entry["bbox"]
            resolved[button] = {
                "shape": "poly",
                "coords": entry["polygons"],
                "label_xy": ((min_x + max_x) / 2, (min_y + max_y) / 2),
            }
        else:
            resolved[button] = manual
    return resolved

RESOLVED_HIT_ZONES: dict[str, dict] = _resolve_hit_zones()

# ── Modifier normalisation ────────────────────────────────────────────────────
_MOD_KEYSYMS = frozenset({
    "Control_L", "Control_R",
    "Shift_L",   "Shift_R",
    "Alt_L",     "Alt_R",
    "Super_L",   "Super_R",
    "Caps_Lock", "Num_Lock",
})


def _build_shortcut(event: tk.Event) -> str:
    """Convert a tkinter KeyPress event → shortcut string like 'ctrl+shift+f13'."""
    if event.keysym in _MOD_KEYSYMS:
        return ""
    parts: list[str] = []
    s = event.state
    if s & 0x0004: parts.append("ctrl")
    if s & 0x0001: parts.append("shift")
    if s & 0x0008: parts.append("alt")
    parts.append(event.keysym.lower())
    return "+".join(parts)


# ── Scale helpers ─────────────────────────────────────────────────────────────

def _scale_coords(coords, sx: float, sy: float) -> list[float]:
    """Scale a flat list of x,y pairs by sx, sy."""
    result = []
    for i, v in enumerate(coords):
        result.append(v * sx if i % 2 == 0 else v * sy)
    return result


def _rect_to_poly(x, y, w, h) -> list[float]:
    return [x, y, x+w, y, x+w, y+h, x, y+h]


# ── Native window chrome ──────────────────────────────────────────────────────
# Strip the native caption/thick-frame styles from the HWND so our own
# TitleBar frame is the only title bar the user sees, while keeping the
# window as a normal top-level (taskbar entry, Alt-Tab, minimize all work
# exactly as before – only the paint style changes).

_GWL_STYLE = -16
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_FRAMECHANGED = 0x0020


def _strip_native_titlebar(root: tk.Tk) -> None:
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_STYLE)
        style &= ~_WS_CAPTION
        style &= ~_WS_THICKFRAME
        ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_STYLE, style)
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            _SWP_FRAMECHANGED | _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER,
        )
    except Exception:
        pass  # non-Windows dev environment, or API unavailable – fine


# ═══════════════════════════════════════════════════════════════════════════════
#  Custom title bar
# ═══════════════════════════════════════════════════════════════════════════════

class TitleBar(tk.Frame):
    """
    Drawn title bar replacing the native one: app icon, title, version,
    minimize + close buttons, and click-drag-to-move.
    """

    HEIGHT = 40

    def __init__(self, parent, root: tk.Tk, title: str, version: str, **kwargs):
        super().__init__(parent, bg=C["titlebar"], height=self.HEIGHT, **kwargs)
        self.pack_propagate(False)
        self._app_root = root
        self._drag_offset_x = 0
        self._drag_offset_y = 0

        left = tk.Frame(self, bg=C["titlebar"])
        left.pack(side="left", fill="y", padx=(14, 0))

        tk.Label(
            left, text="\u25C9", bg=C["titlebar"], fg=C["accent_hover"],
            font=("Segoe UI", 13),
        ).pack(side="left", pady=(0, 1))

        tk.Label(
            left, text=title, bg=C["titlebar"], fg=C["text_bright"],
            font=("Segoe UI", 11, "bold"), padx=8,
        ).pack(side="left")

        tk.Label(
            left, text=version, bg=C["titlebar"], fg=C["text_dim"],
            font=("Segoe UI", 9),
        ).pack(side="left")

        right = tk.Frame(self, bg=C["titlebar"])
        right.pack(side="right", fill="y")

        self._close_btn = self._make_button(right, "\u2715", C["red"], self._on_close)
        self._close_btn.pack(side="right", fill="y")

        self._min_btn = self._make_button(right, "\u2013", C["surface"], self._on_minimize)
        self._min_btn.pack(side="right", fill="y")

        # Dragging: bind on the bar itself and the (non-interactive) labels.
        for widget in (self, left):
            widget.bind("<ButtonPress-1>", self._begin_drag)
            widget.bind("<B1-Motion>", self._do_drag)

    def _make_button(self, parent, symbol: str, hover_bg: str, command) -> tk.Label:
        btn = tk.Label(
            parent, text=symbol, bg=C["titlebar"], fg=C["text_dim"],
            font=("Segoe UI", 10), width=5, cursor="hand2",
        )

        def on_enter(_e):
            btn.config(bg=hover_bg, fg=C["text_bright"])

        def on_leave(_e):
            btn.config(bg=C["titlebar"], fg=C["text_dim"])

        def on_click(_e):
            command()

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<Button-1>", on_click)
        return btn

    # ── Drag to move ─────────────────────────────────────────────────────────

    def _begin_drag(self, event: tk.Event) -> None:
        """Record the pointer offset from the window's top-left corner."""
        self._drag_offset_x = event.x_root - self._app_root.winfo_x()
        self._drag_offset_y = event.y_root - self._app_root.winfo_y()

    def _do_drag(self, event: tk.Event) -> None:
        """
        Move the window by setting only its position ("+x+y"), never
        its size.

        We used to hand this off to Windows via WM_SYSCOMMAND/SC_MOVE.
        That put the OS in charge of the window rect while Tk still
        believed it owned the geometry (this window's native caption /
        thick-frame was stripped via raw ctypes in
        _strip_native_titlebar, but Tk's own cached border metrics from
        window-creation time were never updated to match). Every
        WM_MOVE Tk saw during that native drag made it reassert a
        geometry computed from those stale metrics, so the window grew
        a little on every mouse-move and drifted off screen. Moving it
        ourselves - position only, every <B1-Motion> event - keeps Tk
        from ever touching width/height during a drag.
        """
        x = event.x_root - self._drag_offset_x
        y = event.y_root - self._drag_offset_y
        self._app_root.geometry(f"+{x}+{y}")

    # ── Buttons ──────────────────────────────────────────────────────────────

    def _on_minimize(self) -> None:
        self._app_root.iconify()

    def _on_close(self) -> None:
        self._app_root.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  Canvas controller widget
# ═══════════════════════════════════════════════════════════════════════════════

class ControllerCanvas(tk.Canvas):
    """
    Canvas that shows the controller image (SVG or fallback drawing)
    and renders interactive hit zones for each mappable button.
    """

    CANVAS_W = 900
    CANVAS_H = 625   # 900 * (913/1315), uniform scale – new SVG has no
                      # whitespace to crop like the old one did

    def __init__(self, parent, mapping: dict[str, str],
                 on_button_click, **kwargs):
        super().__init__(
            parent,
            width=self.CANVAS_W,
            height=self.CANVAS_H,
            bg=C["bg"],
            highlightthickness=0,
            **kwargs,
        )
        self._mapping = mapping
        self._on_button_click = on_button_click
        self._active_button: Optional[str] = None

        # Scale factors (SVG coords → canvas pixels)
        self._sx = self.CANVAS_W / SVG_W
        self._sy = self.CANVAS_H / SVG_H    # slightly taller crop ratio

        # canvas item ids for each zone (a button can be made of more
        # than one polygon part, e.g. Start/Select)
        self._zone_ids: dict[str, list[int]] = {}
        # canvas item ids for shortcut labels
        self._label_ids: dict[str, int] = {}

        self._bg_image: Optional[object] = None  # keep PIL reference alive

        self._draw_background()
        self._draw_zones()

    # ── Background ────────────────────────────────────────────────────────────

    def _draw_background(self) -> None:
        """
        Prefer the pre-rendered PNG (tools/render_controller_png.py),
        loaded via tkinter's built-in PNG support - no cairosvg/Pillow/
        native cairo DLL needed, so this always works in the packaged
        .exe. Falls back to live cairosvg rendering only for developers
        running from source with an SVG newer than the last render, and
        to the schematic placeholder as a last resort.
        """
        if self._load_prerendered_png():
            return
        if _CAIROSVG_OK and _SVG_PATH.exists() and self._render_svg_live():
            return
        self._render_fallback()

    def _load_prerendered_png(self) -> bool:
        if not _PNG_PATH.exists():
            return False
        try:
            self._bg_image = tk.PhotoImage(file=str(_PNG_PATH))
            self.create_image(0, 0, anchor="nw", image=self._bg_image)
            return True
        except Exception:
            return False

    def _render_svg_live(self) -> bool:
        try:
            png = cairosvg.svg2png(
                url=str(_SVG_PATH),
                output_width=self.CANVAS_W,
                output_height=self.CANVAS_H,
            )
            img = Image.open(io.BytesIO(png))
            self._bg_image = ImageTk.PhotoImage(img)
            self.create_image(0, 0, anchor="nw", image=self._bg_image)
            return True
        except Exception:
            return False

    def _render_fallback(self) -> None:
        """
        Draw a minimal placeholder scene using only tkinter Canvas when
        cairosvg/Pillow aren't installed.

        Rather than hand-copying the (much more detailed) new controller
        artwork with Canvas primitives, this draws one shape per entry in
        HIT_ZONES. That guarantees the fallback view always lines up with
        the real click targets, even as HIT_ZONES is tuned later.
        """
        sx, sy = self._sx, self._sy

        self.create_rectangle(
            0, 0, self.CANVAS_W, self.CANVAS_H,
            fill=C["surface2"], outline="",
        )

        for button, zone in RESOLVED_HIT_ZONES.items():
            shape = zone["shape"]
            coords = zone["coords"]

            if shape == "rect":
                x, y, w, h = coords
                self.create_rectangle(
                    x * sx, y * sy, (x + w) * sx, (y + h) * sy,
                    fill=C["surface"], outline=C["border"], width=1,
                )
            elif shape == "circle":
                cx, cy, r = coords
                self.create_oval(
                    (cx - r) * sx, (cy - r) * sy,
                    (cx + r) * sx, (cy + r) * sy,
                    fill=C["surface"], outline=C["border"], width=1,
                )
            elif shape == "poly":
                parts = coords if isinstance(coords[0], (list, tuple)) else [coords]
                for points in parts:
                    scaled = _scale_coords(points, sx, sy)
                    self.create_polygon(
                        scaled,
                        fill=C["surface"], outline=C["border"], width=1,
                    )
            else:
                continue

            lx, ly = zone["label_xy"]
            self.create_text(
                lx * sx, ly * sy,
                text=button, fill=C["text_dim"], font=("Segoe UI", 8),
            )

    # ── Hit zones ─────────────────────────────────────────────────────────────

    def _draw_zones(self) -> None:
        for button, zone in RESOLVED_HIT_ZONES.items():
            if button not in MAPPABLE_BUTTONS:
                continue
            self._draw_zone(button, zone)

    # Stipple pattern used to fake partial transparency on the Canvas
    # (Tkinter has no real alpha compositing for fills). "gray25" is a
    # 25%-of-pixels dither - sparse enough that the controller artwork
    # underneath, including the button's printed name, stays legible
    # through an unmapped zone. Mapped zones drop the stipple entirely
    # so they read as solid/opaque.
    _UNMAPPED_STIPPLE = "gray25"

    def _draw_zone(self, button: str, zone: dict) -> None:
        sx, sy = self._sx, self._sy
        shape = zone["shape"]
        coords = zone["coords"]
        mapped = bool(self._mapping.get(button, ""))
        fill = C["mapped"] if mapped else C["surface"]
        stipple = "" if mapped else self._UNMAPPED_STIPPLE

        item_ids: list[int] = []

        # Draw the clickable shape. "poly" may be more than one part
        # (e.g. Start/Select are each drawn as several paths in the
        # SVG) - every part shares the same tags so they behave as one
        # zone for hover/click/highlight purposes.
        if shape == "rect":
            x, y, w, h = coords
            pts = _rect_to_poly(x, y, w, h)
            scaled = _scale_coords(pts, sx, sy)
            item_ids.append(self.create_polygon(
                scaled,
                fill=fill, stipple=stipple, outline=C["border"], width=1.5,
                tags=("zone", f"zone_{button}"),
            ))
        elif shape == "circle":
            cx, cy, r = coords
            item_ids.append(self.create_oval(
                (cx - r) * sx, (cy - r) * sy,
                (cx + r) * sx, (cy + r) * sy,
                fill=fill, stipple=stipple, outline=C["border"], width=1.5,
                tags=("zone", f"zone_{button}"),
            ))
        elif shape == "poly":
            parts = coords if isinstance(coords[0], (list, tuple)) else [coords]
            for points in parts:
                scaled = _scale_coords(points, sx, sy)
                item_ids.append(self.create_polygon(
                    scaled,
                    fill=fill, stipple=stipple, outline=C["border"], width=1.5,
                    tags=("zone", f"zone_{button}"),
                ))
        else:
            return

        self._zone_ids[button] = item_ids

        # Button name label
        lx, ly = zone["label_xy"]
        shortcut = self._mapping.get(button, "")
        display = shortcut if shortcut else "—"
        label_id = self.create_text(
            lx * sx, ly * sy,
            text=f"{button}\n{display}",
            fill=C["mapped"] if shortcut else C["unmapped"],
            font=("Segoe UI", 9, "bold"),
            justify="center",
            tags=(f"label_{button}",),
        )
        self._label_ids[button] = label_id

        # Bind events
        for tag in (f"zone_{button}", f"label_{button}"):
            self.tag_bind(tag, "<Enter>",
                          lambda e, b=button: self._on_hover(b, True))
            self.tag_bind(tag, "<Leave>",
                          lambda e, b=button: self._on_hover(b, False))
            self.tag_bind(tag, "<Button-1>",
                          lambda e, b=button: self._on_click(b))

    # ── Zone state updates ────────────────────────────────────────────────────

    def _on_hover(self, button: str, entering: bool) -> None:
        if button == self._active_button:
            return
        zone_ids = self._zone_ids.get(button)
        if not zone_ids:
            return
        if entering:
            for zone_id in zone_ids:
                self.itemconfig(zone_id, fill=C["highlight"], stipple="",
                                 outline=C["accent"])
            self.config(cursor="hand2")
        else:
            mapped = bool(self._mapping.get(button, ""))
            fill = C["mapped"] if mapped else C["surface"]
            stipple = "" if mapped else self._UNMAPPED_STIPPLE
            for zone_id in zone_ids:
                self.itemconfig(zone_id, fill=fill, stipple=stipple,
                                 outline=C["border"])
            self.config(cursor="")

    def _on_click(self, button: str) -> None:
        self.set_active(button)
        self._on_button_click(button)

    def set_active(self, button: Optional[str]) -> None:
        """Highlight the active button zone; reset the previous one."""
        # Reset previous
        if self._active_button and self._active_button != button:
            prev_mapped = bool(self._mapping.get(self._active_button, ""))
            prev_fill = C["mapped"] if prev_mapped else C["surface"]
            prev_stipple = "" if prev_mapped else self._UNMAPPED_STIPPLE
            for zone_id in self._zone_ids.get(self._active_button, []):
                self.itemconfig(zone_id, fill=prev_fill, stipple=prev_stipple,
                                 outline=C["border"])

        self._active_button = button

        if button is not None:
            for zone_id in self._zone_ids.get(button, []):
                self.itemconfig(zone_id,
                                fill=C["accent_press"], stipple="",
                                outline=C["accent_hover"], width=2)

    def update_label(self, button: str, shortcut: str) -> None:
        """
        Refresh the shortcut text shown inside a zone, and flip the
        zone itself between the dithered "unmapped, see-through" look
        and the solid "mapped" look to match.
        """
        label_id = self._label_ids.get(button)
        if label_id is None:
            return
        display = shortcut if shortcut else "—"
        self.itemconfig(
            label_id,
            text=f"{button}\n{display}",
            fill=C["mapped"] if shortcut else C["unmapped"],
        )

        if button != self._active_button:
            mapped = bool(shortcut)
            fill = C["mapped"] if mapped else C["surface"]
            stipple = "" if mapped else self._UNMAPPED_STIPPLE
            for zone_id in self._zone_ids.get(button, []):
                self.itemconfig(zone_id, fill=fill, stipple=stipple)

    def update_mapping(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping
        for button in MAPPABLE_BUTTONS:
            self.update_label(button, mapping.get(button, ""))


# ═══════════════════════════════════════════════════════════════════════════════
#  Capture bar widget
# ═══════════════════════════════════════════════════════════════════════════════

class CaptureBar(tk.Frame):
    """
    Thin panel below the controller canvas.

    States:
      idle     – "Click a button on the controller to assign a shortcut."
      waiting  – "M1 → press your shortcut now…"
      recorded – "M1 → Ctrl+Shift+P  ✓"
    """

    def __init__(self, parent, on_clear, **kwargs):
        super().__init__(parent, bg=C["surface2"], **kwargs)
        self._on_clear = on_clear

        self._label = tk.Label(
            self,
            text="Click a button on the controller to assign a shortcut.",
            bg=C["surface2"],
            fg=C["text_dim"],
            font=("Segoe UI", 11),
            anchor="w",
            padx=16,
        )
        self._label.pack(side="left", fill="x", expand=True, pady=10)

        self._clear_btn = tk.Button(
            self,
            text="Clear",
            bg=C["surface"],
            fg=C["text_dim"],
            activebackground=C["red"],
            activeforeground=C["text_bright"],
            relief="flat",
            font=("Segoe UI", 10),
            padx=10,
            command=self._on_clear,
        )
        # Clear button only visible when something is selected
        self._clear_btn.pack(side="right", padx=12, pady=6)
        self._clear_btn.pack_forget()

    def set_idle(self) -> None:
        self._label.config(
            text="Click a button on the controller to assign a shortcut.",
            fg=C["text_dim"],
        )
        self._clear_btn.pack_forget()

    def set_waiting(self, button: str) -> None:
        self._label.config(
            text=f"  ● {button}  →  press your shortcut now…",
            fg=C["accent_hover"],
        )
        self._clear_btn.pack(side="right", padx=12, pady=6)

    def set_recorded(self, button: str, shortcut: str) -> None:
        display = shortcut if shortcut else "(unmapped)"
        self._label.config(
            text=f"  ✓ {button}  →  {display}",
            fg=C["green"],
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Status bar
# ═══════════════════════════════════════════════════════════════════════════════

class StatusBar(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=C["bg"], **kwargs)

        self._save_btn = tk.Button(
            self,
            text="Save",
            bg=C["accent"],
            fg=C["text_bright"],
            activebackground=C["accent_hover"],
            activeforeground=C["text_bright"],
            relief="flat",
            font=("Segoe UI", 11, "bold"),
            padx=20, pady=6,
            cursor="hand2",
        )
        self._save_btn.pack(side="left", padx=16, pady=8)

        self._status = tk.Label(
            self,
            text="",
            bg=C["bg"],
            fg=C["text_dim"],
            font=("Segoe UI", 10),
        )
        self._status.pack(side="left", padx=8)

    def bind_save(self, command) -> None:
        self._save_btn.config(command=command)

    def set_status(self, text: str, colour: str = C["text_dim"]) -> None:
        self._status.config(text=text, fg=colour)

    def flash_saved(self) -> None:
        self.set_status("Saved  ✓", C["green"])
        self._status.after(3000, lambda: self.set_status(""))


# ═══════════════════════════════════════════════════════════════════════════════
#  Main application
# ═══════════════════════════════════════════════════════════════════════════════

class VaderConfigApp:

    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._root.title("Flydigi Vader Mapper")
        self._root.configure(bg=C["bg"])
        self._root.resizable(False, False)

        try:
            if _ICON_PATH.exists():
                self._root.iconbitmap(default=str(_ICON_PATH))
        except Exception:
            pass

        self._mapping: dict[str, str] = cfg.load()
        self._active_button: Optional[str] = None

        # ── Outer 1px border (native frame is gone, draw our own) ──────────────
        border_frame = tk.Frame(root, bg=C["border"])
        border_frame.pack(fill="both", expand=True)

        content = tk.Frame(border_frame, bg=C["bg"])
        content.pack(fill="both", expand=True, padx=1, pady=1)

        # ── Custom title bar ─────────────────────────────────────────────────
        TitleBar(content, root, "Vader Remapper", f"v{VERSION}").pack(fill="x")

        # ── Controller canvas ─────────────────────────────────────────────────
        self._canvas = ControllerCanvas(
            content,
            mapping=self._mapping,
            on_button_click=self._on_button_clicked,
        )
        self._canvas.pack()

        # Thin separator
        tk.Frame(content, bg=C["border"], height=1).pack(fill="x")

        # ── Capture bar ───────────────────────────────────────────────────────
        self._capture_bar = CaptureBar(content, on_clear=self._clear_mapping)
        self._capture_bar.pack(fill="x")

        # Thin separator
        tk.Frame(content, bg=C["border"], height=1).pack(fill="x")

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_bar = StatusBar(content)
        self._status_bar.bind_save(self._save)
        self._status_bar.pack(fill="x")

        # Strip the native caption once all widgets (and thus the HWND)
        # exist, then re-center now that the frame size actually changed.
        self._root.after(0, lambda: _strip_native_titlebar(self._root))
        self._center_window()

        # ── Key capture binding ───────────────────────────────────────────────
        # Bound only while a button is active.
        self._capturing = False

    # ── Window placement ──────────────────────────────────────────────────────

    def _center_window(self) -> None:
        self._root.update_idletasks()
        w = self._root.winfo_reqwidth()
        h = self._root.winfo_reqheight()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 3
        self._root.geometry(f"{w}x{h}+{x}+{y}")

    # ── Button selection ──────────────────────────────────────────────────────

    def _on_button_clicked(self, button: str) -> None:
        """Called when the user clicks a zone on the controller canvas."""
        self._active_button = button
        self._capturing = True
        self._canvas.set_active(button)
        self._capture_bar.set_waiting(button)
        self._root.bind("<KeyPress>", self._on_key_press)
        self._status_bar.set_status(
            f"Press your shortcut for {button}…", C["accent"]
        )

    def _finish_capture(self) -> None:
        self._capturing = False
        self._root.unbind("<KeyPress>")

    # ── Key recording ─────────────────────────────────────────────────────────

    def _on_key_press(self, event: tk.Event) -> str:
        if not self._capturing or self._active_button is None:
            return "break"

        shortcut = _build_shortcut(event)
        if not shortcut:
            return "break"   # modifier-only press, keep waiting

        button = self._active_button
        self._mapping[button] = shortcut

        # Update canvas label
        self._canvas.update_label(button, shortcut)

        # Update capture bar
        self._capture_bar.set_recorded(button, shortcut)

        # Reset canvas highlight after short delay
        self._root.after(600, lambda: self._canvas.set_active(None))

        self._finish_capture()

        if AUTOSAVE:
            self._save(silent=True)
        else:
            self._status_bar.set_status(
                "Unsaved changes – click Save.", C["text_dim"]
            )

        return "break"   # prevent the key from firing normally

    # ── Clear mapping ─────────────────────────────────────────────────────────

    def _clear_mapping(self) -> None:
        """Remove the mapping for the currently-selected button."""
        if self._active_button is None:
            return
        button = self._active_button
        self._mapping[button] = ""
        self._canvas.update_label(button, "")
        self._capture_bar.set_idle()
        self._canvas.set_active(None)
        self._active_button = None
        self._finish_capture()

        if AUTOSAVE:
            self._save(silent=True)

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save(self, silent: bool = False) -> None:
        try:
            cfg.save(self._mapping)
            if not silent:
                self._status_bar.flash_saved()
            else:
                self._status_bar.set_status("Auto-saved  ✓", C["green"])
                self._root.after(
                    2000, lambda: self._status_bar.set_status("")
                )
        except Exception as exc:
            messagebox.showerror(
                "Save failed",
                f"Could not write config.json:\n{exc}",
            )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    # Not strictly required (unlike the service, running two copies of the
    # GUI can't corrupt anything thanks to the atomic-write config module),
    # but a second window popping up out of nowhere still looks like a bug.
    if not single_instance.acquire(MUTEX_NAME):
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                "Vader Remapper Config is already open.",
                "Vader Remapper",
                0x00000040,
            )
        except Exception:
            pass
        return

    root = tk.Tk()

    # High-DPI awareness on Windows
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = VaderConfigApp(root)  # noqa: F841
    root.mainloop()


if __name__ == "__main__":
    main()
