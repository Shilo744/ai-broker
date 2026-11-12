"""Writes the files of a transcript from its data (pure standard library: the transcription runner, which lives in another Python, loads this file by path, and the window uses it to
rename speakers). data = {"language", "duration", "segments": [{"start", "end", "text", "speaker" (1, 2, ... or None)}], "names": {"1": "Dana"}}."""
import json
import os


def stamp(t):
    ms = int(round(t * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def label(data, sp):
    if not sp:
        return ""
    name = (data.get("names") or {}).get(str(sp), "").strip()
    if name:
        return name
    return ("דובר %d" if data.get("language") == "he" else "Speaker %d") % sp


def render(data):
    """Returns (text, srt)."""
    rows = data["segments"]
    srt = []
    for i, r in enumerate(rows, 1):
        who = label(data, r.get("speaker"))
        srt.append("%d\n%s --> %s\n%s%s\n" % (i, stamp(r["start"]), stamp(r["end"]), (who + ": ") if who else "", r["text"]))
    paras = []
    for r in rows:
        sp = r.get("speaker")
        if not paras or paras[-1][0] != sp:
            paras.append([sp, r["start"], []])
        paras[-1][2].append(r["text"])
    txt = []
    for sp, start, texts in paras:
        who = label(data, sp)
        txt.append("[%02d:%02d] %s%s\n" % (int(start // 60), int(start % 60), (who + ": ") if who else "", " ".join(texts)))
    return "\n".join(txt), "\n".join(srt)


def write(folder, data):
    txt, srt = render(data)
    with open(os.path.join(folder, "transcript.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    with open(os.path.join(folder, "transcript.srt"), "w", encoding="utf-8") as f:
        f.write(srt)
    with open(os.path.join(folder, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def rename(folder, names):
    """Give the speakers real names ({"1": "Dana"}; an empty name goes back to 'Speaker N') and rewrite the transcript files. Returns the data."""
    p = os.path.join(folder, "transcript.json")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    data["names"] = {str(k): str(v).strip() for k, v in names.items() if str(v).strip()}
    write(folder, data)
    return data
