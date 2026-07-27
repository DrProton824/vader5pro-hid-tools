"""
Generates controller UI assets from a labelled SVG layout.

Creates:
    - controller.png   Rendered controller image
    - hit_zones.json   Button bounding boxes for UI interaction

Development tool only:
    Requires cairosvg and svgelements.
    Generated assets can be used without these dependencies at runtime.

Supports drag-and-drop SVG input or command line usage.
"""

from __future__ import annotations

import json
import pathlib
import sys

import cairosvg          # dev-time only
from svgelements import SVG, Shape, Path  # dev-time only


# Must match ControllerCanvas.CANVAS_W / CANVAS_H
CANVAS_W = 900
CANVAS_H = 625


INKSCAPE_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"


# SVG inkscape:label -> button name
SVG_LABEL_TO_BUTTON: dict[str, str] = {
    "RM": "RM",
    "RB": "RB",
    "RT": "RT",

    "LM": "LM",
    "LB": "LB",
    "LT": "LT",

    "M1": "M1",
    "M2": "M2",
    "M3": "M3",
    "M4": "M4",

    "A": "A",
    "B": "B",
    "X": "X",
    "Y": "Y",
    "Z": "Z",

    "U": "DPad Up",
    "D": "DPad Down",
    "L": "DPad Left",
    "R": "DPad Right",

    "LI": "STICK-L",
    "RI": "STICK-R",

    "SE": "Select",
    "ST": "Start",
}


# Duplicate "C" label exists; only use the actual face button.
C_BUTTON_SHAPE_ID = "path220"


def render_png(svg_path: pathlib.Path, png_path: pathlib.Path) -> None:
    print("Rendering PNG...")

    cairosvg.svg2png(
        url=str(svg_path),
        write_to=str(png_path),
        output_width=CANVAS_W,
        output_height=CANVAS_H,
    )

    print(f"Wrote {png_path} ({CANVAS_W}x{CANVAS_H})")

# Number of points used to approximate a shape's outline as a polygon.
# High enough that curved/chamfered button outlines look like their
# real silhouette rather than a coarse blob; low enough to stay cheap.
POLYGON_SAMPLES = 48


def _shape_to_polygon(element: Shape) -> list[float] | None:
    """
    Approximate a shape's outline as a flat [x0, y0, x1, y1, ...]
    polygon by sampling it as a Path at evenly spaced t values.

    Replaces the old bbox approach: this artwork uses fillet/chamfer/
    perspective-envelope path effects, so a shape's bbox can be
    noticeably bigger than the shape itself. Sampling the actual
    outline gives a hit zone that matches what's on the PNG.
    """
    try:
        path = Path(element)
        length = path.length(error=1e-2)
    except Exception:
        return None

    if not length:
        return None

    points: list[float] = []
    for i in range(POLYGON_SAMPLES):
        t = i / POLYGON_SAMPLES
        try:
            pt = path.point(t)
        except Exception:
            continue
        points.extend([pt.x, pt.y])

    return points if len(points) >= 6 else None  # need >= 3 vertices

def generate_hit_zones(svg_path: pathlib.Path, json_path: pathlib.Path) -> None:
    print("Generating hit zones...")

    svg = SVG.parse(str(svg_path))

    # button -> {"bbox": [minx,miny,maxx,maxy], "polygons": [[x,y,...], ...]}
    zones: dict[str, dict] = {}

    for element in svg.elements():

        if not isinstance(element, Shape):
            continue

        label = None

        if hasattr(element, "values"):
            label = element.values.get(INKSCAPE_LABEL)

        if not label:
            continue

        if label == "C":
            if element.values.get("id") != C_BUTTON_SHAPE_ID:
                continue
            button = "C"
        else:
            button = SVG_LABEL_TO_BUTTON.get(label)

        if not button:
            continue

        try:
            bbox = element.bbox()
        except Exception:
            continue

        if not bbox:
            continue

        min_x, min_y, max_x, max_y = bbox
        polygon = _shape_to_polygon(element)

        entry = zones.setdefault(button, {"bbox": None, "polygons": []})

        if entry["bbox"] is None:
            entry["bbox"] = [min_x, min_y, max_x, max_y]
        else:
            old = entry["bbox"]
            entry["bbox"] = [
                min(min_x, old[0]),
                min(min_y, old[1]),
                max(max_x, old[2]),
                max(max_y, old[3]),
            ]

        if polygon:
            entry["polygons"].append(polygon)
        else:
            # Fall back to a rectangle for this part rather than
            # dropping it silently.
            entry["polygons"].append([
                min_x, min_y, max_x, min_y,
                max_x, max_y, min_x, max_y,
            ])

    missing = (
        set(SVG_LABEL_TO_BUTTON.values()) | {"C"}
    ) - set(zones)

    if missing:
        print(
            "WARNING: no shape found for:",
            sorted(missing)
        )

    json_path.write_text(
        json.dumps(zones, indent=2),
        encoding="utf-8",
    )

    print(
        f"Wrote {json_path} ({len(zones)} buttons, "
        f"{sum(len(v['polygons']) for v in zones.values())} polygon parts)"
    )


def main() -> int:

    if len(sys.argv) < 2:
        print(
            "\nController asset generator\n"
            "\nUsage:\n"
            "  Drag and drop an .svg file onto this script\n"
            "\nOr run from console:\n"
            "  python render_controller_assets.py path/to/file.svg\n"
        )
        return 0

    svg_path = pathlib.Path(sys.argv[1]).resolve()

    if not svg_path.exists():
        print(f"SVG not found: {svg_path}")
        return 1

    if svg_path.suffix.lower() != ".svg":
        print("Input file must be an .svg")
        return 1


    # Output beside the SVG
    assets_dir = svg_path.parent

    png_path = assets_dir / "controller.png"
    json_path = assets_dir / "hit_zones.json"


    try:
        render_png(svg_path, png_path)
        generate_hit_zones(svg_path, json_path)

    except Exception as exc:
        print("\nERROR:")
        print(exc)
        return 1


    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
