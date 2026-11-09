"""One-off: adds the English texts of every job type (en_title, en_group, en_desc, en_about) next to the Hebrew ones (he_*) in the job type JSON files."""
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EN = {
    "acestep_music": dict(title="Create music", group="Audio", desc="Composes music (ACE-Step)",
                          about=dict(what="Composes background music without vocals, for example for a city at night or tense moments. For now it runs a ready-made list of tracks from the lab.",
                                     inp="Length in seconds", out="Audio files (FLAC)", tip="To listen, click the file and it opens in your player.")),
    "blender_bake": dict(title="Detail baking for a model", group="3D", desc="Moves details from a heavy model to a light one (Blender)",
                         about=dict(what="A heavy 3D model is full of small details (wrinkles, pores, hair) and a game cannot use a model that heavy. So a light model is made from it, and baking moves the details from the heavy one into images that are pasted onto the light one. That way the light model looks detailed.",
                                    inp="The heavy model and the light model", out="A light model with the details (GLB), and the detail images: a normal map and a shadow map (AO)",
                                    tip="This is the step after creating a model with TripoSG and before putting it into the game.")),
    "moss_sound": dict(title="Create sounds", group="Audio", desc="Effects and voices (MOSS)",
                       about=dict(what="A sound model that makes effects and voices from a script.", inp="Script file", out="Audio files", tip="Used mostly by the lab agent.")),
    "qwen_image_edit": dict(title="Edit an image", group="Images", desc="Changes an existing image from a written instruction",
                            about=dict(what="A model that changes an existing image from an instruction you write in words. You can change the colour of clothing, replace the background, add or remove an object.",
                                       inp="An image, and an instruction in English", out="A new image: the same image after the change",
                                       example="Change the black coat to dark red. Keep everything else identical.",
                                       tip="Once there is a result you can keep talking: the next message edits the latest result.")),
    "step1x_shape": dict(title="3D model, second model", group="3D", desc="The same with another model, for comparison (Step1X)",
                         about=dict(what="A second model for the same purpose as TripoSG: image to 3D model. Used when the first one did not succeed, or to compare two models.",
                                    inp="A list file (jobs.json) with the images and the names", out="Raw 3D models",
                                    tip="Usually Claude or the lab agent starts it. There is no need to start it by hand.")),
    "triposg_shape": dict(title="3D model from an image", group="3D", desc="Turns an image into a 3D shape (TripoSG)",
                          about=dict(what="A model that turns a picture of an object or a character into a 3D model (a GLB file) that you can rotate and use in a game.",
                                     inp="One image of one object, from the front, on a green or transparent background",
                                     out="A raw 3D model: grey, without colour, and heavy (hundreds of thousands of triangles) because it has not been cleaned yet. After the job a preview you can rotate is created.",
                                     example="A picture of a fur collar on a green background",
                                     tip="Preparing the model for the game (making it light and pasting the details) happens in the next steps: detail baking and Blender jobs.")),
    "zimage_t2i": dict(title="Text to image", group="Images", desc="Draws a new image from a description in words",
                       about=dict(what="A model that draws a new image from a description in words, without a source image.", inp="A description in English", out="An image",
                                  example="A weathered street courier in a rain jacket, studio light, full body",
                                  tip="A detailed description (who, what they wear, lighting, background) gives a better result than a short one.")),
    "godot_film": dict(title="A video from the game", group="Game", desc="Films a short video from the game",
                       about=dict(what="Like the screenshots, but films a short video from the game.", inp="A scenario name and a length in seconds", out="A video (MP4)",
                                  tip="Uses the graphics card, so it waits while you play or record.")),
    "godot_shots": dict(title="Screenshots from the game", group="Game", desc="Runs the game in the background and takes pictures",
                        about=dict(what="Runs the game in the background (on a hidden desktop, without disturbing you) and takes pictures of a scenario, to see how it looks without opening the game.",
                                   inp="A scenario name", out="Screenshots", tip="Uses the graphics card, so it waits while you play or record.")),
    "godot_sim": dict(title="Game test without a screen", group="Game", desc="A light test of the game's logic",
                      about=dict(what="Runs the game without a window and without graphics to check that its logic works: automatic scenarios that pass or fail.",
                                 inp="A test scenario name", out="A results report", tip="Fast and light, and does not use the graphics card.")),
    "blender_script": dict(title="Blender job", group="3D", desc="Runs a script in Blender",
                           about=dict(what="Runs a script in Blender in the background, without opening it. For example reducing a model's triangle count, cleaning it or exporting it.",
                                      inp="A script file, and usually the model it works on", out="Whatever the script saves in the result folder",
                                      tip="For advanced use. Usually Claude starts this.")),
    "custom": dict(title="Another command", group="Other", desc="Any program you write a command for",
                   about=dict(what="Any program that can be run with a command. You say how much RAM it needs, and the queue makes sure it does not collide with the other jobs.",
                              inp="A command", out="Whatever the program saves")),
    "glb_preview": dict(title="3D preview", group="Other", desc="Created automatically after a 3D job"),
    "python_script": dict(title="Python script", group="Other", desc="Runs any script",
                          about=dict(what="Runs any Python script through the queue, with the ComfyUI environment.", inp="A script file", out="Whatever the script saves", tip="For advanced use.")),
}

done = 0
for f in sorted(glob.glob(str(ROOT / "jobtypes" / "*.json")) + glob.glob(str(ROOT / "adapters" / "*" / "jobtypes" / "*.json"))):
    path = Path(f)
    d = json.loads(path.read_text(encoding="utf-8"))
    tid = d.get("id")
    e = EN.get(tid)
    if not e:
        print("no English text for", tid)
        continue
    d["en_title"], d["en_group"], d["en_desc"] = e["title"], e["group"], e["desc"]
    if e.get("about"):
        d["en_about"] = e["about"]
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    done += 1
print("updated", done)
