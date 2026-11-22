"""The khatm ring as one signed distance field, meshed once with marching cubes.

Every part (head, the two arms, the open back, the field recess, the letters) is
a distance field, and they are combined with smooth unions and subtractions.
Joins therefore blend by construction: no welding, no smoothing afterwards, no
seams where a smoothing zone ends.

    khatm sdf [--size "US 9"] [--target-g 5.8] [--solve] [--voxel 0.05] [--out cache/body.ply]
    khatm sdf [--size …] [--w-end …] [--t-end …] [--plate-extra …] --sample points.f32 --sample-out values.f32

The size and target weight come from design/ring.toml unless given here.
`--solve` finds the band's end width that meets the target weight before
meshing, and on a ring too small for the band alone, the plate thickness.
Prints one JSON line of stats on stdout. `--sample` skips meshing and writes
the field at each float32 x, y, z triple in the input file, for checking
another implementation of this field against this one.

Units are millimetres. The finger runs along +Y, the face looks up +Z.
Sizes are estimates from the reference photos; the constants are the knobs.
"""

import argparse
import json
import tomllib
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import map_coordinates
from skimage.measure import marching_cubes

from khatm.paths import BODY, INSCRIPTION, PARAMS
from khatm.ring_size import equivalents, inside_diameter

# Two shar'i dirhams at 2.975 g each is 5.95 g, the Maliki limit for a man's
# silver ring. design/ring.toml sets the target below it, for the disputed
# dirham weight.
DENSITY_G_MM3 = 0.01036  # sterling silver, 925

FACE_D = 17.0
RELIEF = 0.6
CROWN_R = 0.45
HEAD_FLARE = 0.35
HEAD_DROP = 6.0
BOAT_EDGE = 0.9
BOAT_POWER = 2.2
WALL_T = 0.7
CAVITY_LEAN = 0.6
CAVITY_TUCK = 3.0
CAVITY_TUCK_Z = 2.5
HEAD_TUCK = 3.0
HEAD_TUCK_Z = 2.5
HEAD_BURY = 0.2
HEAD_BURY_DEG = 10.0
HEAD_SIDE_INSET = 0.3
HEAD_SIDE_FLARE = 0.5
HEAD_SIDE_START_DEG = 50.0
HEAD_SIDE_END_DEG = 70.0
PLATE_RIM = 0.8
PLATE_CENTRE = 0.6
PLATE_EXTRA = 0.0
PLATE_EXTRA_RANGE = (0.0, 0.5)
LETTER_ROUND = 0.18

BAND_T_ROOT = 1.3
BAND_T_END = 0.95
BAND_T_END_RANGE = (0.8, 1.3)
BAND_W_ROOT = 8.5
BAND_W_END = 3.4
BAND_W_END_RANGE = (2.6, 5.0)
BAND_CORNER = 0.4
BAND_WAVE = 0.035
TIP_W = 2.2
TIP_T = 0.9
TIP_TAPER_DEG = 25.0
FLARE_SPAN = 0.4
ARM_START_DEG = 35.0
ARM_END_DEG = 200.0
RIDE_START_DEG = 95.0
RIDE_END_DEG = 155.0
OVERLAP_GAP = 0.35

K_SHOULDER = 1.5
SHOULDER_FADE_DEG = 35.0
K_SEAT = 0.6
K_BOAT = 1.2
K_LIP = 0.35
K_CAVITY_CORNER = 0.35
K_HEAD_SIDE = 1.0
K_RECESS = 0.08
K_LETTER = 0.1

RASTER = 0.01


# Set by set_size(), which every size change goes through.
INNER_D: float
R_FINGER: float
R_SADDLE: float
Z_TOP: float
Z_FIELD: float


def set_size(inner_d: float) -> None:
    """Fix the finger size; every height on the ring is measured from it."""
    global INNER_D, R_FINGER, R_SADDLE, Z_TOP, Z_FIELD
    INNER_D = inner_d
    R_FINGER = inner_d / 2
    R_SADDLE = R_FINGER + BAND_T_ROOT / 2
    Z_TOP = R_FINGER + BAND_T_ROOT + 1.4
    Z_FIELD = Z_TOP - RELIEF


set_size(19.0)


# ---------------------------------------------------------------- field algebra


def smin(a, b, k):
    k = np.maximum(k, 1e-5)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


def smax(a, b, k):
    return -smin(-a, -b, k)


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def smootherstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * x * (x * (6 * x - 15) + 10)


# ---------------------------------------------------------------- 2D fields


class Field2D:
    """Signed distance to filled polygons, sampled from a fine raster (negative inside)."""

    def __init__(self, polys, u0, u1, v0, v1):
        self.u0, self.v1 = u0, v1
        w, h = round((u1 - u0) / RASTER) + 1, round((v1 - v0) / RASTER) + 1
        mask = np.zeros((h, w), np.uint8)
        for outline, holes in polys:
            cv2.fillPoly(mask, [self._px(outline)], 1)
            for hole in holes:
                cv2.fillPoly(mask, [self._px(hole)], 0)
        self.set_mask(mask)

    def set_mask(self, mask):
        # Exact distances, then a one-pixel blur: the raster's staircase would
        # otherwise print as fine rings on every revolved surface.
        inside = cv2.distanceTransform(mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        outside = cv2.distanceTransform(1 - mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        sdf = (outside - inside).astype(np.float32)
        self.sdf = cv2.GaussianBlur(sdf, (0, 0), 1.5) * RASTER

    def _px(self, pts):
        p = np.asarray(pts, float)
        return np.round(np.column_stack([(p[:, 0] - self.u0) / RASTER, (self.v1 - p[:, 1]) / RASTER])).astype(np.int32)

    def __call__(self, u, v):
        cols = (u - self.u0) / RASTER
        rows = (self.v1 - v) / RASTER
        h, w = self.sdf.shape
        d = map_coordinates(
            self.sdf, [np.clip(rows, 0, h - 1).ravel(), np.clip(cols, 0, w - 1).ravel()], order=1, mode="nearest"
        ).reshape(u.shape)
        # Outside the raster, add the distance to its edge so the field stays a bound.
        over = np.stack([-cols, cols - (w - 1), -rows, rows - (h - 1), np.zeros_like(cols)]).max(axis=0) * RASTER
        return d + over


def head_radius(z):
    """Radius of the head's wall at height z, and its slope. The wall drops from
    the crown and leans out by HEAD_FLARE over HEAD_DROP as it meets the band."""
    u = np.clip((Z_TOP - CROWN_R - z) / HEAD_DROP, 0.0, 1.0)
    return FACE_D / 2 + HEAD_FLARE * u * u, 2 * HEAD_FLARE * u / HEAD_DROP


def tuck(z, x_from, x_meet, z_meet, span):
    """A wall at x_from curving in over span to meet a circle round the finger
    at (x_meet, z_meet) along its tangent: a cubic with no slope at the top.
    Returns the change in radius at height z, and in its slope."""
    shift = x_meet - x_from
    bend = span * z_meet / x_meet
    u = np.clip((z_meet + span - z) / span, 0.0, 1.0)
    dr = shift * u * u * (3 - 2 * u) + bend * u * u * (u - 1)
    return dr, np.abs(shift * 6 * u * (1 - u) + bend * u * (3 * u - 2)) / span


def band_flare(theta):
    """How far the band is through its flare from root to end at theta degrees
    round from the top, 0 to 1."""
    u = (np.clip(theta, ARM_START_DEG, ARM_END_DEG) - ARM_START_DEG) / (ARM_END_DEG - ARM_START_DEG)
    return smootherstep(u / FLARE_SPAN)


def band_thickness(theta):
    """The band's thickness at theta degrees, before its tip."""
    return BAND_T_ROOT + (BAND_T_END - BAND_T_ROOT) * band_flare(theta)


def head_join():
    """Where the head's wall meets the band's outside: (x, z). On a finger so
    small that the wall at its widest would meet the band lower than
    HEAD_TUCK_Z, the wall tucks in to meet it there instead, where the band
    has already thinned a little."""
    r_wall = FACE_D / 2 + HEAD_FLARE
    r_out = R_FINGER + BAND_T_ROOT
    z_join = np.sqrt(max(r_out**2 - r_wall**2, 0.0))
    if z_join >= HEAD_TUCK_Z:
        return r_wall, z_join
    x = np.sqrt(r_out**2 - HEAD_TUCK_Z**2)
    for _ in range(4):
        r_out = R_FINGER + band_thickness(np.degrees(np.arctan2(x, HEAD_TUCK_Z)))
        x = np.sqrt(r_out**2 - HEAD_TUCK_Z**2)
    return float(x), HEAD_TUCK_Z


def head(x, y, rho, z, rf, w_end):
    """The head: a disc with a rounded crown whose wall runs down into the band.

    Across the finger the wall meets the band outright. Along the finger, past
    the band's edges, the underside follows the band's curve and rises to
    BOAT_EDGE under the face edge, so from the side the head is boat-shaped.
    """
    r, slope = head_radius(z)
    x_join, z_join = head_join()
    r_wall = FACE_D / 2 + HEAD_FLARE
    if x_join < r_wall:
        dr, dslope = tuck(z, r_wall, x_join, z_join, HEAD_TUCK)
        r, slope = r + dr, slope + dslope
    qx = (rho - r) / np.sqrt(1 + slope**2) + CROWN_R
    qz = z - Z_TOP + CROWN_R
    d = np.minimum(np.maximum(qx, qz), 0) + np.hypot(np.maximum(qx, 0), np.maximum(qz, 0)) - CROWN_R
    y0 = BAND_W_ROOT / 2 - 0.6
    u = np.clip((np.abs(y) - y0) / (FACE_D / 2 - y0), 0.0, 1.0)
    floor = R_SADDLE + (Z_TOP - BOAT_EDGE - R_SADDLE) * u**BOAT_POWER
    d = smax(d, floor - rf, np.where(u > 0, K_BOAT, K_SEAT))
    # On a small ring the head meets the band where the band has already
    # narrowed. Past HEAD_SIDE_START_DEG round from the top, its sides come in to
    # HEAD_SIDE_INSET inside the band's, widening by HEAD_SIDE_FLARE per mm
    # above the band's outside, so the shoulder fillet runs down into the band.
    theta = np.degrees(np.arctan2(np.abs(x), z))
    w = BAND_W_ROOT + (w_end - BAND_W_ROOT) * band_flare(theta)
    off = 1 - smoothstep((theta - HEAD_SIDE_START_DEG) / (HEAD_SIDE_END_DEG - HEAD_SIDE_START_DEG))
    reach = w / 2 - HEAD_SIDE_INSET + HEAD_SIDE_FLARE * np.maximum(rf - R_FINGER - BAND_T_ROOT, 0) + off * FACE_D
    d = smax(d, np.abs(y) - reach, K_HEAD_SIDE)
    # Stop the wall a millimetre below where it meets the band, inside the band's metal.
    if x_join == r_wall:
        return np.maximum(d, z_join - 1.0 - z)
    # A tucked wall instead runs on, inside the band, until the shoulder fillet
    # has faded, so the fillet never runs into its end. The band thins below
    # the join, so the wall sinks to HEAD_BURY under the band's outside.
    join_deg = np.degrees(np.arctan2(x_join, z_join))
    d = np.maximum(d, np.radians(theta - join_deg - SHOULDER_FADE_DEG) * rf)
    sink = HEAD_BURY * smoothstep((theta - join_deg) / HEAD_BURY_DEG)
    return np.maximum(d, np.where(theta > join_deg, rf - (R_FINGER + band_thickness(theta) - sink), -FACE_D))


def cavity(rho, z):
    """The open back: the head's wall offset in by WALL_T, under a domed ceiling
    that leaves PLATE_RIM of plate at its edge and PLATE_CENTRE in the middle,
    each thickened by PLATE_EXTRA when the band alone is too light."""
    r, slope = head_radius(z)
    # Low down the wall leans out by CAVITY_LEAN and reaches the finger hole
    # along its tangent, so the two run into each other without a ridge.
    x_wall = FACE_D / 2 + HEAD_FLARE - WALL_T
    x_meet = x_wall + CAVITY_LEAN
    z_meet = np.sqrt(max(R_FINGER**2 - x_meet**2, 0.0))
    if z_meet > 0:
        span = 2 * CAVITY_LEAN * x_meet / z_meet
        u = np.clip((z_meet + span - z) / span, 0.0, 1.0)
        r = r + CAVITY_LEAN * u * u
        slope = slope + 2 * CAVITY_LEAN * u / span
    else:
        # A finger narrower than the head: over CAVITY_TUCK the wall curves in
        # to meet the finger hole CAVITY_TUCK_Z above its widest point.
        z_meet = CAVITY_TUCK_Z
        dr, dslope = tuck(z, x_wall, np.sqrt(R_FINGER**2 - z_meet**2), z_meet, CAVITY_TUCK)
        r, slope = r + dr, slope + dslope
    walls = (rho - (r - WALL_T)) / np.sqrt(1 + slope**2)
    walls = np.maximum(walls, z_meet - 0.5 - z)
    r_c = FACE_D / 2 - WALL_T
    dome = (PLATE_RIM - PLATE_CENTRE) / r_c**2
    ceiling = Z_FIELD - PLATE_CENTRE - PLATE_EXTRA - dome * rho**2
    under = (z - ceiling) / np.sqrt(1 + (2 * dome * rho) ** 2)
    return smax(walls, under, K_CAVITY_CORNER)


# ---------------------------------------------------------------- band


def arm(x, y, z, sign, rides_over, w_end, phase):
    """Distance to one arm: a rolled rounded-rectangle section swept round the finger."""
    rf = np.hypot(x, z)
    theta = np.degrees(np.arctan2(sign * x, z)) % 360.0
    th = np.clip(theta, ARM_START_DEG, ARM_END_DEG)
    s = band_flare(theta)
    w = BAND_W_ROOT + (w_end - BAND_W_ROOT) * s
    t = BAND_T_ROOT + (BAND_T_END - BAND_T_ROOT) * s
    tip = smoothstep((th - (ARM_END_DEG - TIP_TAPER_DEG)) / TIP_TAPER_DEG)
    w = w + (TIP_W - w) * tip
    t = t + (TIP_T - t) * tip
    w = w * (1 + BAND_WAVE * np.sin(np.radians(2.5 * th) + phase))
    r_in = np.full_like(th, R_FINGER)
    if rides_over:
        r_in = r_in + (BAND_T_END + OVERLAP_GAP) * smoothstep((th - RIDE_START_DEG) / (RIDE_END_DEG - RIDE_START_DEG))

    # Past either end, measure along the arc so the end is a half disc in plan.
    past = np.where(theta > ARM_END_DEG, theta - ARM_END_DEG, 0.0)
    before = np.where(theta < ARM_START_DEG, ARM_START_DEG - theta, 0.0)
    gap = np.minimum(np.where(theta > ARM_END_DEG, past, 1e3), np.where(theta < ARM_START_DEG, before, 1e3))
    gap = np.where((theta >= ARM_START_DEG) & (theta <= ARM_END_DEG), 0.0, gap)
    arc = np.radians(gap) * (r_in + t / 2)
    yy = np.hypot(y, arc)

    c = np.minimum(BAND_CORNER, t / 2 - 0.05)
    qx = np.abs(rf - (r_in + t / 2)) - (t / 2 - c)
    qy = yy - (w / 2 - c)
    d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - c
    return d, theta


# ---------------------------------------------------------------- whole ring


class Ring:
    def __init__(self):
        data = json.loads(INSCRIPTION.read_text())
        if abs(data["face_mm"] - FACE_D) > 1e-6:
            raise ValueError("face-inscription.json was drawn for a different FACE_D; rerun inscription.py")
        self.field = Field2D([(data["field"], [])], -FACE_D / 2, FACE_D / 2, -FACE_D / 2, FACE_D / 2)
        self.letters = Field2D(
            [(p["outline"], p["holes"]) for p in data["letters"]], -FACE_D / 2, FACE_D / 2, -FACE_D / 2, FACE_D / 2
        )

    def sdf(self, x, y, z, w_end):
        rho = np.hypot(x, y)
        rf = np.hypot(x, z)

        body = head(x, y, rho, z, rf, w_end)
        # The shoulder fillet fades out below where the head meets the band,
        # which sits lower round the finger on smaller rings.
        fade_deg = np.degrees(np.arctan2(*head_join()))
        for sign, rides, phase in ((1, False, 0.0), (-1, True, 1.9)):
            d, theta = arm(x, y, z, sign, rides, w_end, phase)
            # Full fillet on the outside; none at the finger, where it would swell into the hole.
            fade = 1 - smoothstep((theta - fade_deg) / SHOULDER_FADE_DEG)
            k = K_SHOULDER * fade * smoothstep((rf - R_FINGER) / BAND_T_ROOT)
            k = np.where(theta > 300.0, 0.0, k)
            body = smin(body, d, k)
        body = smax(body, -cavity(rho, z), K_LIP)

        # Field recess: inside the hand-cut outline, widening at 45 degrees up to the rim.
        recess = np.maximum(Z_FIELD - z, (self.field(x, y) - (z - Z_FIELD)) * 0.7071)
        body = smax(body, -recess, K_RECESS)

        # Letters: the outlines extruded up from the field, top edges rounded.
        qx = self.letters(x, y) + LETTER_ROUND
        qz = z - (Z_TOP - LETTER_ROUND)
        letters = np.minimum(np.maximum(qx, qz), 0) + np.hypot(np.maximum(qx, 0), np.maximum(qz, 0)) - LETTER_ROUND
        letters = np.maximum(letters, (Z_FIELD - 0.15) - z)
        return smin(body, letters, K_LETTER)

    def grid(self, h):
        lo = np.array([-R_FINGER - BAND_T_ROOT - 1.2, -FACE_D / 2 - 0.4, -R_FINGER - BAND_T_ROOT - 2.0])
        hi = np.array([R_FINGER + BAND_T_ROOT + 1.2, FACE_D / 2 + 0.4, Z_TOP + 0.3])
        axes = [np.arange(a, b + h, h, dtype=np.float32) for a, b in zip(lo, hi, strict=True)]
        return axes

    def volume_field(self, h, w_end):
        xs, ys, zs = self.grid(h)
        vol = np.empty((len(xs), len(ys), len(zs)), np.float32)
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        for k, z in enumerate(zs):
            vol[:, :, k] = self.sdf(X, Y, np.full_like(X, z), w_end)
        return vol, (xs[0], ys[0], zs[0])

    def volume_mm3(self, h, w_end):
        vol, _ = self.volume_field(h, w_end)
        return float(np.clip(0.5 - vol / h, 0.0, 1.0).sum() * h**3)


def secant(volume, x0, step, bounds, target):
    """Find x within bounds where volume(x) meets target, to within 1 mm³."""
    a = (x0, volume(x0))
    b_x = float(np.clip(x0 + (step if a[1] < target else -step), *bounds))
    b = (b_x, volume(b_x))
    for _ in range(6):
        if abs(b[1] - target) < 1.0 or b[1] == a[1]:
            break
        x = float(np.clip(b[0] - (b[1] - target) * (b[0] - a[0]) / (b[1] - a[1]), *bounds))
        a, b = b, (x, volume(x))
    return b[0], b[1]


def solve_band(ring, target_g, h=0.1):
    """Meet the target weight with the band's end width. If the band is still
    too light at its widest, thicken the plate under the face; if too heavy at
    its narrowest, thin the band's ends. Past those limits the ring misses the
    target. Returns (width, thickness, plate extra)."""
    global BAND_T_END, PLATE_EXTRA
    target = target_g / DENSITY_G_MM3
    w, v = secant(lambda w: ring.volume_mm3(h, w), BAND_W_END, 0.5, BAND_W_END_RANGE, target)
    if abs(v - target) > 1.0 and w == BAND_W_END_RANGE[1]:

        def plate(extra):
            global PLATE_EXTRA
            PLATE_EXTRA = extra
            return ring.volume_mm3(h, w)

        PLATE_EXTRA, _ = secant(plate, PLATE_EXTRA, 0.1, PLATE_EXTRA_RANGE, target)
    elif abs(v - target) > 1.0 and w == BAND_W_END_RANGE[0]:

        def thickness(t):
            global BAND_T_END
            BAND_T_END = t
            return ring.volume_mm3(h, w)

        BAND_T_END, _ = secant(thickness, BAND_T_END, 0.1, BAND_T_END_RANGE, target)
    return w, BAND_T_END, PLATE_EXTRA


def write_ply(path, verts, normals, faces):
    """Binary PLY with per-vertex normals, so the importer shades from the
    field's gradient rather than from marching-cubes triangle averages."""
    with Path(path).open("wb") as f:
        f.write(
            f"ply\nformat binary_little_endian 1.0\nelement vertex {len(verts)}\n"
            "property float x\nproperty float y\nproperty float z\n"
            "property float nx\nproperty float ny\nproperty float nz\n"
            f"element face {len(faces)}\nproperty list uchar int vertex_indices\nend_header\n".encode()
        )
        f.write(np.hstack([verts, normals]).astype("<f4").tobytes())
        rows = np.empty(len(faces), dtype=[("n", "u1"), ("i", "<i4", 3)])
        rows["n"] = 3
        rows["i"] = faces
        f.write(rows.tobytes())


def main(argv: list[str] | None = None) -> None:
    global BAND_T_END, PLATE_EXTRA
    params = tomllib.loads(PARAMS.read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default=params["size"])
    ap.add_argument("--target-g", type=float, default=params["target_g"])
    ap.add_argument("--voxel", type=float, default=0.05)
    ap.add_argument("--w-end", type=float, default=BAND_W_END)
    ap.add_argument("--t-end", type=float, default=BAND_T_END)
    ap.add_argument("--plate-extra", type=float, default=PLATE_EXTRA)
    ap.add_argument("--solve", action="store_true")
    ap.add_argument("--out", default=str(BODY))
    ap.add_argument("--sample", type=Path)
    ap.add_argument("--sample-out", type=Path)
    a = ap.parse_args(argv)

    BAND_T_END = a.t_end
    PLATE_EXTRA = a.plate_extra
    set_size(inside_diameter(a.size))
    ring = Ring()
    if a.sample is not None:
        if a.sample_out is None:
            ap.error("--sample needs --sample-out")
        x, y, z = np.fromfile(a.sample, "<f4").reshape(-1, 3).T
        ring.sdf(x, y, z, a.w_end).astype("<f4").tofile(a.sample_out)
        return
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    w_end, t_end, plate = solve_band(ring, a.target_g) if a.solve else (a.w_end, BAND_T_END, PLATE_EXTRA)
    vol, origin = ring.volume_field(a.voxel, w_end)
    verts, faces, normals, _ = marching_cubes(vol, level=0.0, spacing=(a.voxel,) * 3)
    verts += np.asarray(origin, np.float32)
    # With the default gradient direction skimage winds faces outward for a
    # field that is negative inside, but its normals point inward.
    write_ply(a.out, verts, -normals, faces)
    v = float(np.clip(0.5 - vol / a.voxel, 0.0, 1.0).sum() * a.voxel**3)
    stats = {
        "size": equivalents(INNER_D),
        "target_g": a.target_g,
        "volume_mm3": round(v, 1),
        "grams_925": round(v * DENSITY_G_MM3, 3),
        "band_end_width_mm": round(w_end, 2),
        "band_end_thickness_mm": round(t_end, 2),
        "plate_extra_mm": round(plate, 3),
        "z_field": Z_FIELD,
        "faces": len(faces),
        "mesh": a.out,
    }
    if a.solve and abs(stats["grams_925"] - a.target_g) > 0.05:
        stats["warning"] = (
            f"cannot reach {a.target_g} g at this size: band ends {w_end:.2f} x {t_end:.2f} mm, plate +{plate:.2f} mm"
        )
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
