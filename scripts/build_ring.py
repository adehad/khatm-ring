"""Build the khatm ring in Blender from the hand-traced face outlines.

Run headless:
    blender -b -P scripts/build_ring.py -- [--render]

Units are millimetres. The finger runs along +Y, the face looks up +Z, and the
inscription reads upright when viewed from +Z with +Y up. All dimensions are
estimates from the reference photos; the module-level constants are the knobs.
"""

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import inscription  # noqa: E402

FACE_D = 17.0
INNER_D = 19.0
BAND_T = 1.3
BAND_W_TOP = 7.0
BAND_W_END = 4.5
ARM_JOIN_DEG = 60.0
ARM_END_DEG = 205.0
BEZEL_TOP_Z = 12.8
BEZEL_H = 3.2
BEZEL_BOTTOM_R = 7.0
SHELL_T = 1.0
FIELD_DEPTH = 0.5
RIM_BEVEL = 0.35

OUT = ROOT / "model"


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = "MILLIMETERS"


def svg_to_mm(pt) -> tuple[float, float]:
    x, y = pt
    return ((x - 500) / 1000 * FACE_D, -(y - 500) / 1000 * FACE_D)


def prism_from_loops(name: str, loops, z0: float, z1: float) -> bpy.types.Object:
    """Extrude closed 2D loops (outline then holes) between z0 and z1 as a solid mesh."""
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    for loop in loops:
        spline = curve.splines.new("POLY")
        spline.points.add(len(loop) - 1)
        for p, pt in zip(spline.points, loop):
            x, y = svg_to_mm(pt)
            p.co = (x, y, 0.0, 1.0)
        spline.use_cyclic_u = True
    curve.extrude = (z1 - z0) / 2
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.location.z = (z0 + z1) / 2
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")
    obj.select_set(False)
    return obj


def frustum(name: str, r_top: float, r_bot: float, z_top: float, z_bot: float, segs: int = 128):
    bpy.ops.mesh.primitive_cone_add(
        vertices=segs, radius1=r_bot, radius2=r_top, depth=z_top - z_bot, location=(0, 0, (z_top + z_bot) / 2)
    )
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.transform_apply(location=True)
    return obj


def boolean(target, cutter, op: str) -> None:
    mod = target.modifiers.new(f"{op}_{cutter.name}", "BOOLEAN")
    mod.operation = op
    mod.solver = "EXACT"
    mod.object = cutter
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def build_bezel() -> bpy.types.Object:
    face_r = FACE_D / 2
    bot_z = BEZEL_TOP_Z - BEZEL_H
    bezel = frustum("bezel", face_r, BEZEL_BOTTOM_R, BEZEL_TOP_Z, bot_z)

    # Hollow cast back, open towards the finger.
    cavity = frustum(
        "cavity",
        face_r - SHELL_T * 1.4,
        BEZEL_BOTTOM_R - SHELL_T,
        BEZEL_TOP_Z - SHELL_T - FIELD_DEPTH,
        bot_z - 1.0,
    )
    boolean(bezel, cavity, "DIFFERENCE")

    field = inscription.loops()["field"]
    recess = prism_from_loops("field", field, BEZEL_TOP_Z - FIELD_DEPTH, BEZEL_TOP_Z + 1.0)
    boolean(bezel, recess, "DIFFERENCE")

    for name, rings in inscription.loops().items():
        if name == "field":
            continue
        letter = prism_from_loops(name, rings, BEZEL_TOP_Z - FIELD_DEPTH - 0.05, BEZEL_TOP_Z)
        boolean(bezel, letter, "UNION")
    return bezel


def arm_centreline(sign: int, rides_over: bool) -> list[tuple[float, float]]:
    """Centreline of one arm in the XZ plane, from inside the bezel wall to its free end.

    The arm drops almost vertically out of the bezel, then joins the finger
    circle at ARM_JOIN_DEG. The arm that rides over steps out by one band
    thickness where the two ends overlap under the finger.
    """
    rc = INNER_D / 2 + BAND_T / 2

    def circle(deg: float, ride: float = 0.0) -> Vector:
        t = math.radians(deg)
        return Vector((sign * (rc + ride) * math.sin(t), (rc + ride) * math.cos(t)))

    p0 = Vector((sign * (BEZEL_BOTTOM_R - BAND_T / 2 - 0.05), BEZEL_TOP_Z - BEZEL_H + 0.4))
    p3 = circle(ARM_JOIN_DEG)
    t = math.radians(ARM_JOIN_DEG)
    tangent = Vector((sign * math.cos(t), -math.sin(t)))
    k = (p3 - p0).length / 2.5
    p1, p2 = p0 + Vector((0.0, -k)), p3 - tangent * k

    pts = []
    for i in range(24):
        s = i / 24
        b = (1 - s) ** 3 * p0 + 3 * (1 - s) ** 2 * s * p1 + 3 * (1 - s) * s * s * p2 + s**3 * p3
        pts.append(b)
    steps = 120
    for i in range(steps + 1):
        deg = ARM_JOIN_DEG + (ARM_END_DEG - ARM_JOIN_DEG) * i / steps
        ride = BAND_T * min(1.0, max(0.0, deg - 150.0) / 30.0) if rides_over else 0.0
        pts.append(circle(deg, ride))
    return pts


def arm_profile(centre: Vector, normal: Vector, width: float) -> list[Vector]:
    """Rounded-rectangle cross-section, domed slightly on the outside face."""
    n = 6
    corner = min(0.45, BAND_T / 2)
    pts = []
    for side, off, ys in ((0, BAND_T / 2, (-1, 1)), (1, -BAND_T / 2, (1, -1))):
        for k in range(n + 1):
            y = ys[0] * width / 2 + (ys[1] - ys[0]) * width / 2 * k / n
            edge = max(0.0, abs(y) - (width / 2 - corner))
            d = corner - math.sqrt(max(corner * corner - edge * edge, 0.0))
            o = off - d if side == 0 else off + d
            if side == 0:
                o += 0.15 * (1 - (2 * y / width) ** 2)
            p = centre + normal * o
            pts.append(Vector((p.x, y, p.y)))
    return pts


def build_arm(name: str, sign: int, rides_over: bool) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    line = arm_centreline(sign, rides_over)
    lengths = [0.0]
    for a, b in zip(line, line[1:]):
        lengths.append(lengths[-1] + (b - a).length)
    rings = []
    for i, c in enumerate(line):
        t = (line[min(i + 1, len(line) - 1)] - line[max(i - 1, 0)]).normalized()
        normal = Vector((t.y, -t.x))
        if normal.dot(c) < 0:
            normal = -normal
        width = BAND_W_TOP + (BAND_W_END - BAND_W_TOP) * lengths[i] / lengths[-1]
        rings.append([bm.verts.new(p) for p in arm_profile(c, normal, width)])
    m = len(rings[0])
    for a, b in zip(rings, rings[1:]):
        for k in range(m):
            bm.faces.new((a[k], a[(k + 1) % m], b[(k + 1) % m], b[k]))
    bm.faces.new(rings[0])
    bm.faces.new(list(reversed(rings[-1])))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def add_materials(ring: bpy.types.Object) -> None:
    silver = bpy.data.materials.new("silver")
    silver.use_nodes = True
    bsdf = silver.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.92, 0.92, 0.9, 1)
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.22

    oxide = bpy.data.materials.new("oxidised silver")
    oxide.use_nodes = True
    bsdf = oxide.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.03, 0.025, 0.02, 1)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.85
    bsdf.inputs["Specular IOR Level"].default_value = 0.02

    ring.data.materials.append(silver)
    ring.data.materials.append(oxide)
    field_z = BEZEL_TOP_Z - FIELD_DEPTH
    for poly in ring.data.polygons:
        z = poly.center.z
        if abs(z - field_z) < 0.02 and poly.normal.z > 0.9:
            poly.material_index = 1


def build() -> bpy.types.Object:
    reset_scene()
    bezel = build_bezel()
    for p in (build_arm("arm_r", 1, rides_over=False), build_arm("arm_l", -1, rides_over=True)):
        boolean(bezel, p, "UNION")

    bev = bezel.modifiers.new("soften", "BEVEL")
    bev.width = RIM_BEVEL
    bev.segments = 2
    bev.limit_method = "ANGLE"
    bev.angle_limit = math.radians(50)
    bpy.context.view_layer.objects.active = bezel
    bpy.ops.object.modifier_apply(modifier=bev.name)

    bezel.name = "khatm_ring"
    bpy.ops.object.select_all(action="DESELECT")
    bezel.select_set(True)
    bpy.ops.object.shade_auto_smooth(angle=math.radians(35))
    add_materials(bezel)
    return bezel


def setup_render() -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.film_transparent = False

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
        obj = bpy.data.objects.new("light", light)
        obj.location = loc
        obj.rotation_euler = (Vector((0, 0, 3)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(obj)


VIEWS = {
    "face": ((0, 0, 60), (0, 0, 5)),
    "front": ((0, -60, 3), (0, 0, 2)),
    "side": ((60, 0, 3), (0, 0, 2)),
    "three-quarter": ((38, -40, 35), (0, 0, 2)),
    "underside": ((0, -10, -60), (0, 0, 2)),
}


def render_views() -> None:
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 85
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    renders = OUT / "renders"
    renders.mkdir(parents=True, exist_ok=True)
    for name, (loc, target) in VIEWS.items():
        cam.location = loc
        cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(renders / f"{name}.png")
        bpy.ops.render.render(write_still=True)


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ring = build()
    OUT.mkdir(exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    ring.select_set(True)
    bpy.ops.wm.stl_export(filepath=str(OUT / "khatm-ring.stl"), export_selected_objects=True, global_scale=1.0)
    bpy.ops.export_scene.gltf(filepath=str(OUT / "khatm-ring.glb"), use_selection=True)
    if "--render" in args:
        setup_render()
        render_views()
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "khatm-ring.blend"))
    dims = ring.dimensions
    print(f"RING {dims.x:.2f} x {dims.y:.2f} x {dims.z:.2f} mm, {len(ring.data.polygons)} faces")


if __name__ == "__main__":
    main()
