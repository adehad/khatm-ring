# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["opencv-python-headless", "numpy", "shapely"]
# ///
"""The seal inscription, redrawn as even-width strokes, written out for Blender.

Coordinates are on a 1000 x 1000 square inscribed in the bezel's outer edge,
y down, laid over the rectified photo `extracted/face-crop.png`. Every letter
is a centreline swept with a round pen, so stroke width, terminals and joins
are uniform. That keeps every section castable: no hairlines, no pinholes.

Outputs in `extracted/`:
  face-inscription.json  letter and back-pocket outlines in mm, read by `build_ring.py`
  face-inscription.svg   the same outlines, for any vector tool
  face-overlay.png       outlines over the photo, to check the drawing
"""

import json
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
SIZE = 1000
CENTRE = (500, 500)
FACE_MM = 17.0

PEN = 72
FIELD_R = 432
LAYOUT_SCALE = 0.86
COUNTER_R = 28
POCKET_INSET_MM = 0.3
POCKET_MIN_HALF_MM = 0.25


def fit(p):
    """Pull a drawing point towards the centre so the inscription clears the rim."""
    return (CENTRE[0] + (p[0] - CENTRE[0]) * LAYOUT_SCALE, CENTRE[1] + (p[1] - CENTRE[1]) * LAYOUT_SCALE)


def smooth(pts, samples=10):
    """Open Catmull-Rom through the points, so a stroke bends instead of kinking."""
    p = np.asarray([pts[0], *pts, pts[-1]], dtype=float)
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        for t in np.linspace(0, 1, samples, endpoint=False):
            out.append(
                0.5
                * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t**3)
            )
    out.append(p[-2])
    return [tuple(q) for q in out]


def stroke(*pts, w=PEN):
    line = smooth(pts) if len(pts) > 2 else list(pts)
    return LineString([fit(p) for p in line]).buffer(w / 2, quad_segs=24)


def blob(c, r):
    return Point(fit(c)).buffer(r, quad_segs=32)


def loop(c, r):
    """Disc of a looped letter; its counter is cut once the word is assembled."""
    return blob(c, r)


def word(parts, counters):
    shape = unary_union(parts)
    for c in counters:
        shape = shape.difference(blob(c, COUNTER_R))
    return shape


def word_allah():
    alif = stroke((672, 96), (668, 282))
    lam1 = stroke((430, 84), (432, 254))
    lam2 = stroke((536, 74), (542, 254))
    base = stroke((300, 274), (450, 272), (550, 260))
    ha = loop((308, 222), 68)
    hook = stroke((292, 168), (322, 140), (358, 128))
    return [alif, word([lam1, lam2, base, ha, hook], [(308, 222)])]


def word_rasul():
    ra = stroke((826, 362), (818, 488), w=80)
    lam = stroke((152, 344), (168, 420), (162, 520), (148, 616))
    base = stroke((278, 566), (480, 542), (690, 496))
    teeth = [stroke((450, 534), (448, 436)), stroke((566, 514), (564, 424))]
    sad = stroke((668, 494), (700, 426), (716, 420), w=86)
    waw = loop((304, 472), 64)
    return [ra, lam, word([base, *teeth, sad, waw], [(304, 472)])]


def word_muhammad():
    mim1 = loop((736, 652), 68)
    neck = stroke((686, 690), (620, 718))
    ha_diag = stroke((616, 724), (690, 766), (762, 808))
    ha_base = stroke((584, 818), (680, 820), (768, 814))
    mim2 = loop((505, 776), 60)
    dal = stroke((268, 694), (300, 708), (372, 710), (452, 742))
    tail = stroke((456, 816), (380, 838), (300, 850), (266, 840))
    return [word([mim1, neck, ha_diag, ha_base, mim2, dal, tail], [(736, 652), (505, 776)])]


def letters() -> MultiPolygon:
    shapes = unary_union(word_allah() + word_rasul() + word_muhammad())
    polys = shapes.geoms if isinstance(shapes, MultiPolygon) else [shapes]
    # Where strokes cross they can trap slivers smaller than a counter: fill them,
    # they would only trap investment in the casting.
    min_hole = 0.8 * np.pi * COUNTER_R**2
    clean = [Polygon(p.exterior, [h for h in p.interiors if Polygon(h).area > min_hole]) for p in polys]
    return MultiPolygon(clean)


def to_mm(x: float, y: float) -> tuple[float, float]:
    return ((x - CENTRE[0]) / SIZE * FACE_MM, -(y - CENTRE[1]) / SIZE * FACE_MM)


def polygons_json(shapes: MultiPolygon, tolerance: float = 0.6) -> list[dict]:
    out = []
    for poly in shapes.geoms:
        poly = poly.simplify(tolerance)
        out.append(
            {
                "outline": [to_mm(x, y) for x, y in list(poly.exterior.coords)[:-1]],
                "holes": [[to_mm(x, y) for x, y in list(h.coords)[:-1]] for h in poly.interiors],
            }
        )
    return out


def svg(shapes: MultiPolygon) -> str:
    def path(coords):
        return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords) + " Z"

    body = [
        f'<circle cx="{CENTRE[0]}" cy="{CENTRE[1]}" r="{SIZE / 2}" fill="none" stroke="black"/>',
        f'<circle cx="{CENTRE[0]}" cy="{CENTRE[1]}" r="{FIELD_R}" fill="none" stroke="black"/>',
    ]
    for p in shapes.geoms:
        d = " ".join(path(r.coords) for r in [p.exterior, *p.interiors])
        body.append(f'<path d="{d}" fill-rule="evenodd"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" '
        f'viewBox="0 0 {SIZE} {SIZE}">\n' + "\n".join(body) + "\n</svg>\n"
    )


def overlay(shapes: MultiPolygon, path: Path) -> None:
    import cv2

    img = cv2.resize(cv2.imread(str(ROOT / "extracted" / "face-crop.png")), (SIZE, SIZE))
    paint = img.copy()
    for p in shapes.geoms:
        cv2.fillPoly(paint, [np.asarray(r.coords, np.int32) for r in [p.exterior, *p.interiors]], (0, 200, 255))
    cv2.circle(paint, CENTRE, FIELD_R, (255, 0, 255), 3)
    cv2.imwrite(str(path), cv2.addWeighted(img, 0.45, paint, 0.55, 0))


def main() -> None:
    out = ROOT / "extracted"
    shapes = letters()
    # The back of the face plate is pocketed under each letter so the plate is one
    # thickness throughout. The inset keeps a wall round each pocket.
    inset = POCKET_INSET_MM / FACE_MM * SIZE
    # Opening drops any sliver narrower than 2 * POCKET_MIN_HALF_MM: it would not
    # fill with investment and would self-intersect when its edges are rounded.
    half = POCKET_MIN_HALF_MM / FACE_MM * SIZE
    pockets = shapes.buffer(-inset - half, quad_segs=16).buffer(half, quad_segs=16)
    pockets = pockets if isinstance(pockets, MultiPolygon) else MultiPolygon([pockets])
    pockets = MultiPolygon([p for p in pockets.geoms if p.area > (2 * inset) ** 2])
    data = {
        "face_mm": FACE_MM,
        "field_radius_mm": FIELD_R / SIZE * FACE_MM,
        "letters": polygons_json(shapes),
        "pockets": polygons_json(pockets),
    }
    (out / "face-inscription.json").write_text(json.dumps(data, indent=1))
    (out / "face-inscription.svg").write_text(svg(shapes))
    overlay(shapes, out / "face-overlay.png")
    pen_mm = PEN / SIZE * FACE_MM
    print(f"{len(shapes.geoms)} letter shapes, pen {pen_mm:.2f} mm, counters {2 * COUNTER_R / SIZE * FACE_MM:.2f} mm")


if __name__ == "__main__":
    main()
