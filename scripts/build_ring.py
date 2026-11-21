"""Build the khatm ring in Blender: mesh the ring's distance field, then dress and export it.

The geometry lives in `ring_sdf.py`, which models the whole ring as one signed
distance field and meshes it with marching cubes. This script runs it, imports
the mesh, assigns materials, exports STL and GLB, and renders.

Headless:
    blender -b -P scripts/build_ring.py -- [--render]
Live, in a Blender running the BlenderMCP add-on:
    python scripts/blender_live.py scripts/live_build.py
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "model"
BODY = OUT / "body.ply"
KEEP_COLLECTION = "inscription"
DECIMATE_RATIO = 0.25


# ---------------------------------------------------------------- scene


def clear_scene() -> None:
    """Empty the scene without a factory reset, which would unload the MCP add-on.

    Objects in the KEEP_COLLECTION (the draggable letter pieces) survive.
    """
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    keep = bpy.data.collections.get(KEEP_COLLECTION)
    kept = set(keep.objects) if keep else set()
    for obj in list(bpy.data.objects):
        if obj not in kept:
            bpy.data.objects.remove(obj)
    kept_data = {o.data for o in kept}
    kept_mats = {m for o in kept for m in o.data.materials}
    for coll in (bpy.data.meshes, bpy.data.curves):
        for block in list(coll):
            if block not in kept_data:
                coll.remove(block)
    for mat in list(bpy.data.materials):
        if mat not in kept_mats:
            bpy.data.materials.remove(mat)
    for coll in (bpy.data.lights, bpy.data.cameras, bpy.data.worlds):
        for block in list(coll):
            coll.remove(block)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = "MILLIMETERS"


def link(obj: bpy.types.Object) -> bpy.types.Object:
    bpy.context.scene.collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------- body


def mesh_body(solve: bool = True) -> dict:
    """Run the distance-field script with uv (Blender's Python lacks its packages)."""
    cmd = ["uv", "run", str(ROOT / "scripts" / "ring_sdf.py"), "--out", str(BODY)]
    if solve:
        cmd.append("--solve")
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-2000:])
    return json.loads(done.stdout.strip().splitlines()[-1])


def import_body(stats: dict) -> bpy.types.Object:
    bpy.ops.wm.ply_import(filepath=str(BODY))
    ring = bpy.context.selected_objects[0]
    ring.name = "khatm_ring"
    # Marching cubes winds faces outward and the PLY carries the field's
    # gradient as custom normals; recalculating either would lose them.
    bm = bmesh.new()
    bm.from_mesh(ring.data)
    if bm.calc_volume(signed=True) < 0:
        raise RuntimeError("body.ply faces wind inward")
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    f = bm.faces[0]
    shading = ring.data.corner_normals[ring.data.polygons[0].loop_start].vector
    if shading.dot(f.normal) < 0:
        raise RuntimeError("body.ply normals point inward")
    bm.free()
    # Marching cubes leaves far more triangles than the shape needs; collapsing
    # to DECIMATE_RATIO moves the surface by microns and keeps exports small.
    mod = ring.modifiers.new("lighten", "DECIMATE")
    mod.ratio = DECIMATE_RATIO
    mod.use_collapse_triangulate = True
    with bpy.context.temp_override(object=ring, active_object=ring):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    add_materials(ring, stats["z_field"])
    return ring


def add_materials(ring: bpy.types.Object, z_field: float) -> None:
    silver = bpy.data.materials.new("silver")
    silver.use_nodes = True
    bsdf = next(n for n in silver.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (0.92, 0.92, 0.9, 1)
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.2

    oxide = bpy.data.materials.new("oxidised silver")
    oxide.use_nodes = True
    bsdf = next(n for n in oxide.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (0.03, 0.025, 0.02, 1)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.85
    bsdf.inputs["Specular IOR Level"].default_value = 0.02

    ring.data.materials.append(silver)
    ring.data.materials.append(oxide)
    # The recessed field is the only upward face at field height; letter tops
    # and the rim sit RELIEF higher.
    for poly in ring.data.polygons:
        if abs(poly.center.z - z_field) < 0.06 and poly.normal.z > 0.8:
            poly.material_index = 1


def build(solve: bool = True) -> dict:
    stats = mesh_body(solve)
    clear_scene()
    ring = import_body(stats)
    stats["non_manifold_edges"] = non_manifold(ring)
    bm = bmesh.new()
    bm.from_mesh(ring.data)
    stats["mesh_volume_mm3"] = round(bm.calc_volume(signed=True), 1)
    stats["faces"] = len(bm.faces)
    bm.free()
    print(stats)
    return stats


def non_manifold(ring: bpy.types.Object) -> int:
    bm = bmesh.new()
    bm.from_mesh(ring.data)
    n = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    return n


# ---------------------------------------------------------------- look


def setup_render() -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900

    world = bpy.data.worlds.new("studio")
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
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
    "low-three-quarter": ((42, -38, 8), (0, 0, 6)),
    "underside": ((0, -14, -58), (0, 0, 4)),
}


def render_views(views=VIEWS, folder: Path = OUT / "renders") -> None:
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 85
    cam = link(bpy.data.objects.new("cam", cam_data))
    scene.camera = cam
    folder.mkdir(parents=True, exist_ok=True)
    letters = bpy.data.collections.get(KEEP_COLLECTION)
    if letters:
        letters.hide_render = True
    for name, (loc, target) in views.items():
        cam.location = loc
        cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(folder / f"{name}.png")
        bpy.ops.render.render(write_still=True)


def export(ring: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    ring.select_set(True)
    bpy.context.view_layer.objects.active = ring
    bpy.ops.wm.stl_export(filepath=str(OUT / "khatm-ring.stl"), export_selected_objects=True)
    bpy.ops.export_scene.gltf(filepath=str(OUT / "khatm-ring.glb"), use_selection=True)


def run(render: bool = False) -> dict:
    stats = build()
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
