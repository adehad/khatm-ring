# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["numpy", "scipy", "scikit-image", "opencv-python-headless"]
# ///
"""The khatm ring as one signed distance field, meshed once with marching cubes.

Every part (head, the two arms, the open back, the field recess, the letters) is
a distance field, and they are combined with smooth unions and subtractions.
Joins therefore blend by construction: no welding, no smoothing afterwards, no
seams where a smoothing zone ends.

    uv run scripts/ring_sdf.py [--voxel 0.05] [--w-end 3.4] [--solve] [--out model/body.ply]

`--solve` finds the band's end width that meets TARGET_G before meshing. Prints
one JSON line of stats on stdout.

Units are millimetres. The finger runs along +Y, the face looks up +Z.
Sizes are estimates from the reference photos; the constants are the knobs.
"""

import argparse
import json
import struct
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import map_coordinates
from skimage.measure import marching_cubes

ROOT = Path(__file__).resolve().parent.parent
INSCRIPTION = ROOT / "extracted" / "face-inscription.json"

# Two shar'i dirhams at 2.975 g each is 5.95 g, the Maliki limit for a man's
# silver ring. The target leaves margin for the disputed dirham weight.
TARGET_G = 5.8
DENSITY_G_MM3 = 0.01036  # sterling silver, 925

FACE_D = 17.0
INNER_D = 19.0
RELIEF = 0.6
CROWN_R = 0.45
FOOT_R = 6.8
WALL_T = 0.7
PLATE_RIM = 0.8
PLATE_CENTRE = 0.6
LETTER_ROUND = 0.18

BAND_T_ROOT = 1.3
BAND_T_END = 0.95
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
K_SEAT = 0.6
K_LIP = 0.35
K_CAVITY_CORNER = 0.35
K_RECESS = 0.08
K_LETTER = 0.1

R_FINGER = INNER_D / 2
R_SADDLE = R_FINGER + BAND_T_ROOT / 2
Z_TOP = R_FINGER + BAND_T_ROOT + 1.4
Z_FIELD = Z_TOP - RELIEF

RASTER = 0.01


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
        w, h = int(round((u1 - u0) / RASTER)) + 1, int(round((v1 - v0) / RASTER)) + 1
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
        d = map_coordinates(self.sdf, [np.clip(rows, 0, h - 1).ravel(), np.clip(cols, 0, w - 1).ravel()],
                            order=1, mode="nearest").reshape(u.shape)
        # Outside the raster, add the distance to its edge so the field stays a bound.
        over = np.maximum.reduce([-cols, cols - (w - 1), -rows, rows - (h - 1), np.zeros_like(cols)]) * RASTER
        return d + over


def bezier(p0, p1, p2, p3, n=40):
    t = np.linspace(0, 1, n)[:, None]
    return ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3).tolist()


def head_side():
    """Outside of the head as (r, z) from the face edge down: a crown round, then
    one curve that leaves the crown straight down and eases in to the foot."""
    R = FACE_D / 2
    a = np.linspace(np.pi / 2, 0, 10)
    crown = np.column_stack([R - CROWN_R + CROWN_R * np.cos(a), Z_TOP - CROWN_R + CROWN_R * np.sin(a)]).tolist()
    z0 = Z_TOP - CROWN_R
    side = bezier(np.array([R, z0]), np.array([R, z0 - 1.2]), np.array([FOOT_R + 0.25, 9.7]), np.array([FOOT_R, 8.4]))
    return crown + side[1:] + [[FOOT_R, 2.0]]


def offset_inward(pts, d):
    out = []
    for i, (r, z) in enumerate(pts):
        r0, z0 = pts[max(i - 1, 0)]
        r1, z1 = pts[min(i + 1, len(pts) - 1)]
        tr, tz = r1 - r0, z1 - z0
        n = np.hypot(tr, tz) or 1.0
        out.append([r + tz / n * d, z - tr / n * d])
    return out


def head_fields():
    side = head_side()
    outer = [[0.0, Z_TOP]] + side + [[0.0, side[-1][1]]]
    head = Field2D([(outer, [])], 0.0, 11.0, 1.5, Z_TOP + 0.5)

    # Cavity: the side wall offset in by WALL_T, under a domed ceiling that
    # leaves PLATE_RIM of plate at its edge and PLATE_CENTRE in the middle.
    # The ceiling is analytic: it is nearly flat, and a raster of it would
    # step in 0.01 mm terraces that print as rings.
    inner = offset_inward(side, WALL_T)
    r_c = next(r for r, z in inner if z <= Z_FIELD - PLATE_RIM)
    wall = [[r, z] for r, z in inner if z <= Z_FIELD]
    walls = Field2D([([[0.0, Z_FIELD], *wall, [wall[-1][0], 1.0], [0.0, 1.0]], [])], 0.0, 11.0, 0.5, Z_TOP + 0.5)
    dome = (PLATE_RIM - PLATE_CENTRE) / r_c ** 2

    def cavity(rho, z):
        ceiling = Z_FIELD - PLATE_CENTRE - dome * rho ** 2
        under = (z - ceiling) / np.sqrt(1 + (2 * dome * rho) ** 2)
        return smax(walls(rho, z), under, K_CAVITY_CORNER)

    return head, cavity


# ---------------------------------------------------------------- band


def arm(x, y, z, sign, rides_over, w_end, phase):
    """Distance to one arm: a rolled rounded-rectangle section swept round the finger."""
    rf = np.hypot(x, z)
    theta = np.degrees(np.arctan2(sign * x, z)) % 360.0
    span = ARM_END_DEG - ARM_START_DEG
    th = np.clip(theta, ARM_START_DEG, ARM_END_DEG)
    u = (th - ARM_START_DEG) / span
    s = smootherstep(u / FLARE_SPAN)
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
        self.head, self.cavity = head_fields()
        self.field = Field2D([(data["field"], [])], -FACE_D / 2, FACE_D / 2, -FACE_D / 2, FACE_D / 2)
        self.letters = Field2D([(p["outline"], p["holes"]) for p in data["letters"]],
                               -FACE_D / 2, FACE_D / 2, -FACE_D / 2, FACE_D / 2)

    def sdf(self, x, y, z, w_end):
        rho = np.hypot(x, y)
        rf = np.hypot(x, z)

        body = smax(self.head(rho, z), R_SADDLE - rf, K_SEAT)
        for sign, rides, phase in ((1, False, 0.0), (-1, True, 1.9)):
            d, theta = arm(x, y, z, sign, rides, w_end, phase)
            k = K_SHOULDER * (1 - smoothstep((theta - 55.0) / 35.0))
            k = np.where(theta > 300.0, 0.0, k)
            body = smin(body, d, k)
        body = smax(body, -self.cavity(rho, z), K_LIP)

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
        axes = [np.arange(a, b + h, h, dtype=np.float32) for a, b in zip(lo, hi)]
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
        return float(np.clip(0.5 - vol / h, 0.0, 1.0).sum() * h ** 3)


def solve_w_end(ring, h=0.1):
    target = TARGET_G / DENSITY_G_MM3
    lo, hi = BAND_W_END_RANGE
    a = (BAND_W_END, ring.volume_mm3(h, BAND_W_END))
    b_w = BAND_W_END + (0.5 if a[1] < target else -0.5)
    b = (b_w, ring.volume_mm3(h, b_w))
    for _ in range(6):
        if abs(b[1] - target) < 1.0 or b[1] == a[1]:
            break
        w = float(np.clip(b[0] - (b[1] - target) * (b[0] - a[0]) / (b[1] - a[1]), lo, hi))
        a, b = b, (w, ring.volume_mm3(h, w))
    return b[0]


def write_ply(path, verts, normals, faces):
    """Binary PLY with per-vertex normals, so the importer shades from the
    field's gradient rather than from marching-cubes triangle averages."""
    with open(path, "wb") as f:
        f.write(f"ply\nformat binary_little_endian 1.0\nelement vertex {len(verts)}\n"
                "property float x\nproperty float y\nproperty float z\n"
                "property float nx\nproperty float ny\nproperty float nz\n"
                f"element face {len(faces)}\nproperty list uchar int vertex_indices\nend_header\n".encode())
        f.write(np.hstack([verts, normals]).astype("<f4").tobytes())
        rows = np.empty(len(faces), dtype=[("n", "u1"), ("i", "<i4", 3)])
        rows["n"] = 3
        rows["i"] = faces
        f.write(rows.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voxel", type=float, default=0.05)
    ap.add_argument("--w-end", type=float, default=BAND_W_END)
    ap.add_argument("--solve", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "model" / "body.ply"))
    a = ap.parse_args()

    ring = Ring()
    w_end = solve_w_end(ring) if a.solve else a.w_end
    vol, origin = ring.volume_field(a.voxel, w_end)
    verts, faces, normals, _ = marching_cubes(vol, level=0.0, spacing=(a.voxel,) * 3)
    verts += np.asarray(origin, np.float32)
    # With the default gradient direction skimage winds faces outward for a
    # field that is negative inside, but its normals point inward.
    write_ply(a.out, verts, -normals, faces)
    v = float(np.clip(0.5 - vol / a.voxel, 0.0, 1.0).sum() * a.voxel ** 3)
    stats = {
        "volume_mm3": round(v, 1),
        "grams_925": round(v * DENSITY_G_MM3, 3),
        "band_end_width_mm": round(w_end, 2),
        "z_field": Z_FIELD,
        "faces": int(len(faces)),
        "mesh": a.out,
    }
    if w_end in BAND_W_END_RANGE:
        stats["warning"] = f"band end width hit its limit {w_end} mm"
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
