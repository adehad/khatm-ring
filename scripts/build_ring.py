"""Build the khatm ring in Blender, sized to a target silver weight.

Headless:
    blender -b -P scripts/build_ring.py -- [--render]
Live, in a Blender running the BlenderMCP add-on:
    python scripts/blender_live.py scripts/live_build.py

Units are millimetres. The finger runs along +Y, the face looks up +Z, and the
inscription reads upright from +Z with +Y up. Sizes are estimates from the
reference photos; the module constants are the knobs.

Casting rules the geometry follows:
  - Face plate, bezel wall and band are all close to one section thickness,
    so the metal freezes evenly and does not shrink-porous at thick spots.
  - The back of the face is pocketed under each letter for the same reason.
  - Every outside edge is rounded; the arms are filleted into the bezel.
  - The two band ends overlap with a clearance gap, so the cast ring stays
    adjustable instead of fusing shut.
"""

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "model"
INSCRIPTION = ROOT / "extracted" / "face-inscription.json"

# Two shar'i dirhams at 2.975 g each is 5.95 g, the Maliki limit for a man's
# silver ring. The target leaves margin for the disputed dirham weight.
TARGET_G = 5.8
DENSITY_G_MM3 = 0.01036  # sterling silver, 925

FACE_D = 17.0
INNER_D = 19.0
RELIEF = 0.6
PLATE_T = 0.9
WALL_T = 0.9
BEZEL_H = 2.7
BEZEL_BOTTOM_R = 6.9
TOP_EDGE_R = 0.55
LETTER_ROUND = 0.18

BAND_T = 1.25
BAND_W_TOP = 5.2
BAND_W_END = 3.6
BAND_MIN_W = 2.8
ARM_JOIN_DEG = 62.0
ARM_END_DEG = 200.0
OVERLAP_GAP = 0.35

JOIN_FILLET_MM = 2.2
VOXEL = 0.05

Z_TOP = INNER_D / 2 + BAND_T + BEZEL_H - 0.6
Z_FIELD = Z_TOP - RELIEF
Z_CEILING = Z_FIELD - PLATE_T
Z_BOTTOM = Z_TOP - BEZEL_H


# ---------------------------------------------------------------- scene


def clear_scene() -> None:
    """Empty the scene without a factory reset, which would unload the MCP add-on."""
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                 bpy.data.lights, bpy.data.cameras, bpy.data.worlds):
        for block in list(coll):
            coll.remove(block)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = "MILLIMETERS"


def link(obj: bpy.types.Object) -> bpy.types.Object:
    bpy.context.scene.collection.objects.link(obj)
    return obj


def mesh_object(name: str, bm: bmesh.types.BMesh) -> bpy.types.Object:
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return link(bpy.data.objects.new(name, mesh))


def apply(obj, mod) -> None:
    with bpy.context.temp_override(object=obj, active_object=obj):
        bpy.ops.object.modifier_apply(modifier=mod.name)


def boolean(target, cutter, op: str) -> None:
    mod = target.modifiers.new(f"{op}_{cutter.name}", "BOOLEAN")
    mod.operation = op
    mod.solver = "EXACT"
    mod.object = cutter
    apply(target, mod)
    bpy.data.objects.remove(cutter, do_unlink=True)


def volume(obj) -> float:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    v = bm.calc_volume(signed=False)
    bm.free()
    return v


# ---------------------------------------------------------------- shapes


def arc(c, r, a0, a1, n=10):
    return [(c[0] + r * math.cos(a), c[1] + r * math.sin(a)) for a in
            (a0 + (a1 - a0) * i / n for i in range(n + 1))]


def lathe(name: str, profile, segs: int = 192) -> bpy.types.Object:
    """Revolve an (r, z) profile that starts and ends on the axis into a closed solid."""
    bm = bmesh.new()
    rings = []
    for r, z in profile:
        if r < 1e-6:
            rings.append([bm.verts.new((0, 0, z))])
            continue
        rings.append([bm.verts.new((r * math.cos(2 * math.pi * k / segs),
                                    r * math.sin(2 * math.pi * k / segs), z)) for k in range(segs)])
    for a, b in zip(rings, rings[1:]):
        if len(a) == 1:
            for k in range(segs):
                bm.faces.new((a[0], b[k], b[(k + 1) % segs]))
        elif len(b) == 1:
            for k in range(segs):
                bm.faces.new((a[k], b[0], a[(k + 1) % segs]))
        else:
            for k in range(segs):
                bm.faces.new((a[k], b[k], b[(k + 1) % segs], a[(k + 1) % segs]))
    return mesh_object(name, bm)


def bezel_outer() -> bpy.types.Object:
    """Solid bezel: flat top, rounded crown edge, tapered wall, rounded foot."""
    R, rb, e = FACE_D / 2, BEZEL_BOTTOM_R, TOP_EDGE_R
    foot = 0.45
    prof = [(0.0, Z_TOP)]
    prof += arc((R - e, Z_TOP - e), e, math.pi / 2, 0.0)
    prof += arc((rb + foot * 0.3, Z_BOTTOM + foot), foot, 0.0, -math.pi / 2)
    prof += [(0.0, Z_BOTTOM)]
    return lathe("bezel", prof)


def bezel_cavity() -> bpy.types.Object:
    """Open back of the bezel: the outer shape inset by one wall thickness."""
    R, rb = FACE_D / 2 - WALL_T, BEZEL_BOTTOM_R - WALL_T + 0.15
    k = 0.6
    prof = [(0.0, Z_CEILING)]
    prof += arc((R - TOP_EDGE_R - k, Z_CEILING - k), k, math.pi / 2, 0.0)
    prof += [(rb, Z_BOTTOM - 1.0), (0.0, Z_BOTTOM - 1.0)]
    return lathe("cavity", prof)


def prism(name: str, polys, z0: float, z1: float, round_r: float) -> bpy.types.Object:
    """Extrude mm outlines (with holes) from z0 to z1, every edge rounded by round_r."""
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    for p in polys:
        for loop in [p["outline"], *p["holes"]]:
            spline = curve.splines.new("POLY")
            spline.points.add(len(loop) - 1)
            for pt, (x, y) in zip(spline.points, loop):
                pt.co = (x, y, 0.0, 1.0)
            spline.use_cyclic_u = True
    curve.bevel_depth = round_r
    curve.bevel_resolution = 3
    curve.offset = -round_r
    curve.extrude = max((z1 - z0) / 2 - round_r, 0.01)
    obj = link(bpy.data.objects.new(name, curve))
    obj.location.z = (z0 + z1) / 2
    with bpy.context.temp_override(selected_objects=[obj], selected_editable_objects=[obj],
                                   object=obj, active_object=obj):
        bpy.ops.object.convert(target="MESH")
    obj = bpy.data.objects[name]
    bpy.ops.object.select_all(action="DESELECT")
    with bpy.context.temp_override(object=obj, active_object=obj, selected_editable_objects=[obj]):
        bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    return obj


def field_recess(radius: float) -> bpy.types.Object:
    k = 0.2
    prof = [(0.0, Z_FIELD)]
    prof += arc((radius - k, Z_FIELD + k), k, -math.pi / 2, 0.0, n=4)
    prof += [(radius, Z_TOP + 1.0), (0.0, Z_TOP + 1.0)]
    return lathe("recess", prof)


# ---------------------------------------------------------------- band


def arm_centreline(sign: int, rides_over: bool):
    """Arm path in XZ: out of the bezel foot, onto the finger circle, to the free end.

    The outer arm steps out by one band plus OVERLAP_GAP where the ends overlap.
    """
    rc = INNER_D / 2 + BAND_T / 2

    def circle(deg, ride=0.0):
        t = math.radians(deg)
        return Vector((sign * (rc + ride) * math.sin(t), (rc + ride) * math.cos(t)))

    p0 = Vector((sign * (BEZEL_BOTTOM_R - 0.6), Z_BOTTOM + 1.1))
    p3 = circle(ARM_JOIN_DEG)
    t = math.radians(ARM_JOIN_DEG)
    tangent = Vector((sign * math.cos(t), -math.sin(t)))
    k = (p3 - p0).length / 2.5
    p1 = p0 + Vector((sign * 0.3 * k, -k))
    p2 = p3 - tangent * k
    pts = [(1 - s) ** 3 * p0 + 3 * (1 - s) ** 2 * s * p1 + 3 * (1 - s) * s * s * p2 + s ** 3 * p3
           for s in (i / 24 for i in range(24))]
    step_out = BAND_T + OVERLAP_GAP
    for i in range(141):
        deg = ARM_JOIN_DEG + (ARM_END_DEG - ARM_JOIN_DEG) * i / 140
        ride = step_out * min(1.0, max(0.0, deg - 140.0) / 30.0) if rides_over else 0.0
        pts.append(circle(deg, ride))
    return pts


def arm_section(centre: Vector, normal: Vector, width: float, n: int = 16):
    """Comfort-fit section: domed outside, gently domed inside, fully rounded edges."""
    pts = []
    for k in range(2 * n):
        a = 2 * math.pi * k / (2 * n)
        c, s = math.cos(a), math.sin(a)
        # Superellipse: flat-ish faces, round edges.
        y = width / 2 * math.copysign(abs(c) ** 0.45, c)
        o = BAND_T / 2 * math.copysign(abs(s) ** 0.6, s)
        p = centre + normal * o
        pts.append(Vector((p.x, y, p.y)))
    return pts


def build_arm(name: str, sign: int, rides_over: bool, width_scale: float) -> bpy.types.Object:
    bm = bmesh.new()
    line = arm_centreline(sign, rides_over)
    lengths = [0.0]
    for a, b in zip(line, line[1:]):
        lengths.append(lengths[-1] + (b - a).length)
    w_top = BAND_W_TOP * width_scale
    w_end = max(BAND_W_END * width_scale, BAND_MIN_W)
    rings = []
    for i, c in enumerate(line):
        t = (line[min(i + 1, len(line) - 1)] - line[max(i - 1, 0)]).normalized()
        normal = Vector((t.y, -t.x))
        if normal.dot(c) < 0:
            normal = -normal
        u = lengths[i] / lengths[-1]
        rings.append([bm.verts.new(p) for p in arm_section(c, normal, w_top + (w_end - w_top) * u)])
    m = len(rings[0])
    for a, b in zip(rings, rings[1:]):
        for k in range(m):
            bm.faces.new((a[k], a[(k + 1) % m], b[(k + 1) % m], b[k]))
    # Round the free end with a few rings that shrink onto its centre.
    last = rings[-1]
    centre = sum((v.co for v in last), Vector()) / m
    direction = (line[-1] - line[-2]).normalized()
    d3 = Vector((direction.x, 0.0, direction.y))
    prev = last
    for j in range(1, 5):
        f = math.cos(j / 5 * math.pi / 2)
        ring = [bm.verts.new(centre + (v.co - centre) * f + d3 * (BAND_T * 0.5 * math.sin(j / 5 * math.pi / 2)))
                for v in last]
        for k in range(m):
            bm.faces.new((prev[k], prev[(k + 1) % m], ring[(k + 1) % m], ring[k]))
        prev = ring
    bm.faces.new(list(reversed(prev)))
    bm.faces.new(rings[0])
    return mesh_object(name, bm)


# ---------------------------------------------------------------- body


def fillet_joins(body: bpy.types.Object) -> None:
    """Smooth only the region round each arm root, turning the crease into a fillet."""
    group = body.vertex_groups.new(name="joins")
    roots = [Vector((s * BEZEL_BOTTOM_R, 0.0, Z_BOTTOM + 0.3)) for s in (1, -1)]
    for v in body.data.vertices:
        d = min((v.co - r).length for r in roots)
        if d < JOIN_FILLET_MM:
            x = 1 - d / JOIN_FILLET_MM
            group.add([v.index], x * x * (3 - 2 * x), "REPLACE")
    mod = body.modifiers.new("fillet", "SMOOTH")
    mod.factor = 0.9
    mod.iterations = 40
    mod.vertex_group = group.name
    apply(body, mod)
    if "joins" in body.vertex_groups:
        body.vertex_groups.remove(body.vertex_groups["joins"])


def build(width_scale: float = 1.0, verbose: bool = True) -> dict:
    clear_scene()
    data = json.loads(INSCRIPTION.read_text())
    if abs(data["face_mm"] - FACE_D) > 1e-6:
        raise ValueError("face-inscription.json was drawn for a different FACE_D; rerun inscription.py")

    body = bezel_outer()
    arms = [build_arm("arm_r", 1, False, width_scale), build_arm("arm_l", -1, True, width_scale)]
    arm_volume = sum(volume(a) for a in arms)
    for a in arms:
        boolean(body, a, "UNION")

    remesh = body.modifiers.new("weld", "REMESH")
    remesh.mode = "VOXEL"
    remesh.voxel_size = VOXEL
    apply(body, remesh)
    fillet_joins(body)

    boolean(body, bezel_cavity(), "DIFFERENCE")
    boolean(body, field_recess(data["field_radius_mm"]), "DIFFERENCE")
    letters = prism("letters", data["letters"], Z_FIELD - 0.15, Z_TOP, LETTER_ROUND)
    boolean(body, letters, "UNION")
    pockets = prism("pockets", data["pockets"], Z_CEILING - 0.3, Z_CEILING + RELIEF, LETTER_ROUND)
    boolean(body, pockets, "DIFFERENCE")

    body.name = "khatm_ring"
    with bpy.context.temp_override(object=body, active_object=body, selected_editable_objects=[body]):
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))
    add_materials(body)

    v = volume(body)
    stats = {
        "volume_mm3": v,
        "grams_925": v * DENSITY_G_MM3,
        "arm_volume_mm3": arm_volume,
        "width_scale": width_scale,
        "faces": len(body.data.polygons),
        "size_mm": tuple(round(d, 2) for d in body.dimensions),
    }
    if verbose:
        print(stats)
    return stats


def build_to_weight() -> dict:
    """Rebuild with the band width scaled so the finished ring meets TARGET_G."""
    first = build(1.0, verbose=False)
    excess = first["volume_mm3"] - TARGET_G / DENSITY_G_MM3
    scale = max(0.4, 1.0 - excess / first["arm_volume_mm3"])
    second = build(scale, verbose=False)
    # One secant step corrects for the part of each arm buried in the bezel.
    dv_ds = (second["volume_mm3"] - first["volume_mm3"]) / (scale - 1.0) if abs(scale - 1.0) > 1e-3 else None
    if dv_ds:
        scale = scale - (second["volume_mm3"] - TARGET_G / DENSITY_G_MM3) / dv_ds
        second = build(scale, verbose=False)
    print(second)
    return second


# ---------------------------------------------------------------- look


def add_materials(ring: bpy.types.Object) -> None:
    silver = bpy.data.materials.new("silver")
    silver.use_nodes = True
    bsdf = silver.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.92, 0.92, 0.9, 1)
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.2

    oxide = bpy.data.materials.new("oxidised silver")
    oxide.use_nodes = True
    bsdf = oxide.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.03, 0.025, 0.02, 1)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.85
    bsdf.inputs["Specular IOR Level"].default_value = 0.02

    ring.data.materials.append(silver)
    ring.data.materials.append(oxide)
    for poly in ring.data.polygons:
        if abs(poly.center.z - Z_FIELD) < 0.02 and poly.normal.z > 0.9:
            poly.material_index = 1


def setup_render() -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900

    world = bpy.data.worlds.new("studio")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    sky = world.node_tree.nodes.new("ShaderNodeTexSky")
    sky.sun_disc = False
    sky.sun_elevation = math.radians(20)
    world.node_tree.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.15
    scene.world = world

    for loc, energy in (((40, -40, 60), 80), ((-50, 30, 30), 50), ((0, 60, -20), 30)):
        light = bpy.data.lights.new("key", "AREA")
        light.energy = energy
        light.size = 30
        obj = link(bpy.data.objects.new("light", light))
        obj.location = loc
        obj.rotation_euler = (Vector((0, 0, 3)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


VIEWS = {
    "face": ((0, 0, 60), (0, 0, 5)),
    "front": ((0, -60, 3), (0, 0, 2)),
    "side": ((60, 0, 3), (0, 0, 2)),
    "three-quarter": ((38, -40, 35), (0, 0, 2)),
    "underside": ((0, -14, -58), (0, 0, 4)),
}


def render_views() -> None:
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 85
    cam = link(bpy.data.objects.new("cam", cam_data))
    scene.camera = cam
    renders = OUT / "renders"
    renders.mkdir(parents=True, exist_ok=True)
    for name, (loc, target) in VIEWS.items():
        cam.location = loc
        cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(renders / f"{name}.png")
        bpy.ops.render.render(write_still=True)


def export(ring: bpy.types.Object) -> None:
    OUT.mkdir(exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    ring.select_set(True)
    bpy.context.view_layer.objects.active = ring
    bpy.ops.wm.stl_export(filepath=str(OUT / "khatm-ring.stl"), export_selected_objects=True)
    bpy.ops.export_scene.gltf(filepath=str(OUT / "khatm-ring.glb"), use_selection=True)


def run(render: bool = False) -> dict:
    stats = build_to_weight()
    ring = bpy.data.objects["khatm_ring"]
    export(ring)
    if render:
        setup_render()
        render_views()
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "khatm-ring.blend"))
    return stats


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    run(render="--render" in args)
