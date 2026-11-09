"""Blender background script: a turntable of a GLB for the AI Broker window (Workbench engine, clay look, transparent background).
  blender -b --python blender_preview.py -- <in.glb> <out_dir> [frames=36] [size=512]
Writes <out_dir>/frame_000.png ... and <out_dir>/preview.png (a three-quarter view)."""
import math
import os
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
glb, out = os.path.abspath(args[0]), os.path.abspath(args[1])
frames = int(args[2]) if len(args) > 2 else 36
size = int(args[3]) if len(args) > 3 else 512
os.makedirs(out, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
scene = bpy.context.scene
meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh in " + glb)

lo = Vector((1e9, 1e9, 1e9))
hi = Vector((-1e9, -1e9, -1e9))
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector((min(lo[i], w[i]) for i in range(3)))
        hi = Vector((max(hi[i], w[i]) for i in range(3)))
center = (lo + hi) / 2
ext = max((hi - lo)[i] for i in range(3)) or 1.0

pivot = bpy.data.objects.new("pivot", None)
scene.collection.objects.link(pivot)
pivot.location = center
for o in meshes:                     # parent every mesh to the pivot without moving it
    mw = o.matrix_world.copy()
    o.parent = pivot
    o.matrix_parent_inverse = pivot.matrix_world.inverted()
    o.matrix_world = mw
scale = 2.5 / ext
pivot.scale = (scale, scale, scale)
pivot.location = Vector((0, 0, 0))   # move the model centre to the origin (scaled)
for o in meshes:
    o.location = o.location            # keep local transforms

cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 55
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (0, -3.6, 0.8)
target = bpy.data.objects.new("target", None)
scene.collection.objects.link(target)
con = cam.constraints.new("TRACK_TO")
con.target = target
con.track_axis = "TRACK_NEGATIVE_Z"
con.up_axis = "UP_Y"
scene.camera = cam

scene.render.engine = "BLENDER_WORKBENCH"
sh = scene.display.shading
sh.light = "STUDIO"
sh.color_type = "SINGLE"
sh.single_color = (0.70, 0.76, 0.90)
sh.show_cavity = True
scene.render.resolution_x = scene.render.resolution_y = size
scene.render.film_transparent = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "Standard"

for i in range(frames):
    pivot.rotation_euler = (0, 0, 2 * math.pi * i / frames)
    scene.render.filepath = os.path.join(out, "frame_%03d.png" % i)
    bpy.ops.render.render(write_still=True)
    if i == frames // 8:
        import shutil
        shutil.copyfile(scene.render.filepath, os.path.join(out, "preview.png"))
print("PREVIEW frames=%d size=%d meshes=%d" % (frames, size, len(meshes)), flush=True)
