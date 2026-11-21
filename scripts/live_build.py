"""Snippet sent to a live Blender by `blender_live.py`: rebuild the ring and frame it."""

import importlib
import sys

import bpy

SCRIPTS = r"V:\dev\Personal\khatm-ring\scripts"
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import build_ring  # noqa: E402

importlib.reload(build_ring)
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
