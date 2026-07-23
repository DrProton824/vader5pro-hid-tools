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

Layout (900 × 720 window)
──────────────────────────
  ┌──────────────────────────────────────────┐
  │  title bar                               │
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

import io
import pathlib
import sys
import tkinter as tk
from tkinter import font as tkfont
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
from src.shared.constants import MAPPABLE_BUTTONS

# ── Optional SVG rendering ────────────────────────────────────────────────────
try:
    import cairosvg          # type: ignore
    from PIL import Image, ImageTk  # type: ignore
    _SVG_OK = True
except ImportError:
    _SVG_OK = False

_SVG_PATH = _ROOT / "assets" / "controller.svg"

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

SVG_W, SVG_H = 860, 580   # SVG viewBox dimensions

HIT_ZONES: dict[str, dict] = {
    "M1": {
        "shape": "poly",
        "coords": [480,450, 590,450, 602,458, 602,487, 464,487, 456,475],
        "label_xy": (531, 468),
    },
    "M2": {
        "shape": "poly",
        "coords": [270,450, 360,450, 380,475, 376,487, 258,487, 258,458],
        "label_xy": (319, 468),
    },
    "M3": {
        "shape": "poly",
        "coords": [485,497, 605,497, 616,505, 616,530, 467,530, 470,518],
        "label_xy": (543, 513),
    },
    "M4": {
        "shape": "poly",
        "coords": [255,497, 375,497, 390,518, 385,530, 244,530, 244,505],
        "label_xy": (317, 513),
    },
    "LM": {
        "shape": "rect",
        "coords": (170, 100, 80, 36),
        "label_xy": (210, 118),
    },
    "RM": {
        "shape": "rect",
        "coords": (610, 100, 80, 36),
        "label_xy": (650, 118),
    },
    "Z": {
        "shape": "circle",
        "coords": (690, 350, 20),
        "label_xy": (690, 348),
    },
    "C": {
        "shape": "circle",
        "coords": (655, 390, 20),
        "label_xy": (655, 388),
    },
    "Home": {
        "shape": "circle",
        "coords": (430, 175, 16),
        "label_xy": (430, 173),
    },
    "Arrow": {
        "shape": "circle",
        "coords": (430, 430, 14),
        "label_xy": (430, 428),
    },
    "Circle": {
        "shape": "circle",
        "coords": (430, 430, 14),   # placeholder – adjust if Circle differs
        "label_xy": (480, 395),
    },
}

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


# ═══════════════════════════════════════════════════════════════════════════════
#  Canvas controller widget
# ═══════════════════════════════════════════════════════════════════════════════

class ControllerCanvas(tk.Canvas):
    """
    Canvas that shows the controller image (SVG or fallback drawing)
    and renders interactive hit zones for each mappable button.
    """

    CANVAS_W = 860
    CANVAS_H = 500   # crop some whitespace from SVG bottom

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

        # canvas item ids for each zone
        self._zone_ids: dict[str, int] = {}
        # canvas item ids for shortcut labels
        self._label_ids: dict[str, int] = {}

        self._bg_image: Optional[object] = None  # keep PIL reference alive

        self._draw_background()
        self._draw_zones()

    # ── Background ────────────────────────────────────────────────────────────

    def _draw_background(self) -> None:
        """Render SVG to canvas, or draw a simple schematic fallback."""
        if _SVG_OK and _SVG_PATH.exists():
            self._render_svg()
        else:
            self._render_fallback()

    def _render_svg(self) -> None:
        try:
            png = cairosvg.svg2png(
                url=str(_SVG_PATH),
                output_width=self.CANVAS_W,
                output_height=self.CANVAS_H,
            )
            img = Image.open(io.BytesIO(png))
            self._bg_image = ImageTk.PhotoImage(img)
            self.create_image(0, 0, anchor="nw", image=self._bg_image)
        except Exception:
            self._render_fallback()

    def _render_fallback(self) -> None:
        """
        Draw a simple dark controller schematic using only tkinter Canvas.
        Matches the general layout so hit zones line up correctly.
        """
        sx, sy = self._sx, self._sy

        def rx(x): return x * sx
        def ry(y): return y * sy

        # Body
        body_pts = [
            180,140, 430,95, 680,140,
            710,320, 700,470, 620,510,
            560,510, 510,490, 490,465,
            430,445, 370,465, 350,490,
            300,510, 240,510, 160,470,
            130,420, 150,320,
        ]
        scaled_body = _scale_coords(body_pts, sx, sy)
        self.create_polygon(
            scaled_body,
            fill=C["surface2"], outline=C["border"], width=2,
            smooth=True,
        )

        # V-stripe
        self.create_line(
            rx(350), ry(130), rx(430), ry(230), rx(510), ry(130),
            fill="#1a3050", width=14, joinstyle="round",
        )

        # Left stick
        self.create_oval(
            rx(218), ry(218), rx(322), ry(322),
            fill=C["surface2"], outline=C["border"], width=2,
        )
        self.create_oval(
            rx(235), ry(235), rx(305), ry(305),
            fill="#0d1520", outline=C["border"], width=1,
        )

        # Right stick
        self.create_oval(
            rx(498), ry(303), rx(602), ry(407),
            fill=C["surface2"], outline=C["border"], width=2,
        )
        self.create_oval(
            rx(515), ry(320), rx(585), ry(390),
            fill="#0d1520", outline=C["border"], width=1,
        )

        # D-pad horizontal
        self.create_rectangle(
            rx(300), ry(335), rx(384), ry(363),
            fill=C["surface"], outline=C["border"], width=1,
        )
        # D-pad vertical
        self.create_rectangle(
            rx(328), ry(307), rx(356), ry(391),
            fill=C["surface"], outline=C["border"], width=1,
        )

        # Face buttons (non-mappable, dim)
        for cx, cy, label in [
            (630, 235, "Y"), (590, 275, "X"),
            (670, 275, "B"), (630, 315, "A"),
        ]:
            self.create_oval(
                rx(cx-22), ry(cy-22), rx(cx+22), ry(cy+22),
                fill=C["surface2"], outline=C["border"], width=1,
            )
            self.create_text(
                rx(cx), ry(cy),
                text=label, fill=C["text_dim"], font=("Segoe UI", 11),
            )

        # Shoulder placeholders (non-mappable)
        for x, y, w, h, label in [
            (80, 100, 80, 36, "LT"), (115, 145, 80, 32, "LB"),
            (700, 100, 80, 36, "RT"), (665, 145, 80, 32, "RB"),
        ]:
            self.create_rectangle(
                rx(x), ry(y), rx(x+w), ry(y+h),
                fill=C["surface2"], outline=C["border"], width=1,
            )
            self.create_text(
                rx(x+w//2), ry(y+h//2),
                text=label, fill=C["text_dim"], font=("Segoe UI", 11),
            )

    # ── Hit zones ─────────────────────────────────────────────────────────────

    def _draw_zones(self) -> None:
        for button, zone in HIT_ZONES.items():
            if button not in MAPPABLE_BUTTONS:
                continue
            self._draw_zone(button, zone)

    def _draw_zone(self, button: str, zone: dict) -> None:
        sx, sy = self._sx, self._sy
        shape = zone["shape"]
        coords = zone["coords"]

        # Draw the clickable shape
        if shape == "rect":
            x, y, w, h = coords
            pts = _rect_to_poly(x, y, w, h)
            scaled = _scale_coords(pts, sx, sy)
            item_id = self.create_polygon(
                scaled,
                fill=C["surface"], outline=C["border"], width=1.5,
                tags=("zone", f"zone_{button}"),
            )
        elif shape == "circle":
            cx, cy, r = coords
            item_id = self.create_oval(
                (cx - r) * sx, (cy - r) * sy,
                (cx + r) * sx, (cy + r) * sy,
                fill=C["surface"], outline=C["border"], width=1.5,
                tags=("zone", f"zone_{button}"),
            )
        elif shape == "poly":
            scaled = _scale_coords(coords, sx, sy)
            item_id = self.create_polygon(
                scaled,
                fill=C["surface"], outline=C["border"], width=1.5,
                tags=("zone", f"zone_{button}"),
            )
        else:
            return

        self._zone_ids[button] = item_id

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
        zone_id = self._zone_ids.get(button)
        if zone_id is None:
            return
        if entering:
            self.itemconfig(zone_id, fill=C["highlight"], outline=C["accent"])
            self.config(cursor="hand2")
        else:
            self.itemconfig(zone_id, fill=C["surface"], outline=C["border"])
            self.config(cursor="")

    def _on_click(self, button: str) -> None:
        self.set_active(button)
        self._on_button_click(button)

    def set_active(self, button: Optional[str]) -> None:
        """Highlight the active button zone; reset the previous one."""
        # Reset previous
        if self._active_button and self._active_button != button:
            prev_id = self._zone_ids.get(self._active_button)
            if prev_id:
                self.itemconfig(prev_id,
                                fill=C["surface"], outline=C["border"])

        self._active_button = button

        if button is not None:
            zone_id = self._zone_ids.get(button)
            if zone_id:
                self.itemconfig(zone_id,
                                fill=C["accent_press"], outline=C["accent_hover"],
                                width=2)

    def update_label(self, button: str, shortcut: str) -> None:
        """Refresh the shortcut text shown inside a zone."""
        label_id = self._label_ids.get(button)
        if label_id is None:
            return
        display = shortcut if shortcut else "—"
        self.itemconfig(
            label_id,
            text=f"{button}\n{display}",
            fill=C["mapped"] if shortcut else C["unmapped"],
        )

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

        self._mapping: dict[str, str] = cfg.load()
        self._active_button: Optional[str] = None

        # ── Title ─────────────────────────────────────────────────────────────
        title_frame = tk.Frame(root, bg=C["bg"])
        title_frame.pack(fill="x", padx=0, pady=0)

        tk.Label(
            title_frame,
            text="Flydigi Vader Mapper",
            bg=C["bg"],
            fg=C["text_bright"],
            font=("Segoe UI", 15, "bold"),
            anchor="w",
            padx=16,
        ).pack(side="left", pady=(14, 8))

        tk.Label(
            title_frame,
            text="v1.0",
            bg=C["bg"],
            fg=C["text_dim"],
            font=("Segoe UI", 10),
        ).pack(side="right", padx=16, pady=(14, 8))

        # ── Controller canvas ─────────────────────────────────────────────────
        self._canvas = ControllerCanvas(
            root,
            mapping=self._mapping,
            on_button_click=self._on_button_clicked,
        )
        self._canvas.pack()

        # Thin separator
        tk.Frame(root, bg=C["border"], height=1).pack(fill="x")

        # ── Capture bar ───────────────────────────────────────────────────────
        self._capture_bar = CaptureBar(root, on_clear=self._clear_mapping)
        self._capture_bar.pack(fill="x")

        # Thin separator
        tk.Frame(root, bg=C["border"], height=1).pack(fill="x")

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_bar = StatusBar(root)
        self._status_bar.bind_save(self._save)
        self._status_bar.pack(fill="x")

        # ── Key capture binding ───────────────────────────────────────────────
        # Bound only while a button is active.
        self._capturing = False

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