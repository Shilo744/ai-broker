"""Blender background script: import a GLB, report face counts, decimate to a ratio, export a GLB.
  blender -b --python blender_decimate.py -- <in.glb> <out.glb> [ratio=0.5]"""
import sys
import bpy

args = sys.argv[sys.argv.index("--") + 1:]
src, dst = args[0], args[1]
ratio = float(args[2]) if len(args) > 2 else 0.5
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
before = sum(len(o.data.polygons) for o in meshes)
for o in meshes:
    bpy.context.view_layer.objects.active = o
    m = o.modifiers.new("dec", "DECIMATE")
    m.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=m.name)
after = sum(len(o.data.polygons) for o in meshes)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB")
print("FACES before %d after %d (ratio %.2f)" % (before, after, ratio), flush=True)
