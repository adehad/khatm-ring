"""Edit the inscription layout by hand in a live Blender.

Sent to Blender through the BlenderMCP add-on (`blender_live.py`, or the MCP
`execute_blender_code` tool):

    exec(open(r"...\\scripts\\live_letters.py").read()); show()
        Lays each letter piece from `extracted/face-inscription.json` on the
        ring face as its own flat object in the "inscription" collection. Move
        (G), turn about Z (R Z) or scale (S) them in the top view.
    exec(open(r"...\\scripts\\live_letters.py").read()); read_back()
        Folds those moves into `design/inscription-layout.json`. Then run
        `uv run scripts/inscription.py` and rebuild the ring.

Each object stores the centroid it was laid at, so read_back() adds only what
changed since show().
"""

import json
import math
from pathlib import Path

import bpy

ROOT = Path(r"V:\dev\Personal\khatm-ring")
INSCRIPTION = ROOT / "extracted" / "face-inscription.json"
LAYOUT = ROOT / "design" / "inscription-layout.json"
COLLECTION = "inscription"


def _centroid(ring):
    xs, ys = zip(*ring)
    return sum(xs) / len(xs), sum(ys) / len(ys)


def show(z: float | None = None) -> None:
    data = json.loads(INSCRIPTION.read_text())
    if z is None:
        ring = bpy.data.objects.get("khatm_ring")
        z = max(v.co.z for v in ring.data.vertices) + 0.05 if ring else 13.0
    coll = bpy.data.collections.get(COLLECTION) or bpy.data.collections.new(COLLECTION)
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    mat = bpy.data.materials.get("letter preview") or bpy.data.materials.new("letter preview")
    mat.diffuse_color = (0.95, 0.55, 0.1, 1.0)
    for piece in data["letters"]:
        cx, cy = _centroid(piece["outline"])
        curve = bpy.data.curves.new(piece["name"], "CURVE")
        curve.dimensions = "2D"
        curve.fill_mode = "BOTH"
        for loop in [piece["outline"], *piece["holes"]]:
            spline = curve.splines.new("POLY")
            spline.points.add(len(loop) - 1)
            for pt, (x, y) in zip(spline.points, loop):
                pt.co = (x - cx, y - cy, 0.0, 1.0)
            spline.use_cyclic_u = True
        curve.materials.append(mat)
        obj = bpy.data.objects.new(piece["name"], curve)
        obj.location = (cx, cy, z)
        obj["laid_at"] = (cx, cy)
        obj.lock_location[2] = True
        obj.lock_rotation[0] = obj.lock_rotation[1] = True
        coll.objects.link(obj)
    print(f"{len(data['letters'])} pieces in '{COLLECTION}' at z={z:.2f}")


def read_back() -> dict:
    coll = bpy.data.collections[COLLECTION]
    variant = json.loads(INSCRIPTION.read_text())["variant"]
    layout = json.loads(LAYOUT.read_text()) if LAYOUT.exists() else {}
    pieces = layout.setdefault(variant, {})
    for obj in coll.objects:
        x0, y0 = obj["laid_at"]
        t = pieces.setdefault(obj.name, {})
        t["dx"] = round(t.get("dx", 0.0) + obj.location.x - x0, 3)
        t["dy"] = round(t.get("dy", 0.0) + obj.location.y - y0, 3)
        turn = math.degrees(obj.rotation_euler.z)
        if abs(turn) > 1e-3:
            t["rotate"] = round(t.get("rotate", 0.0) + turn, 2)
        if abs(obj.scale.x - 1.0) > 1e-4:
            t["scale"] = round(t.get("scale", 1.0) * obj.scale.x, 4)
    LAYOUT.write_text(json.dumps(layout, indent=1) + "\n")
    print(json.dumps(pieces, indent=1))
    return pieces
