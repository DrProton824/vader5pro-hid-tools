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
import xml.etree.ElementTree as ET

import cairosvg                          # dev-time only
from svgelements import SVG, Shape, Path # dev-time only

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from PIL import Image


# ===========================================================================
# SETTINGS
# ===========================================================================

# Must match ControllerCanvas.CANVAS_W / CANVAS_H
CANVAS_W = 889
CANVAS_H = 500

# Polygon point count bounds (adaptive: simple shapes use MIN, complex use MAX)
POLYGON_MIN_POINTS = 6     # Minimum points (e.g., hexagon for circles)
POLYGON_MAX_POINTS = 12    # Maximum points (for complex chamfered/filleted shapes)

# RDP simplification tolerance as a fraction of shape diagonal.
# The algorithm will auto-adjust this per shape to stay within [MIN, MAX] points.
# Lower base = prefers more detail; higher base = prefers simplicity.
RDP_TOLERANCE_BASE = 0.004

# Which contour to keep when a button shape produces multiple polygon rings.
#   "outer"  – keep only the polygon with the largest area
#   "inner"  – keep only the polygon with the smallest area
#   "all"    – keep every ring
CONTOUR_MODE = "outer"   # "outer" | "inner" | "all"

# Show a matplotlib preview of controller.png + hit zones after generation.
SHOW_PREVIEW = True

# ===========================================================================


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


# ---------------------------------------------------------------------------
# SVG intrinsic size helpers
# ---------------------------------------------------------------------------

def _parse_svg_dimensions(svg_path: pathlib.Path) -> tuple[float, float] | None:
    """Return (width, height) in user-units from the SVG root element."""
    try:
        tree = ET.parse(str(svg_path))
        root = tree.getroot()
    except ET.ParseError:
        return None

    def _px(value: str) -> float | None:
        """Convert a CSS length string to float pixels (96 dpi assumed)."""
        value = value.strip()
        conversions = {
            "px": 1,
            "pt": 96 / 72,
            "mm": 96 / 25.4,
            "cm": 96 / 2.54,
            "in": 96,
        }
        for unit, factor in conversions.items():
            if value.endswith(unit):
                try:
                    return float(value[: -len(unit)]) * factor
                except ValueError:
                    return None
        if value.endswith("%"):
            return None
        try:
            return float(value)
        except ValueError:
            return None

    w_attr = root.get("width", "")
    h_attr = root.get("height", "")
    vb_attr = root.get("viewBox", "")

    w = _px(w_attr) if w_attr else None
    h = _px(h_attr) if h_attr else None

    if w and h:
        return w, h

    if vb_attr:
        parts = vb_attr.replace(",", " ").split()
        if len(parts) == 4:
            try:
                vb_w = float(parts[2])
                vb_h = float(parts[3])
                if vb_w > 0 and vb_h > 0:
                    return vb_w, vb_h
            except ValueError:
                pass

    return None


def _check_aspect_ratio(
    svg_w: float,
    svg_h: float,
    target_w: int,
    target_h: int,
    tol: float = 0.01,
) -> bool:
    """Return True when the SVG aspect ratio matches the target within *tol*."""
    svg_ar    = svg_w / svg_h
    target_ar = target_w / target_h
    return abs(svg_ar - target_ar) / target_ar <= tol


def _ask_scale_options(
    svg_w: float,
    svg_h: float,
    target_w: int,
    target_h: int,
) -> tuple[int, int]:
    """Present three scaling choices to the user."""
    svg_ar = svg_w / svg_h

    opt1_w = target_w
    opt1_h = round(target_w / svg_ar)

    opt2_h = target_h
    opt2_w = round(target_h * svg_ar)

    opt3_w = target_w
    opt3_h = target_h

    print()
    print("=" * 60)
    print("WARNING: SVG aspect ratio does not match canvas settings.")
    print(f"  SVG size   : {svg_w:.1f} x {svg_h:.1f}  (ratio {svg_ar:.4f})")
    print(f"  Canvas size: {target_w} x {target_h}  (ratio {target_w/target_h:.4f})")
    print()
    print("Choose a scaling option:")
    print(f"  [1] Match width  → output {opt1_w} x {opt1_h} px")
    print(f"  [2] Match height → output {opt2_w} x {opt2_h} px")
    print(f"  [3] Force fit    → output {opt3_w} x {opt3_h} px  (may distort)")
    print("=" * 60)

    while True:
        raw = input("Enter choice [1/2/3]: ").strip()
        if raw == "1":
            return opt1_w, opt1_h
        if raw == "2":
            return opt2_w, opt2_h
        if raw == "3":
            return opt3_w, opt3_h
        print("  Please enter 1, 2, or 3.")


# ---------------------------------------------------------------------------
# PNG rendering
# ---------------------------------------------------------------------------

def render_png(
    svg_path: pathlib.Path,
    png_path: pathlib.Path,
    out_w: int,
    out_h: int,
) -> None:
    """Render *svg_path* to a PNG at exactly *out_w* × *out_h* pixels."""
    print(f"Rendering PNG at {out_w}x{out_h}...")
    cairosvg.svg2png(
        url=str(svg_path),
        write_to=str(png_path),
        output_width=out_w,
        output_height=out_h,
    )
    print(f"Wrote {png_path} ({out_w}x{out_h})")


# ---------------------------------------------------------------------------
# Polygon simplification (Ramer-Douglas-Peucker)
# ---------------------------------------------------------------------------

def _rdp_simplify(
    points: list[tuple[float, float]],
    epsilon: float
) -> list[tuple[float, float]]:
    """
    Ramer-Douglas-Peucker polygon simplification.
    
    Recursively removes points within *epsilon* perpendicular distance
    from the line segment connecting their neighbors.
    
    Preserves sharp corners while removing redundant points on smooth sections.
    """
    if len(points) < 3:
        return points
    
    dmax = 0.0
    index = 0
    end = len(points) - 1
    
    x1, y1 = points[0]
    x2, y2 = points[end]
    
    dx = x2 - x1
    dy = y2 - y1
    norm = (dx * dx + dy * dy) ** 0.5
    
    if norm < 1e-10:
        return [points[0]]
    
    for i in range(1, end):
        x, y = points[i]
        d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            dmax = d
            index = i
    
    if dmax > epsilon:
        left = _rdp_simplify(points[:index + 1], epsilon)
        right = _rdp_simplify(points[index:], epsilon)
        result = left[:-1] + right
    else:
        result = [points[0], points[end]]
    
    return result


def _adaptive_simplify(
    points: list[tuple[float, float]],
    base_epsilon: float,
    min_points: int,
    max_points: int,
) -> list[tuple[float, float]]:
    """
    Apply RDP simplification with adaptive epsilon to keep point count
    within [min_points, max_points].
    
    Simple shapes (circles) will naturally settle near min_points;
    complex shapes will use more points up to max_points.
    
    Parameters
    ----------
    points : dense sampled points
    base_epsilon : starting tolerance
    min_points : minimum allowed points
    max_points : maximum allowed points
    
    Returns
    -------
    Simplified polygon with point count in [min, max]
    """
    if len(points) <= max_points:
        return points
    
    # Try base tolerance first
    result = _rdp_simplify(points, base_epsilon)
    
    # Already in range? Done.
    if min_points <= len(result) <= max_points:
        return result
    
    # Too few points → tighten tolerance (smaller epsilon = keep more points)
    if len(result) < min_points:
        epsilon = base_epsilon
        for _ in range(20):  # max 20 iterations
            epsilon *= 0.7  # tighten
            result = _rdp_simplify(points, epsilon)
            if len(result) >= min_points:
                break
        return result
    
    # Too many points → loosen tolerance (larger epsilon = remove more points)
    if len(result) > max_points:
        epsilon = base_epsilon
        for _ in range(20):
            epsilon *= 1.4  # loosen
            result = _rdp_simplify(points, epsilon)
            if len(result) <= max_points:
                break
        return result
    
    return result


# ---------------------------------------------------------------------------
# Hit-zone extraction
# ---------------------------------------------------------------------------

def _polygon_area(points: list[float]) -> float:
    """Shoelace formula for polygon area (flat [x,y,x,y,...] format)."""
    coords = list(zip(points[0::2], points[1::2]))
    n = len(coords)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x0, y0 = coords[i]
        x1, y1 = coords[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def _apply_contour_mode(polygons: list[list[float]]) -> list[list[float]]:
    """Filter polygons according to CONTOUR_MODE."""
    if CONTOUR_MODE == "all" or len(polygons) <= 1:
        return polygons

    ranked = sorted(polygons, key=_polygon_area)

    if CONTOUR_MODE == "inner":
        return [ranked[0]]

    # "outer"
    return [ranked[-1]]


def _sample_single_path(path: Path) -> list[float] | None:
    """
    Sample a single-subpath Path into a polygon using dense sampling
    followed by adaptive RDP simplification.
    
    Point count will be between POLYGON_MIN_POINTS and POLYGON_MAX_POINTS,
    automatically using fewer points for simple shapes and more for complex ones.
    """
    try:
        length = path.length(error=1e-2)
        bbox = path.bbox()
    except Exception:
        return None

    if not length or length < 1e-6 or not bbox:
        return None

    # Dense initial sampling (enough to capture all detail)
    dense_count = POLYGON_MAX_POINTS * 10
    dense_points: list[tuple[float, float]] = []
    
    for i in range(dense_count):
        t = i / dense_count
        try:
            pt = path.point(t)
            dense_points.append((pt.x, pt.y))
        except Exception:
            continue
    
    if len(dense_points) < 3:
        return None
    
    # Calculate base tolerance from shape size
    min_x, min_y, max_x, max_y = bbox
    diagonal = ((max_x - min_x) ** 2 + (max_y - min_y) ** 2) ** 0.5
    base_epsilon = diagonal * RDP_TOLERANCE_BASE
    
    # Adaptive simplification: simple shapes → MIN points, complex → MAX points
    simplified = _adaptive_simplify(
        dense_points,
        base_epsilon,
        POLYGON_MIN_POINTS,
        POLYGON_MAX_POINTS
    )
    
    # Flatten to [x0, y0, x1, y1, ...]
    points = []
    for x, y in simplified:
        points.extend([x, y])
    
    return points if len(points) >= 6 else None


def _split_path_into_subpaths(path: Path) -> list[Path]:
    """
    Split a multi-subpath Path (e.g. "M ... z M ... z") into separate
    Path objects, one per closed subpath.
    """
    from svgelements import Move, Close
    
    subpath_segments = []
    current_segments = []
    prev_was_close = False

    for segment in path:
        seg_type = type(segment).__name__

        if prev_was_close and seg_type == "Move":
            if current_segments:
                subpath_segments.append(current_segments)
            current_segments = [segment]
            prev_was_close = False
        else:
            current_segments.append(segment)
            prev_was_close = (seg_type == "Close")

    if current_segments:
        subpath_segments.append(current_segments)

    subpaths = []
    for segments in subpath_segments:
        if not segments:
            continue
        sub = Path()
        for seg in segments:
            sub.append(seg)
        subpaths.append(sub)

    return subpaths if subpaths else [path]


def _shape_to_polygons(element: Shape) -> list[list[float]]:
    """
    Convert a Shape to one or more polygons with adaptive point counts.
    """
    try:
        path = Path(element)
    except Exception:
        return []

    subpaths = _split_path_into_subpaths(path)

    polygons = []
    for sub in subpaths:
        poly = _sample_single_path(sub)
        if poly:
            polygons.append(poly)

    return polygons


def _scale_zones(
    zones: dict,
    svg_w: float,
    svg_h: float,
    out_w: int,
    out_h: int,
) -> dict:
    """Re-scale all coordinates from SVG user-units to output-pixel space."""
    sx = out_w / svg_w
    sy = out_h / svg_h

    scaled: dict = {}
    for button, entry in zones.items():
        new_entry: dict = {"bbox": None, "polygons": []}

        if entry["bbox"] is not None:
            bx0, by0, bx1, by1 = entry["bbox"]
            new_entry["bbox"] = [
                bx0 * sx, by0 * sy,
                bx1 * sx, by1 * sy,
            ]

        for poly in entry["polygons"]:
            new_poly: list[float] = []
            it = iter(poly)
            for x in it:
                y = next(it)
                new_poly.append(x * sx)
                new_poly.append(y * sy)
            new_entry["polygons"].append(new_poly)

        scaled[button] = new_entry

    return scaled


def generate_hit_zones(
    svg_path: pathlib.Path,
    json_path: pathlib.Path,
    svg_w: float,
    svg_h: float,
    out_w: int,
    out_h: int,
) -> None:
    """Parse SVG, extract per-button hit zones with adaptive detail, write JSON."""
    print(
        f"Generating hit zones  (CONTOUR_MODE={CONTOUR_MODE!r}, "
        f"points: {POLYGON_MIN_POINTS}–{POLYGON_MAX_POINTS})..."
    )

    svg = SVG.parse(str(svg_path))
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

        polys = _shape_to_polygons(element)

        entry = zones.setdefault(button, {"bbox": None, "polygons": []})

        if entry["bbox"] is None:
            entry["bbox"] = [min_x, min_y, max_x, max_y]
        else:
            old = entry["bbox"]
            entry["bbox"] = [
                min(min_x, old[0]), min(min_y, old[1]),
                max(max_x, old[2]), max(max_y, old[3]),
            ]

        if polys:
            entry["polygons"].extend(polys)
        else:
            entry["polygons"].append([
                min_x, min_y, max_x, min_y,
                max_x, max_y, min_x, max_y,
            ])

    # Apply contour filtering per button
    for button in zones:
        before = len(zones[button]["polygons"])
        zones[button]["polygons"] = _apply_contour_mode(
            zones[button]["polygons"]
        )
        after = len(zones[button]["polygons"])
        
        # Report point counts per polygon
        for poly in zones[button]["polygons"]:
            pt_count = len(poly) // 2
            print(f"  {button}: {pt_count} points")
        
        if before > after:
            print(f"  {button}: filtered {before} → {after} polygon(s)")

    missing = (set(SVG_LABEL_TO_BUTTON.values()) | {"C"}) - set(zones)
    if missing:
        print("WARNING: no shape found for:", sorted(missing))

    zones = _scale_zones(zones, svg_w, svg_h, out_w, out_h)

    json_path.write_text(json.dumps(zones, indent=2), encoding="utf-8")
    
    total_polys = sum(len(v["polygons"]) for v in zones.values())
    total_pts = sum(len(p) // 2 for v in zones.values() for p in v["polygons"])
    avg_pts = total_pts / total_polys if total_polys else 0
    
    print(
        f"Wrote {json_path} ({len(zones)} buttons, {total_polys} polygon(s), "
        f"avg {avg_pts:.1f} pts/polygon)"
    )


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def show_preview(png_path: pathlib.Path, json_path: pathlib.Path) -> None:
    """Display controller PNG with hit-zone polygons overlaid."""
    print("Opening preview...")
    
    img  = Image.open(png_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))

    fig, ax = plt.subplots(figsize=(14, 8))
    ax.imshow(img)

    colors = plt.cm.tab20.colors

    for idx, (name, item) in enumerate(data.items()):
        color = colors[idx % len(colors)]
        label_drawn = False

        for flat in item.get("polygons", []):
            pts = list(zip(flat[0::2], flat[1::2]))
            if len(pts) < 3:
                continue

            ax.add_patch(
                MplPolygon(
                    pts,
                    closed=True,
                    fill=False,
                    edgecolor=color,
                    linewidth=2.5,
                )
            )

            # Draw vertex markers
            xs, ys = zip(*pts)
            ax.plot(xs, ys, 'o', color=color, markersize=5, alpha=0.8)

            if not label_drawn and pts:
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                
                # Show point count in label
                pt_count = len(pts)
                ax.text(
                    cx, cy, f"{name}\n{pt_count}pts",
                    color="white",
                    fontsize=8,
                    ha="center",
                    va="center",
                    fontweight="bold",
                    bbox=dict(
                        facecolor=color,
                        alpha=0.8,
                        pad=3,
                        boxstyle="round,pad=0.4"
                    ),
                )
                label_drawn = True

    ax.set_title(
        f"{png_path.name}  —  hit zones preview\n"
        f"CONTOUR_MODE={CONTOUR_MODE!r}  ·  points: {POLYGON_MIN_POINTS}–{POLYGON_MAX_POINTS}",
        fontsize=11,
        pad=12,
    )
    ax.axis("off")
    plt.tight_layout()
    plt.show()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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

    dims = _parse_svg_dimensions(svg_path)

    if dims is None:
        print(
            "WARNING: Could not read SVG dimensions. "
            f"Falling back to canvas size {CANVAS_W}x{CANVAS_H}."
        )
        svg_w, svg_h = float(CANVAS_W), float(CANVAS_H)
        out_w, out_h = CANVAS_W, CANVAS_H
    else:
        svg_w, svg_h = dims
        if _check_aspect_ratio(svg_w, svg_h, CANVAS_W, CANVAS_H):
            out_w, out_h = CANVAS_W, CANVAS_H
        else:
            out_w, out_h = _ask_scale_options(svg_w, svg_h, CANVAS_W, CANVAS_H)

    assets_dir = svg_path.parent
    png_path   = assets_dir / "controller.png"
    json_path  = assets_dir / "hit_zones.json"

    try:
        render_png(svg_path, png_path, out_w, out_h)
        generate_hit_zones(svg_path, json_path, svg_w, svg_h, out_w, out_h)
    except Exception as exc:
        print("\nERROR:")
        print(exc)
        import traceback
        traceback.print_exc()
        return 1

    print("\nDone.")

    if SHOW_PREVIEW:
        show_preview(png_path, json_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())