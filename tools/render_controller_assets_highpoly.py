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
POLYGON_MIN_POINTS = 32     # Minimum points
POLYGON_MAX_POINTS = 64     # Maximum points

# RDP simplification tolerance as a fraction of shape diagonal.
RDP_TOLERANCE_BASE = 0.002

# Which contour to keep when a button shape produces multiple polygon rings.
#   "outer"  – keep only the polygon with the largest area
#   "inner"  – keep only the polygon with the smallest area
#   "middle" – compute midpoint between outer and inner contours
CONTOUR_MODE = "middle"   # "outer" | "inner" | "middle"

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
    """Ramer-Douglas-Peucker polygon simplification."""
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
    """
    if len(points) <= max_points:
        return points

    result = _rdp_simplify(points, base_epsilon)

    if min_points <= len(result) <= max_points:
        return result

    if len(result) < min_points:
        epsilon = base_epsilon
        for _ in range(20):
            epsilon *= 0.7
            result = _rdp_simplify(points, epsilon)
            if len(result) >= min_points:
                break
        return result

    if len(result) > max_points:
        epsilon = base_epsilon
        for _ in range(20):
            epsilon *= 1.4
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


def _sample_path_dense(path: Path, count: int) -> list[tuple[float, float]]:
    """
    Sample a Path at *count* evenly-spaced t values.
    Returns list of (x, y) tuples.
    """
    pts: list[tuple[float, float]] = []
    for i in range(count):
        t = i / count
        try:
            pt = path.point(t)
            pts.append((pt.x, pt.y))
        except Exception:
            continue
    return pts


def _sample_middle_from_paths(
    outer_path: Path,
    inner_path: Path,
) -> list[float] | None:
    """
    Compute the true geometric middle contour between outer and inner paths.

    Uses perpendicular projection onto the inner path treated as a continuous
    polyline, eliminating the vertex-density bias that nearest-neighbour
    snapping produces in curves.
    """
    DENSE = 2000

    try:
        bbox = outer_path.bbox()
    except Exception:
        return None
    if not bbox:
        return None

    outer_dense = _sample_path_dense(outer_path, DENSE)
    inner_dense = _sample_path_dense(inner_path, DENSE)

    if len(outer_dense) < 3 or len(inner_dense) < 3:
        return None

    def nearest_point_on_polyline(
        px: float,
        py: float,
        poly: list[tuple[float, float]],
    ) -> tuple[float, float]:
        """
        Find the nearest point on a closed polyline to (px, py).
        Projects onto each edge segment and picks the closest result.
        This is continuous - not limited to vertices - so it has no
        density bias.
        """
        min_dist_sq = float('inf')
        nearest = poly[0]
        n = len(poly)

        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]

            dx = x2 - x1
            dy = y2 - y1
            seg_len_sq = dx * dx + dy * dy

            if seg_len_sq < 1e-12:
                # Degenerate edge - just check the vertex
                dist_sq = (px - x1) ** 2 + (py - y1) ** 2
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    nearest = (x1, y1)
                continue

            # Project point onto segment, clamped to [0, 1]
            t = ((px - x1) * dx + (py - y1) * dy) / seg_len_sq
            t = max(0.0, min(1.0, t))

            # Closest point on segment
            cx = x1 + t * dx
            cy = y1 + t * dy

            dist_sq = (px - cx) ** 2 + (py - cy) ** 2
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                nearest = (cx, cy)

        return nearest

    middle_dense: list[tuple[float, float]] = []

    for ox, oy in outer_dense:
        ix, iy = nearest_point_on_polyline(ox, oy, inner_dense)
        middle_dense.append((
            (ox + ix) / 2.0,
            (oy + iy) / 2.0,
        ))

    # Simplify to normal point budget
    min_x, min_y, max_x, max_y = bbox
    diagonal = ((max_x - min_x) ** 2 + (max_y - min_y) ** 2) ** 0.5
    base_epsilon = diagonal * RDP_TOLERANCE_BASE

    simplified = _adaptive_simplify(
        middle_dense,
        base_epsilon,
        POLYGON_MIN_POINTS,
        POLYGON_MAX_POINTS,
    )

    result: list[float] = []
    for x, y in simplified:
        result.extend([x, y])

    return result if len(result) >= 6 else None


def _apply_contour_mode(
    polygons: list[list[float]],
    subpaths: list[Path] | None = None,
) -> list[list[float]]:
    """
    Filter / compute polygons according to CONTOUR_MODE.

    For "middle": if the raw Path subpaths are available we compute the
    middle directly from the high-density curve samples (accurate).
    Falling back to the already-simplified polygons is only a last resort.
    """
    if len(polygons) <= 1:
        return polygons

    ranked_polys = sorted(polygons, key=_polygon_area)

    if CONTOUR_MODE == "inner":
        return [ranked_polys[0]]

    if CONTOUR_MODE == "outer":
        return [ranked_polys[-1]]

    if CONTOUR_MODE == "middle":
        # ------------------------------------------------------------------
        # Best path: re-sample from the actual SVG curves at high density.
        # subpaths are passed in ranked smallest→largest area so that
        # subpaths[0] = inner curve, subpaths[-1] = outer curve.
        # ------------------------------------------------------------------
        if subpaths and len(subpaths) >= 2:
            middle = _sample_middle_from_paths(subpaths[-1], subpaths[0])
            if middle:
                return [middle]

        # Fallback (should not normally be reached)
        return [ranked_polys[-1]]

    return polygons


def _sample_single_path(path: Path) -> list[float] | None:
    """
    Sample a single-subpath Path into a polygon using dense sampling
    followed by adaptive RDP simplification.
    """
    try:
        length = path.length(error=1e-2)
        bbox = path.bbox()
    except Exception:
        return None

    if not length or length < 1e-6 or not bbox:
        return None

    dense_count = POLYGON_MAX_POINTS * 10
    dense_points = _sample_path_dense(path, dense_count)

    if len(dense_points) < 3:
        return None

    min_x, min_y, max_x, max_y = bbox
    diagonal = ((max_x - min_x) ** 2 + (max_y - min_y) ** 2) ** 0.5
    base_epsilon = diagonal * RDP_TOLERANCE_BASE

    simplified = _adaptive_simplify(
        dense_points,
        base_epsilon,
        POLYGON_MIN_POINTS,
        POLYGON_MAX_POINTS,
    )

    points: list[float] = []
    for x, y in simplified:
        points.extend([x, y])

    return points if len(points) >= 6 else None


def _split_path_into_subpaths(path: Path) -> list[Path]:
    """Split a multi-subpath Path into separate Path objects."""
    subpath_segments = []
    current_segments: list = []

    for segment in path:
        seg_type = type(segment).__name__

        if seg_type == "Move" and current_segments:
            subpath_segments.append(current_segments)
            current_segments = [segment]
        else:
            current_segments.append(segment)

    if current_segments:
        subpath_segments.append(current_segments)

    subpaths = []
    for segments in subpath_segments:
        if not segments:
            continue
        sub = Path()
        if hasattr(path, 'transform') and path.transform is not None:
            sub.transform = path.transform
        for seg in segments:
            sub.append(seg)
        subpaths.append(sub)

    return subpaths if subpaths else [path]


def _shape_to_polygons(element: Shape) -> tuple[list[list[float]], list[Path]]:
    """
    Convert a Shape to one or more polygons with adaptive point counts.

    Returns
    -------
    polygons  : list of flat [x,y,...] polygon lists
    subpaths  : the corresponding Path objects (same order / length),
                needed by _apply_contour_mode for middle computation.
    """
    try:
        path = Path(element)
    except Exception:
        return [], []

    subpaths = _split_path_into_subpaths(path)

    polygons: list[list[float]] = []
    valid_subpaths: list[Path] = []

    for sub in subpaths:
        poly = _sample_single_path(sub)
        if poly:
            polygons.append(poly)
            valid_subpaths.append(sub)

    return polygons, valid_subpaths


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
    # Store subpaths alongside polygons so _apply_contour_mode can use them
    zones_subpaths: dict[str, list[Path]] = {}

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

        polys, subpaths = _shape_to_polygons(element)

        entry = zones.setdefault(button, {"bbox": None, "polygons": []})
        zones_subpaths.setdefault(button, [])

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
            zones_subpaths[button].extend(subpaths)
        else:
            entry["polygons"].append([
                min_x, min_y, max_x, min_y,
                max_x, max_y, min_x, max_y,
            ])

    # Apply contour filtering per button
    for button in zones:
        before = len(zones[button]["polygons"])

        # Sort subpaths by polygon area (smallest=inner, largest=outer)
        # to match what _apply_contour_mode expects
        paired = list(zip(
            zones[button]["polygons"],
            zones_subpaths.get(button, []),
        ))
        paired.sort(key=lambda p: _polygon_area(p[0]))
        sorted_subpaths = [p[1] for p in paired]

        zones[button]["polygons"] = _apply_contour_mode(
            zones[button]["polygons"],
            subpaths=sorted_subpaths,
        )
        after = len(zones[button]["polygons"])

        for poly in zones[button]["polygons"]:
            pt_count = len(poly) // 2
            print(f"  {button}: {pt_count} points")

        if before > after:
            print(f"  {button}: filtered {before} → {after} polygon(s)")

    missing = (set(SVG_LABEL_TO_BUTTON.values()) | {"C"}) - set(zones)
    if missing:
        print("WARNING: no shape found for:", sorted(missing))

    # Sanity check polygon sizes
    for button, entry in zones.items():
        for poly in entry["polygons"]:
            area = _polygon_area(poly)
            if area < 100:
                print(f"  WARNING: {button} has suspiciously small polygon (area={area:.1f})")
            if area > svg_w * svg_h * 0.5:
                print(f"  WARNING: {button} has suspiciously large polygon (area={area:.1f})")

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

            xs, ys = zip(*pts)
            ax.plot(xs, ys, 'o', color=color, markersize=5, alpha=0.8)

            if not label_drawn and pts:
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                ax.text(
                    cx, cy, name,
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