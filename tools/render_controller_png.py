"""
Pre-render assets/controller.svg to a fixed 900x625 PNG.

VaderConfig used to rasterize the SVG at runtime with cairosvg, which
needs the native libcairo library. PyInstaller does not reliably bundle
that, so the packaged .exe silently fell back to drawing bare hit-zone
boxes with no artwork behind them. Rendering once here (on a dev machine
that has cairosvg) and shipping the PNG as a normal asset means the app
only ever needs tkinter's built-in PNG support (tk.PhotoImage handles
PNG natively since Tk 8.6) - no cairosvg/Pillow/cairo DLL at runtime.

Usage:
    pip install cairosvg
    python tools/render_controller_png.py
"""
from __future__ import annotations
import pathlib
import sys
import cairosvg  # dev-time only

ROOT = pathlib.Path(__file__).resolve().parent.parent
SVG_PATH = ROOT / "assets" / "controller.svg"
PNG_PATH = ROOT / "assets" / "controller.png"

# Must match ControllerCanvas.CANVAS_W / CANVAS_H in src/config_gui/main.py
CANVAS_W = 900
CANVAS_H = 625


def main() -> int:
    if not SVG_PATH.exists():
        print(f"Not found: {SVG_PATH}")
        return 1
    cairosvg.svg2png(
        url=str(SVG_PATH), write_to=str(PNG_PATH),
        output_width=CANVAS_W, output_height=CANVAS_H,
    )
    print(f"Wrote {PNG_PATH} ({CANVAS_W}x{CANVAS_H})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
