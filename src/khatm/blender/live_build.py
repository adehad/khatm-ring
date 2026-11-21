"""Snippet sent to a live Blender by `khatm live-build`: rebuild the ring and frame it."""

import importlib

import bpy

import khatm.paths
import khatm.ring_size
from khatm.blender import build_ring

for module in (khatm.paths, khatm.ring_size, build_ring):
    importlib.reload(module)
build_ring.register()
stats = build_ring.run(render=False)

ring = bpy.data.objects["khatm_ring"]
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.shading.type = "MATERIAL"
        space.clip_start = 0.1
        region = next(r for r in area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.object.select_all(action="DESELECT")
            ring.select_set(True)
            bpy.context.view_layer.objects.active = ring
            bpy.ops.view3d.view_selected()
print(stats)
