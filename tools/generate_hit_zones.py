"""
Derive controller.svg button hit-zones -> assets/hit_zones.json.

Computing accurate bounding boxes for curved/rotated shapes (the stick
caps and D-pad use elliptical arcs and rotate() transforms) needs a real
SVG geometry library - svgelements does this correctly and is pure
Python, but there's no reason for every run of VaderConfig.exe to carry
that dependency just to re-derive numbers that only change when someone
edits controller.svg. Run this once per SVG change; the app reads the
resulting JSON with nothing but the stdlib `json` module.

Usage:
    pip install svgelements
    python tools/generate_hit_zones.py
"""
from __future__ import annotations
import json
import pathlib
import sys
from svgelements import SVG, Shape  # dev-time only

ROOT = pathlib.Path(__file__).resolve().parent.parent
SVG_PATH = ROOT / "assets" / "controller.svg"
OUT_PATH = ROOT / "assets" / "hit_zones.json"

INKSCAPE_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"

# SVG inkscape:label -> our button name (see src/shared/constants.py).
# Only unambiguous, single-shape labels are listed; "Home"/"Arrow"/
# "Circle" have no distinct shape yet in the artwork (only one shared
# "FN" toggle near the logo) and stay on main.py's manual placeholder.
SVG_LABEL_TO_BUTTON: dict[str, str] = {
    "RM": "RM", "RB": "RB", "RT": "RT",
    "LM": "LM", "LB": "LB", "LT": "LT",
    "M1": "M1", "M2": "M2", "M3": "M3", "M4": "M4",
    "A": "A", "B": "B", "X": "X", "Y": "Y", "Z": "Z",
    "U": "DPad Up", "D": "DPad Down", "L": "DPad Left", "R": "DPad Right",
    "LI": "STICK-L", "RI": "STICK-R",
    "SE": "Select", "ST": "Start",
}

# "C" appears twice with the same inkscape:label - the real face button
# (BUTTONS layer, id "path220") and an unrelated toggle shape near the
# logo (FUNCT layer, id "rect3"). Only trust the former.
C_BUTTON_SHAPE_ID = "path220"


def main() -> int:
    if not SVG_PATH.exists():
        print(f"Not found: {SVG_PATH}")
        return 1

    svg = SVG.parse(str(SVG_PATH))
    zones: dict[str, list[float]] = {}

    for el in svg.elements():
        if not isinstance(el, Shape):
            continue
        label = el.values.get(INKSCAPE_LABEL) if hasattr(el, "values") else None
        if not label:
            continue

        if label == "C":
            if el.values.get("id") != C_BUTTON_SHAPE_ID:
                continue
            button = "C"
        else:
            button = SVG_LABEL_TO_BUTTON.get(label)
        if not button:
            continue

        try:
            bbox = el.bbox()
        except Exception:
            continue
        if not bbox:
            continue

        min_x, min_y, max_x, max_y = bbox
        if button in zones:
            ox0, oy0, ox1, oy1 = zones[button]
            min_x, min_y = min(min_x, ox0), min(min_y, oy0)
            max_x, max_y = max(max_x, ox1), max(max_y, oy1)
        zones[button] = [min_x, min_y, max_x, max_y]

    missing = (set(SVG_LABEL_TO_BUTTON.values()) | {"C"}) - set(zones)
    if missing:
        print(f"WARNING: no shape found for: {sorted(missing)}")

    OUT_PATH.write_text(json.dumps(zones, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(zones)} buttons)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
