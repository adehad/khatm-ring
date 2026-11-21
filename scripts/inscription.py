# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["opencv-python-headless", "numpy", "shapely"]
# ///
"""Lift the seal inscription from a reference rendering and lay it out on the ring face.

The references in `reference/seal/` are public-domain renderings of the prophetic
seal: white letters on a dark seal. Their outlines keep the calligraphy's
thick-thin strokes and tapered ends, so they are traced as they are, not redrawn.
For casting, the letters are emboldened to the stroke weight of the original
ring and any tip too fine to fill is rounded off.

Each connected letter group is a named piece (`allah_1` is the rightmost piece of
the top line, and so on). `design/inscription-layout.json` moves, turns and
scales each piece; edit it by hand, or drag the pieces in Blender with
`live_letters.py` and read them back.

    uv run scripts/inscription.py [variant]        variant: one of VARIANTS, default DEFAULT

Outputs in `extracted/`:
  face-inscription.json   laid-out pieces in mm, read by `build_ring.py`
  face-inscription.svg    one <g> per piece, for any vector tool
  inscription-<variant>.png   preview of each variant with the layout applied
  inscription-variants.jpg    those previews beside the original ring's face
  inscription-labelled.png    the chosen variant with piece names
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from shapely import affinity, minimum_bounding_circle, minimum_bounding_radius
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
SEALS = ROOT / "reference" / "seal"
LAYOUT = ROOT / "design" / "inscription-layout.json"

VARIANTS = {
    "canonical": "Muhammad_Seal.png",
    "impression": "Seal_of_Muhammad.png",
    "asymmetric": "Muhammad_Seal_asymmetric.png",
}
DEFAULT = "impression"
LINES = ("allah", "rasul", "muhammad")

FACE_MM = 17.0
FIELD_R_MM = 7.3
FIELD_WOBBLE_MM = 0.3
RIM_GAP_MM = 0.25
PIECE_GAP_MM = 0.35
BOLD_MM = 0.18
MIN_FEATURE_MM = 0.4
MIN_COUNTER_MM = 0.6


def trace(image: Path) -> tuple[MultiPolygon, Polygon]:
    """White letters inside the dark seal, and the seal's own outline, in pixel coordinates."""
    rgba = cv2.imread(str(image), cv2.IMREAD_UNCHANGED)
    if rgba.shape[2] == 4:
        a = rgba[..., 3:4] / 255.0
        rgb = (rgba[..., :3] * a + 255 * (1 - a)).astype(np.uint8)
    else:
        rgb = rgba
    dark = (cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY) < 128).astype(np.uint8)
    seal = max(cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)
    inside = np.zeros_like(dark)
    cv2.drawContours(inside, [seal], -1, 1, -1)
    letters = (inside & (1 - dark)) * 255

    cnts, hier = cv2.findContours(letters, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    polys = []
    for i, c in enumerate(cnts):
        if hier[0][i][3] != -1 or len(c) < 4:
            continue
        holes = []
        child = hier[0][i][2]
        while child != -1:
            if len(cnts[child]) >= 4:
                holes.append(cnts[child][:, 0, :])
            child = hier[0][child][0]
        polys.append(Polygon(c[:, 0, :], holes).buffer(0))
    return MultiPolygon([p for p in polys if p.area > 30]), Polygon(seal[:, 0, :]).buffer(0)


def fit_to_face(letters: MultiPolygon, seal: Polygon) -> tuple[MultiPolygon, Polygon]:
    """Move both to mm, y up, centred on the letters, scaled so the letters fill the field."""
    letters, seal = (affinity.scale(g, 1, -1, origin=(0, 0)) for g in (letters, seal))
    centre = minimum_bounding_circle(letters).centroid
    letters, seal = (affinity.translate(g, -centre.x, -centre.y) for g in (letters, seal))
    k = (FIELD_R_MM - FIELD_WOBBLE_MM - RIM_GAP_MM - BOLD_MM) / minimum_bounding_radius(letters)
    return tuple(affinity.scale(g, k, k, origin=(0, 0)) for g in (letters, seal))


def field_outline(seal: Polygon, n: int = 360) -> Polygon:
    """Inner edge of the rim, with the hand-cut wobble of the seal's own border.

    The seal outline's radius is read all round the centre, smoothed, and its
    deviation from the median capped at FIELD_WOBBLE_MM about FIELD_R_MM.
    """
    edge = seal.exterior
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    far = 4 * FIELD_R_MM * 10
    radii = []
    for a in angles:
        ray = LineString([(0, 0), (far * np.cos(a), far * np.sin(a))])
        hit = ray.intersection(edge)
        pts = getattr(hit, "geoms", [hit])
        radii.append(max(Point(0, 0).distance(p) for p in pts))
    r = np.asarray(radii)
    kernel = np.ones(5) / 5
    r = np.convolve(np.concatenate([r[-2:], r, r[:2]]), kernel, mode="valid")
    dev = r - np.median(r)
    dev *= FIELD_WOBBLE_MM / np.abs(dev).max()
    rr = FIELD_R_MM + dev
    return Polygon(np.column_stack([rr * np.cos(angles), rr * np.sin(angles)]))


def make_castable(shapes: MultiPolygon) -> list[Polygon]:
    """Embolden, then round off anything narrower than MIN_FEATURE_MM.

    The opening (shrink then grow) only touches features thinner than the
    feature size, so tapered tips end in a small round instead of a needle.
    """
    smooth = shapes.buffer(0.03, quad_segs=8).buffer(-0.03, quad_segs=8)
    bold = smooth.buffer(BOLD_MM, quad_segs=12)
    r = MIN_FEATURE_MM / 2
    opened = bold.buffer(-r, quad_segs=12).buffer(r, quad_segs=12)
    # Keep the tips the opening cut back, as far as a 0.25 mm round reaches.
    tips = bold.difference(opened).buffer(-0.12, quad_segs=8).buffer(0.12, quad_segs=8)
    out = unary_union([opened, tips])
    # Emboldening closes the counters of ه, و and م; cut them back at their drawn
    # size, opened up to MIN_COUNTER_MM so investment can fill them.
    counters = [Polygon(h) for p in shapes.geoms for h in p.interiors]
    for c in counters:
        grow = max(0.0, MIN_COUNTER_MM / 2 - np.sqrt(c.area / np.pi))
        out = out.difference(c.buffer(grow, quad_segs=12))
    out = out.simplify(0.01)
    geoms = out.geoms if isinstance(out, MultiPolygon) else [out]
    return [g for g in geoms if g.area > 0.05]


def name_pieces(pieces: list[Polygon]) -> dict[str, Polygon]:
    """Group pieces into lines top to bottom, then number each line right to left."""
    pieces = sorted(pieces, key=lambda p: -p.centroid.y)
    lines: list[list[Polygon]] = []
    for p in pieces:
        if lines and abs(lines[-1][-1].centroid.y - p.centroid.y) < 1.6:
            lines[-1].append(p)
        else:
            lines.append([p])
    named = {}
    for i, line in enumerate(lines):
        word = LINES[i] if len(lines) == len(LINES) else f"line{i + 1}"
        for k, p in enumerate(sorted(line, key=lambda q: -q.centroid.x), start=1):
            named[f"{word}_{k}"] = p
    return named


def apply_layout(pieces: dict[str, Polygon], layout: dict) -> dict[str, Polygon]:
    """Move, turn and scale each piece about its own centroid."""
    out = {}
    for name, p in pieces.items():
        t = layout.get(name, {})
        c = p.centroid
        q = affinity.scale(p, t.get("scale", 1.0), t.get("scale", 1.0), origin=c)
        q = affinity.rotate(q, t.get("rotate", 0.0), origin=c)
        out[name] = affinity.translate(q, t.get("dx", 0.0), t.get("dy", 0.0))
    return out


def clearances(pieces: dict[str, Polygon], field: Polygon) -> list[str]:
    """Warnings for pieces that crowd each other or the rim."""
    warn = []
    inside = field.buffer(-RIM_GAP_MM)
    names = list(pieces)
    for i, a in enumerate(names):
        spill = pieces[a].difference(inside)
        if not spill.is_empty:
            depth = max(inside.exterior.distance(Point(xy)) for xy in pieces[a].exterior.coords
                        if not inside.contains(Point(xy)))
            warn.append(f"{a} is {depth:.2f} mm into the rim gap")
        for b in names[i + 1:]:
            gap = pieces[a].distance(pieces[b])
            if gap < PIECE_GAP_MM:
                warn.append(f"{a} and {b} are {gap:.2f} mm apart")
    return warn


def ring_json(ring) -> list:
    return [(round(x, 4), round(y, 4)) for x, y in list(ring.coords)[:-1]]


def svg(pieces: dict[str, Polygon], field: Polygon) -> str:
    s = 1000 / FACE_MM

    def path(coords):
        return "M" + " L".join(f"{500 + x * s:.1f},{500 - y * s:.1f}" for x, y in coords) + " Z"

    body = [
        '<circle cx="500" cy="500" r="500" fill="none" stroke="black"/>',
        f'<path id="field" d="{path(field.exterior.coords)}" fill="none" stroke="black"/>',
    ]
    for name, p in pieces.items():
        d = " ".join(path(r.coords) for r in [p.exterior, *p.interiors])
        body.append(f'<g id="{name}"><path d="{d}" fill-rule="evenodd"/></g>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000" viewBox="0 0 1000 1000">\n'
            + "\n".join(body) + "\n</svg>\n")


def preview(pieces: dict[str, Polygon], field: Polygon, path: Path, labels: bool = False, px: int = 700) -> None:
    s = px / FACE_MM
    img = np.full((px, px, 3), (22, 26, 30), np.uint8)
    c = px // 2

    def pts(ring):
        return np.asarray([(c + x * s, c - y * s) for x, y in ring.coords], np.int32)

    cv2.circle(img, (c, c), c - 2, (205, 200, 200), -1, cv2.LINE_AA)
    cv2.fillPoly(img, [pts(field.exterior)], (35, 40, 45), cv2.LINE_AA)
    for name, p in pieces.items():
        cv2.fillPoly(img, [pts(p.exterior)], (225, 222, 220), cv2.LINE_AA)
        for h in p.interiors:
            cv2.fillPoly(img, [pts(h)], (35, 40, 45), cv2.LINE_AA)
        if labels:
            q = p.representative_point()
            cv2.putText(img, name, (int(c + q.x * s) - 30, int(c - q.y * s)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (0, 90, 230), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), img)


def variant_sheet(out: Path, px: int = 450) -> None:
    """The variant previews side by side, ending with the original ring's face."""
    tiles = [cv2.resize(cv2.imread(str(out / f"inscription-{n}.png")), (px, px)) for n in VARIANTS]
    original = cv2.imread(str(ROOT / "reference" / "02-face-inscription.jpg"))[960:1340, 470:850]
    tiles.append(cv2.resize(original, (px, px)))
    cv2.imwrite(str(out / "inscription-variants.jpg"), np.hstack(tiles))


def face_for(variant: str, layout: dict) -> tuple[dict[str, Polygon], Polygon]:
    letters, seal = fit_to_face(*trace(SEALS / VARIANTS[variant]))
    pieces = apply_layout(name_pieces(make_castable(letters)), layout.get(variant, {}))
    return pieces, field_outline(seal)


def main() -> None:
    variant = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    layout = json.loads(LAYOUT.read_text()) if LAYOUT.exists() else {}
    out = ROOT / "extracted"
    for name in VARIANTS:
        preview(*face_for(name, layout), out / f"inscription-{name}.png")
    variant_sheet(out)
    pieces, field = face_for(variant, layout)
    preview(pieces, field, out / "inscription-labelled.png", labels=True)
    data = {
        "face_mm": FACE_MM,
        "source": VARIANTS[variant],
        "variant": variant,
        "field": ring_json(field.exterior),
        "letters": [{"name": n, "outline": ring_json(p.exterior), "holes": [ring_json(h) for h in p.interiors]}
                    for n, p in pieces.items()],
    }
    (out / "face-inscription.json").write_text(json.dumps(data, indent=1))
    (out / "face-inscription.svg").write_text(svg(pieces, field))
    print(f"{variant}: {', '.join(pieces)}")
    for w in clearances(pieces, field):
        print("  warning:", w)


if __name__ == "__main__":
    main()
